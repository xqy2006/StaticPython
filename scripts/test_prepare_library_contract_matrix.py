from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SPEC = importlib.util.spec_from_file_location(
    "staticpython_prepare_library_contract_matrix",
    REPO_ROOT / "scripts" / "prepare_library_contract_matrix.py",
)
assert SPEC is not None and SPEC.loader is not None
matrix_builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(matrix_builder)


def contract() -> dict:
    return {
        "contract_sha256": "contract",
        "status_counts": {"candidate": 1, "configured": 0, "unbuildable": 0},
        "libraries": {
            "demo": {
                "project_name": "Demo-Project",
                "versions": {
                    "1.0": {
                        "targets": {
                            "3.13.14": {
                                "status": "candidate",
                                "source": {
                                    "filename": "demo-1.0.tar.gz",
                                    "url": "https://files.pythonhosted.org/demo-1.0.tar.gz",
                                    "sha256": "a" * 64,
                                },
                            }
                        }
                    }
                },
            }
        },
    }


def delta() -> dict:
    return {
        "baseline": False,
        "current_contract_sha256": "contract",
        "new_candidates": [
            {
                "library": "demo",
                "version": "1.0",
                "python_version": "3.13.14",
                "status": "candidate",
                "source": {
                    "filename": "demo-1.0.tar.gz",
                    "url": "https://files.pythonhosted.org/demo-1.0.tar.gz",
                    "sha256": "a" * 64,
                },
            }
        ],
        "new_unbuildable": [],
        "drifted_candidates": [],
        "regressions": [],
    }


def append_candidates(payload: dict, count: int) -> None:
    for index in range(1, count):
        version = f"1.{index}"
        source_sha256 = f"{index:064x}"
        payload["new_candidates"].append(
            {
                "library": "demo",
                "version": version,
                "python_version": "3.13.14",
                "status": "candidate",
                "source": {
                    "filename": f"demo-{version}.tar.gz",
                    "url": f"https://files.pythonhosted.org/demo-{version}.tar.gz",
                    "sha256": source_sha256,
                },
            }
        )


