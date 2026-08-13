from __future__ import annotations

import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import verify_pack_with_runtime_sdk as verifier

sys.path.insert(0, str(REPO_ROOT))
import build


def _file_records(root: Path) -> list[dict]:
    return [
        {
            "path": path.relative_to(root).as_posix(),
            "size": path.stat().st_size,
            "sha256": verifier.sha256_file(path),
        }
        for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix())
    ]


def _runtime_metadata(root: Path) -> dict:
    return {
        "schema_version": 1,
        "kind": "staticpython-runtime-sdk",
        "runtime_abi": "staticpython-pack-v1-cp313",
        "cpython_abi": "cp313",
        "cpython_version": "3.13.14",
        "cpython_commit": "cpython-commit",
        "cpython_tag": "v3.13.14",
        "staticpython_commit": "staticpython-commit",
        "platform": "x64",
        "base_pack_symbol": "StaticPython_BaseResourcePackV1",
        "pack_registration_function": "StaticPython_RegisterPacks",
        "include_directory": "include",
        "library_directory": "lib",
        "link_libraries": ["staticpython_runtime.lib", "python313.lib"],
        "system_libraries": ["kernel32.lib"],
        "frozen_module_names": ["importlib", "_staticpython_runtime"],
        "builtin_module_names": ["sys"],
        "toolchain": {
            "platform_toolset": "v143",
            "runtime_library": "MultiThreaded",
            "visual_studio_version": "17.0",
            "vscmd_version": "17.0.0",
            "vc_tools_version": "14.44.35207",
            "windows_sdk_version": "10.0.26100.0",
        },
        "verification": {
            "status": "passed",
            "generic_executable_published": False,
        },
        "files": _file_records(root),
    }


def _pack_metadata(root: Path, runtime: dict, *, name: str = "demo") -> dict:
    return {
        "schema_version": 1,
        "kind": "staticpython-library-pack",
        "name": name,
        "version": "1.0",
        "runtime_abi": runtime["runtime_abi"],
        "cpython_abi": runtime["cpython_abi"],
        "cpython_version": runtime["cpython_version"],
        "cpython_commit": runtime["cpython_commit"],
        "cpython_tag": runtime["cpython_tag"],
        "staticpython_commit": runtime["staticpython_commit"],
        "platform": runtime["platform"],
        "toolchain": json.loads(json.dumps(runtime["toolchain"])),
        "descriptor_symbol": f"StaticPython_Pack_{name}",
        "sources": ["src/pack.c"],
        "libraries": [],
        "wholearchive": [],
        "system_libraries": [],
        "suppressed_system_libraries": [],
        "trusted_object_origins": [],
        "dependencies": [],
        "conflicts": [],
        "frozen_modules": [f"{name}.child"],
        "top_level_import_names": [name],
        "builtin_modules": [],
        "resources": [],
        "smoke_tests": [{"kind": "import", "module": name}],
        "license": {"status": "complete", "expression": "MIT"},
        "verification": {"status": "not-run", "smoke_tests": []},
        "files": _file_records(root),
    }


class VerifyPackWithRuntimeSDKTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _make_runtime(self) -> tuple[Path, dict]:
        root = self.root / "runtime"
        (root / "include").mkdir(parents=True)
        (root / "lib").mkdir()
        (root / "include" / "Python.h").write_text("/* Python */\n", encoding="utf-8")
        (root / "include" / "staticpython_pack.h").write_text("/* pack */\n", encoding="utf-8")
        (root / "lib" / "staticpython_runtime.lib").write_bytes(b"runtime")
        (root / "lib" / "python313.lib").write_bytes(b"python")
        metadata = _runtime_metadata(root)
        metadata_path = root / verifier.RUNTIME_METADATA_PATH
        metadata_path.parent.mkdir(parents=True)
        metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
        return root, metadata

    def _make_pack(self, runtime: dict, *, name: str = "demo") -> tuple[Path, dict]:
        root = self.root / f"pack-{name}"
        (root / "src").mkdir(parents=True)
        (root / "licenses").mkdir()
        (root / "src" / "pack.c").write_text("/* descriptor */\n", encoding="utf-8")
        (root / "licenses" / "LICENSE.txt").write_text("license\n", encoding="utf-8")
        metadata = _pack_metadata(root, runtime, name=name)
        (root / verifier.PACK_METADATA_PATH).write_text(json.dumps(metadata), encoding="utf-8")
        return root, metadata

    def test_safe_zip_extraction_rejects_traversal_and_case_collisions(self) -> None:
        traversal = self.root / "traversal.zip"
        with ZipFile(traversal, "w") as archive:
            archive.writestr("../outside.txt", "bad")
        with self.assertRaisesRegex(RuntimeError, "unsafe ZIP member"):
            verifier.safe_extract_zip(traversal, self.root / "extract-traversal")

        collision = self.root / "collision.zip"
        with ZipFile(collision, "w") as archive:
            archive.writestr("Lib/demo.txt", "one")
            archive.writestr("lib/DEMO.txt", "two")
        with self.assertRaisesRegex(RuntimeError, "case-colliding"):
            verifier.safe_extract_zip(collision, self.root / "extract-collision")

        for index, unsafe_name in enumerate(
            ("C:evil", "dir/file:stream", "NUL.txt", "trailing.")
        ):
            with self.subTest(unsafe_name=unsafe_name):
                archive_path = self.root / f"windows-unsafe-{index}.zip"
                with ZipFile(archive_path, "w") as archive:
                    archive.writestr(unsafe_name, "bad")
                with self.assertRaisesRegex(RuntimeError, "unsafe ZIP member"):
                    verifier.safe_extract_zip(
                        archive_path,
                        self.root / f"extract-windows-unsafe-{index}",
                    )

    def test_runtime_and_pack_hashes_and_provenance_are_validated(self) -> None:
        runtime_root, runtime = self._make_runtime()
        self.assertEqual(verifier.validate_runtime_sdk(runtime_root)["runtime_abi"], "staticpython-pack-v1-cp313")
        pack_root, _metadata = self._make_pack(runtime)
        self.assertEqual(verifier.validate_pack(pack_root, runtime)["name"], "demo")

        (runtime_root / "include" / "Python.h").write_text("/* Tamper */\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            verifier.validate_runtime_sdk(runtime_root)

    def test_vscmd_servicing_drift_does_not_change_toolchain_abi(self) -> None:
        _runtime_root, runtime = self._make_runtime()
        pack_root, metadata = self._make_pack(runtime)
        metadata["toolchain"]["vscmd_version"] = "17.14.37"
        (pack_root / verifier.PACK_METADATA_PATH).write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        self.assertEqual(verifier.validate_pack(pack_root, runtime)["name"], "demo")

        metadata["toolchain"]["vc_tools_version"] = "14.45.00000"
        (pack_root / verifier.PACK_METADATA_PATH).write_text(
            json.dumps(metadata), encoding="utf-8"
        )
        with self.assertRaisesRegex(RuntimeError, "toolchain ABI"):
            verifier.validate_pack(pack_root, runtime)

    def test_trusted_object_origin_must_be_exact_and_pack_owned(self) -> None:
        _runtime_root, runtime = self._make_runtime()
        pack_root, metadata = self._make_pack(runtime)
        (pack_root / "lib").mkdir()
        (pack_root / "lib" / "owned.lib").write_bytes(b"library")
        metadata["libraries"] = ["owned.lib"]
        metadata["trusted_object_origins"] = [
            {"library": "owned.lib", "object": "main.obj"},
        ]
        metadata["files"] = [
            record
            for record in _file_records(pack_root)
            if record["path"] != verifier.PACK_METADATA_PATH
        ]
        (pack_root / verifier.PACK_METADATA_PATH).write_text(json.dumps(metadata), encoding="utf-8")
        self.assertEqual(
            verifier.validate_pack(pack_root, runtime)["trusted_object_origins"],
            [{"library": "owned.lib", "object": "main.obj"}],
        )

        metadata["trusted_object_origins"] = [
            {"library": "outside.lib", "object": "main.obj"},
        ]
        (pack_root / verifier.PACK_METADATA_PATH).write_text(json.dumps(metadata), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "trusted object library is missing"):
            verifier.validate_pack(pack_root, runtime)

    def test_main_object_audit_allows_only_declared_archive_origin(self) -> None:
        allowed, forbidden = verifier._classify_main_object_records(
            "\n".join(
                [
                    "0001:00000000 wxEntry wxbase33u.lib(main.obj)",
                    "0001:00000008 wxEntryCleanup wxbase33u:main.obj",
                    "0001:00000010 Py_Main pythoncore.lib(main.obj)",
                    r"0001:00000020 custom_entry C:\build\main.obj",
                    "0001:00000030 impostor notwxbase33u:main.obj",
                    "0001:00000040 mixed wxbase33u.lib(main.obj) pythoncore.lib(main.obj)",
                ]
            ),
            {("wxbase33u.lib", "main.obj")},
        )
        self.assertEqual(
            allowed,
            [
                "0001:00000000 wxEntry wxbase33u.lib(main.obj)",
                "0001:00000008 wxEntryCleanup wxbase33u:main.obj",
            ],
        )
        self.assertEqual(
            forbidden,
            [
                "0001:00000010 Py_Main pythoncore.lib(main.obj)",
                r"0001:00000020 custom_entry C:\build\main.obj",
                "0001:00000030 impostor notwxbase33u:main.obj",
                "0001:00000040 mixed wxbase33u.lib(main.obj) pythoncore.lib(main.obj)",
            ],
        )

    def test_trusted_object_origin_rejects_ambiguous_link_inputs(self) -> None:
        trusted = {("owned.lib", "main.obj")}
        pack = self.root / "pack" / "owned.lib"
        runtime = self.root / "runtime" / "owned.lib"

        verifier._validate_trusted_object_link_inputs(
            trusted,
            pack_libraries=[pack],
            runtime_libraries=[],
            system_libraries=["user32.lib"],
        )
        with self.assertRaisesRegex(RuntimeError, "owned.lib.*runtime SDK"):
            verifier._validate_trusted_object_link_inputs(
                trusted,
                pack_libraries=[pack],
                runtime_libraries=[runtime],
                system_libraries=[],
            )
        with self.assertRaisesRegex(RuntimeError, "owned.lib.*system libraries"):
            verifier._validate_trusted_object_link_inputs(
                trusted,
                pack_libraries=[pack],
                runtime_libraries=[],
                system_libraries=["OWNED.LIB"],
            )
        with self.assertRaisesRegex(RuntimeError, "exactly one selected pack archive"):
            verifier._validate_trusted_object_link_inputs(
                trusted,
                pack_libraries=[],
                runtime_libraries=[],
                system_libraries=[],
            )

    def test_composition_and_namespace_parents_are_inferred(self) -> None:
        runtime = {
            "frozen_module_names": ["importlib"],
            "builtin_module_names": ["sys"],
        }
        metadata = {
            "name": "namespaces",
            "descriptor_symbol": "StaticPython_Pack_namespaces",
            "frozen_modules": ["google.auth", "google.auth.transport", "zope.interface"],
            "builtin_modules": [{"name": "native.child"}],
            "resources": [],
            "dependencies": [],
            "conflicts": [],
        }
        pack = verifier.MaterializedPack(Path("pack.zip"), self.root, metadata)
        verifier.validate_composition(runtime, [pack])
        self.assertEqual(
            verifier.infer_namespace_packages(runtime, [pack]),
            ("google", "native", "zope"),
        )

    def test_verification_root_must_be_selected(self) -> None:
        runtime_root, runtime = self._make_runtime()
        pack_root, _metadata = self._make_pack(runtime)
        pack_archive = self.root / "demo.zip"
        with ZipFile(pack_archive, "w") as archive:
            for path in pack_root.rglob("*"):
                if path.is_file():
                    archive.write(path, path.relative_to(pack_root).as_posix())
        args = mock.Mock(
            runtime_sdk=runtime_root,
            pack=[pack_archive],
            root_pack=["missing"],
            repo_root=REPO_ROOT,
            work_dir=self.root / "work",
            report_json=self.root / "report.json",
            build_workers=1,
            skip_group=[],
        )
        with self.assertRaisesRegex(RuntimeError, "verification root is not selected"):
            verifier.verify_assets(args)

    def test_smoke_sources_are_embedded_with_virtual_script_paths(self) -> None:
        script = self.root / "smoke.py"
        script.write_text("assert __name__ == '__main__'\n", encoding="utf-8")
        import_name, import_kind, import_code, _timeout, _group = verifier._smoke_body(
            self.root,
            "demo",
            1,
            {"kind": "import", "module": "demo"},
        )
        self.assertEqual((import_name, import_kind), ("import-1", "import"))
        self.assertIn("importlib.import_module('demo')", import_code)

        name, kind, code, timeout, group = verifier._smoke_body(
            self.root,
            "demo",
            2,
            {
                "name": "script-smoke",
                "kind": "script",
                "script": "smoke.py",
                "args": ["unicode-参数"],
                "timeout": 12,
                "skip_group": "gui",
            },
        )
        self.assertEqual((name, kind, timeout, group), ("script-smoke", "script", 12.0, "gui"))
        self.assertIn("staticpython-smoke://repo/smoke.py", code)
        self.assertIn("unicode-参数", code)
        self.assertIn("assert __name__", code)

    def test_launcher_is_isolated_and_has_no_generic_python_entry(self) -> None:
        metadata = {
            "name": "demo",
            "descriptor_symbol": "StaticPython_Pack_demo",
        }
        pack = verifier.MaterializedPack(Path("demo.zip"), self.root, metadata)
        smoke = verifier.SmokeCase("demo", "import-demo", "import", "import demo\n", 10)
        launcher = verifier.write_launcher(
            self.root / "launcher.c",
            [pack],
            [smoke],
            ("demo_namespace",),
        )
        text = launcher.read_text(encoding="utf-8")
        self.assertIn("PyConfig_InitIsolatedConfig", text)
        self.assertIn("config.parse_argv = 0", text)
        self.assertIn("config.use_environment = 0", text)
        self.assertIn("&StaticPython_BaseResourcePackV1", text)
        self.assertIn("&StaticPython_Pack_demo", text)
        self.assertIn("wmain", text)
        for symbol in verifier.FORBIDDEN_ENTRY_SYMBOLS:
            self.assertNotIn(symbol, text)

    def test_launcher_embeds_large_utf8_smoke_without_c_string_literals(self) -> None:
        metadata = {
            "name": "demo",
            "descriptor_symbol": "StaticPython_Pack_demo",
        }
        pack = verifier.MaterializedPack(Path("demo.zip"), self.root, metadata)
        code = ("value = 'static-python'\n" * 1200) + "assert value == '参数\\\\quoted'\n"
        smoke = verifier.SmokeCase("demo", "large", "inline", code, 10)
        launcher = verifier.write_launcher(self.root / "large-launcher.c", [pack], [smoke], ())
        text = launcher.read_text(encoding="utf-8")

        marker = "static const unsigned char verification_smoke_0000[] = {"
        self.assertIn(marker, text)
        self.assertIn("(const char *)verification_smoke_0000", text)
        self.assertNotIn(code[:100], text)
        initializer = text.split(marker, 1)[1].split("};", 1)[0]
        encoded = bytes(
            int(token.strip().rstrip(","), 16)
            for line in initializer.splitlines()
            for token in line.split(",")
            if token.strip()
        )
        self.assertEqual(encoded, code.encode("utf-8") + b"\0")
        self.assertLessEqual(max(map(len, initializer.splitlines())), 100)

    def test_system_library_suppressions_apply_to_runtime_and_pack_inputs(self) -> None:
        runtime = {"system_libraries": ["gdiplus.lib", "kernel32.lib"]}
        metadata = {
            "system_libraries": ["comdlg32.lib", "user32.lib"],
            "suppressed_system_libraries": ["gdiplus.lib"],
        }
        pack = verifier.MaterializedPack(Path("demo.zip"), self.root, metadata)
        self.assertEqual(
            verifier._resolve_system_libraries(runtime, [pack]),
            ["comdlg32.lib", "user32.lib", "kernel32.lib", "advapi32.lib", "shell32.lib"],
        )

    def test_windows_link_library_allowlist_matches_the_builder(self) -> None:
        self.assertEqual(
            verifier.WINDOWS_LINK_LIBRARY_NAMES,
            build.WINDOWS_SYSTEM_LIBRARY_NAMES | build.WINDOWS_SDK_LIBRARY_NAMES,
        )

    def test_dependency_parser_is_stable(self) -> None:
        output = """
Dump of file demo.exe

  Image has the following dependencies:

    KERNEL32.dll
    USER32.dll
    KERNEL32.dll

  Summary
"""
        self.assertEqual(verifier._dependency_names(output), ["KERNEL32.dll", "USER32.dll"])

    def test_failure_log_includes_structured_smoke_details(self) -> None:
        line = verifier._failure_log_line(
            2,
            {
                "integration": "tkinter",
                "name": "tcl-zipfs-no-extraction",
                "returncode": 1,
                "stderr": "Tcl_Init error",
            },
        )
        self.assertTrue(line.startswith("[pack-sdk-verify] issue 2: "))
        payload = json.loads(line.split(": ", 1)[1])
        self.assertEqual(payload["integration"], "tkinter")
        self.assertEqual(payload["stderr"], "Tcl_Init error")

    def test_existing_msvc_developer_environment_is_reused(self) -> None:
        environment = {
            "INCLUDE": r"C:\VS\include",
            "LIB": r"C:\VS\lib",
            "VCToolsInstallDir": "C:\\VS\\Tools\\",
            "WindowsSdkDir": "C:\\Windows SDK\\",
        }
        with (
            mock.patch.dict(verifier.os.environ, environment, clear=True),
            mock.patch.object(verifier.shutil, "which", return_value=r"C:\VS\bin\cl.exe"),
            mock.patch.object(verifier, "resolve_tool_exe") as fallback,
        ):
            self.assertEqual(verifier.resolve_verifier_tool("cl"), r"C:\VS\bin\cl.exe")
        fallback.assert_not_called()

    def test_missing_msvc_environment_uses_the_vcvars_fallback(self) -> None:
        with (
            mock.patch.dict(verifier.os.environ, {}, clear=True),
            mock.patch.object(verifier.shutil, "which") as which,
            mock.patch.object(verifier, "resolve_tool_exe", return_value=r"C:\VS\bin\cl.exe") as fallback,
        ):
            self.assertEqual(verifier.resolve_verifier_tool("cl"), r"C:\VS\bin\cl.exe")
        which.assert_not_called()
        fallback.assert_called_once_with("cl")


if __name__ == "__main__":
    unittest.main(verbosity=2)
