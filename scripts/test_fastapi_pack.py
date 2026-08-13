from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build
import libs
from packaging.version import Version


EXPECTED_VERSIONS = {
    "annotated_doc": "0.0.5",
    "annotated_types": "0.8.0",
    "anyio": "4.14.2",
    "fastapi": "0.141.1",
    "idna": "3.18",
    "pydantic": "2.13.4",
    "pydantic_core": "2.46.4",
    "starlette": "1.6.0",
    "typing_extensions": "4.16.0",
    "typing_inspection": "0.4.3",
}


class FastAPIPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(
            (REPO_ROOT / "config.json").read_text(encoding="utf-8")
        )
        cls.catalog = {
            item["name"]: item
            for item in cls.config["third_party_library_catalog"]["libraries"]
        }

    def test_catalog_pins_current_stable_source_and_core_dependencies(self) -> None:
        entry = self.catalog["fastapi"]
        self.assertEqual(entry["release_version"], "0.141.1")
        self.assertEqual(
            entry["source_archive_sha256_by_version"],
            {
                "0.141.1": "e8822fc40db1e1858054d7a949a888695bc9bdce70139178e33bd2871a453ca1"
            },
        )
        self.assertEqual(
            entry["dependencies"],
            [
                "annotated_doc",
                "pydantic",
                "starlette",
                "typing_extensions",
                "typing_inspection",
            ],
        )
        self.assertEqual(
            entry["dependency_constraints"],
            {
                "annotated_doc": ">=0.0.2",
                "pydantic": ">=2.9.0",
                "starlette": ">=0.46.0",
                "typing_extensions": ">=4.8.0",
                "typing_inspection": ">=0.4.2",
            },
        )
        self.assertEqual(entry["license_expression"], "MIT")
        self.assertEqual(
            entry["smoke_tests"],
            [
                {
                    "name": "in-memory-asgi-pydantic-route",
                    "kind": "script",
                    "script": "scripts/fastapi_runtime.py",
                    "timeout": 30,
                }
            ],
        )

    def test_runtime_smoke_exercises_asgi_validation_without_files(self) -> None:
        smoke_path = REPO_ROOT / "scripts" / "fastapi_runtime.py"
        source = smoke_path.read_text(encoding="utf-8")
        compile(source, str(smoke_path), "exec")
        self.assertIn("await app(scope, receive, send)", source)
        self.assertIn('assert status == 200', source)
        self.assertIn('assert status == 422', source)
        self.assertIn('payload == {"name": "widget", "price": 2.5}', source)
        self.assertNotIn("tempfile", source)
        self.assertNotIn("open(", source)

    def test_catalog_hash_pin_reaches_library_integration(self) -> None:
        integration = libs._integration_from_catalog_entry(self.catalog["fastapi"])
        self.assertEqual(integration.release_version, "0.141.1")
        self.assertEqual(
            integration.source_archive_sha256_by_version,
            {
                "0.141.1": "e8822fc40db1e1858054d7a949a888695bc9bdce70139178e33bd2871a453ca1"
            },
        )
        self.assertEqual(integration.python_packages, ["fastapi"])
        self.assertTrue(integration.auto_resolve_dependencies)

    def test_experimental_profile_locks_complete_dependency_closure(self) -> None:
        profile = self.config["profiles"]["fastapi-experimental"]
        self.assertEqual(profile["third_party_libraries"], ["fastapi"])
        self.assertEqual(
            profile["third_party_library_version_overrides"],
            EXPECTED_VERSIONS,
        )
        self.assertNotIn(
            "fastapi",
            self.config["profiles"]["full"]["third_party_libraries"],
        )

    def test_starlette_and_anyio_catalog_dependencies_are_explicit(self) -> None:
        self.assertEqual(
            self.catalog["starlette"]["dependencies"],
            ["anyio", "typing_extensions"],
        )
        self.assertEqual(
            self.catalog["starlette"]["dependency_constraints"],
            {"anyio": ">=3.6.2,<5", "typing_extensions": ">=4.10.0"},
        )
        self.assertEqual(
            self.catalog["anyio"]["dependencies"],
            ["idna", "typing_extensions"],
        )
        self.assertEqual(
            self.catalog["anyio"]["dependency_constraints"],
            {"idna": ">=2.8", "typing_extensions": ">=4.5"},
        )

    def test_selected_pack_set_contains_transitive_runtime_dependencies(self) -> None:
        _name, profile = build.resolve_profile(self.config, "fastapi-experimental")
        catalog = build.profile_library_catalog(
            self.config,
            profile,
            "third_party_library_catalog",
        )
        selected = libs.load_integrations(
            build.LIB_PATCH_ROOT,
            ["fastapi"],
            target_version=Version("3.13.15"),
            version_overrides=profile["third_party_library_version_overrides"],
            library_catalog=catalog,
        )
        self.assertEqual(
            {integration.name for integration in selected},
            set(EXPECTED_VERSIONS),
        )

    def test_workflow_runs_fastapi_on_every_supported_cpython_series(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "pydantic-core-static.yml"
        ).read_text(encoding="utf-8")
        push_paths = workflow.split("  pull_request:\n", 1)[0]
        self.assertIn('      - "scripts/test_fastapi_pack.py"', push_paths)
        self.assertIn('      - "scripts/fastapi_runtime.py"', push_paths)
        job = workflow.split("  sdk-linked-fastapi:\n", 1)[1]
        targets = {
            "3.11.15": "cp311",
            "3.12.13": "cp312",
            "3.13.15": "cp313",
            "3.14.7": "cp314",
            "3.15.0rc1": "cp315",
        }
        for version, tag in targets.items():
            with self.subTest(version=version):
                self.assertEqual(job.count(f'cpython_version: "{version}"'), 1)
                self.assertEqual(job.count(f"python_tag: {tag}"), 1)
        self.assertIn(
            "VERIFY_CPYTHON_VERSION: ${{ matrix.cpython_version }}", job
        )
        self.assertIn("pydantic-core-runtime-sdk-${{ matrix.python_tag }}", job)
        self.assertIn("fastapi-static-0.141.1-${{ matrix.python_tag }}", job)
        self.assertNotIn("fastapi-static-0.141.1-cp313", job)

    def test_workflow_reaudits_the_uploaded_fastapi_verifier_pe(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "pydantic-core-static.yml"
        ).read_text(encoding="utf-8")
        job = workflow.split("  sdk-linked-fastapi:\n", 1)[1]
        core_job = workflow.split("  sdk-linked-pydantic-core:\n", 1)[1].split(
            "  sdk-linked-pydantic:\n", 1
        )[0]

        self.assertNotIn("Expected dependency-closure verifier directories", core_job)
        self.assertIn(
            '"$sourceRoot\\PCbuild\\staticpython-pack-verify\\staticpython-pack-verify.exe"',
            core_job,
        )
        self.assertIn("Expected dependency-closure verifier directories", job)
        self.assertIn("$report.verification_mode -ne 'dependency-closure-set'", job)
        self.assertIn("$report.closure_verifications", job)
        self.assertIn("closure-{0:D4}", job)
        self.assertIn("Get-CombinedEvidenceHash", job)
        self.assertIn("$report.pe_audit.executable_sha256", job)
        self.assertIn("$report.pe_audit.map_sha256", job)
        self.assertIn("@($report.pe_audit.main_object_records).Count -ne 0", job)
        self.assertIn("dumpbin /NOLOGO /DEPENDENTS $exePath", job)
        self.assertIn(
            "Compare-Object $reportedDependencies $observedDependencies",
            job,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