class PrepareLibraryContractMatrixTests(unittest.TestCase):
    def test_builds_locked_matrix_record(self) -> None:
        result = matrix_builder.prepare_matrix(contract(), delta())
        self.assertEqual(len(result["include"]), 1)
        record = result["include"][0]
        self.assertEqual(record["project_name"], "Demo-Project")
        self.assertEqual(record["source_sha256"], "a" * 64)
        self.assertNotIn("/", record["slug"])
        self.assertEqual(record["validation_reason"], "new-candidate")
        self.assertEqual(len(result["batches"]), 1)
        self.assertEqual(result["batches"][0]["candidate_count"], 1)
        self.assertEqual(json.loads(result["batches"][0]["candidates_json"]), [record])

    def test_baseline_produces_an_empty_matrix(self) -> None:
        payload = delta()
        payload["baseline"] = True
        payload["new_candidates"] = []
        self.assertEqual(
            matrix_builder.prepare_matrix(contract(), payload),
            {"include": [], "batches": []},
        )

    def test_source_drift_and_regression_are_red_lights(self) -> None:
        for field in ("drifted_candidates", "regressions"):
            with self.subTest(field=field):
                payload = delta()
                payload[field] = [{"library": "demo"}]
                with self.assertRaisesRegex(RuntimeError, "source drift|regression"):
                    matrix_builder.prepare_matrix(contract(), payload)

    def test_pull_request_smoke_selects_latest_compatible_candidate(self) -> None:
        payload = delta()
        payload["new_candidates"] = []
        result = matrix_builder.prepare_matrix(
            contract(),
            payload,
            smoke_library="DEMO",
            smoke_python_series="3.13",
        )
        self.assertEqual(len(result["include"]), 1)
        self.assertEqual(result["include"][0]["version"], "1.0")
        self.assertEqual(result["include"][0]["python_version"], "3.13.14")
        self.assertEqual(result["include"][0]["validation_reason"], "pull-request-smoke")

    def test_matrix_limit_fails_instead_of_silently_skipping(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "matrix limit"):
            matrix_builder.prepare_matrix(contract(), delta(), limit=0)

    def test_batch_size_is_fail_closed(self) -> None:
        for invalid in (0, 3, True):
            with self.subTest(invalid=invalid):
                with self.assertRaisesRegex(RuntimeError, "maximum candidates per batch"):
                    matrix_builder.prepare_matrix(
                        contract(),
                        delta(),
                        max_candidates_per_batch=invalid,
                    )

    def test_moderate_matrix_is_deterministically_batched_without_truncation(self) -> None:
        candidate_delta = delta()
        append_candidates(candidate_delta, 491)
        result = matrix_builder.prepare_matrix(contract(), candidate_delta)
        repeated = matrix_builder.prepare_matrix(contract(), candidate_delta)

        self.assertEqual(len(result["include"]), 491)
        self.assertEqual(len(result["batches"]), 256)
        self.assertEqual(result["batches"], repeated["batches"])
        self.assertLessEqual(
            max(batch["candidate_count"] for batch in result["batches"]),
            2,
        )
        decoded = [
            candidate
            for batch in result["batches"]
            for candidate in json.loads(batch["candidates_json"])
        ]
        self.assertEqual(
            sorted(record["slug"] for record in decoded),
            sorted(record["slug"] for record in result["include"]),
        )

    def test_more_than_bounded_daily_capacity_is_deferred(self) -> None:
        candidate_delta = delta()
        append_candidates(candidate_delta, 513)
        result = matrix_builder.prepare_matrix(
            contract(),
            candidate_delta,
            defer_overflow_to_history=True,
        )
        self.assertEqual(result["include"], [])
        self.assertEqual(result["batches"], [])
        self.assertEqual(
            result["deferred"],
            {
                "reason": "weekly-history-shards",
                "candidate_count": 513,
                "contract_sha256": "contract",
                "matrix_limit": 256,
                "max_candidates_per_batch": 2,
                "incremental_candidate_limit": 512,
            },
        )

    def test_overflow_is_explicitly_deferred_to_weekly_history(self) -> None:
        payload = contract()
        payload["libraries"]["demo"]["versions"]["2.0"] = {
            "targets": {
                "3.13.14": {
                    "status": "candidate",
                    "source": {
                        "filename": "demo-2.0.tar.gz",
                        "url": "https://files.pythonhosted.org/demo-2.0.tar.gz",
                        "sha256": "b" * 64,
                    },
                }
            }
        }
        candidate_delta = delta()
        candidate_delta["new_candidates"].append(
            {
                "library": "demo",
                "version": "2.0",
                "python_version": "3.13.14",
                "status": "candidate",
                "source": {
                    "filename": "demo-2.0.tar.gz",
                    "url": "https://files.pythonhosted.org/demo-2.0.tar.gz",
                    "sha256": "b" * 64,
                },
            }
        )
        result = matrix_builder.prepare_matrix(
            payload,
            candidate_delta,
            limit=1,
            max_candidates_per_batch=1,
            smoke_library="demo",
            smoke_python_series="3.13",
            defer_overflow_to_history=True,
        )
        self.assertEqual(len(result["include"]), 1)
        self.assertEqual(result["include"][0]["version"], "2.0")
        self.assertEqual(result["include"][0]["validation_reason"], "pull-request-smoke")
        self.assertEqual(
            result["deferred"],
            {
                "reason": "weekly-history-shards",
                "candidate_count": 2,
                "contract_sha256": "contract",
                "matrix_limit": 1,
                "max_candidates_per_batch": 1,
                "incremental_candidate_limit": 1,
            },
        )
        self.assertEqual(len(result["batches"]), 1)

    def test_deferred_candidates_are_still_fully_validated(self) -> None:
        payload = contract()
        payload["libraries"]["demo"]["versions"]["2.0"] = {
            "targets": {
                "3.13.14": {
                    "status": "candidate",
                    "source": {
                        "filename": "demo-2.0.tar.gz",
                        "url": "https://files.pythonhosted.org/demo-2.0.tar.gz",
                        "sha256": "b" * 64,
                    },
                }
            }
        }
        candidate_delta = delta()
        invalid_candidate = {
            "library": "demo",
            "version": "2.0",
            "python_version": "3.13.14",
            "status": "candidate",
            "source": {
                "filename": "demo-2.0.tar.gz",
                "sha256": "b" * 64,
            },
        }
        candidate_delta["new_candidates"].append(invalid_candidate)
        with self.assertRaisesRegex(RuntimeError, "incomplete source provenance"):
            matrix_builder.prepare_matrix(
                payload,
                candidate_delta,
                limit=1,
                max_candidates_per_batch=1,
                defer_overflow_to_history=True,
            )

    def test_workflows_route_overflow_to_current_source_history(self) -> None:
        daily = (REPO_ROOT / ".github" / "workflows" / "library-version-discovery.yml").read_text(
            encoding="utf-8"
        )
        weekly = (REPO_ROOT / ".github" / "workflows" / "library-history-weekly.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn('"--defer-overflow-to-history"', daily)
        self.assertIn(
            "include: ${{ fromJSON(needs.discover.outputs.matrix).include }}",
            daily,
        )
        self.assertNotIn("matrix: ${{ fromJSON(needs.discover.outputs.matrix) }}", daily)
        self.assertIn("$matrixDocument.batches", daily)
        self.assertIn("CONTRACT_BATCH_JSON", daily)
        self.assertIn("Build and verify candidate batch", daily)
        self.assertIn("StaticPython verification report is missing", daily)
        self.assertIn("[IO.Path]::GetRelativePath", daily)
        self.assertIn("Remove-Item -LiteralPath $buildRootPath -Recurse -Force", daily)
        self.assertIn("Discover current source version contract", weekly)
        self.assertIn('selection = "current-source-discovery"', weekly)
        self.assertIn('"previous-library-version-contract.json"', weekly)


if __name__ == "__main__":
    unittest.main(verbosity=2)
