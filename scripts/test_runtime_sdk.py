from __future__ import annotations

import json
import hashlib
import importlib.util
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
import resolve_pack_versions as pack_version_resolver

_LICENSE_AUDIT_SPEC = importlib.util.spec_from_file_location(
    "staticpython_audit_library_licenses",
    REPO_ROOT / "scripts" / "audit_library_licenses.py",
)
assert _LICENSE_AUDIT_SPEC is not None and _LICENSE_AUDIT_SPEC.loader is not None
audit_library_licenses = importlib.util.module_from_spec(_LICENSE_AUDIT_SPEC)
_LICENSE_AUDIT_SPEC.loader.exec_module(audit_library_licenses)

_RESOURCE_SCAN_SPEC = importlib.util.spec_from_file_location(
    "staticpython_scan_library_resources",
    REPO_ROOT / "scripts" / "scan_library_resources.py",
)
assert _RESOURCE_SCAN_SPEC is not None and _RESOURCE_SCAN_SPEC.loader is not None
scan_library_resources = importlib.util.module_from_spec(_RESOURCE_SCAN_SPEC)
sys.modules[_RESOURCE_SCAN_SPEC.name] = scan_library_resources
_RESOURCE_SCAN_SPEC.loader.exec_module(scan_library_resources)


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

    def test_runtime_sdk_links_pythoncore_registry_and_security_apis(self) -> None:
        manifest = build.load_manifest()
        dependencies = {
            build.normalize_library_name(name).casefold()
            for name in manifest["python_link_dependencies_release_x64"]
        }
        self.assertIn("advapi32.lib", dependencies)

    def test_pack_only_build_compiles_only_integration_owned_projects(self) -> None:
        pcbuild = self.root / "PCbuild"
        pcbuild.mkdir(parents=True)
        (pcbuild / "demo_static.vcxproj").write_text("<Project />", encoding="utf-8")
        (pcbuild / "pythoncore.vcxproj").write_text("<Project />", encoding="utf-8")
        (pcbuild / "python.vcxproj").write_text("<Project />", encoding="utf-8")
        integration = libs.LibraryIntegration(
            name="demo",
            static_library_projects_release_x64=["demo_static.vcxproj"],
        )
        with (
            mock.patch.object(build, "run_pre_build_hooks") as pre_build,
            mock.patch.object(build, "stage_static_libraries") as stage,
            mock.patch.object(build, "resolve_msbuild_exe", return_value=Path("msbuild.exe")),
            mock.patch.object(
                build,
                "msbuild_args",
                return_value=["/p:Configuration=Release"],
            ) as msbuild_args,
            mock.patch.object(build, "run") as run,
        ):
            build.build_pack_static_libraries(
                self.root,
                "Release",
                "x64",
                [integration],
                (3, 13, 14),
                "3.13",
                "3.13.14",
                2,
            )
        pre_build.assert_called_once()
        stage.assert_called_once_with(self.root, "x64", {}, [integration])
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertIn(str(pcbuild / "demo_static.vcxproj"), command)
        self.assertNotIn(str(pcbuild / "pythoncore.vcxproj"), command)
        self.assertNotIn(str(pcbuild / "python.vcxproj"), command)
        self.assertIn("BuildProjectReferences=false", msbuild_args.call_args.args)

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

    def test_runtime_builtin_module_names_come_from_target_inittab(self) -> None:
        config = self.root / "PC" / "config.c"
        config.parent.mkdir(parents=True)
        config.write_text(
            '''
static struct _inittab unrelated[] = {
    {"must_not_ship", PyInit_must_not_ship},
    {0, 0}
};
struct _inittab _PyImport_Inittab[] = {
    {"_abc", PyInit__abc},
    {"builtins", NULL},
    {"sys", NULL},
    {0, 0} /* Sentinel */
};
''',
            encoding="utf-8",
        )
        self.assertEqual(
            build.runtime_builtin_module_names(self.root),
            ["_abc", "builtins", "sys"],
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

    def test_freezer_preserves_nested_runtime_docs_packages(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_freeze_modules_test",
            REPO_ROOT / "assets" / "overlay" / "Tools" / "build" / "freeze_modules.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for relative in (
            "Lib/docs/__init__.py",
            "Lib/botocore/__init__.py",
            "Lib/botocore/docs/__init__.py",
            "Lib/botocore/docs/bcdoc.py",
            "Lib/botocore/tests/__init__.py",
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# test\n", encoding="utf-8")

        names = {item.fullname for item in module.find_python_modules(str(self.root))}
        self.assertIn("botocore.docs", names)
        self.assertIn("botocore.docs.bcdoc", names)
        self.assertNotIn("docs", names)
        self.assertNotIn("botocore.tests", names)

    def test_wxpython_pack_declares_gdiplus_provider_and_behavior_smokes(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_wxpython_pack_test",
            REPO_ROOT / "Lib" / "wxpython" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        integration = module.LIBRARY_INTEGRATION
        self.assertEqual(integration.release_version, "4.2.5")
        self.assertEqual(integration.minimum_release_version, "4.2.5")
        self.assertEqual(integration.license_expression, "wxWindows")
        self.assertEqual(
            integration.suppressed_system_libraries_release_x64,
            ["gdiplus.lib"],
        )
        self.assertEqual(
            integration.trusted_object_origins,
            [{"library": "wxbase32u.lib", "object": "main.obj"}],
        )
        self.assertEqual(
            [
                name
                for name in module.WXPYTHON_SYSTEM_LIBRARIES
                if not build.is_windows_system_library(name)
                and not build.is_windows_sdk_library(name)
            ],
            [],
        )
        self.assertEqual(
            [test["name"] for test in integration.smoke_tests],
            ["wx-native-modules", "wx-window-lifecycle"],
        )

    def test_wxpython_link_metadata_tracks_bundled_wxwidgets_version(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_wxpython_versioned_libraries_test",
            REPO_ROOT / "Lib" / "wxpython" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        header = self.root / "wxpython_builtin" / "wxWidgets" / "include" / "wx" / "version.h"
        header.parent.mkdir(parents=True)
        header.write_text(
            "#define wxMAJOR_VERSION 3\n#define wxMINOR_VERSION 3\n",
            encoding="utf-8",
        )
        messages: list[str] = []
        context = SimpleNamespace(source_root=self.root, log=messages.append)
        libraries = module._synchronize_wxwidgets_link_metadata(context)

        self.assertIn("wxbase33u.lib", libraries)
        self.assertIn("wxmsw33u_core.lib", libraries)
        self.assertNotIn("wxbase32u.lib", libraries)
        self.assertEqual(
            module.LIBRARY_INTEGRATION.trusted_object_origins,
            [{"library": "wxbase33u.lib", "object": "main.obj"}],
        )
        self.assertEqual(
            module.LIBRARY_INTEGRATION.python_link_dependencies_release_x64,
            [
                *module.WXPYTHON_MODULE_LIBRARIES,
                *libraries,
                *module.WXPYTHON_SYSTEM_LIBRARIES,
            ],
        )
        self.assertEqual(messages, ["using wxWidgets 3.3 static library names"])

    def test_wxpython_version_header_drift_fails_closed(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_wxpython_version_header_drift_test",
            REPO_ROOT / "Lib" / "wxpython" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        header = self.root / "wxpython_builtin" / "wxWidgets" / "include" / "wx" / "version.h"
        header.parent.mkdir(parents=True)
        header.write_text(
            "#define wxMAJOR_VERSION 3\n"
            "#define wxMAJOR_VERSION 4\n"
            "#define wxMINOR_VERSION 3\n",
            encoding="utf-8",
        )
        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        with self.assertRaisesRegex(RuntimeError, "wxMAJOR_VERSION exactly once"):
            module._synchronize_wxwidgets_link_metadata(context)

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
            suppressed_system_libraries_release_x64=["GdiPlus.lib"],
            python_link_dependencies_release_x64=["demo-native.lib"],
            trusted_object_origins=[
                {"library": "demo-native.lib", "object": "MAIN.OBJ"},
            ],
            license_expression="MIT",
            license_files=["Lib/demo/LICENSE.txt"],
        )
        native_output = self.root / "PCbuild" / "amd64"
        native_output.mkdir(parents=True)
        (native_output / "demo-native.lib").write_bytes(b"library")
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
            self.assertEqual(metadata["suppressed_system_libraries"], ["gdiplus.lib"])
            self.assertEqual(
                metadata["trusted_object_origins"],
                [{"library": "demo-native.lib", "object": "main.obj"}],
            )
            self.assertEqual(
                metadata["verification"]["smoke_tests"],
                [{"name": "import-demo", "kind": "import", "status": "passed"}],
            )
            self.assertIn('"demo"', descriptor)
            self.assertIn("staticpython_pack_demo_resource_", descriptor)
            self.assertNotIn('_Py_M__other', descriptor)

    def test_system_library_suppression_resolves_pack_link_collisions(self) -> None:
        consumer = libs.LibraryIntegration(
            name="consumer",
            python_link_dependencies_release_x64=["gdiplus.lib", "user32.lib"],
        )
        provider = libs.LibraryIntegration(
            name="provider",
            suppressed_system_libraries_release_x64=["GDIPLUS.LIB"],
        )
        dependencies = build.iter_python_link_dependencies(
            self.root,
            {"python_link_dependencies_release_x64": []},
            [consumer, provider],
        )
        self.assertEqual(dependencies, ["user32.lib"])

        provider.suppressed_system_libraries_release_x64 = ["private.lib"]
        with self.assertRaisesRegex(RuntimeError, "only name Windows system libraries"):
            build.iter_python_link_dependencies(
                self.root,
                {"python_link_dependencies_release_x64": []},
                [consumer, provider],
            )

    def test_trusted_object_origin_must_name_a_pack_owned_library(self) -> None:
        integration = libs.LibraryIntegration(
            name="demo",
            trusted_object_origins=[
                {"library": "outside.lib", "object": "main.obj"},
            ],
        )
        with self.assertRaisesRegex(RuntimeError, "not owned by the pack"):
            build._integration_trusted_object_origins(
                integration,
                [{"logical_name": "owned.lib"}],
            )


    def test_prepare_hooks_finalize_custom_pypi_license_metadata(self) -> None:
        source_root = self.root / "source"
        package = source_root / "Lib" / "demo"
        package.mkdir(parents=True)
        cache_root = self.root / "work"
        upstream = cache_root / "pypi" / "demo-project" / "1.2.3" / "extracted" / "demo-1.2.3"
        upstream.mkdir(parents=True)
        (upstream / "LICENSE.txt").write_text("upstream license\n", encoding="utf-8")

        def prepare_demo(_context: libs.LibraryHookContext) -> None:
            (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            project_name="demo-project",
            release_version="1.2.3",
            materialized_paths=["Lib/demo"],
            prepare_source_hooks=[prepare_demo],
        )
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=source_root,
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=cache_root,
            asset_overlay_root=self.root / "assets",
            log=lambda _message: None,
        )
        with mock.patch.object(
            libs,
            "_load_pypi_release_payload",
            return_value={"info": {"license_expression": "Apache-2.0"}},
        ):
            libs.run_prepare_source_hooks([integration], context)

        self.assertEqual(integration.license_expression, "Apache-2.0")
        self.assertEqual(len(integration.license_files), 1)
        copied_license = source_root / integration.license_files[0]
        self.assertEqual(copied_license.read_text(encoding="utf-8"), "upstream license\n")

    def test_temporary_pypi_release_cache_discards_only_selected_release(self) -> None:
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=self.root / "source",
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=self.root / "work",
            asset_overlay_root=self.root / "assets",
            log=lambda _message: None,
        )
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            project_name="demo-project",
        )
        selected_roots = []
        sibling_roots = []
        for cache_root in (context.download_cache_root, context.work_cache_root):
            selected = cache_root / "pypi" / "demo-project" / "1.2.3"
            selected.mkdir(parents=True)
            (selected / "payload.bin").write_bytes(b"selected")
            selected_roots.append(selected)
            sibling = cache_root / "pypi" / "demo-project" / "1.2.4"
            sibling.mkdir(parents=True)
            (sibling / "payload.bin").write_bytes(b"sibling")
            sibling_roots.append(sibling)

        with libs.temporary_pypi_release_cache(context, integration, "1.2.3"):
            self.assertTrue(all(path.exists() for path in selected_roots))

        self.assertTrue(all(not path.exists() for path in selected_roots))
        self.assertTrue(all(path.exists() for path in sibling_roots))

    def test_temporary_pypi_release_cache_discards_after_failure(self) -> None:
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=self.root / "source",
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=self.root / "work",
            asset_overlay_root=self.root / "assets",
            log=lambda _message: None,
        )
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            project_name="demo-project",
        )
        selected_roots = []
        for cache_root in (context.download_cache_root, context.work_cache_root):
            selected = cache_root / "pypi" / "demo-project" / "1.2.3"
            selected.mkdir(parents=True)
            (selected / "payload.bin").write_bytes(b"selected")
            selected_roots.append(selected)

        with self.assertRaisesRegex(RuntimeError, "version failed"):
            with libs.temporary_pypi_release_cache(context, integration, "1.2.3"):
                raise RuntimeError("version failed")

        self.assertTrue(all(not path.exists() for path in selected_roots))

    def test_declared_license_source_is_versioned_and_hash_verified(self) -> None:
        payload = b"fallback license\n"
        digest = hashlib.sha256(payload).hexdigest()
        source_root = self.root / "source"
        source_root.mkdir()
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            project_name="demo-project",
            release_version="1.2.3",
            license_expression="MIT",
            license_sources=[
                {
                    "filename": "LICENSE",
                    "url": "https://example.invalid/demo/v{release_version}/LICENSE",
                    "sha256": digest,
                }
            ],
        )
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=source_root,
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=self.root / "work",
            asset_overlay_root=self.root / "assets",
            log=lambda _message: None,
        )
        with mock.patch.object(libs, "_read_url_bytes", return_value=payload) as read:
            libs._finalize_integration_license_metadata(context, integration)

        read.assert_called_once_with("https://example.invalid/demo/v1.2.3/LICENSE")
        self.assertEqual(integration.license_files, ["licenses/demo/LICENSE"])
        self.assertEqual((source_root / integration.license_files[0]).read_bytes(), payload)
        self.assertEqual(
            build.resolved_license_sources(integration),
            [
                {
                    "filename": "LICENSE",
                    "url": "https://example.invalid/demo/v1.2.3/LICENSE",
                    "sha256": digest,
                }
            ],
        )

    def test_declared_license_source_rejects_hash_drift(self) -> None:
        source_root = self.root / "source"
        source_root.mkdir()
        integration = libs.LibraryIntegration(
            name="demo",
            release_version="1.2.3",
            license_sources=[
                {
                    "filename": "LICENSE",
                    "url": "https://example.invalid/LICENSE",
                    "sha256": "0" * 64,
                }
            ],
        )
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=source_root,
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=self.root / "work",
            asset_overlay_root=self.root / "assets",
            log=lambda _message: None,
        )
        with mock.patch.object(libs, "_read_url_bytes", return_value=b"changed\n"):
            with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                libs._materialize_declared_license_sources(context, integration)

    def test_license_expression_inference_prefers_specific_metadata(self) -> None:
        cases = {
            "Apache-2.0 AND MIT": "Apache-2.0 AND MIT",
            "BSD-2-Clause": "BSD-2-Clause",
            "3-Clause BSD License": "BSD-3-Clause",
            "Apache License, Version 2.0": "Apache-2.0",
            "MIT OR Apache-2.0": "MIT OR Apache-2.0",
            "MPL-2.0 AND MIT": "MPL-2.0 AND MIT",
            "Unlicense": "Unlicense",
        }
        for raw_license, expected in cases.items():
            with self.subTest(raw_license=raw_license):
                self.assertEqual(
                    libs._infer_license_expression(
                        {
                            "license": raw_license,
                            "classifiers": ["License :: OSI Approved :: BSD License"],
                        }
                    ),
                    expected,
                )

    def test_ambiguous_library_licenses_are_declared_explicitly(self) -> None:
        config = build.load_config()
        _profile_name, profile = build.resolve_profile(config, "full")
        catalog = build.profile_library_catalog(config, profile, "third_party_library_catalog")
        integrations = libs.load_integration_definitions(
            build.LIB_PATCH_ROOT,
            library_catalog=catalog,
        )
        by_name = {integration.name: integration for integration in integrations}
        expected = {
            "Crypto": "BSD-2-Clause AND LicenseRef-Public-Domain",
            "dateutil": "Apache-2.0 OR BSD-3-Clause",
            "dearpygui": "MIT",
            "dialite": "BSD-2-Clause",
            "fsspec": "BSD-3-Clause",
            "glfw": "Zlib",
            "mypy_extensions": "MIT",
            "pscript": "BSD-2-Clause",
            "pyglet": "BSD-3-Clause",
            "pystray": "LGPL-3.0-only",
            "socks": "BSD-3-Clause",
            "text_unidecode": "GPL-1.0-or-later OR Artistic-1.0-Perl",
        }
        for name, expression in expected.items():
            with self.subTest(name=name):
                self.assertEqual(by_name[name].license_expression, expression)

        fallback_sources = {
            "humanize",
            "loguru",
            "tqdm",
            "ua_parser_builtins",
            "webencodings",
        }
        for name in fallback_sources:
            with self.subTest(license_source=name):
                self.assertEqual(len(by_name[name].license_sources), 1)
                self.assertRegex(by_name[name].license_sources[0]["sha256"], r"^[0-9a-f]{64}$")

    def test_library_license_audit_reports_all_incomplete_integrations(self) -> None:
        source_root = self.root / "source"
        license_path = source_root / "licenses" / "good" / "LICENSE"
        license_path.parent.mkdir(parents=True)
        license_path.write_text("permission notice\n", encoding="utf-8")
        integrations = [
            libs.LibraryIntegration(
                name="good",
                release_version="1.0",
                license_expression="MIT",
                license_files=["licenses/good/LICENSE"],
            ),
            libs.LibraryIntegration(name="missing-expression", release_version="2.0"),
            libs.LibraryIntegration(
                name="missing-file",
                release_version="3.0",
                license_expression="Apache-2.0",
                license_files=["licenses/missing/LICENSE"],
            ),
        ]

        summary = audit_library_licenses.audit_integration_licenses(
            source_root,
            integrations,
        )

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["integration_count"], 3)
        self.assertEqual(summary["failure_count"], 2)
        self.assertEqual(
            {failure["name"] for failure in summary["failures"]},
            {"missing-expression", "missing-file"},
        )
        self.assertEqual(summary["integrations"][0]["status"], "passed")
        self.assertEqual(len(summary["integrations"][0]["files"][0]["sha256"]), 64)

    def test_license_collision_names_are_independent_of_source_paths(self) -> None:
        def materialize(label: str, first_payload: bytes, second_payload: bytes) -> dict[str, bytes]:
            upstream = self.root / f"upstream-{label}"
            first = upstream / "a" / "LICENSE"
            second = upstream / "z" / "LICENSE"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(first_payload)
            second.write_bytes(second_payload)
            source_root = self.root / f"source-{label}"
            source_root.mkdir()
            context = libs.LibraryHookContext(
                repo_root=REPO_ROOT,
                source_root=source_root,
                version_info=(3, 13, 0),
                version_mm="3.13",
                version_full="3.13.0",
                download_cache_root=self.root / "downloads",
                work_cache_root=self.root / "work",
                asset_overlay_root=self.root / "assets",
                log=lambda _message: None,
            )
            integration = libs.LibraryIntegration(name="demo")
            libs._materialize_license_candidates(
                context,
                integration,
                [first, second],
            )
            return {
                relative: (source_root / relative).read_bytes()
                for relative in integration.license_files
            }

        first = materialize("one", b"alpha\n", b"beta\n")
        second = materialize("two", b"beta\n", b"alpha\n")
        self.assertEqual(first, second)

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

        globally_resolved = {"mpmath": "1.3.0", "sympy": "1.14.0"}
        shard_config, _selected = build_pack_shard_config.build_shard_config(
            config,
            "m-r",
            version_overrides=globally_resolved,
        )
        self.assertEqual(
            shard_config["profiles"]["pack-shard"]["third_party_library_version_overrides"],
            globally_resolved,
        )

    def test_global_pack_version_lock_preserves_cross_family_solution(self) -> None:
        config = build.load_config()
        integrations = [
            libs.LibraryIntegration(
                name="mpmath",
                source_provider="pypi",
                project_name="mpmath",
                release_version="1.3.0",
            ),
            libs.LibraryIntegration(
                name="sympy",
                source_provider="pypi",
                project_name="sympy",
                release_version="1.14.0",
                dependencies=["mpmath"],
                dependency_constraints={"mpmath": "<1.4,>=1.1.0"},
            ),
        ]
        with mock.patch.object(
            pack_version_resolver.libs,
            "load_integrations",
            return_value=integrations,
        ) as load:
            payload = pack_version_resolver.resolve_pack_versions(config, "3.11.15")

        self.assertEqual(payload["versions"]["mpmath"], "1.3.0")
        self.assertEqual(payload["versions"]["sympy"], "1.14.0")
        self.assertEqual(payload["target_python_version"], "3.11.15")
        selected = load.call_args.args[1]
        self.assertIn("mpmath", selected)
        self.assertIn("sympy", selected)

        lock_path = self.root / "pack-version-lock.json"
        lock_path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = pack_version_resolver.load_pack_version_lock(
            lock_path,
            target_python_version="3.11.15",
        )
        self.assertEqual(loaded["versions"]["mpmath"], "1.3.0")
        with self.assertRaisesRegex(RuntimeError, "targets Python"):
            pack_version_resolver.load_pack_version_lock(
                lock_path,
                target_python_version="3.12.13",
            )

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

    def test_aws_sdk_catalog_declares_resource_behavior_smokes(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        catalog = {
            item["name"]: item
            for item in config["third_party_library_catalog"]["libraries"]
        }
        full = config["profiles"]["full"]["third_party_libraries"]
        self.assertEqual(
            [name for name in full if name in {"boto3", "botocore", "s3transfer"}],
            ["boto3", "botocore", "s3transfer"],
        )
        self.assertEqual(catalog["boto3"]["license_expression"], "Apache-2.0")
        self.assertEqual(catalog["botocore"]["license_expression"], "Apache-2.0")
        self.assertEqual(catalog["s3transfer"]["license_expression"], "Apache-2.0")
        self.assertEqual(
            [test["name"] for test in catalog["boto3"]["smoke_tests"]],
            ["s3-client-model"],
        )
        self.assertEqual(
            [test["name"] for test in catalog["botocore"]["smoke_tests"]],
            ["embedded-s3-service-model"],
        )
        self.assertEqual(
            [test["name"] for test in catalog["s3transfer"]["smoke_tests"]],
            ["transfer-config"],
        )

    def test_resource_scanner_loads_generic_catalog_integrations(self) -> None:
        config_path = self.root / "config.json"
        catalog = {
            "libraries": [
                {
                    "name": "demo",
                    "overlay_entries": ["Lib/demo"],
                    "source_provider": "pypi",
                }
            ]
        }
        config_path.write_text(
            json.dumps({
                "default_profile": "full",
                "third_party_library_catalog": catalog,
                "profiles": {"full": {"third_party_libraries": ["demo"]}},
            }),
            encoding="utf-8",
        )
        with mock.patch.object(scan_library_resources, "load_integrations", return_value=[]) as load:
            result = scan_library_resources.main([
                "--repo-root", str(self.root),
                "--config", str(config_path),
                "--profile", "full",
                "--python-version", "3.13",
                "--libraries", "demo",
                "--work-root", str(self.root / "work"),
                "--json", str(self.root / "report.json"),
                "--markdown", str(self.root / "report.md"),
            ])
        self.assertEqual(result, 0)
        self.assertEqual(load.call_args.kwargs["library_catalog"], catalog)

    def test_resource_scanner_recognizes_pack_roots_and_custom_pypi_hooks(self) -> None:
        resource = self.root / "service-2.json"
        resource.write_text("{}", encoding="utf-8")
        integration = SimpleNamespace(
            name="botocore",
            project_name="botocore",
            materialized_paths=["Lib/botocore"],
            prepare_source_hooks=[],
        )
        status, reason = scan_library_resources.classify_resource(
            resource,
            "Lib/botocore/data/s3/2006-03-01/service-2.json",
            "botocore/data/s3/2006-03-01/service-2.json",
            "",
            integration,
        )
        self.assertEqual(status, "handled")
        self.assertIn("StaticPythonPackV1", reason)

        source_info = scan_library_resources.pypi_source_info(SimpleNamespace(
            name="six",
            project_name="six",
            materialized_paths=["Lib/six"],
            prepare_source_hooks=[lambda _context: None],
        ))
        self.assertIsNotNone(source_info)
        assert source_info is not None
        self.assertEqual(source_info.source_mapping, {"six": "Lib/six"})

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
            "trusted_object_origins": [
                {"library": "attrs.lib", "object": "main.obj"},
            ],
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
        self.assertEqual(
            pack["metadata"]["trusted_object_origins"],
            [{"library": "attrs.lib", "object": "main.obj"}],
        )

    def test_release_index_keeps_only_resolver_metadata(self) -> None:
        runtime_metadata = {
            "runtime_abi": "staticpython-pack-v1-cp313",
            "link_libraries": ["pythoncore.lib"],
            "verification": {"status": "passed"},
            "files": [{"path": "lib/pythoncore.lib", "sha256": "a" * 64}],
        }
        self.assertEqual(
            build_release_index.runtime_index_metadata(runtime_metadata),
            {
                "runtime_abi": "staticpython-pack-v1-cp313",
                "link_libraries": ["pythoncore.lib"],
                "verification": {"status": "passed"},
            },
        )

        pack_path = self.root / "demo.zip"
        pack_metadata = {
            "name": "demo",
            "version": "1.0",
            "sources": ["src/pack.c", "src/resources/resource_000001.c"],
            "resources": [
                {
                    "path": "demo/data.json",
                    "symbol": "staticpython_pack_demo_resource_1",
                    "source": "src/resources/resource_000001.c",
                    "size": 42,
                    "compressed_size": 21,
                    "sha256": "b" * 64,
                }
            ],
            "libraries": ["demo.lib"],
            "suppressed_system_libraries": ["gdiplus.lib"],
            "trusted_object_origins": [
                {"library": "demo.lib", "object": "main.obj"},
            ],
            "source_files": [{"path": "demo/data.json", "sha256": "b" * 64}],
            "smoke_tests": [{"kind": "import", "module": "demo"}],
            "files": [{"path": "lib/demo.lib", "sha256": "c" * 64}],
        }
        projected = build_release_index.pack_index_metadata(pack_metadata, pack_path)
        self.assertEqual(projected["resources"], [{"path": "demo/data.json"}])
        self.assertEqual(projected["sources"], pack_metadata["sources"])
        self.assertEqual(projected["libraries"], ["demo.lib"])
        self.assertEqual(projected["suppressed_system_libraries"], ["gdiplus.lib"])
        self.assertEqual(
            projected["trusted_object_origins"],
            [{"library": "demo.lib", "object": "main.obj"}],
        )
        self.assertEqual(
            build_release_index.pack_index_metadata(
                {"trusted_object_origins": []},
                pack_path,
            )["trusted_object_origins"],
            [],
        )
        self.assertNotIn("source_files", projected)
        self.assertNotIn("smoke_tests", projected)
        self.assertNotIn("files", projected)
        self.assertEqual(
            pack_metadata["resources"][0]["symbol"],
            "staticpython_pack_demo_resource_1",
        )

    def test_release_index_rejects_resource_without_virtual_path(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "invalid resource record"):
            build_release_index.pack_index_metadata(
                {"resources": [{"source": "src/resources/resource_000001.c"}]},
                self.root / "demo.zip",
            )

    def test_release_index_serialization_is_compact_and_newline_terminated(self) -> None:
        self.assertEqual(
            build_release_index.serialize_index({"schema_version": 1, "values": [1, 2]}),
            '{"schema_version":1,"values":[1,2]}\n',
        )

    def test_release_index_requires_every_pack_for_every_target_abi(self) -> None:
        packs = {"demo": {"1.0": {"cp311": {}}}}
        with self.assertRaisesRegex(RuntimeError, "missing target ABIs"):
            build_release_index.validate_expected_pack_matrix(packs, ["demo"])
        packs["demo"]["1.0"].update({abi: {} for abi in build_release_index.TARGET_ABIS})
        build_release_index.validate_expected_pack_matrix(packs, ["demo"])
        with self.assertRaisesRegex(RuntimeError, "missing current library packs"):
            build_release_index.validate_expected_pack_matrix(packs, ["demo", "other"])

    def test_release_index_reports_every_incomplete_license_asset(self) -> None:
        assets = self.root / "assets"
        assets.mkdir()
        commit = build.git_commit_or_none(REPO_ROOT)
        for name in ("alpha", "beta"):
            stage = self.root / f"{name}-stage"
            stage.mkdir()
            metadata = {
                "name": name,
                "version": "1.0",
                "cpython_abi": "cp313",
                "staticpython_commit": commit,
                "verification": {"status": "passed"},
                "license": {"status": "missing"},
            }
            (stage / "pack.json").write_text(json.dumps(metadata), encoding="utf-8")
            build.write_deterministic_zip(stage, assets / f"{name}.zip")

        with self.assertRaisesRegex(RuntimeError, r"alpha\.zip[\s\S]*beta\.zip"):
            build_release_index.build_index(
                assets,
                "xqy2006/StaticPython",
                commit,
                "runtime-tag",
                "pack-tag",
                require_all_targets=False,
                require_verified=True,
            )

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

    def test_release_index_toolchain_fingerprint_ignores_vscmd_servicing_revision(self) -> None:
        runtime = {
            "toolchain": {
                "visual_studio_version": "17.0",
                "vscmd_version": "17.14.36",
                "vc_tools_version": "14.44.35207",
                "windows_sdk_version": "10.0.26100.0\\",
                "platform_toolset": "v143",
                "runtime_library": "MultiThreaded",
            }
        }
        pack = json.loads(json.dumps(runtime))
        pack["toolchain"]["vscmd_version"] = "17.14.37"
        self.assertEqual(
            build_release_index.toolchain_abi_fingerprint(runtime),
            build_release_index.toolchain_abi_fingerprint(pack),
        )

    def test_release_index_toolchain_fingerprint_rejects_compiler_drift(self) -> None:
        runtime = {
            "toolchain": {
                "visual_studio_version": "17.0",
                "vscmd_version": "17.14.36",
                "vc_tools_version": "14.44.35207",
                "windows_sdk_version": "10.0.26100.0\\",
                "platform_toolset": "v143",
                "runtime_library": "MultiThreaded",
            }
        }
        pack = json.loads(json.dumps(runtime))
        pack["toolchain"]["vc_tools_version"] = "14.45.00000"
        self.assertNotEqual(
            build_release_index.toolchain_abi_fingerprint(runtime),
            build_release_index.toolchain_abi_fingerprint(pack),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
