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
    "starlette": "1.3.1",
    "typing_extensions": "4.16.0",
    "typing_inspection": "0.4.2",
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
        smoke = entry["smoke_tests"][0]["code"]
        self.assertIn("FastAPI", smoke)
        self.assertIn("app.openapi()", smoke)
        self.assertIn("BaseModel", smoke)

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
            target_version=Version("3.13.14"),
            version_overrides=profile["third_party_library_version_overrides"],
            library_catalog=catalog,
        )
        self.assertEqual(
            {integration.name for integration in selected},
            set(EXPECTED_VERSIONS),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
