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


class PrepareLibraryContractMatrixTests(unittest.TestCase):
    def test_builds_locked_matrix_record(self) -> None:
        result = matrix_builder.prepare_matrix(contract(), delta())
        self.assertEqual(len(result["include"]), 1)
        batch = result["include"][0]
        self.assertEqual(batch["candidate_count"], 1)
        record = json.loads(batch["candidates_json"])[0]
        self.assertEqual(record["project_name"], "Demo-Project")
        self.assertEqual(record["source_sha256"], "a" * 64)
        self.assertNotIn("/", record["slug"])
        self.assertEqual(record["validation_reason"], "new-candidate")

    def test_baseline_produces_an_empty_matrix(self) -> None:
        payload = delta()
        payload["baseline"] = True
        payload["new_candidates"] = []
        self.assertEqual(
            matrix_builder.prepare_matrix(contract(), payload),
            {"include": []},
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
        record = json.loads(result["include"][0]["candidates_json"])[0]
        self.assertEqual(record["version"], "1.0")
        self.assertEqual(record["python_version"], "3.13.14")
        self.assertEqual(record["validation_reason"], "pull-request-smoke")

    def test_matrix_limit_must_be_positive(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "matrix limit must be positive"):
            matrix_builder.prepare_matrix(contract(), delta(), limit=0)

    def test_large_delta_is_deterministically_batched_without_skipping(self) -> None:
        payload = delta()
        payload["new_candidates"] = []
        for index in range(491):
            payload["new_candidates"].append(
                {
                    "library": "demo",
                    "version": f"1.{index}",
                    "python_version": "3.13.14",
                    "status": "candidate",
                    "source": {
                        "filename": f"demo-1.{index}.tar.gz",
                        "url": f"https://files.pythonhosted.org/demo-1.{index}.tar.gz",
                        "sha256": f"{index + 1:064x}",
                    },
                }
            )

        first = matrix_builder.prepare_matrix(contract(), payload)
        second = matrix_builder.prepare_matrix(contract(), payload)
        self.assertEqual(first, second)
        self.assertEqual(len(first["include"]), 256)
        self.assertEqual(max(batch["candidate_count"] for batch in first["include"]), 2)
        candidates = [
            candidate
            for batch in first["include"]
            for candidate in json.loads(batch["candidates_json"])
        ]
        self.assertEqual(len(candidates), 491)
        self.assertEqual(len({candidate["slug"] for candidate in candidates}), 491)
        json.dumps(first, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main(verbosity=2)
