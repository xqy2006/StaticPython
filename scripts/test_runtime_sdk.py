from __future__ import annotations

import json
import importlib.util
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build
import libs

_INDEX_SPEC = importlib.util.spec_from_file_location(
    "staticpython_build_release_index",
    REPO_ROOT / "scripts" / "build_release_index.py",
)
assert _INDEX_SPEC is not None and _INDEX_SPEC.loader is not None
build_release_index = importlib.util.module_from_spec(_INDEX_SPEC)
_INDEX_SPEC.loader.exec_module(build_release_index)


class RuntimeSDKTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_runtime_sdk_profile_is_minimal(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        profile = config["profiles"]["runtime-sdk"]
        self.assertEqual(profile["build_type"], "runtime-sdk")
        self.assertEqual(profile["core_libraries"], "all")
        self.assertEqual(profile["third_party_libraries"], [])

    def test_native_wheels_are_never_source_inputs(self) -> None:
        files = [
            {
                "filename": "demo-1.0-cp313-cp313-win_amd64.whl",
                "packagetype": "bdist_wheel",
                "requires_python": ">=3.11",
                "yanked": False,
            }
        ]
        compatible = libs._compatible_pypi_files(
            files,
            project_requires_python=None,
            target_version=libs.Version("3.13"),
        )
        self.assertEqual(compatible, [])

    def test_sdist_and_universal_wheel_are_valid_source_inputs(self) -> None:
        files = [
            {
                "filename": "demo-1.0.tar.gz",
                "packagetype": "sdist",
                "requires_python": ">=3.11",
                "yanked": False,
            },
            {
                "filename": "demo-1.0-py3-none-any.whl",
                "packagetype": "bdist_wheel",
                "requires_python": ">=3.11",
                "yanked": False,
            },
        ]
        compatible = libs._compatible_pypi_files(
            files,
            project_requires_python=None,
            target_version=libs.Version("3.13"),
        )
        self.assertEqual([item["packagetype"] for item in compatible], ["sdist", "bdist_wheel"])

    def test_automatic_version_scan_excludes_prerelease_and_dev(self) -> None:
        releases = {"2.0rc1": [], "2.0.dev1": [], "1.9": [], "1.8": []}
        self.assertEqual(libs._sorted_release_versions(releases), ["1.9", "1.8"])

    def test_patch_rules_are_strict_and_idempotent(self) -> None:
        target = self.root / "Lib" / "demo.py"
        target.parent.mkdir(parents=True)
        target.write_text("VALUE = 1\n", encoding="utf-8")
        integration = libs.LibraryIntegration(
            name="demo",
            release_version="1.2.0",
            patch_rules=[
                {
                    "package": ">=1,<2",
                    "python": ">=3.11,<3.16",
                    "path": "Lib/demo.py",
                    "replacements": [{"old": "VALUE = 1", "new": "VALUE = 2", "count": 1}],
                }
            ],
        )
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=self.root,
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=self.root / "work",
            asset_overlay_root=REPO_ROOT / "assets" / "overlay",
            log=lambda _message: None,
        )
        libs.run_pre_patch_hooks([integration], context)
        libs.run_pre_patch_hooks([integration], context)
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 2\n")
        target.write_text("VALUE = 3\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "anchor mismatch"):
            libs.run_pre_patch_hooks([integration], context)

    def test_runtime_pythoncore_patch_removes_main_and_legacy_resource_store(self) -> None:
        project = self.root / "PCbuild" / "pythoncore.vcxproj"
        project.parent.mkdir(parents=True)
        project.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup><ConfigurationType>DynamicLibrary</ConfigurationType></PropertyGroup>
  <ItemGroup>
    <ClCompile Include="..\\Modules\\main.c" />
    <ClCompile Include="..\\Python\\frozen.c" />
    <ClCompile Include="..\\Python\\staticpython_resource_store.c" />
  </ItemGroup>
</Project>
""",
            encoding="utf-8",
        )
        build.patch_pythoncore_vcxproj(self.root, runtime_sdk=True)
        text = project.read_text(encoding="utf-8")
        self.assertIn("<ConfigurationType>StaticLibrary</ConfigurationType>", text)
        self.assertNotIn("Modules\\main.c", text)
        self.assertNotIn("Python\\staticpython_resource_store.c", text)

    def test_pack_resource_descriptor_is_sorted_and_uses_v1(self) -> None:
        build._write_staticpython_pack_resource_store_c(
            self.root,
            target_records=[
                ("Lib/z/data.bin", "shard_z", "sha256:z", 2),
                ("Lib/a/data.bin", "shard_a", "sha256:a", 3),
            ],
        )
        text = (self.root / build.RUNTIME_RESOURCE_STORE_C_RELATIVE_PATH).read_text(encoding="utf-8")
        self.assertIn("StaticPython_BaseResourcePackV1", text)
        self.assertIn("STATICPYTHON_PACK_ABI_VERSION", text)
        self.assertLess(text.index("Lib/a/data.bin"), text.index("Lib/z/data.bin"))

    def test_deterministic_zip_is_byte_stable(self) -> None:
        staging = self.root / "staging"
        staging.mkdir()
        (staging / "b.txt").write_text("b\n", encoding="utf-8")
        (staging / "a.txt").write_text("a\n", encoding="utf-8")
        first = self.root / "first.zip"
        second = self.root / "second.zip"
        build.write_deterministic_zip(staging, first)
        build.write_deterministic_zip(staging, second)
        self.assertEqual(build.sha256_file(first), build.sha256_file(second))
        with ZipFile(first) as archive:
            self.assertEqual(archive.namelist(), ["a.txt", "b.txt"])

    def test_library_pack_contains_only_selected_modules_and_resources(self) -> None:
        frozen = self.root / "Python" / "frozen_modules"
        frozen.mkdir(parents=True)
        (frozen / "demo.h").write_text(
            "const unsigned char _Py_M__demo[] = {1, 2, 3,};\n",
            encoding="utf-8",
        )
        (frozen / "other.h").write_text(
            "const unsigned char _Py_M__other[] = {4, 5,};\n",
            encoding="utf-8",
        )
        package = self.root / "Lib" / "demo"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
        (package / "data.json").write_text('{"ok": true}\n', encoding="utf-8")
        (package / "LICENSE.txt").write_text("demo license\n", encoding="utf-8")
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            source_resolver="pypi-sdist",
            project_name="demo-project",
            release_version="1.2.3",
            python_packages=["demo"],
            top_level_import_names=["demo"],
            materialized_paths=["Lib/demo"],
            license_expression="MIT",
            license_files=["Lib/demo/LICENSE.txt"],
        )
        output = self.root / "dist"
        archive_path = build.export_library_pack(
            self.root,
            output,
            (3, 13, 0),
            "3.13.0",
            "x64",
            integration,
        )
        with ZipFile(archive_path) as archive:
            metadata = json.loads(archive.read("pack.json"))
            descriptor = archive.read("src/pack.c").decode("utf-8")
            self.assertEqual(metadata["frozen_modules"], ["demo"])
            self.assertNotIn("other", metadata["frozen_modules"])
            self.assertIn("Lib/demo/data.json", [item["path"] for item in metadata["resources"]])
            self.assertEqual(metadata["license"]["status"], "complete")
            self.assertIn('"demo"', descriptor)
            self.assertNotIn('_Py_M__other', descriptor)

    def test_release_index_uses_immutable_urls_and_pack_families(self) -> None:
        assets = self.root / "assets"
        runtime_stage = self.root / "runtime-stage"
        (runtime_stage / "metadata").mkdir(parents=True)
        commit = build.git_commit_or_none(REPO_ROOT)
        runtime_metadata = {
            "cpython_abi": "cp313",
            "cpython_version": "3.13.0",
            "runtime_abi": "staticpython-pack-v1-cp313",
            "staticpython_commit": commit,
            "verification": {"status": "passed"},
        }
        (runtime_stage / build.RUNTIME_SDK_METADATA_RELATIVE_PATH).write_text(
            json.dumps(runtime_metadata),
            encoding="utf-8",
        )
        assets.mkdir()
        runtime_zip = assets / "runtime.zip"
        build.write_deterministic_zip(runtime_stage, runtime_zip)

        pack_stage = self.root / "pack-stage"
        pack_stage.mkdir()
        pack_metadata = {
            "name": "attrs",
            "version": "25.1.0",
            "cpython_abi": "cp313",
            "staticpython_commit": commit,
            "verification": {"status": "not-run"},
            "license": {"status": "complete"},
        }
        (pack_stage / "pack.json").write_text(json.dumps(pack_metadata), encoding="utf-8")
        pack_zip = assets / "attrs.zip"
        build.write_deterministic_zip(pack_stage, pack_zip)

        index = build_release_index.build_index(
            assets,
            "xqy2006/StaticPython",
            commit,
            "staticpython-runtime-deadbeef",
            "staticpython-packs-deadbeef",
            require_all_targets=False,
            require_verified=False,
        )
        self.assertEqual(index["runtimes"]["cp313"]["sha256"], build.sha256_file(runtime_zip))
        pack = index["packs"]["attrs"]["25.1.0"]["cp313"]
        self.assertEqual(pack["release_family"], "a-f")
        self.assertIn("/staticpython-packs-deadbeef-a-f/attrs.zip", pack["url"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
