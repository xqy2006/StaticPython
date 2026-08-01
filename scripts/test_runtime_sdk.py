from __future__ import annotations

import json
import importlib.util
import shutil
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build
import libs
import verify as staticpython_verify

_INDEX_SPEC = importlib.util.spec_from_file_location(
    "staticpython_build_release_index",
    REPO_ROOT / "scripts" / "build_release_index.py",
)
assert _INDEX_SPEC is not None and _INDEX_SPEC.loader is not None
build_release_index = importlib.util.module_from_spec(_INDEX_SPEC)
_INDEX_SPEC.loader.exec_module(build_release_index)

_SHARD_SPEC = importlib.util.spec_from_file_location(
    "staticpython_build_pack_shard_config",
    REPO_ROOT / "scripts" / "build_pack_shard_config.py",
)
assert _SHARD_SPEC is not None and _SHARD_SPEC.loader is not None
build_pack_shard_config = importlib.util.module_from_spec(_SHARD_SPEC)
_SHARD_SPEC.loader.exec_module(build_pack_shard_config)


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

    def test_runtime_sdk_prefers_generated_pyconfig_header(self) -> None:
        generated = build.get_pcbuild_output_dir(self.root, "x64") / "pyconfig.h"
        generated.parent.mkdir(parents=True)
        generated.write_text("generated", encoding="utf-8")
        source = self.root / "PC" / "pyconfig.h"
        source.parent.mkdir(parents=True)
        source.write_text("legacy", encoding="utf-8")
        self.assertEqual(build.resolve_runtime_sdk_pyconfig_header(self.root, "x64"), generated)

    def test_parse_cpython_version_preserves_prerelease_suffix(self) -> None:
        include = self.root / "Include"
        include.mkdir()
        (include / "patchlevel.h").write_text(
            '#define PY_MAJOR_VERSION 3\n'
            '#define PY_MINOR_VERSION 15\n'
            '#define PY_MICRO_VERSION 0\n'
            '#define PY_VERSION "3.15.0b4"\n',
            encoding="utf-8",
        )
        self.assertEqual(
            build.parse_cpython_version(self.root),
            ((3, 15, 0), "3.15", "3.15.0b4"),
        )

    def test_runtime_frozen_module_names_come_from_runtime_tables_only(self) -> None:
        frozen = self.root / "Python" / "frozen.c"
        frozen.parent.mkdir(parents=True)
        frozen.write_text(
            '''
static const struct _frozen bootstrap_modules[] = {
    {"importlib._bootstrap", bootstrap, 1, false},
    {0, 0, 0} /* bootstrap sentinel */
};
static const struct _frozen stdlib_modules[] = {
    {"asyncio", asyncio_data, 1, true},
    {"asyncio.tasks", asyncio_tasks_data, 1, false},
    {0, 0, 0} /* stdlib sentinel */
};
static const struct _frozen test_modules[] = {
    {"test.should_not_ship", test_data, 1, false},
    {0, 0, 0} /* test sentinel */
};
const struct _module_alias aliases[] = {
    {"os.path", "ntpath"},
    {0, 0} /* aliases sentinel */
};
''',
            encoding="utf-8",
        )
        self.assertEqual(
            build.runtime_frozen_module_names(self.root),
            ["asyncio", "asyncio.tasks", "importlib._bootstrap", "os.path"],
        )

    def test_cpython_tag_resolution_prefers_peeled_commit(self) -> None:
        direct = "1" * 40
        peeled = "2" * 40
        result = SimpleNamespace(
            returncode=0,
            stdout=(
                f"{direct}\trefs/tags/v3.13.14\n"
                f"{peeled}\trefs/tags/v3.13.14^{{}}\n"
            ),
            stderr="",
        )
        with mock.patch("build.subprocess.run", return_value=result):
            self.assertEqual(build.resolve_cpython_tag_commit("3.13.14"), peeled)

    def test_prompt_toolkit_3053_lazy_version_patch_is_strict(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_prompt_toolkit_setup_test",
            REPO_ROOT / "Lib" / "prompt_toolkit" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.LIBRARY_INTEGRATION.release_version = "3.0.53"
        source = (
            "from importlib import metadata\n"
            "import re\n\n"
            "def _load_version():\n"
            '    version = metadata.version("prompt_toolkit")\n'
            "    assert re.fullmatch(pep440_pattern, version)\n"
        )
        patched = module._patch_prompt_toolkit_init(source)
        self.assertIn("except metadata.PackageNotFoundError:", patched)
        self.assertIn('version = "3.0.53"', patched)
        self.assertEqual(module._patch_prompt_toolkit_init(patched), patched)

    def test_portalocker_400_optional_win32_needs_no_legacy_patch(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_portalocker_setup_test",
            REPO_ROOT / "Lib" / "portalocker" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = (
            "    class MsvcrtLocker(BaseLocker):\n"
            "        _win32_locker: Win32Locker | None\n"
            "        def __init__(self) -> None:\n"
            "            try:\n"
            "                self._win32_locker = Win32Locker()\n"
            "            except ImportError:\n"
            "                self._win32_locker = None\n"
            "        def lock(self, file_obj, flags):\n"
            "            if flags:\n"
            "                win32_locker = self._win32_locker\n"
            "                if win32_locker is None:\n"
            "                    raise ImportError(\n"
            "                        'pywin32 is optional'\n"
            "                    )\n"
        )
        target = self.root / "Lib" / "portalocker" / "portalocker.py"
        target.parent.mkdir(parents=True)
        target.write_text(source, encoding="utf-8")
        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        module.patch_portalocker_sources(context)
        self.assertEqual(target.read_text(encoding="utf-8"), source)

    def test_ujson_project_defines_the_resolved_release_version(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_ujson_setup_test",
            REPO_ROOT / "Lib" / "ujson" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        project = module._render_ujson_project(["python/ujson.c"], ["python"], "5.13.0")
        self.assertIn("UJSON_VERSION=&quot;5.13.0&quot;", project)

    def test_hypothesis_native_compatibility_is_frozen_and_functional(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_hypothesis_setup_test",
            REPO_ROOT / "Lib" / "hypothesis" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.LIBRARY_INTEGRATION.release_version, "6.164.0")
        self.assertEqual(module.LIBRARY_INTEGRATION.license_expression, "MPL-2.0")

        internal = self.root / "Lib" / "hypothesis" / "internal"
        internal.mkdir(parents=True)
        (internal / "floats.py").write_text(
            "from hypothesis._native.internal.floats import (\n    float_of,\n)\n",
            encoding="utf-8",
        )
        (self.root / "Lib" / "hypothesis" / "version.py").write_text(
            "from hypothesis._native import __version__ as __version__\n",
            encoding="utf-8",
        )
        core = self.root / "Lib" / "hypothesis" / "strategies" / "_internal" / "core.py"
        core.parent.mkdir(parents=True)
        core.write_text(
            "from hypothesis._native.internal.cathetus import cathetus\n",
            encoding="utf-8",
        )
        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        module._install_hypothesis_native_compatibility(context)

        floats_path = self.root / "Lib" / "hypothesis" / "_native" / "internal" / "floats.py"
        floats_spec = importlib.util.spec_from_file_location(
            "staticpython_hypothesis_floats_test",
            floats_path,
        )
        assert floats_spec is not None and floats_spec.loader is not None
        floats = importlib.util.module_from_spec(floats_spec)
        floats_spec.loader.exec_module(floats)
        negative_zero = floats.int_to_float(floats.float_to_int(-0.0), 64)
        self.assertLess(floats.math.copysign(1.0, negative_zero), 0.0)
        self.assertGreater(floats.next_up(0.0), 0.0)
        self.assertEqual(floats.width_smallest_normals(32), 2.0**-126)

        cathetus_path = floats_path.with_name("cathetus.py")
        cathetus_spec = importlib.util.spec_from_file_location(
            "staticpython_hypothesis_cathetus_test",
            cathetus_path,
        )
        assert cathetus_spec is not None and cathetus_spec.loader is not None
        cathetus = importlib.util.module_from_spec(cathetus_spec)
        cathetus_spec.loader.exec_module(cathetus)
        self.assertEqual(cathetus.cathetus(5.0, 4.0), 3.0)
        self.assertTrue(cathetus.math.isnan(cathetus.cathetus(1.0, 2.0)))

        before = floats_path.read_text(encoding="utf-8")
        module._install_hypothesis_native_compatibility(context)
        self.assertEqual(floats_path.read_text(encoding="utf-8"), before)

    def test_hypothesis_native_compatibility_routes_transition_and_legacy_versions(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_hypothesis_transition_test",
            REPO_ROOT / "Lib" / "hypothesis" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original_version = module.LIBRARY_INTEGRATION.release_version
        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)

        module.LIBRARY_INTEGRATION.release_version = "6.155.7"
        try:
            module._install_hypothesis_native_compatibility(context)

            module.LIBRARY_INTEGRATION.release_version = "6.157.1"
            internal = self.root / "Lib" / "hypothesis" / "internal"
            internal.mkdir(parents=True)
            (internal / "floats.py").write_text("FLOATS_ARE_PYTHON = True\n", encoding="utf-8")
            (self.root / "Lib" / "hypothesis" / "version.py").write_text(
                "from hypothesis._native import __version__ as __version__\n",
                encoding="utf-8",
            )
            core = self.root / "Lib" / "hypothesis" / "strategies" / "_internal" / "core.py"
            core.parent.mkdir(parents=True)
            core.write_text(
                "from hypothesis._native.internal.cathetus import cathetus\n",
                encoding="utf-8",
            )
            module._install_hypothesis_native_compatibility(context)
        finally:
            module.LIBRARY_INTEGRATION.release_version = original_version

        native = self.root / "Lib" / "hypothesis" / "_native"
        self.assertTrue((native / "__init__.py").is_file())
        self.assertTrue((native / "internal" / "cathetus.py").is_file())
        self.assertFalse((native / "internal" / "floats.py").exists())

    def test_hypothesis_native_compatibility_rejects_partial_upstream_drift(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_hypothesis_drift_test",
            REPO_ROOT / "Lib" / "hypothesis" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        internal = self.root / "Lib" / "hypothesis" / "internal"
        internal.mkdir(parents=True)
        (internal / "floats.py").write_text(
            "from hypothesis._native.internal.floats import (\n    float_of,\n)\n",
            encoding="utf-8",
        )
        (self.root / "Lib" / "hypothesis" / "version.py").write_text(
            "__version__ = 'changed'\n",
            encoding="utf-8",
        )
        core = self.root / "Lib" / "hypothesis" / "strategies" / "_internal" / "core.py"
        core.parent.mkdir(parents=True)
        core.write_text(
            "from hypothesis._native.internal.cathetus import cathetus\n",
            encoding="utf-8",
        )
        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        with self.assertRaisesRegex(RuntimeError, "anchors changed"):
            module._install_hypothesis_native_compatibility(context)

    def test_cppy_frozen_runtime_patch_is_strict_and_idempotent(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_cppy_setup_test",
            REPO_ROOT / "Lib" / "cppy" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = "import os\nfrom setuptools.command.build_ext import build_ext\n"
        patched = module._patch_cppy_setuptools_import(source)
        compile(patched, "<cppy-patch>", "exec")
        self.assertIn("Unavailable build command placeholder", patched)

        original_import = __import__

        def import_without_setuptools(name, *args, **kwargs):
            if name == "setuptools" or name.startswith("setuptools."):
                raise ModuleNotFoundError("No module named 'setuptools'", name="setuptools")
            return original_import(name, *args, **kwargs)

        namespace = {}
        with mock.patch("builtins.__import__", side_effect=import_without_setuptools):
            exec(compile(patched, "<cppy-no-setuptools>", "exec"), namespace)
        with self.assertRaisesRegex(RuntimeError, "requires setuptools"):
            namespace["build_ext"]()

        self.assertEqual(module._patch_cppy_setuptools_import(patched), patched)
        with self.assertRaisesRegex(RuntimeError, "expected snippet"):
            module._patch_cppy_setuptools_import("import os\n")

        legacy_version = module.LIBRARY_INTEGRATION.release_version
        module.LIBRARY_INTEGRATION.release_version = "1.1.0"
        try:
            module.patch_cppy_sources(
                SimpleNamespace(source_root=self.root, log=lambda _message: None)
            )
        finally:
            module.LIBRARY_INTEGRATION.release_version = legacy_version

    def test_pybind11_frozen_version_matches_header_and_is_strict(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_pybind11_setup_test",
            REPO_ROOT / "Lib" / "pybind11" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        header = self.root / "pybind11_builtin" / "include" / "pybind11" / "detail" / "common.h"
        header.parent.mkdir(parents=True)
        header.write_text(
            "#define PYBIND11_VERSION_MAJOR 3\n"
            "#define PYBIND11_VERSION_MINOR 0\n"
            "#define PYBIND11_VERSION_PATCH 4\n",
            encoding="utf-8",
        )
        version_file = self.root / "Lib" / "pybind11" / "_version.py"
        version_file.parent.mkdir(parents=True)
        version_file.write_text(
            "# This file will be replaced in the wheel with a hard-coded version.\n"
            "from pathlib import Path\n"
            "DIR = Path(__file__).parent.resolve()\n"
            'input_file = DIR.parent / "include/pybind11/detail/common.h"\n'
            'match = regex.search(input_file.read_text(encoding="utf-8"))\n',
            encoding="utf-8",
        )
        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        module.patch_pybind11_sources(context)
        rendered = version_file.read_text(encoding="utf-8")
        namespace = {}
        exec(compile(rendered, "<pybind11-version>", "exec"), namespace)
        self.assertEqual(namespace["__version__"], "3.0.4")
        self.assertEqual(namespace["version_info"], (3, 0, 4))
        module.patch_pybind11_sources(context)
        self.assertEqual(version_file.read_text(encoding="utf-8"), rendered)

        header.write_text(
            "#define PYBIND11_VERSION_MAJOR 3\n"
            "#define PYBIND11_VERSION_MINOR 0\n"
            "#define PYBIND11_VERSION_PATCH 5\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            module.patch_pybind11_sources(context)

        legacy_version = module.LIBRARY_INTEGRATION.release_version
        module.LIBRARY_INTEGRATION.release_version = "2.13.6"
        try:
            module.patch_pybind11_sources(
                SimpleNamespace(source_root=self.root, log=lambda _message: None)
            )
        finally:
            module.LIBRARY_INTEGRATION.release_version = legacy_version

    def test_aiohttp_pack_metadata_tracks_generated_extension_layout(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_aiohttp_layout_test",
            REPO_ROOT / "Lib" / "aiohttp" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        aiohttp = self.root / "Lib" / "aiohttp"
        websocket = aiohttp / "_websocket"
        websocket.mkdir(parents=True)
        for relative in (
            "_http_parser.c",
            "_find_header.c",
            "_http_writer.c",
            "_websocket/mask.c",
            "_websocket/reader_c.c",
        ):
            path = aiohttp / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("/* test */\n", encoding="utf-8")
        llhttp = self.root / "aiohttp_builtin" / "vendor" / "llhttp"
        for relative in ("build/c/llhttp.c", "src/native/api.c", "src/native/http.c"):
            path = llhttp / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("/* test */\n", encoding="utf-8")

        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        module.prepare_aiohttp_projects(context)
        selected_names = [
            "aiohttp._http_parser",
            "aiohttp._http_writer",
            "aiohttp._websocket.mask",
            "aiohttp._websocket.reader_c",
        ]
        integration = module.LIBRARY_INTEGRATION
        self.assertEqual(
            integration.static_library_projects_release_x64,
            [f"{name}.vcxproj" for name in selected_names],
        )
        self.assertEqual(
            [item["name"] for item in integration.builtin_module_registrations],
            selected_names,
        )
        self.assertEqual(
            integration.python_link_dependencies_release_x64,
            [f"{name}.lib" for name in selected_names],
        )

        output = self.root / "PCbuild" / "amd64"
        output.mkdir(parents=True)
        for name in selected_names:
            (output / f"{name}.lib").write_bytes(b"library")
        native_records, _wholearchive, _system = build._integration_native_libraries(
            self.root,
            "x64",
            integration,
        )
        self.assertEqual(
            [record["logical_name"] for record in native_records],
            [f"{name}.lib" for name in selected_names],
        )

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

    def test_pack_registration_validates_before_mutating_cpython_tables(self) -> None:
        text = (
            REPO_ROOT / "assets" / "overlay" / "Python" / "staticpython_pack_runtime.c"
        ).read_text(encoding="utf-8")
        hook_call = text.index("packs[index]->before_initialize()")
        table_allocation = text.index("staticpython_frozen_modules = (struct _frozen *)calloc")
        extend_inittab = text.index("PyImport_ExtendInittab(staticpython_builtin_modules)")
        self.assertLess(hook_call, table_allocation)
        self.assertLess(table_allocation, extend_inittab)
        self.assertIn("duplicate builtin module name", text)
        self.assertIn("builtin module conflicts with the runtime SDK", text)
        self.assertIn("_PyImport_FrozenStdlib", text)
        self.assertIn("required dependency pack is missing", text)

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
            verification_status="passed",
            verification_report={
                "integration_smoke_tests": [
                    {"integration": "demo", "name": "import-demo", "kind": "import", "status": "passed"},
                    {"integration": "other", "name": "import-other", "kind": "import", "status": "passed"},
                ]
            },
        )
        with ZipFile(archive_path) as archive:
            metadata = json.loads(archive.read("pack.json"))
            descriptor = archive.read("src/pack.c").decode("utf-8")
            self.assertEqual(metadata["frozen_modules"], ["demo"])
            self.assertNotIn("other", metadata["frozen_modules"])
            self.assertIn("Lib/demo/data.json", [item["path"] for item in metadata["resources"]])
            self.assertEqual(metadata["license"]["status"], "complete")
            self.assertEqual(metadata["verification"]["status"], "passed")
            self.assertEqual(
                metadata["verification"]["smoke_tests"],
                [{"name": "import-demo", "kind": "import", "status": "passed"}],
            )
            self.assertIn('"demo"', descriptor)
            self.assertIn("staticpython_pack_demo_resource_", descriptor)
            self.assertNotIn('_Py_M__other', descriptor)

    def test_native_only_pack_does_not_require_a_frozen_module(self) -> None:
        (self.root / "Python" / "frozen_modules").mkdir(parents=True)
        integration = libs.LibraryIntegration(
            name="native_demo",
            python_packages=["native_demo"],
            top_level_import_names=["native_demo"],
            builtin_module_registrations=[
                {"name": "native_demo", "pyinit": "PyInit_native_demo"}
            ],
        )
        self.assertEqual(build._integration_frozen_modules(self.root, integration), [])

    def test_pack_shards_partition_current_full_catalog(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        expected = config["profiles"]["full"]["third_party_libraries"]
        observed: list[str] = []
        for family in ("a-f", "g-l", "m-r", "s-z"):
            shard_config, selected = build_pack_shard_config.build_shard_config(config, family)
            self.assertTrue(selected)
            self.assertEqual(shard_config["profiles"]["pack-shard"]["third_party_libraries"], selected)
            self.assertEqual(shard_config["profiles"]["pack-shard"]["verification"], {"enabled": False})
            self.assertTrue(all(build_release_index.pack_family(name) == family for name in selected))
            observed.extend(selected)
        self.assertCountEqual(observed, expected)
        self.assertEqual(len({name.casefold() for name in observed}), len(observed))

    def test_loading_cleanup_definitions_does_not_resolve_remote_dependencies(self) -> None:
        library_root = self.root / "Lib"
        library_root.mkdir()
        catalog = {
            "libraries": [
                {
                    "name": "demo",
                    "overlay_entries": ["Lib/demo"],
                    "source_provider": "pypi",
                }
            ]
        }
        with mock.patch.object(libs, "_resolve_selected_integrations") as resolver:
            definitions = libs.load_integration_definitions(
                library_root,
                library_catalog=catalog,
            )
        resolver.assert_not_called()
        self.assertEqual([integration.name for integration in definitions], ["demo"])

    def test_output_pack_filter_keeps_dependencies_linked_but_not_exported(self) -> None:
        dependency = SimpleNamespace(name="dependency")
        root = SimpleNamespace(name="root")
        selected = build.select_output_pack_integrations([dependency, root], ["root"])
        self.assertEqual(selected, [root])
        with self.assertRaisesRegex(RuntimeError, "did not match"):
            build.select_output_pack_integrations([dependency, root], ["missing"])

    def test_resolved_dependencies_are_canonicalized_for_pack_metadata(self) -> None:
        dependency = libs.LibraryIntegration(
            name="dependency",
            project_name="dependency-project",
            release_version="2.1",
        )
        root = libs.LibraryIntegration(
            name="root",
            source_provider="pypi",
            project_name="root-project",
            release_version="1.0",
            auto_resolve_dependencies=True,
        )
        with mock.patch.object(
            libs,
            "_pypi_dependency_requirements",
            return_value=[("dependency-project", ">=2")],
        ):
            selected = libs._resolve_selected_integrations(
                [root, dependency],
                ["root"],
                target_version=libs.Version("3.13"),
            )
        self.assertEqual([integration.name for integration in selected], ["dependency", "root"])
        self.assertEqual(root.dependencies, ["dependency"])
        self.assertEqual(root.dependency_constraints, {"dependency": ">=2"})

    def test_dependency_resolution_selects_latest_compatible_source_release(self) -> None:
        dependency = libs.LibraryIntegration(
            name="dependency",
            source_provider="pypi",
            project_name="dependency-project",
        )
        root = libs.LibraryIntegration(
            name="root",
            release_version="1.0",
            dependencies=["dependency"],
            dependency_constraints={"dependency": "<2"},
        )
        candidates = [("2.1", {"url": "new"}), ("1.5", {"url": "compatible"})]
        with mock.patch.object(libs, "_iter_pypi_distribution_candidates", return_value=candidates):
            selected = libs._resolve_selected_integrations(
                [root, dependency],
                ["root"],
                target_version=libs.Version("3.13"),
            )
        self.assertEqual([integration.name for integration in selected], ["dependency", "root"])
        self.assertEqual(dependency.release_version, "1.5")

    def test_dependency_cycles_are_kept_as_stable_components(self) -> None:
        first = libs.LibraryIntegration(name="first", dependencies=["second"])
        second = libs.LibraryIntegration(name="second", dependencies=["first"])
        selected_from_first = libs.select_integrations([first, second], ["first"])
        selected_from_second = libs.select_integrations([first, second], ["second"])
        self.assertEqual([integration.name for integration in selected_from_first], ["first", "second"])
        self.assertEqual([integration.name for integration in selected_from_second], ["first", "second"])

    def test_catalog_declares_dependencies_missing_from_upstream_metadata(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        catalog = {
            item["name"]: item
            for item in config["third_party_library_catalog"]["libraries"]
        }
        self.assertEqual(catalog["soupsieve"]["dependencies"], ["bs4"])
        self.assertEqual(catalog["webruntime"]["dependencies"], ["dialite"])
        self.assertEqual(catalog["bleach"]["release_version"], "6.4.0")
        self.assertEqual(catalog["bleach"]["dependencies"], ["tinycss2"])
        self.assertEqual(
            catalog["bleach"]["dependency_constraints"],
            {"tinycss2": ">=1.1.0"},
        )
        self.assertEqual(catalog["janus"]["release_version"], "2.0.0")
        self.assertEqual(catalog["janus"]["license_expression"], "Apache-2.0")

        dash_spec = importlib.util.spec_from_file_location(
            "staticpython_dash_dependency_test",
            REPO_ROOT / "Lib" / "dash" / "setup.py",
        )
        assert dash_spec is not None and dash_spec.loader is not None
        dash_module = importlib.util.module_from_spec(dash_spec)
        dash_spec.loader.exec_module(dash_module)
        self.assertEqual(dash_module.LIBRARY_INTEGRATION.dependencies, ["janus"])
        self.assertEqual(
            dash_module.LIBRARY_INTEGRATION.dependency_constraints,
            {"janus": ">=1.0.0"},
        )

    def test_default_integration_smoke_executes_real_import(self) -> None:
        integration = libs.LibraryIntegration(name="demo", top_level_import_names=["demo.api"])
        result = {
            "ok": True,
            "timeout": False,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "display": "python -c import-demo",
            "duration_seconds": 0.01,
        }
        with mock.patch.object(staticpython_verify, "run_capture", return_value=result) as run_capture:
            failures, records = staticpython_verify.verify_integration_smoke_tests(
                ["python.exe"],
                None,
                REPO_ROOT,
                [integration],
                set(),
            )
        self.assertEqual(failures, [])
        self.assertEqual(records[0]["status"], "passed")
        command = run_capture.call_args.args[0]
        self.assertEqual(command[:2], ["python.exe", "-c"])
        self.assertIn("importlib.import_module('demo.api')", command[2])

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

    def test_release_index_requires_every_pack_for_every_target_abi(self) -> None:
        packs = {"demo": {"1.0": {"cp311": {}}}}
        with self.assertRaisesRegex(RuntimeError, "missing target ABIs"):
            build_release_index.validate_expected_pack_matrix(packs, ["demo"])
        packs["demo"]["1.0"].update({abi: {} for abi in build_release_index.TARGET_ABIS})
        build_release_index.validate_expected_pack_matrix(packs, ["demo"])
        with self.assertRaisesRegex(RuntimeError, "missing current library packs"):
            build_release_index.validate_expected_pack_matrix(packs, ["demo", "other"])

    def test_release_index_requires_dependency_assets_for_the_same_abi(self) -> None:
        packs = {
            "root": {
                "1.0": {
                    "cp313": {
                        "metadata": {
                            "dependencies": ["dependency"],
                            "dependency_constraints": {"dependency": "<2"},
                        }
                    }
                }
            }
        }
        with self.assertRaisesRegex(RuntimeError, "requires unpublished pack"):
            build_release_index.validate_pack_dependency_assets(packs)
        packs["dependency"] = {
            "2.1": {"cp313": {"metadata": {"dependencies": [], "dependency_constraints": {}}}}
        }
        with self.assertRaisesRegex(RuntimeError, "no published dependency<2"):
            build_release_index.validate_pack_dependency_assets(packs)
        packs["dependency"]["1.5"] = {
            "cp313": {"metadata": {"dependencies": [], "dependency_constraints": {}}}
        }
        build_release_index.validate_pack_dependency_assets(packs)


if __name__ == "__main__":
    unittest.main(verbosity=2)
