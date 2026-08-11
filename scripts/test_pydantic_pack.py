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


class PydanticPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(
            (REPO_ROOT / "config.json").read_text(encoding="utf-8")
        )
        cls.catalog = {
            item["name"]: item
            for item in cls.config["third_party_library_catalog"]["libraries"]
        }

    def test_catalog_pins_current_stable_source_and_dependency_contract(self) -> None:
        entry = self.catalog["pydantic"]
        self.assertEqual(entry["release_version"], "2.13.4")
        self.assertEqual(
            entry["source_archive_sha256_by_version"],
            {
                "2.13.4": "c40756b57adaa8b1efeeced5c196f3f3b7c435f90e84ea7f443901bec8099ef6"
            },
        )
        self.assertEqual(
            entry["dependencies"],
            [
                "annotated_types",
                "pydantic_core",
                "typing_extensions",
                "typing_inspection",
            ],
        )
        self.assertEqual(
            entry["dependency_constraints"],
            {
                "annotated_types": ">=0.6.0",
                "pydantic_core": "==2.46.4",
                "typing_extensions": ">=4.14.1",
                "typing_inspection": ">=0.4.2",
            },
        )
        self.assertEqual(entry["license_expression"], "MIT")
        self.assertIn("BaseModel", entry["smoke_tests"][0]["code"])
        self.assertIn("model_json_schema", entry["smoke_tests"][0]["code"])

    def test_catalog_hash_pin_reaches_library_integration(self) -> None:
        integration = libs._integration_from_catalog_entry(self.catalog["pydantic"])
        self.assertEqual(integration.project_name, "pydantic")
        self.assertEqual(integration.release_version, "2.13.4")
        self.assertEqual(
            integration.source_archive_sha256_by_version,
            {
                "2.13.4": "c40756b57adaa8b1efeeced5c196f3f3b7c435f90e84ea7f443901bec8099ef6"
            },
        )
        self.assertEqual(integration.python_packages, ["pydantic"])
        self.assertTrue(integration.auto_resolve_dependencies)

    def test_experimental_profile_locks_complete_dependency_closure(self) -> None:
        profile = self.config["profiles"]["pydantic-experimental"]
        self.assertEqual(profile["third_party_libraries"], ["pydantic"])
        self.assertEqual(
            profile["third_party_library_version_overrides"],
            {
                "annotated_types": "0.8.0",
                "pydantic": "2.13.4",
                "pydantic_core": "2.46.4",
                "typing_extensions": "4.16.0",
                "typing_inspection": "0.4.3",
            },
        )
        self.assertNotIn(
            "pydantic",
            self.config["profiles"]["full"]["third_party_libraries"],
        )

    def test_selected_pack_set_contains_all_runtime_dependencies(self) -> None:
        _name, profile = build.resolve_profile(self.config, "pydantic-experimental")
        catalog = build.profile_library_catalog(
            self.config,
            profile,
            "third_party_library_catalog",
        )
        integrations = libs.load_integration_definitions(
            build.LIB_PATCH_ROOT,
            library_catalog=catalog,
        )
        overrides = profile["third_party_library_version_overrides"]
        for integration in integrations:
            if integration.name in overrides:
                integration.release_version = overrides[integration.name]
        selected = libs.select_integrations(integrations, ["pydantic"])
        self.assertEqual(
            {integration.name for integration in selected},
            {
                "annotated_types",
                "pydantic",
                "pydantic_core",
                "typing_extensions",
                "typing_inspection",
            },
        )

    def test_workflow_runs_pydantic_on_every_supported_cpython_series(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "pydantic-core-static.yml"
        ).read_text(encoding="utf-8")
        job = workflow.split("  sdk-linked-pydantic:\n", 1)[1]
        targets = {
            "3.11.15": "cp311",
            "3.12.13": "cp312",
            "3.13.15": "cp313",
            "3.14.7": "cp314",
            "3.15.0rc1": "cp315",
        }
        for version, tag in targets.items():
            with self.subTest(version=version):
                self.assertIn(f'cpython_version: "{version}"', job)
                self.assertIn(f"python_tag: {tag}", job)
        self.assertIn(
            "VERIFY_CPYTHON_VERSION: ${{ matrix.cpython_version }}", job
        )
        self.assertIn("pydantic-core-runtime-sdk-${{ matrix.python_tag }}", job)
        self.assertIn("pydantic-static-2.13.4-${{ matrix.python_tag }}", job)
        self.assertNotIn("pydantic-static-2.13.4-cp313", job)


if __name__ == "__main__":
    unittest.main(verbosity=2)
