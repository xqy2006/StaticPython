from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

PROMOTION_SPEC = importlib.util.spec_from_file_location(
    "staticpython_promote_library_contract",
    REPO_ROOT / "scripts" / "promote_library_contract.py",
)
assert PROMOTION_SPEC is not None and PROMOTION_SPEC.loader is not None
promotion = importlib.util.module_from_spec(PROMOTION_SPEC)
PROMOTION_SPEC.loader.exec_module(promotion)

CONTRACT_SPEC = importlib.util.spec_from_file_location(
    "staticpython_library_version_contract_for_promotion_tests",
    REPO_ROOT / "scripts" / "library_version_contract.py",
)
assert CONTRACT_SPEC is not None and CONTRACT_SPEC.loader is not None
contract_module = importlib.util.module_from_spec(CONTRACT_SPEC)
CONTRACT_SPEC.loader.exec_module(contract_module)


def source(sha: str) -> dict:
    return {
        "filename": "demo-1.0.tar.gz",
        "packagetype": "sdist",
        "requires_python": ">=3.11",
        "url": "https://files.pythonhosted.org/demo-1.0.tar.gz",
        "sha256": sha,
    }


def contract(targets: dict) -> dict:
    payload = {
        "schema_version": 1,
        "target_python_versions": ["3.13.14"],
        "libraries": {
            "demo": {
                "project_name": "demo",
                "source_provider": "pypi",
                "minimum_release_version": None,
                "versions": {"1.0": {"targets": targets}},
            }
        },
        "status_counts": {
            "candidate": sum(1 for item in targets.values() if item["status"] == "candidate"),
            "configured": 0,
            "not-applicable": 0,
            "unbuildable": sum(1 for item in targets.values() if item["status"] == "unbuildable"),
        },
    }
    payload["contract_sha256"] = contract_module._contract_sha256(payload)
    return payload


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def candidate_record(sha: str) -> dict:
    return {
        "library": "demo",
        "version": "1.0",
        "python_version": "3.13.14",
        "status": "candidate",
        "source": source(sha),
    }


def delta(previous_sha: str | None, current_sha: str, **overrides: object) -> dict:
    payload = {
        "schema_version": 1,
        "baseline": previous_sha is None,
        "previous_contract_sha256": previous_sha,
        "current_contract_sha256": current_sha,
        "new_candidates": [],
        "new_unbuildable": [],
        "drifted_candidates": [],
        "regressions": [],
    }
    payload.update(overrides)
    return payload


def matrix_record(sha: str, reason: str = "new-candidate") -> dict:
    return {
        "library": "demo",
        "project_name": "demo",
        "version": "1.0",
        "python_version": "3.13.14",
        "source_filename": "demo-1.0.tar.gz",
        "source_url": "https://files.pythonhosted.org/demo-1.0.tar.gz",
        "source_sha256": sha,
        "slug": f"demo-1.0-py3.13.14-{sha[:12]}",
        "validation_reason": reason,
    }


def report(sha: str, *, status: str = "passed") -> dict:
    return {
        "schema_version": 1,
        "library": "demo",
        "project_name": "demo",
        "version": "1.0",
        "python_version": "3.13.14",
        "source_archive": "downloads/demo-1.0.tar.gz",
        "source_archive_sha256": sha,
        "pack": "packs/demo.zip",
        "pack_sha256": "b" * 64,
        "python_exe": "python.exe",
        "pe_dependencies": ["KERNEL32.dll"],
        "status": status,
    }


class PromotionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def run_promotion(
        self,
        candidate: dict,
        delta_payload: dict,
        *,
        mode: str = "promote",
        matrix_payload: dict | None = None,
        validation_report: dict | None = None,
        validation_reports: list[dict] | None = None,
        previous_catalog: Path | None = None,
        legacy_baseline: Path | None = None,
        output_name: str = "catalog",
    ) -> tuple[dict, Path]:
        candidate_path = write_json(self.root / f"{output_name}-candidate.json", candidate)
        delta_path = write_json(self.root / f"{output_name}-delta.json", delta_payload)
        matrix_path = None
        if matrix_payload is not None:
            matrix_path = write_json(self.root / f"{output_name}-matrix.json", matrix_payload)
        validation_root = self.root / f"{output_name}-validation"
        if validation_report is not None:
            write_json(validation_root / "job" / "library-contract-build-report.json", validation_report)
        for index, candidate_report in enumerate(validation_reports or [], start=1):
            write_json(
                validation_root
                / "library-contract-batch-001"
                / f"candidate-{index}"
                / "library-contract-build-report.json",
                candidate_report,
            )
        output = self.root / output_name
        result = promotion.promote_catalog(
            candidate_path,
            delta_path,
            output,
            matrix_path=matrix_path,
            validation_root=validation_root,
            previous_catalog_root=previous_catalog,
            legacy_baseline_contract_path=legacy_baseline,
            mode=mode,
            provenance={"run_id": "123", "source_commit": "c" * 40},
        )
        return result, output

    def test_bootstrap_is_explicit_discovery_baseline(self) -> None:
        candidate = contract({"3.13.14": {"status": "candidate", "source": source("a" * 64)}})
        result, output = self.run_promotion(
            candidate,
            delta(None, candidate["contract_sha256"]),
        )
        self.assertEqual(result["decision"]["status"], "promoted")
        self.assertEqual(result["active"]["promotion_basis"], "discovery-baseline")
        self.assertEqual(result["active"]["verified_combinations"], [])
        self.assertEqual(
            json.loads((output / "active" / "library-version-contract.json").read_text())["contract_sha256"],
            candidate["contract_sha256"],
        )

    def test_incremental_pass_promotes_and_records_verified_identity(self) -> None:
        baseline = contract({"3.13.14": {"status": "unbuildable", "reason": "no source"}})
        baseline_path = write_json(self.root / "legacy.json", baseline)
        initial, previous_catalog = self.run_promotion(
            baseline,
            delta(baseline["contract_sha256"], baseline["contract_sha256"], baseline=False),
            legacy_baseline=baseline_path,
            output_name="previous",
        )
        self.assertEqual(initial["decision"]["status"], "unchanged")

        source_sha = "a" * 64
        candidate = contract({"3.13.14": {"status": "candidate", "source": source(source_sha)}})
        new_record = candidate_record(source_sha)
        result, output = self.run_promotion(
            candidate,
            delta(
                baseline["contract_sha256"],
                candidate["contract_sha256"],
                baseline=False,
                new_candidates=[new_record],
            ),
            matrix_payload={"include": [matrix_record(source_sha)]},
            validation_report=report(source_sha),
            previous_catalog=previous_catalog,
            output_name="promoted",
        )
        self.assertEqual(result["decision"]["status"], "promoted")
        self.assertEqual(result["active"]["contract_sha256"], candidate["contract_sha256"])
        self.assertEqual(result["active"]["promotion_basis"], "incremental-validation")
        self.assertEqual(len(result["active"]["verified_combinations"]), 1)
        evidence = json.loads(
            (
                output
                / "candidates"
                / candidate["contract_sha256"]
                / "promotion-evidence.v1.json"
            ).read_text()
        )
        self.assertEqual(evidence["validation"]["passed_count"], 1)

    def test_batched_reports_are_recursively_matched_to_exact_candidates(self) -> None:
        baseline = contract({"3.13.14": {"status": "unbuildable", "reason": "no source"}})
        baseline["libraries"]["demo"]["versions"]["1.1"] = {
            "targets": {"3.13.14": {"status": "unbuildable", "reason": "no source"}}
        }
        baseline["status_counts"]["unbuildable"] = 2
        baseline["contract_sha256"] = contract_module._contract_sha256(
            {key: value for key, value in baseline.items() if key != "contract_sha256"}
        )
        baseline_path = write_json(self.root / "batched-legacy.json", baseline)
        _initial, previous_catalog = self.run_promotion(
            baseline,
            delta(baseline["contract_sha256"], baseline["contract_sha256"], baseline=False),
            legacy_baseline=baseline_path,
            output_name="batched-previous",
        )

        first_sha = "a" * 64
        second_sha = "c" * 64
        candidate = contract(
            {"3.13.14": {"status": "candidate", "source": source(first_sha)}}
        )
        second_source = {
            **source(second_sha),
            "filename": "demo-1.1.tar.gz",
            "url": "https://files.pythonhosted.org/demo-1.1.tar.gz",
        }
        candidate["libraries"]["demo"]["versions"]["1.1"] = {
            "targets": {"3.13.14": {"status": "candidate", "source": second_source}}
        }
        candidate["status_counts"]["candidate"] = 2
        candidate["contract_sha256"] = contract_module._contract_sha256(
            {key: value for key, value in candidate.items() if key != "contract_sha256"}
        )

        first_delta = candidate_record(first_sha)
        second_delta = {
            **candidate_record(second_sha),
            "version": "1.1",
            "source": second_source,
        }
        first_matrix = matrix_record(first_sha)
        second_matrix = {
            **matrix_record(second_sha),
            "version": "1.1",
            "source_filename": "demo-1.1.tar.gz",
            "source_url": "https://files.pythonhosted.org/demo-1.1.tar.gz",
            "slug": f"demo-1.1-py3.13.14-{second_sha[:12]}",
        }
        batch_candidates = [first_matrix, second_matrix]
        first_report = report(first_sha)
        second_report = {
            **report(second_sha),
            "version": "1.1",
            "source_archive": "downloads/demo-1.1.tar.gz",
            "pack": "packs/demo-1.1.zip",
            "pack_sha256": "d" * 64,
        }

        result, output = self.run_promotion(
            candidate,
            delta(
                baseline["contract_sha256"],
                candidate["contract_sha256"],
                baseline=False,
                new_candidates=[first_delta, second_delta],
            ),
            matrix_payload={
                "include": batch_candidates,
                "batches": [
                    {
                        "slug": "batch-001-test",
                        "candidate_count": 2,
                        "candidates_json": json.dumps(
                            batch_candidates,
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                ],
            },
            validation_reports=[first_report, second_report],
            previous_catalog=previous_catalog,
            output_name="batched-promoted",
        )
        self.assertEqual(result["decision"]["status"], "promoted")
        self.assertEqual(len(result["active"]["verified_combinations"]), 2)
        evidence = json.loads(
            (
                output
                / "candidates"
                / candidate["contract_sha256"]
                / "promotion-evidence.v1.json"
            ).read_text()
        )
        self.assertEqual(evidence["validation"]["expected_count"], 2)
        self.assertEqual(evidence["validation"]["passed_count"], 2)
        self.assertEqual(evidence["validation"]["missing"], [])
        self.assertEqual(evidence["validation"]["unexpected"], [])
        self.assertEqual(
            {record["artifact"] for record in evidence["validation"]["passed"]},
            {"library-contract-batch-001-test"},
        )

        tampered_second = dict(second_matrix)
        tampered_second["source_url"] = "https://example.invalid/tampered.tar.gz"
        with self.assertRaisesRegex(RuntimeError, "payload differs from include record"):
            self.run_promotion(
                candidate,
                delta(
                    baseline["contract_sha256"],
                    candidate["contract_sha256"],
                    baseline=False,
                    new_candidates=[first_delta, second_delta],
                ),
                matrix_payload={
                    "include": batch_candidates,
                    "batches": [
                        {
                            "slug": "batch-001-test",
                            "candidate_count": 2,
                            "candidates_json": json.dumps(
                                [first_matrix, tampered_second],
                                sort_keys=True,
                                separators=(",", ":"),
                            ),
                        }
                    ],
                },
                validation_reports=[first_report, second_report],
                previous_catalog=previous_catalog,
                output_name="batched-tampered",
            )

    def test_missing_validation_freezes_previous_active_directory(self) -> None:
        baseline = contract({"3.13.14": {"status": "unbuildable", "reason": "no source"}})
        baseline_path = write_json(self.root / "missing-legacy.json", baseline)
        _initial, previous_catalog = self.run_promotion(
            baseline,
            delta(baseline["contract_sha256"], baseline["contract_sha256"], baseline=False),
            legacy_baseline=baseline_path,
            output_name="missing-previous",
        )
        source_sha = "a" * 64
        candidate = contract({"3.13.14": {"status": "candidate", "source": source(source_sha)}})
        result, output = self.run_promotion(
            candidate,
            delta(
                baseline["contract_sha256"],
                candidate["contract_sha256"],
                baseline=False,
                new_candidates=[candidate_record(source_sha)],
            ),
            matrix_payload={"include": [matrix_record(source_sha)]},
            previous_catalog=previous_catalog,
            output_name="missing-frozen",
        )
        self.assertEqual(result["decision"]["status"], "frozen")
        self.assertEqual(result["active"]["contract_sha256"], baseline["contract_sha256"])
        active = json.loads((output / "active" / "library-version-contract.json").read_text())
        self.assertEqual(active["contract_sha256"], baseline["contract_sha256"])
        self.assertIn("missing-validation", {item["code"] for item in result["decision"]["blockers"]})

    def test_regression_is_structured_and_does_not_move_active(self) -> None:
        source_sha = "a" * 64
        baseline = contract({"3.13.14": {"status": "candidate", "source": source(source_sha)}})
        baseline_path = write_json(self.root / "regression-legacy.json", baseline)
        _initial, previous_catalog = self.run_promotion(
            baseline,
            delta(baseline["contract_sha256"], baseline["contract_sha256"], baseline=False),
            legacy_baseline=baseline_path,
            output_name="regression-previous",
        )
        candidate = contract({"3.13.14": {"status": "unbuildable", "reason": "source removed"}})
        regression = {
            "library": "demo",
            "version": "1.0",
            "python_version": "3.13.14",
            "status": "unbuildable",
            "previous_status": "candidate",
            "reason": "source removed",
        }
        unbuildable = {
            key: value for key, value in regression.items() if key != "previous_status"
        }
        result, output = self.run_promotion(
            candidate,
            delta(
                baseline["contract_sha256"],
                candidate["contract_sha256"],
                baseline=False,
                regressions=[regression],
                new_unbuildable=[unbuildable],
            ),
            previous_catalog=previous_catalog,
            output_name="regression-frozen",
        )
        self.assertEqual(result["decision"]["status"], "frozen")
        self.assertEqual(result["active"]["contract_sha256"], baseline["contract_sha256"])
        evidence = json.loads(
            (
                output
                / "candidates"
                / candidate["contract_sha256"]
                / "promotion-evidence.v1.json"
            ).read_text()
        )
        self.assertEqual(evidence["delta"]["regressions"], [regression])
        self.assertEqual(evidence["delta"]["new_unbuildable"], [unbuildable])

    def test_new_unbuildable_evidence_does_not_block_other_promotion(self) -> None:
        baseline = contract({"3.13.14": {"status": "not-applicable", "reason": "requires newer Python"}})
        baseline_path = write_json(self.root / "unbuildable-legacy.json", baseline)
        _initial, previous_catalog = self.run_promotion(
            baseline,
            delta(baseline["contract_sha256"], baseline["contract_sha256"], baseline=False),
            legacy_baseline=baseline_path,
            output_name="unbuildable-previous",
        )
        unbuildable = {
            "library": "demo",
            "version": "1.0",
            "python_version": "3.13.14",
            "status": "unbuildable",
            "reason": "native wheels are not static inputs",
            "artifacts": ["demo-1.0-cp313-win_amd64.whl"],
        }
        candidate = contract(
            {
                "3.13.14": {
                    "status": "unbuildable",
                    "reason": unbuildable["reason"],
                    "artifacts": unbuildable["artifacts"],
                }
            }
        )
        result, _output = self.run_promotion(
            candidate,
            delta(
                baseline["contract_sha256"],
                candidate["contract_sha256"],
                baseline=False,
                new_unbuildable=[unbuildable],
            ),
            matrix_payload={"include": []},
            previous_catalog=previous_catalog,
            output_name="unbuildable-promoted",
        )
        self.assertEqual(result["decision"]["status"], "promoted")
        self.assertEqual(result["active"]["promotion_basis"], "unbuildable-evidence-update")

    def test_preview_never_moves_active(self) -> None:
        baseline = contract({"3.13.14": {"status": "not-applicable", "reason": "old"}})
        baseline_path = write_json(self.root / "preview-legacy.json", baseline)
        _initial, previous_catalog = self.run_promotion(
            baseline,
            delta(baseline["contract_sha256"], baseline["contract_sha256"], baseline=False),
            legacy_baseline=baseline_path,
            output_name="preview-previous",
        )
        candidate = contract({"3.13.14": {"status": "unbuildable", "reason": "new"}})
        result, _output = self.run_promotion(
            candidate,
            delta(
                baseline["contract_sha256"],
                candidate["contract_sha256"],
                baseline=False,
                new_unbuildable=[
                    {
                        "library": "demo",
                        "version": "1.0",
                        "python_version": "3.13.14",
                        "status": "unbuildable",
                        "reason": "new",
                    }
                ],
            ),
            mode="preview",
            matrix_payload={"include": []},
            previous_catalog=previous_catalog,
            output_name="preview",
        )
        self.assertEqual(result["decision"]["status"], "eligible")
        self.assertEqual(result["active"]["contract_sha256"], baseline["contract_sha256"])
        self.assertEqual(result["proposed_active"]["contract_sha256"], candidate["contract_sha256"])

    def test_overflow_deferral_keeps_last_known_good_and_passes_gate(self) -> None:
        baseline = contract({"3.13.14": {"status": "unbuildable", "reason": "not integrated"}})
        baseline_path = write_json(self.root / "deferred-legacy.json", baseline)
        _initial, previous_catalog = self.run_promotion(
            baseline,
            delta(baseline["contract_sha256"], baseline["contract_sha256"], baseline=False),
            legacy_baseline=baseline_path,
            output_name="deferred-previous",
        )
        source_sha = "a" * 64
        candidate = contract({"3.13.14": {"status": "candidate", "source": source(source_sha)}})
        result, output = self.run_promotion(
            candidate,
            delta(
                baseline["contract_sha256"],
                candidate["contract_sha256"],
                baseline=False,
                new_candidates=[candidate_record(source_sha)],
            ),
            matrix_payload={
                "include": [],
                "deferred": {
                    "reason": "weekly-history-shards",
                    "candidate_count": 1,
                    "contract_sha256": candidate["contract_sha256"],
                    "matrix_limit": 0,
                    "max_candidates_per_batch": 1,
                    "incremental_candidate_limit": 0,
                },
            },
            previous_catalog=previous_catalog,
            output_name="deferred-candidate",
        )
        self.assertEqual(result["decision"]["status"], "frozen")
        self.assertEqual(result["decision"]["gate"], "failed")
        self.assertIn(
            "invalid-history-deferral",
            {record["code"] for record in result["decision"]["blockers"]},
        )
        self.assertEqual(result["active"]["contract_sha256"], baseline["contract_sha256"])

        deferred = {
            "reason": "weekly-history-shards",
            "candidate_count": 1,
            "contract_sha256": candidate["contract_sha256"],
            "matrix_limit": 1,
            "max_candidates_per_batch": 1,
            "incremental_candidate_limit": 1,
        }
        # A real overflow must be larger than its matrix limit. Model two
        # exact candidates without weakening the production invariant.
        second = candidate_record(source_sha)
        second["version"] = "1.1"
        second["source"] = {**second["source"], "filename": "demo-1.1.tar.gz"}
        candidate["libraries"]["demo"]["versions"]["1.1"] = {
            "targets": {"3.13.14": {"status": "candidate", "source": second["source"]}}
        }
        candidate["status_counts"]["candidate"] = 2
        candidate["contract_sha256"] = contract_module._contract_sha256(
            {key: value for key, value in candidate.items() if key != "contract_sha256"}
        )
        deferred["candidate_count"] = 2
        deferred["contract_sha256"] = candidate["contract_sha256"]
        result, output = self.run_promotion(
            candidate,
            delta(
                baseline["contract_sha256"],
                candidate["contract_sha256"],
                baseline=False,
                new_candidates=[candidate_record(source_sha), second],
            ),
            matrix_payload={"include": [], "deferred": deferred},
            previous_catalog=previous_catalog,
            output_name="deferred-valid",
        )
        self.assertEqual(result["decision"]["status"], "deferred")
        self.assertEqual(result["decision"]["gate"], "passed")
        self.assertEqual(result["active"]["contract_sha256"], baseline["contract_sha256"])
        self.assertIsNone(result["proposed_active"])
        evidence = json.loads(
            (
                output
                / "candidates"
                / candidate["contract_sha256"]
                / "promotion-evidence.v1.json"
            ).read_text()
        )
        self.assertEqual(evidence["validation"]["deferred"], deferred)

        for label, updates in (
            (
                "oversized-batch",
                {"max_candidates_per_batch": 3, "incremental_candidate_limit": 3},
            ),
            ("capacity-mismatch", {"max_candidates_per_batch": 2}),
            ("not-overflow", {"incremental_candidate_limit": 2}),
        ):
            with self.subTest(label=label):
                tampered = {**deferred, **updates}
                invalid, _invalid_output = self.run_promotion(
                    candidate,
                    delta(
                        baseline["contract_sha256"],
                        candidate["contract_sha256"],
                        baseline=False,
                        new_candidates=[candidate_record(source_sha), second],
                    ),
                    matrix_payload={"include": [], "deferred": tampered},
                    previous_catalog=previous_catalog,
                    output_name=f"deferred-{label}",
                )
                self.assertEqual(invalid["decision"]["status"], "frozen")
                self.assertIn(
                    "invalid-history-deferral",
                    {record["code"] for record in invalid["decision"]["blockers"]},
                )

    def test_tampered_delta_cannot_hide_a_regression(self) -> None:
        source_sha = "a" * 64
        baseline = contract({"3.13.14": {"status": "candidate", "source": source(source_sha)}})
        baseline_path = write_json(self.root / "tampered-legacy.json", baseline)
        _initial, previous_catalog = self.run_promotion(
            baseline,
            delta(baseline["contract_sha256"], baseline["contract_sha256"], baseline=False),
            legacy_baseline=baseline_path,
            output_name="tampered-previous",
        )
        candidate = contract({"3.13.14": {"status": "unbuildable", "reason": "removed"}})
        forged_delta = delta(
            baseline["contract_sha256"],
            candidate["contract_sha256"],
            baseline=False,
        )
        result, output = self.run_promotion(
            candidate,
            forged_delta,
            matrix_payload={"include": []},
            previous_catalog=previous_catalog,
            output_name="tampered-frozen",
        )
        self.assertEqual(result["decision"]["status"], "frozen")
        codes = {record["code"] for record in result["decision"]["blockers"]}
        self.assertIn("delta-integrity-mismatch", codes)
        self.assertIn("candidate-regression", codes)
        evidence = json.loads(
            (
                output
                / "candidates"
                / candidate["contract_sha256"]
                / "promotion-evidence.v1.json"
            ).read_text()
        )
        self.assertEqual(len(evidence["delta"]["regressions"]), 1)

    def test_verified_regression_is_labeled_and_freezes_last_known_good(self) -> None:
        baseline = contract({"3.13.14": {"status": "unbuildable", "reason": "not integrated"}})
        baseline_path = write_json(self.root / "verified-legacy.json", baseline)
        _initial, legacy_catalog = self.run_promotion(
            baseline,
            delta(baseline["contract_sha256"], baseline["contract_sha256"], baseline=False),
            legacy_baseline=baseline_path,
            output_name="verified-legacy-catalog",
        )

        source_sha = "a" * 64
        verified_contract = contract(
            {"3.13.14": {"status": "candidate", "source": source(source_sha)}}
        )
        candidate = candidate_record(source_sha)
        _promoted, verified_catalog = self.run_promotion(
            verified_contract,
            delta(
                baseline["contract_sha256"],
                verified_contract["contract_sha256"],
                baseline=False,
                new_candidates=[candidate],
            ),
            matrix_payload={"include": [matrix_record(source_sha)]},
            validation_report=report(source_sha),
            previous_catalog=legacy_catalog,
            output_name="verified-active-catalog",
        )

        failed_contract = contract(
            {
                "3.13.14": {
                    "status": "unbuildable",
                    "reason": "upstream now ships native wheels only",
                    "artifacts": ["demo-1.0-cp313-win_amd64.whl"],
                }
            }
        )
        unbuildable = {
            "library": "demo",
            "version": "1.0",
            "python_version": "3.13.14",
            "status": "unbuildable",
            "reason": "upstream now ships native wheels only",
            "artifacts": ["demo-1.0-cp313-win_amd64.whl"],
        }
        regression = {**unbuildable, "previous_status": "candidate"}
        result, output = self.run_promotion(
            failed_contract,
            delta(
                verified_contract["contract_sha256"],
                failed_contract["contract_sha256"],
                baseline=False,
                new_unbuildable=[unbuildable],
                regressions=[regression],
            ),
            previous_catalog=verified_catalog,
            output_name="verified-regression-frozen",
        )
        self.assertEqual(result["decision"]["status"], "frozen")
        self.assertEqual(result["active"]["contract_sha256"], verified_contract["contract_sha256"])
        evidence = json.loads(
            (
                output
                / "candidates"
                / failed_contract["contract_sha256"]
                / "promotion-evidence.v1.json"
            ).read_text()
        )
        self.assertEqual(evidence["delta"]["verified_regressions"], [regression])


if __name__ == "__main__":
    unittest.main(verbosity=2)
