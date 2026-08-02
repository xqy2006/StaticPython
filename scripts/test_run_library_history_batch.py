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
history_evidence = load_script("library_history_evidence")
runner = load_script("run_library_history_batch")


def contract() -> dict:
    versions = {}
    for version, digit in (("1.0", "1"), ("2.0", "2")):
        versions[version] = {
            "targets": {
                "3.13.14": {
                    "status": "candidate",
                    "source": {
                        "filename": f"demo-{version}.tar.gz",
                        "packagetype": "sdist",
                        "requires_python": ">=3.11",
                        "url": f"https://files.pythonhosted.org/demo-{version}.tar.gz",
                        "sha256": digit * 64,
                    },
                }
            }
        }
    payload = {
        "schema_version": 1,
        "target_python_versions": ["3.13.14"],
        "libraries": {
            "demo": {
                "source_provider": "pypi",
                "project_name": "demo-project",
                "minimum_release_version": None,
                "versions": versions,
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


class RunLibraryHistoryBatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.contract = contract()
        self.manifest = history_batches.prepare_history_batches(
            self.contract,
            {"demo": "pure-python"},
            pure_batch_size=2,
        )
        self.batch = self.manifest["batches"][0]
        self.runtime_sdk = self.root / "runtime.zip"
        self.runtime_sdk.write_bytes(b"runtime-sdk")
        self.result_root = self.root / "result"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def context(self) -> dict:
        return {
            "runtime_sdk": self.runtime_sdk,
            "build_root": self.root / "build",
            "source_cache": self.root / "sources",
            "result_root": self.result_root,
            "build_workers": 2,
            "provenance": {"artifact": "batch-artifact"},
        }

    def passed_execution(
        self, record: dict, context: dict
    ) -> tuple[dict, list[Path]]:
        combination_root = Path(context["result_root"]) / record["version"]
        verifier_path = combination_root / "staticpython-pack-verify-report.json"
        verifier_path.parent.mkdir(parents=True, exist_ok=True)
        verifier_path.write_text(
            json.dumps({"status": "passed", "version": record["version"]}),
            encoding="utf-8",
        )
        pack_metadata_path = combination_root / "pack-metadata.json"
        pack_metadata_path.write_text(
            json.dumps(
                {
                    "name": record["library"],
                    "version": record["version"],
                    "cpython_version": record["python_version"],
                    "verification": {"status": "passed"},
                }
            ),
            encoding="utf-8",
        )
        combination = {
            "schema_version": 1,
            "kind": history_evidence.COMBINATION_EVIDENCE_KIND,
            "library": record["library"],
            "version": record["version"],
            "python_version": record["python_version"],
            "source_sha256": record["source_sha256"],
            "runtime_sdk_sha256": context["runtime_sdk_sha256"],
            "pack_sha256": "a" * 64,
            "status": "passed",
        }
        combination["evidence_sha256"] = history_evidence.canonical_sha256(
            combination
        )
        combination_path = combination_root / "combination-evidence.v1.json"
        combination_path.write_text(json.dumps(combination), encoding="utf-8")
        return (
            {
                "library": record["library"],
                "version": record["version"],
                "python_version": record["python_version"],
                "source_sha256": record["source_sha256"],
                "pack_sha256": "a" * 64,
                "runtime_sdk_sha256": context["runtime_sdk_sha256"],
                "verifier_report_sha256": history_evidence.file_sha256(
                    verifier_path
                ),
                "combination_evidence_sha256": combination["evidence_sha256"],
                "status": "passed",
            },
            [verifier_path, pack_metadata_path, combination_path],
        )

    def test_runner_records_every_passed_combination_and_hashed_files(self) -> None:
        def fake_executor(record: dict, context: dict) -> tuple[dict, list[Path]]:
            return self.passed_execution(record, context)

        evidence = runner.run_history_batch(
            self.contract,
            self.manifest,
            self.batch["batch_id"],
            self.context(),
            executor=fake_executor,
        )
        self.assertEqual(evidence["status"], "passed")
        self.assertEqual(len(evidence["results"]), 2)
        self.assertEqual(len(evidence["files"]), 6)
        history_evidence.validate_batch_evidence(
            evidence,
            self.result_root,
            self.contract,
            self.manifest,
            self.batch,
        )
        unlinked = json.loads(json.dumps(evidence))
        pack_metadata_hash = next(
            record["sha256"]
            for record in unlinked["files"]
            if Path(record["path"]).name == "pack-metadata.json"
        )
        unlinked["results"][0]["verifier_report_sha256"] = pack_metadata_hash
        unlinked["evidence_sha256"] = history_evidence.canonical_sha256(
            {
                key: value
                for key, value in unlinked.items()
                if key != "evidence_sha256"
            }
        )
        with self.assertRaisesRegex(RuntimeError, "not hash-linked"):
            history_evidence.validate_batch_evidence(
                unlinked,
                self.result_root,
                self.contract,
                self.manifest,
                self.batch,
            )

    def test_runner_continues_after_failure_and_returns_structured_evidence(
        self,
    ) -> None:
        attempted = []

        def fake_executor(record: dict, context: dict) -> tuple[dict, list[Path]]:
            attempted.append(record["version"])
            if record["version"] == "1.0":
                raise RuntimeError("strict patch anchor mismatch")
            return self.passed_execution(record, context)

        evidence = runner.run_history_batch(
            self.contract,
            self.manifest,
            self.batch["batch_id"],
            self.context(),
            executor=fake_executor,
        )
        self.assertEqual(attempted, ["1.0", "2.0"])
        self.assertEqual(evidence["status"], "failed")
        self.assertEqual(evidence["results"][0]["failure"]["type"], "RuntimeError")
        history_evidence.validate_batch_evidence(
            evidence,
            self.result_root,
            self.contract,
            self.manifest,
            self.batch,
        )

    def test_verifier_report_requires_runtime_pack_pe_and_smoke_evidence(self) -> None:
        pack = self.root / "demo.zip"
        pack.write_bytes(b"pack")
        runtime_sha = history_evidence.file_sha256(self.runtime_sdk)
        pack_sha = history_evidence.file_sha256(pack)
        report = {
            "status": "passed",
            "failures": [],
            "runtime_sdk": {
                "archive_sha256": runtime_sha,
                "cpython_version": "3.13.14",
                "runtime_abi": "staticpython-pack-v1-cp313",
            },
            "packs": [{"name": "demo", "version": "1.0", "sha256": pack_sha}],
            "pe_audit": {"status": "passed", "dependencies": ["KERNEL32.dll"]},
            "integration_smoke_tests": [{"name": "import", "status": "passed"}],
            "executable_sha256": "f" * 64,
        }
        result = runner._validate_verifier_report(
            report,
            runtime_sdk_sha256=runtime_sha,
            pack_path=pack,
            library="demo",
            version="1.0",
            python_version="3.13.14",
        )
        self.assertEqual(result["pack_sha256"], pack_sha)
        report["pe_audit"]["dependencies"] = []
        with self.assertRaisesRegex(RuntimeError, "PE dependency"):
            runner._validate_verifier_report(
                report,
                runtime_sdk_sha256=runtime_sha,
                pack_path=pack,
                library="demo",
                version="1.0",
                python_version="3.13.14",
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
