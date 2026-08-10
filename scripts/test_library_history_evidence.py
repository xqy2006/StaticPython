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


def load_script(name: str):
    spec = importlib.util.spec_from_file_location(
        name, REPO_ROOT / "scripts" / f"{name}.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


contract_module = load_script("library_version_contract")
history_batches = load_script("prepare_library_history_batches")
evidence_module = load_script("library_history_evidence")


def source(version: str) -> dict:
    return {
        "filename": f"demo-{version}.tar.gz",
        "packagetype": "sdist",
        "requires_python": ">=3.11",
        "url": f"https://files.pythonhosted.org/demo-{version}.tar.gz",
        "sha256": (version.replace(".", "") + "a" * 64)[:64],
    }


def contract() -> dict:
    payload = {
        "schema_version": 1,
        "target_python_versions": ["3.13.14"],
        "libraries": {
            "demo": {
                "source_provider": "pypi",
                "project_name": "demo-project",
                "minimum_release_version": None,
                "versions": {
                    version: {
                        "targets": {
                            "3.13.14": {
                                "status": "candidate",
                                "source": source(version),
                            }
                        }
                    }
                    for version in ("1.0", "2.0")
                },
            }
        },
        "status_counts": {
            "candidate": 2,
            "configured": 0,
            "not-applicable": 0,
            "unbuildable": 0,
        },
    }
    payload["contract_sha256"] = contract_module._contract_sha256(payload)
    return payload


def manifest(contract_payload: dict) -> dict:
    return history_batches.prepare_history_batches(
        contract_payload,
        {"demo": "pure-python"},
        pure_batch_size=1,
        max_jobs_per_run=1,
    )


def write_json(path: Path, payload: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


class LibraryHistoryEvidenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.contract = contract()
        self.manifest = manifest(self.contract)
        self.contract_path = write_json(
            self.root / "library-version-contract.json", self.contract
        )
        self.manifest_path = write_json(
            self.root / "library-history-manifest.json", self.manifest
        )

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def write_batch_evidence(
        self,
        batch: dict,
        *,
        status: str = "passed",
        evidence_parent: Path | None = None,
    ) -> Path:
        batch_root = (evidence_parent or (self.root / "batch-evidence")) / batch[
            "batch_id"
        ]
        results = []
        files = []
        for record in evidence_module.expected_combinations(self.contract, batch):
            result = {
                "library": record["library"],
                "version": record["version"],
                "python_version": record["python_version"],
                "source_sha256": record["source_sha256"],
                "status": status,
            }
            if status == "failed":
                result["failure"] = {
                    "type": "RuntimeError",
                    "message": "patch anchor drift",
                }
            else:
                combination_root = batch_root / record["version"]
                verifier_path = write_json(
                    combination_root / "staticpython-pack-verify-report.json",
                    {"status": "passed", "version": record["version"]},
                )
                pack_metadata_path = write_json(
                    combination_root / "pack-metadata.json",
                    {
                        "name": record["library"],
                        "version": record["version"],
                        "cpython_version": record["python_version"],
                        "verification": {"status": "passed"},
                    },
                )
                combination = {
                    "schema_version": 1,
                    "kind": evidence_module.COMBINATION_EVIDENCE_KIND,
                    "library": record["library"],
                    "version": record["version"],
                    "python_version": record["python_version"],
                    "source_sha256": record["source_sha256"],
                    "runtime_sdk_sha256": "e" * 64,
                    "pack_sha256": "a" * 64,
                    "status": "passed",
                }
                combination["evidence_sha256"] = evidence_module.canonical_sha256(
                    combination
                )
                combination_path = write_json(
                    combination_root / "combination-evidence.v1.json", combination
                )
                result.update(
                    {
                        "pack_sha256": "a" * 64,
                        "runtime_sdk_sha256": "e" * 64,
                        "verifier_report_sha256": evidence_module.file_sha256(
                            verifier_path
                        ),
                        "combination_evidence_sha256": combination[
                            "evidence_sha256"
                        ],
                    }
                )
                for path in (
                    verifier_path,
                    pack_metadata_path,
                    combination_path,
                ):
                    files.append(
                        {
                            "path": path.relative_to(batch_root).as_posix(),
                            "sha256": evidence_module.file_sha256(path),
                        }
                    )
            results.append(result)
        payload = {
            "schema_version": 1,
            "kind": evidence_module.BATCH_EVIDENCE_KIND,
            "contract_sha256": self.manifest["contract_sha256"],
            "manifest_sha256": self.manifest["manifest_sha256"],
            "batch_id": batch["batch_id"],
            "batch_sha256": batch["batch_sha256"],
            "shard_index": batch["run_shard_index"],
            "runtime_sdk_sha256": "e" * 64,
            "results": results,
            "files": files,
            "status": status,
            "provenance": {"artifact": f"batch-{batch['batch_id']}"},
        }
        payload["evidence_sha256"] = evidence_module.canonical_sha256(payload)
        return write_json(
            batch_root / "library-history-batch-evidence.v1.json", payload
        )

    def finalize_all_shards(self) -> Path:
        shard_root = self.root / "shards"
        for shard in self.manifest["run_shards"]:
            batch_root = self.root / f"batch-evidence-shard-{shard['shard_index']}"
            for batch in self.manifest["batches"]:
                if batch["run_shard_index"] == shard["shard_index"]:
                    self.write_batch_evidence(batch, evidence_parent=batch_root)
            evidence_module.finalize_shard(
                self.contract_path,
                self.manifest_path,
                batch_root,
                shard["shard_index"],
                shard_root
                / f"shard-{shard['shard_index']}"
                / "library-history-shard-evidence.v1.json",
                provenance={"run_id": "123"},
            )
        return shard_root

    def test_prepare_shard_matrix_is_bound_to_manifest_and_runtime(self) -> None:
        plan, matrix = evidence_module.prepare_shard_plan(
            self.contract,
            self.manifest,
            0,
            plan_artifact="library-history-plan-demo",
            artifact_suffix="a2",
        )
        self.assertEqual(len(matrix["include"]), 1)
        self.assertEqual(
            matrix["include"][0]["runtime_artifact"],
            evidence_module.runtime_artifact_name(
                self.contract["contract_sha256"], "3.13.14", "a2"
            ),
        )
        with self.assertRaisesRegex(RuntimeError, "suffix is invalid"):
            evidence_module.runtime_artifact_name(
                self.contract["contract_sha256"], "3.13.14", "../attempt-2"
            )
        self.assertEqual(
            plan["shard"]["shard_sha256"],
            self.manifest["run_shards"][0]["shard_sha256"],
        )

    def test_complete_evidence_promotes_support_directory(self) -> None:
        shard_root = self.finalize_all_shards()
        output = self.root / "catalog"
        index = evidence_module.promote_support_catalog(
            self.contract_path,
            self.manifest_path,
            shard_root,
            output,
            mode="promote",
            provenance={"source_commit": "c" * 40},
        )
        self.assertEqual(index["decision"]["status"], "promoted")
        self.assertEqual(
            index["active"]["manifest_sha256"], self.manifest["manifest_sha256"]
        )
        active = json.loads(
            (output / Path(index["active"]["support"])).read_text()
        )
        self.assertEqual(active["status"], "verified")
        self.assertEqual(active["verified_combination_count"], 2)
        self.assertEqual(
            index["active"]["directory"], index["candidate"]["directory"]
        )
        for field in ("contract", "manifest", "support", "evidence", "shards"):
            self.assertTrue((output / Path(index["active"][field])).exists())

    def test_missing_shard_freezes_and_retains_last_known_good(self) -> None:
        complete_shards = self.finalize_all_shards()
        previous = self.root / "previous-catalog"
        evidence_module.promote_support_catalog(
            self.contract_path,
            self.manifest_path,
            complete_shards,
            previous,
            mode="promote",
        )
        incomplete = self.root / "incomplete-shards"
        incomplete.mkdir()
        first_shard = next(
            complete_shards.rglob("library-history-shard-evidence.v1.json")
        )
        target = incomplete / "one" / first_shard.name
        target.parent.mkdir()
        target.write_bytes(first_shard.read_bytes())
        frozen_root = self.root / "frozen-catalog"
        index = evidence_module.promote_support_catalog(
            self.contract_path,
            self.manifest_path,
            incomplete,
            frozen_root,
            previous_catalog_root=previous,
            mode="promote",
        )
        self.assertEqual(index["decision"]["status"], "frozen")
        self.assertEqual(
            index["active"]["manifest_sha256"], self.manifest["manifest_sha256"]
        )
        candidate_support = json.loads(
            (frozen_root / Path(index["candidate"]["support"])).read_text()
        )
        self.assertEqual(candidate_support["status"], "failed")
        self.assertLess(candidate_support["verified_combination_count"], 2)
        self.assertNotEqual(
            index["active"]["directory"], index["candidate"]["directory"]
        )
        retained_support = json.loads(
            (frozen_root / Path(index["active"]["support"])).read_text()
        )
        self.assertEqual(retained_support["status"], "verified")
        for field in ("contract", "manifest", "support", "evidence", "shards"):
            self.assertTrue((frozen_root / Path(index["active"][field])).exists())

    def test_tampered_last_known_good_directory_is_rejected(self) -> None:
        previous = self.root / "previous-catalog"
        previous_index = evidence_module.promote_support_catalog(
            self.contract_path,
            self.manifest_path,
            self.finalize_all_shards(),
            previous,
            mode="promote",
        )
        shard_path = next(
            (previous / Path(previous_index["active"]["shards"])).iterdir()
        )
        shard_path.write_text("tampered\n", encoding="utf-8")
        empty_shards = self.root / "no-current-shards"
        empty_shards.mkdir()
        with self.assertRaisesRegex(RuntimeError, "shard evidence"):
            evidence_module.promote_support_catalog(
                self.contract_path,
                self.manifest_path,
                empty_shards,
                self.root / "rejected-catalog",
                previous_catalog_root=previous,
                mode="promote",
            )

    def test_preview_records_proposal_without_active_support(self) -> None:
        index = evidence_module.promote_support_catalog(
            self.contract_path,
            self.manifest_path,
            self.finalize_all_shards(),
            self.root / "preview-catalog",
            mode="preview",
        )
        self.assertEqual(index["decision"]["status"], "eligible")
        self.assertIsNone(index["active"])
        self.assertEqual(
            index["proposed_active"]["manifest_sha256"],
            self.manifest["manifest_sha256"],
        )

    def test_smoke_selection_can_never_promote_active_support(self) -> None:
        self.manifest = history_batches.prepare_history_batches(
            self.contract,
            {"demo": "pure-python"},
            smoke_library="demo",
            smoke_python_series="3.13",
        )
        self.manifest_path = write_json(
            self.root / "smoke-library-history-manifest.json", self.manifest
        )
        index = evidence_module.promote_support_catalog(
            self.contract_path,
            self.manifest_path,
            self.finalize_all_shards(),
            self.root / "smoke-promote-catalog",
            mode="promote",
        )
        self.assertEqual(index["decision"]["status"], "frozen")
        self.assertIsNone(index["active"])
        self.assertIn(
            "non-full-history-selection",
            {record["code"] for record in index["decision"]["blockers"]},
        )

    def test_pull_request_smoke_passes_without_becoming_eligible(self) -> None:
        self.manifest = history_batches.prepare_history_batches(
            self.contract,
            {"demo": "pure-python"},
            smoke_library="demo",
            smoke_python_series="3.13",
        )
        self.manifest_path = write_json(
            self.root / "smoke-preview-manifest.json", self.manifest
        )
        index = evidence_module.promote_support_catalog(
            self.contract_path,
            self.manifest_path,
            self.finalize_all_shards(),
            self.root / "smoke-preview-catalog",
            mode="preview",
        )
        self.assertEqual(index["decision"]["status"], "preview-passed")
        self.assertEqual(index["decision"]["gate"], "passed")
        self.assertIsNone(index["active"])
        self.assertIsNone(index["proposed_active"])

    def test_empty_full_history_can_never_promote_active_support(self) -> None:
        empty_contract = contract()
        empty_contract["libraries"]["demo"]["versions"] = {}
        empty_contract["status_counts"] = {
            "candidate": 0,
            "configured": 0,
            "not-applicable": 0,
            "unbuildable": 0,
        }
        empty_contract["contract_sha256"] = contract_module._contract_sha256(
            {key: value for key, value in empty_contract.items() if key != "contract_sha256"}
        )
        empty_manifest = history_batches.prepare_history_batches(
            empty_contract,
            {"demo": "pure-python"},
        )
        empty_contract_path = write_json(
            self.root / "empty-contract.json", empty_contract
        )
        empty_manifest_path = write_json(
            self.root / "empty-manifest.json", empty_manifest
        )
        empty_shards = self.root / "empty-shards"
        empty_shards.mkdir()
        index = evidence_module.promote_support_catalog(
            empty_contract_path,
            empty_manifest_path,
            empty_shards,
            self.root / "empty-catalog",
            mode="promote",
        )
        self.assertEqual(index["decision"]["status"], "frozen")
        self.assertIsNone(index["active"])
        self.assertIn(
            "empty-full-history-selection",
            {record["code"] for record in index["decision"]["blockers"]},
        )

    def test_forged_shard_aggregate_cannot_promote(self) -> None:
        shard_root = self.finalize_all_shards()
        shard_path = next(
            shard_root.rglob("library-history-shard-evidence.v1.json")
        )
        forged = json.loads(shard_path.read_text(encoding="utf-8"))
        forged["batches"] = []
        forged["evidence_sha256"] = evidence_module.canonical_sha256(
            {key: value for key, value in forged.items() if key != "evidence_sha256"}
        )
        write_json(shard_path, forged)
        index = evidence_module.promote_support_catalog(
            self.contract_path,
            self.manifest_path,
            shard_root,
            self.root / "forged-catalog",
            mode="promote",
        )
        self.assertEqual(index["decision"]["status"], "frozen")
        self.assertIsNone(index["active"])
        self.assertIn(
            "invalid-shard-evidence",
            {record["code"] for record in index["decision"]["blockers"]},
        )

    def test_runtime_sdk_hash_drift_across_shards_freezes_promotion(self) -> None:
        shard_root = self.finalize_all_shards()
        shard_paths = sorted(
            shard_root.rglob("library-history-shard-evidence.v1.json")
        )
        self.assertGreaterEqual(len(shard_paths), 2)
        drifted = json.loads(shard_paths[1].read_text(encoding="utf-8"))
        drifted["batches"][0]["runtime_sdk_sha256"] = "d" * 64
        for result in drifted["batches"][0]["results"]:
            if result["status"] == "passed":
                result["runtime_sdk_sha256"] = "d" * 64
        drifted["evidence_sha256"] = evidence_module.canonical_sha256(
            {key: value for key, value in drifted.items() if key != "evidence_sha256"}
        )
        write_json(shard_paths[1], drifted)
        index = evidence_module.promote_support_catalog(
            self.contract_path,
            self.manifest_path,
            shard_root,
            self.root / "runtime-drift-catalog",
            mode="promote",
        )
        self.assertEqual(index["decision"]["status"], "frozen")
        self.assertIn(
            "runtime-sdk-hash-mismatch",
            {record["code"] for record in index["decision"]["blockers"]},
        )

    def test_tampered_batch_file_becomes_structured_failed_shard(self) -> None:
        batch = self.manifest["batches"][0]
        evidence_path = self.write_batch_evidence(batch)
        verifier_path = next(
            evidence_path.parent.rglob("staticpython-pack-verify-report.json")
        )
        verifier_path.write_text("tampered\n", encoding="utf-8")
        shard_path = self.root / "tampered-shard.json"
        shard = evidence_module.finalize_shard(
            self.contract_path,
            self.manifest_path,
            self.root / "batch-evidence",
            batch["run_shard_index"],
            shard_path,
        )
        self.assertEqual(shard["status"], "failed")
        self.assertIn(
            "invalid-batch-evidence", {item["code"] for item in shard["blockers"]}
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
