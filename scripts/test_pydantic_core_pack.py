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
        self.assertEqual(integration.release_version, "2.48.0")
        self.assertEqual(
            integration.source_archive_sha256_by_version,
            {
                "2.46.4": "62f875393d7f270851f20523dd2e29f082bcc82292d66db2b64ea71f64b6e1c1",
                "2.47.0": "422c1797a7864b2a9a996435aba92fe571fb80190f67a31edbc1ac040c7b51fe",
                "2.48.0": "8714f70dafdffea0a5596cc88eddbdc71f5856563947970dcbd0f1ced61ed05f"
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
            ["==2.46.4", "==2.47.0", "==2.48.0"],
        )
        for rule in integration.patch_rules:
            replacement = rule["replacements"][0]
            self.assertEqual(replacement["old"], 'crate-type = ["cdylib", "rlib"]')
            self.assertEqual(replacement["new"], 'crate-type = ["staticlib", "rlib"]')
        self.assertEqual(
            integration.license_expression,
            "Apache-2.0 AND (Apache-2.0 WITH LLVM-exception) AND MIT AND "
            "Unicode-3.0 AND Unicode-DFS-2016 AND Zlib",
        )

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
            profiles["pydantic-core-2-47-experimental"][
                "third_party_library_version_overrides"
            ],
            {"pydantic_core": "2.47.0"},
        )
        self.assertEqual(
            profiles["pydantic-core-latest-experimental"][
                "third_party_library_version_overrides"
            ],
            {"pydantic_core": "2.48.0"},
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

    def test_rust_dependency_licenses_are_lock_bound_and_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            crate_root = root / "pydantic-core"
            crate_root.mkdir()
            registry_source = "registry+https://github.com/rust-lang/crates.io-index"
            packages = []

            def package(
                name: str,
                version: str,
                expression: str,
                *,
                source: str | None,
                license_name: str | None,
                package_root: Path | None = None,
            ) -> dict:
                package_root = package_root or root / f"{name}-{version}"
                package_root.mkdir(exist_ok=True)
                manifest = package_root / "Cargo.toml"
                manifest.write_text("[package]\n", encoding="utf-8")
                if license_name is not None:
                    (package_root / license_name).write_text(
                        f"license for {name} {version}\n",
                        encoding="utf-8",
                    )
                record = {
                    "authors": [f"{name} authors"],
                    "license": expression,
                    "manifest_path": str(manifest),
                    "name": name,
                    "repository": f"https://example.invalid/{name}",
                    "source": source,
                    "version": version,
                }
                packages.append(record)
                return record

            root_package = package(
                "pydantic-core",
                "2.47.0",
                "MIT",
                source=None,
                license_name="LICENSE",
                package_root=crate_root,
            )
            helper = package(
                "helper",
                "1.0.0",
                "MIT OR Apache-2.0",
                source=registry_source,
                license_name="LICENSE-APACHE",
            )
            fallback = package(
                "r-efi",
                "5.2.0",
                "MIT OR Apache-2.0 OR LGPL-2.1-or-later",
                source=registry_source,
                license_name=None,
            )
            helper_checksum = "a" * 64
            fallback_checksum = "b" * 64
            lock_text = (
                'version = 4\n\n'
                '[[package]]\nname = "pydantic-core"\nversion = "2.47.0"\n\n'
                '[[package]]\nname = "helper"\nversion = "1.0.0"\n'
                f'source = "{registry_source}"\nchecksum = "{helper_checksum}"\n\n'
                '[[package]]\nname = "r-efi"\nversion = "5.2.0"\n'
                f'source = "{registry_source}"\nchecksum = "{fallback_checksum}"\n'
            )
            (crate_root / "Cargo.lock").write_text(lock_text, encoding="utf-8")
            destination = root / "licenses"

            generated, manifest = self.module._collect_rust_dependency_licenses(
                crate_root,
                {"packages": packages},
                destination,
            )
            first_manifest = (destination / "rust-dependencies.json").read_bytes()
            generated_again, manifest_again = self.module._collect_rust_dependency_licenses(
                crate_root,
                {"packages": packages},
                destination,
            )

            self.assertEqual(manifest, manifest_again)
            self.assertEqual(
                first_manifest,
                (destination / "rust-dependencies.json").read_bytes(),
            )
            self.assertEqual(
                [path.relative_to(destination).as_posix() for path in generated],
                [path.relative_to(destination).as_posix() for path in generated_again],
            )
            self.assertEqual(manifest["package_count"], 3)
            self.assertEqual(manifest["root_package"], {"name": "pydantic-core", "version": "2.47.0"})
            by_name = {record["name"]: record for record in manifest["packages"]}
            self.assertIsNone(by_name[root_package["name"]]["checksum"])
            self.assertEqual(by_name[helper["name"]]["checksum"], "a" * 64)
            self.assertEqual(by_name[fallback["name"]]["selected_license"], "Apache-2.0")
            self.assertTrue(by_name[fallback["name"]]["license_files"])
            self.assertTrue(
                all(
                    not Path(file["path"]).is_absolute()
                    for record in manifest["packages"]
                    for file in record["license_files"]
                )
            )

            helper["license"] = "GPL-3.0-only"
            with self.assertRaisesRegex(RuntimeError, "unreviewed license"):
                self.module._collect_rust_dependency_licenses(
                    crate_root,
                    {"packages": packages},
                    root / "invalid-licenses",
                )

    def test_workflow_requires_complete_rust_dependency_license_evidence(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "pydantic-core-static.yml"
        ).read_text(encoding="utf-8")

        self.assertIn('GetEntry("licenses/rust-dependencies.json")', workflow)
        self.assertIn("staticpython-rust-license-manifest", workflow)
        self.assertIn("$metadata.toolchain.rust.cargo_lock_sha256", workflow)
        self.assertIn("$metadata.toolchain.rust.package_count", workflow)
        self.assertIn("$incompleteRustLicenses.Count -ne 0", workflow)
        self.assertIn('pydantic_core_version: "2.47.0"', workflow)
        self.assertIn('pydantic_core_version: "2.48.0"', workflow)

    def test_workflow_covers_all_supported_cpython_series(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "pydantic-core-static.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("push:\n    branches: [master]", workflow)
        self.assertIn("pull_request:\n    paths:", workflow)
        runtime_job, core_tail = workflow.split(
            "  sdk-linked-pydantic-core:\n", 1
        )
        next_job = core_tail.find("\n  sdk-linked-")
        core_job = core_tail if next_job < 0 else core_tail[:next_job]
        workflow = runtime_job + core_job

        targets = {
            "3.11.15": "cp311",
            "3.12.13": "cp312",
            "3.13.15": "cp313",
            "3.14.7": "cp314",
            "3.15.0rc1": "cp315",
        }
        for version, tag in targets.items():
            with self.subTest(version=version):
                self.assertEqual(workflow.count(f'cpython_version: "{version}"'), 4)
                self.assertEqual(workflow.count(f"python_tag: {tag}"), 4)
        for version in ("2.46.4", "2.47.0", "2.48.0"):
            with self.subTest(pydantic_core=version):
                self.assertEqual(
                    workflow.count(f'pydantic_core_version: "{version}"'), 5
                )
        self.assertEqual(
            workflow.count("VERIFY_CPYTHON_VERSION: ${{ matrix.cpython_version }}"),
            2,
        )
        self.assertIn("pydantic-core-runtime-sdk-${{ matrix.python_tag }}", workflow)
        self.assertIn(
            "pydantic-core-static-${{ matrix.pydantic_core_version }}-${{ matrix.python_tag }}",
            workflow,
        )

    def test_workflow_audits_released_files_per_smoke_record(self) -> None:
        workflow = (REPO_ROOT / ".github" / "workflows" / "pydantic-core-static.yml").read_text(
            encoding="utf-8"
        )
        self.assertNotIn("@($report.released_files)", workflow)
        self.assertIn("$smoke.PSObject.Properties['released_files']", workflow)
        self.assertIn("foreach ($path in @($smoke.released_files))", workflow)


if __name__ == "__main__":
    unittest.main(verbosity=2)
