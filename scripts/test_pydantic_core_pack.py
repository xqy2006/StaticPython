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
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import build
import libs
import verify_pack_with_runtime_sdk


def load_integration_module():
    path = REPO_ROOT / "Lib" / "pydantic_core" / "setup.py"
    spec = importlib.util.spec_from_file_location(
        "staticpython_pydantic_core_test", path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PydanticCorePackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = load_integration_module()

    def test_pack_contract_is_pinned_and_static(self) -> None:
        integration = self.module.LIBRARY_INTEGRATION
        self.assertEqual(integration.release_version, "2.47.0")
        self.assertEqual(
            integration.source_archive_sha256_by_version,
            {
                "2.46.4": "62f875393d7f270851f20523dd2e29f082bcc82292d66db2b64ea71f64b6e1c1",
                "2.47.0": "422c1797a7864b2a9a996435aba92fe571fb80190f67a31edbc1ac040c7b51fe"
            },
        )
        self.assertEqual(integration.dependencies, ["typing_extensions"])
        self.assertEqual(
            integration.dependency_constraints,
            {"typing_extensions": ">=4.14.1"},
        )
        self.assertEqual(
            integration.builtin_module_registrations,
            [
                {
                    "name": "pydantic_core._pydantic_core",
                    "pyinit": "PyInit__pydantic_core",
                    "library": "pydantic_core._pydantic_core.lib",
                }
            ],
        )
        self.assertNotIn(
            "pydantic_core._pydantic_core.lib",
            integration.python_link_wholearchive_release_x64,
        )
        self.assertIn("ntdll.lib", integration.python_link_dependencies_release_x64)
        self.assertTrue(build.is_windows_sdk_library("ntdll.lib"))
        self.assertFalse(build.is_packaged_static_library("ntdll.lib"))
        self.assertIn(
            "ntdll.lib",
            verify_pack_with_runtime_sdk.WINDOWS_LINK_LIBRARY_NAMES,
        )
        self.assertEqual(
            [rule["package"] for rule in integration.patch_rules],
            ["==2.46.4", "==2.47.0"],
        )
        for rule in integration.patch_rules:
            replacement = rule["replacements"][0]
            self.assertEqual(replacement["old"], 'crate-type = ["cdylib", "rlib"]')
            self.assertEqual(replacement["new"], 'crate-type = ["staticlib", "rlib"]')
        self.assertEqual(integration.license_expression, "MIT")

    def test_pyo3_config_targets_exact_non_abi3_cpython(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            context = libs.LibraryHookContext(
                repo_root=REPO_ROOT,
                source_root=source_root,
                version_info=(3, 15, 0),
                version_mm="3.15",
                version_full="3.15.0b4",
                download_cache_root=source_root / "downloads",
                work_cache_root=source_root / "work",
                asset_overlay_root=REPO_ROOT / "assets" / "overlay",
                log=lambda _message: None,
            )
            path = self.module._write_pyo3_config(context)
            self.assertEqual(
                path.read_text(encoding="utf-8").splitlines(),
                [
                    "implementation=CPython",
                    "version=3.15",
                    "shared=false",
                    "abi3=false",
                    "pointer_width=64",
                    "build_flags=",
                    "suppress_build_script_link_lines=true",
                ],
            )

    def test_experimental_profiles_cover_stable_pydantic_and_latest_core(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        profiles = config["profiles"]
        self.assertEqual(
            profiles["pydantic-core-experimental"]["third_party_library_version_overrides"],
            {"pydantic_core": "2.46.4"},
        )
        self.assertEqual(
            profiles["pydantic-core-latest-experimental"][
                "third_party_library_version_overrides"
            ],
            {"pydantic_core": "2.47.0"},
        )

    def test_encoded_rustflags_preserve_paths_with_spaces(self) -> None:
        source = Path("C:/build root/source tree")
        target = Path("C:/build root/target tree")
        self.assertEqual(
            self.module._cargo_encoded_rustflags(source, target).split("\x1f"),
            [
                "-C",
                "target-feature=+crt-static",
                f"--remap-path-prefix={source.resolve()}=C:/staticpython/source",
                f"--remap-path-prefix={target.resolve()}=C:/staticpython/target",
            ],
        )

    def test_rustc_verbose_version_parser_preserves_provenance(self) -> None:
        parsed = self.module._parse_rustc_verbose_version(
            "rustc 1.88.0 (6b00bc388 2025-06-23)\n"
            "binary: rustc\n"
            "commit-hash: 6b00bc3880198600130e1cf62b8f8a93494488cc\n"
            "host: x86_64-pc-windows-msvc\n"
        )
        self.assertEqual(parsed["version"], "rustc 1.88.0 (6b00bc388 2025-06-23)")
        self.assertEqual(
            parsed["commit_hash"], "6b00bc3880198600130e1cf62b8f8a93494488cc"
        )
        self.assertEqual(parsed["host"], "x86_64-pc-windows-msvc")


if __name__ == "__main__":
    unittest.main(verbosity=2)
