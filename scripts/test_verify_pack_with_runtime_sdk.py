from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_ROOT = REPO_ROOT / "scripts"
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import verify_pack_with_runtime_sdk as verifier


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
        "toolchain": runtime["toolchain"],
        "descriptor_symbol": f"StaticPython_Pack_{name}",
        "sources": ["src/pack.c"],
        "libraries": [],
        "wholearchive": [],
        "system_libraries": [],
        "suppressed_system_libraries": [],
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

    def test_runtime_and_pack_hashes_and_provenance_are_validated(self) -> None:
        runtime_root, runtime = self._make_runtime()
        self.assertEqual(verifier.validate_runtime_sdk(runtime_root)["runtime_abi"], "staticpython-pack-v1-cp313")
        pack_root, _metadata = self._make_pack(runtime)
        self.assertEqual(verifier.validate_pack(pack_root, runtime)["name"], "demo")

        (runtime_root / "include" / "Python.h").write_text("/* Tamper */\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            verifier.validate_runtime_sdk(runtime_root)

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
