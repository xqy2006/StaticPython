from __future__ import annotations

import importlib.util
import io
import os
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


SCRIPT_PATH = REPO_ROOT / "scripts" / "tcltk_zipfs.py"
spec = importlib.util.spec_from_file_location("staticpython_tcltk_zipfs", SCRIPT_PATH)
if spec is None or spec.loader is None:
    raise RuntimeError(f"could not load {SCRIPT_PATH}")
tcltk_zipfs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tcltk_zipfs)


def _load_module(name: str, path: Path):
    module_spec = importlib.util.spec_from_file_location(name, path)
    if module_spec is None or module_spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    return module


tkinter_setup = _load_module(
    "staticpython_tkinter_setup_test",
    REPO_ROOT / "Lib" / "tkinter" / "setup.py",
)
freeze_modules = _load_module(
    "staticpython_freeze_modules_test",
    REPO_ROOT / "assets" / "overlay" / "Tools" / "build" / "freeze_modules.py",
)


def _write(path: Path, payload: bytes = b"# runtime\n") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)


class TclTkZipfsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.tcl = self.root / "tcl-library"
        self.tk = self.root / "tk-library"
        for relative in tcltk_zipfs.TCL_REQUIRED_PATHS:
            _write(self.tcl / relative, relative.encode("utf-8"))
        for relative in tcltk_zipfs.TK_REQUIRED_PATHS:
            _write(self.tk / relative, relative.encode("utf-8"))
        _write(self.tcl / "msgs" / "en.msg")
        _write(self.tcl / "tcltest" / "tcltest.tcl", b"must not ship\n")
        _write(self.tk / "images" / "logo.gif", b"GIF89a")
        _write(self.tk / "demos" / "widget", b"must not ship\n")

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_archive_is_deterministic_complete_and_excludes_demo_test_trees(self) -> None:
        first = tcltk_zipfs.build_tcltk_zipfs(self.tcl, self.tk)
        os.utime(self.tcl / "init.tcl", None)
        second = tcltk_zipfs.build_tcltk_zipfs(self.tcl, self.tk)
        self.assertEqual(first, second)

        with ZipFile(io.BytesIO(first)) as archive:
            names = set(archive.namelist())
            self.assertIn("tcl9.0/init.tcl", names)
            self.assertIn("tcl9.0/encoding/cp1252.enc", names)
            self.assertIn("tcl9.0/msgs/en.msg", names)
            self.assertIn("tk9.0/tk.tcl", names)
            self.assertIn("tk9.0/ttk/vistaTheme.tcl", names)
            self.assertIn("tk9.0/images/logo.gif", names)
            self.assertNotIn("tcl9.0/tcltest/tcltest.tcl", names)
            self.assertNotIn("tk9.0/demos/widget", names)
            self.assertIsNone(archive.testzip())

    def test_missing_required_file_is_a_hard_failure(self) -> None:
        (self.tk / "ttk" / "ttk.tcl").unlink()
        with self.assertRaisesRegex(RuntimeError, "ttk/ttk.tcl"):
            tcltk_zipfs.build_tcltk_zipfs(self.tcl, self.tk)

    def test_rendered_mount_uses_only_linked_memory_and_fixed_virtual_paths(self) -> None:
        payload = tcltk_zipfs.build_tcltk_zipfs(self.tcl, self.tk)
        source = tcltk_zipfs.render_tcltk_zipfs_c(
            payload,
            release_version="9.0.4",
        )
        self.assertIn("TclZipfs_MountBuffer", source)
        self.assertIn("//zipfs:/staticpython/tcltk-9.0.4/tcl9.0", source)
        self.assertIn("//zipfs:/staticpython/tcltk-9.0.4/tk9.0", source)
        self.assertIn("TCL_DECLARE_MUTEX", source)
        self.assertNotIn("fopen(", source)
        self.assertNotIn("CreateFile", source)
        self.assertNotIn("TCL_LIBRARY", source)

    def test_artifact_writer_emits_identical_zip_and_c_digest(self) -> None:
        zip_path = self.root / "out" / "tcltk.zip"
        c_path = self.root / "out" / "zipfs.c"
        tcltk_zipfs.write_tcltk_zipfs_artifacts(
            self.tcl,
            self.tk,
            zip_path=zip_path,
            c_path=c_path,
            release_version="9.0.4",
        )
        self.assertTrue(zip_path.is_file())
        source = c_path.read_text(encoding="utf-8")
        self.assertIn("Tcl/Tk ZipFS SHA-256:", source)
        self.assertGreater(zip_path.stat().st_size, 100)

    def test_cpython_discovery_patch_is_strict_and_idempotent(self) -> None:
        source = r'''#ifdef MS_WINDOWS
#include <conio.h>
#define WAIT_FOR_STDIN

static PyObject *
_get_tcl_lib_path(void)
{
    if (1) {
        return NULL;
    }
    return NULL;
}
#endif /* MS_WINDOWS */

static void create_interp(void) {
#ifdef MS_WINDOWS
    {
        DWORD ret;
        ret = GetEnvironmentVariableW(L"TCL_LIBRARY", NULL, 0);
    }
#endif
}

static void init_module(void) {
#ifdef MS_WINDOWS
            int set_var = 0;
            DWORD ret;
            ret = GetEnvironmentVariableW(L"TCL_LIBRARY", NULL, 0);
            Tcl_FindExecutable(PyBytes_AS_STRING(cexe));
#else
            Tcl_FindExecutable(PyBytes_AS_STRING(cexe));
#endif /* MS_WINDOWS */
}
'''
        patched = tkinter_setup._patch_tkinter_text(source)
        self.assertNotIn("TCL_LIBRARY", patched)
        self.assertNotIn("_get_tcl_lib_path", patched)
        self.assertEqual(patched.count("Tcl_FindExecutable(PyBytes_AS_STRING(cexe));"), 1)
        self.assertEqual(tkinter_setup._patch_tkinter_text(patched), patched)

        with self.assertRaisesRegex(RuntimeError, "no guarded TCL_LIBRARY"):
            tkinter_setup._patch_tkinter_text(
                "static PyObject *\n_get_tcl_lib_path(void)\n{\n    return NULL;\n}\n"
            )

    def test_tcl_appinit_mount_precedes_tcl_init(self) -> None:
        source = '''#include "tkinter.h"

int
Tcl_AppInit(Tcl_Interp *interp)
{
    if (Tcl_Init (interp) == TCL_ERROR)
        return TCL_ERROR;
    return TCL_OK;
}
'''
        patched = tkinter_setup._patch_tkappinit_text(source)
        self.assertLess(
            patched.index("StaticPython_TkinterZipfsMount(interp)"),
            patched.index("Tcl_Init (interp)"),
        )
        self.assertEqual(tkinter_setup._patch_tkappinit_text(patched), patched)

    def test_optional_freeze_marker_enables_only_declared_skipped_tree(self) -> None:
        root = self.root / "cpython"
        _write(root / "Lib" / "tkinter" / "__init__.py")
        _write(root / "Lib" / "tkinter" / "ttk.py")
        _write(root / "Lib" / "idlelib" / "__init__.py")
        without_marker = {module.fullname for module in freeze_modules.find_python_modules(root)}
        self.assertNotIn("tkinter", without_marker)

        marker = root / freeze_modules.OPTIONAL_FROZEN_TREES_FILE
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text("tkinter\n", encoding="utf-8")
        with_marker = {module.fullname for module in freeze_modules.find_python_modules(root)}
        self.assertIn("tkinter", with_marker)
        self.assertIn("tkinter.ttk", with_marker)
        self.assertNotIn("idlelib", with_marker)

        marker.write_text("not_a_skipped_tree\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "unknown optional frozen module tree"):
            list(freeze_modules.find_python_modules(root))

    def test_resource_rule_exposes_only_the_zipfs_payload(self) -> None:
        root = self.root / "resource-root"
        zip_resource = root / "Lib" / "tkinter" / "_staticpython" / "tcltk-library.zip"
        _write(zip_resource, b"zip")
        _write(root / "tkinter_builtin" / "staticpython_tkinter_zipfs.c", b"source")
        integration = SimpleNamespace(
            name="tkinter",
            resource_rules=[
                {
                    "action": "include",
                    "path": "Lib/tkinter/_staticpython/tcltk-library.zip",
                }
            ],
            materialized_paths=["Lib/tkinter", "tkinter_builtin"],
            overlay_entries=[],
        )
        resources = build.collect_runtime_resource_files(root, [integration])
        self.assertEqual(
            resources,
            {"Lib/tkinter/_staticpython/tcltk-library.zip": zip_resource},
        )

    def test_integration_contract_pins_sources_and_behavior(self) -> None:
        integration = tkinter_setup.LIBRARY_INTEGRATION
        self.assertEqual(integration.release_version, "9.0.4")
        self.assertRegex(tkinter_setup.TCL_COMMIT, r"^[0-9a-f]{40}$")
        self.assertRegex(tkinter_setup.TK_COMMIT, r"^[0-9a-f]{40}$")
        self.assertRegex(tkinter_setup.TCL_ARCHIVE_SHA256, r"^[0-9a-f]{64}$")
        self.assertRegex(tkinter_setup.TK_ARCHIVE_SHA256, r"^[0-9a-f]{64}$")
        self.assertEqual(integration.license_expression, "TCL")
        self.assertEqual(len(integration.license_files), 2)
        self.assertGreaterEqual(len(integration.smoke_tests), 2)
        self.assertNotIn("tkinter", build.load_config(REPO_ROOT / "config.json")["profiles"]["full"]["third_party_libraries"])


if __name__ == "__main__":
    unittest.main()
