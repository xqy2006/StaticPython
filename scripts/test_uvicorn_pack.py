from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

from packaging.version import Version


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build
import libs


EXPECTED_VERSIONS = {
    "click": "8.4.2",
    "colorama": "0.4.6",
    "h11": "0.16.0",
    "uvicorn": "0.52.1",
}


class UvicornPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(
            (REPO_ROOT / "config.json").read_text(encoding="utf-8")
        )
        cls.catalog = {
            item["name"]: item
            for item in cls.config["third_party_library_catalog"]["libraries"]
        }

    def test_catalog_pins_current_stable_sdist_and_minimal_dependencies(self) -> None:
        entry = self.catalog["uvicorn"]
        self.assertEqual(entry["release_version"], "0.52.1")
        self.assertEqual(entry["dependencies"], ["click", "h11"])
        self.assertEqual(
            entry["dependency_constraints"],
            {"click": ">=7.0", "h11": ">=0.8"},
        )
        self.assertEqual(entry["license_expression"], "BSD-3-Clause")
        self.assertEqual(
            entry["source_archive_sha256_by_version"],
            {
                "0.52.1": "112ec661814189acbccd3f7b86460147cc065fc92c0821afa78918780e4354dd"
            },
        )
        self.assertEqual(
            entry["smoke_tests"],
            [
                {
                    "kind": "script",
                    "name": "h11-loopback-asgi-server",
                    "script": "scripts/uvicorn_runtime.py",
                    "timeout": 30,
                }
            ],
        )

    def test_dependency_source_hashes_are_pinned(self) -> None:
        definitions = libs.load_integration_definitions(REPO_ROOT / "Lib")
        colorama = next(
            integration for integration in definitions if integration.name == "colorama"
        )
        self.assertEqual(colorama.release_version, "0.4.6")
        self.assertEqual(
            colorama.source_archive_sha256_by_version,
            {
                "0.4.6": "08695f5cb7ed6e0531a20572697297273c47b8cae5a63ffc6d6ed5c201be6e44"
            },
        )

        h11 = libs._integration_from_catalog_entry(self.catalog["h11"])
        self.assertEqual(h11.release_version, "0.16.0")
        self.assertEqual(
            h11.source_archive_sha256_by_version,
            {
                "0.16.0": "4e35b956cf45792e4caa5885e69fba00bdbc6ffafbfa020300e549b208ee5ff1"
            },
        )

        click = next(integration for integration in definitions if integration.name == "click")
        self.assertEqual(click.release_version, "8.4.2")
        self.assertEqual(click.dependencies, ["colorama"])
        self.assertEqual(
            click.source_archive_sha256_by_version,
            {
                "8.4.2": "9a6cea6e60b17ebe0a44c5cc636d94f09bd66142c1cd7d8b4cd731c4917a15f6"
            },
        )

    def test_profile_resolves_exact_four_pack_closure(self) -> None:
        _name, profile = build.resolve_profile(self.config, "uvicorn-experimental")
        self.assertEqual(profile["third_party_libraries"], ["uvicorn"])
        self.assertEqual(
            profile["third_party_library_version_overrides"],
            EXPECTED_VERSIONS,
        )
        catalog = build.profile_library_catalog(
            self.config,
            profile,
            "third_party_library_catalog",
        )
        selected = libs.load_integrations(
            build.LIB_PATCH_ROOT,
            ["uvicorn"],
            target_version=Version("3.13.14"),
            version_overrides=profile["third_party_library_version_overrides"],
            library_catalog=catalog,
        )
        self.assertEqual(
            [integration.name for integration in selected],
            ["colorama", "click", "h11", "uvicorn"],
        )

    def test_runtime_smoke_is_real_loopback_http_and_not_file_backed(self) -> None:
        smoke_path = REPO_ROOT / "scripts" / "uvicorn_runtime.py"
        source = smoke_path.read_text(encoding="utf-8")
        compile(source, str(smoke_path), "exec")
        self.assertIn('http="h11"', source)
        self.assertIn("asyncio.open_connection", source)
        self.assertIn("HTTP/1.1 200 OK", source)
        self.assertNotIn("tempfile", source)
        self.assertNotIn("open(", source)

    def test_full_conflict_profile_keeps_uvicorn_regression_coverage(self) -> None:
        self.assertIn(
            "uvicorn",
            self.config["profiles"]["full"]["third_party_libraries"],
        )

    def test_dedicated_workflow_requires_behavior_no_extraction_and_pe_evidence(
        self,
    ) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "uvicorn-static.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("--profile uvicorn-experimental", workflow)
        self.assertIn("Expected four dependency-complete Uvicorn packs", workflow)
        self.assertIn("$report.integration_smoke_tests", workflow)
        self.assertIn("PSObject.Properties['released_files']", workflow)
        self.assertNotIn("@($report.released_files).Count", workflow)
        self.assertIn("Uvicorn verification released runtime files", workflow)
        self.assertIn("Uvicorn loopback ASGI behavior smoke", workflow)
        self.assertIn("$report.pe_audit.status -ne 'passed'", workflow)
        self.assertIn("python.*\\.dll", workflow)

    def test_dedicated_workflow_covers_every_target_cpython_series(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "uvicorn-static.yml"
        ).read_text(encoding="utf-8")
        expected_targets = {
            "3.11.15": "cp311",
            "3.12.13": "cp312",
            "3.13.15": "cp313",
            "3.14.7": "cp314",
            "3.15.0rc1": "cp315",
        }
        self.assertIn("VERIFY_CPYTHON_VERSION: ${{ matrix.cpython_version }}", workflow)
        self.assertIn("uvicorn-static-0.52.1-${{ matrix.python_tag }}", workflow)
        for version, tag in expected_targets.items():
            self.assertEqual(workflow.count(f'cpython_version: "{version}"'), 1)
            self.assertEqual(workflow.count(f"python_tag: {tag}"), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
