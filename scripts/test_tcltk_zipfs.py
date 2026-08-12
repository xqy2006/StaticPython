from __future__ import annotations

import importlib.util
import io
import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
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
            payload = relative.encode("utf-8")
            if relative == "tm.tcl":
                payload = (
                    b"namespace eval ::tcl::tm { variable paths {} }\n"
                    + tcltk_zipfs.TCL_TM_DEFAULTS_ANCHOR
                    + b"\n"
                )
            _write(self.tcl / relative, payload)
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
            self.assertIn("tcl9.0/tm.tcl", names)
            self.assertIn("tcl9.0/encoding/cp1252.enc", names)
            self.assertIn("tcl9.0/msgs/en.msg", names)
            self.assertIn("tk9.0/tk.tcl", names)
            self.assertIn("tk9.0/ttk/vistaTheme.tcl", names)
            self.assertIn("tk9.0/images/logo.gif", names)
            self.assertNotIn("tcl9.0/tcltest/tcltest.tcl", names)
            self.assertNotIn("tk9.0/demos/widget", names)
            self.assertIsNone(archive.testzip())
            tm_source = archive.read("tcl9.0/tm.tcl")
            self.assertNotIn(tcltk_zipfs.TCL_TM_DEFAULTS_ANCHOR, tm_source)
            self.assertIn(
                tcltk_zipfs.TCL_TM_STATICPYTHON_INITIALIZATION,
                tm_source,
            )

    def test_missing_required_file_is_a_hard_failure(self) -> None:
        (self.tk / "ttk" / "ttk.tcl").unlink()
        with self.assertRaisesRegex(RuntimeError, "ttk/ttk.tcl"):
            tcltk_zipfs.build_tcltk_zipfs(self.tcl, self.tk)

    def test_archive_rejects_directory_symlinks(self) -> None:
        outside = self.root / "outside"
        outside.mkdir()
        _write(outside / "host.tcl", b"host filesystem payload")
        link = self.tcl / "linked-host-directory"
        try:
            link.symlink_to(outside, target_is_directory=True)
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"directory symlinks are unavailable: {exc}")
        with self.assertRaisesRegex(RuntimeError, "must not contain symlinks"):
            tcltk_zipfs.build_tcltk_zipfs(self.tcl, self.tk)

    def test_archive_rejects_broken_symlinks(self) -> None:
        link = self.tcl / "broken-host-file"
        try:
            link.symlink_to(self.root / "missing-host-file")
        except (NotImplementedError, OSError) as exc:
            self.skipTest(f"file symlinks are unavailable: {exc}")
        with self.assertRaisesRegex(RuntimeError, "must not contain symlinks"):
            tcltk_zipfs.build_tcltk_zipfs(self.tcl, self.tk)

    def test_iterator_rejects_non_file_symlink_before_file_filter(self) -> None:
        root = mock.Mock()
        entry = mock.Mock()
        entry.as_posix.return_value = "tcl9.0/linked-host-directory"
        entry.is_symlink.return_value = True
        entry.is_file.side_effect = AssertionError(
            "symlink entries must be rejected before file classification"
        )
        root.rglob.return_value = [entry]

        with self.assertRaisesRegex(RuntimeError, "must not contain symlinks"):
            list(tcltk_zipfs._iter_library_files(root, frozenset()))
        entry.is_file.assert_not_called()

    def test_tcl_module_path_patch_fails_closed_on_upstream_drift(self) -> None:
        (self.tcl / "tm.tcl").write_bytes(b"# upstream changed initialization\n")
        with self.assertRaisesRegex(RuntimeError, "anchor must match exactly once"):
            tcltk_zipfs.build_tcltk_zipfs(self.tcl, self.tk)

    def test_tcl_module_path_patch_rejects_ambiguous_anchor(self) -> None:
        (self.tcl / "tm.tcl").write_bytes(
            tcltk_zipfs.TCL_TM_DEFAULTS_ANCHOR
            + b"\n"
            + tcltk_zipfs.TCL_TM_DEFAULTS_ANCHOR
        )
        with self.assertRaisesRegex(RuntimeError, "found 2 matches"):
            tcltk_zipfs.build_tcltk_zipfs(self.tcl, self.tk)

    def test_rendered_mount_uses_only_linked_memory_and_fixed_virtual_paths(self) -> None:
        payload = tcltk_zipfs.build_tcltk_zipfs(self.tcl, self.tk)
        source = tcltk_zipfs.render_tcltk_zipfs_c(
            payload,
            release_version="9.0.4",
        )
        self.assertIn("TclZipfs_MountBuffer", source)
        self.assertIn("#define TCL_THREADS 1", source)
        self.assertIn("staticpython_tkinter_zipfs_mounted", source)
        self.assertIn("StaticPython_TkinterZipfsRestrictAutoPath", source)
        self.assertIn("StaticPython_TkinterZipfsRestrictTkPaths", source)
        self.assertIn('Tcl_SetVar(interp, "auto_path", staticpython_tcl_library', source)
        self.assertIn('Tcl_SetVar(interp, "auto_path", staticpython_tcltk_auto_path', source)
        self.assertIn('Tcl_SetVar(interp, "tcl_pkgPath", ""', source)
        self.assertIn("Tcl_EvalFile(interp, staticpython_tcl_tm_file)", source)
        self.assertIn("Tcl_SetEncodingSearchPath(encoding_path)", source)
        self.assertIn("/tcl9.0/encoding", source)
        self.assertIn('Tcl_SetVar(interp, "::tcl::tm::paths", ""', source)
        self.assertLess(
            source.index("Tcl_EvalFile(interp, staticpython_tcl_tm_file)"),
            source.index('Tcl_SetVar(interp, "::tcl::tm::paths", ""'),
        )
        self.assertIn("//zipfs:/staticpython/tcltk-9.0.4/tcl9.0", source)
        self.assertIn("//zipfs:/staticpython/tcltk-9.0.4/tk9.0", source)
        self.assertIn("TCL_DECLARE_MUTEX", source)
        self.assertNotIn("Tcl_FSStat", source)
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

    def test_cpython_311_tcl9_backport_is_strict_and_idempotent(self) -> None:
        for preamble_index in range(len(tkinter_setup.TCL9_COMPAT_PREAMBLE_REPLACEMENTS)):
            legacy = "\n/* next strict anchor */\n".join(
                [tkinter_setup.TCL9_COMPAT_PREAMBLE_REPLACEMENTS[preamble_index][0]]
                + [anchor for anchor, _ in tkinter_setup.TCL9_COMPAT_REPLACEMENTS]
            )
            patched = tkinter_setup._patch_tcl9_compat_text(legacy)
            self.assertIn(tkinter_setup.TCL9_COMPAT_MARKER, patched)
            for anchor, replacement in tkinter_setup.TCL9_COMPAT_REPLACEMENTS:
                self.assertNotIn(anchor, patched)
                self.assertIn(replacement, patched)
            self.assertEqual(tkinter_setup._patch_tcl9_compat_text(patched), patched)

        partial = patched.replace("    Tcl_Size len;", "    int len;", 1)
        with self.assertRaisesRegex(RuntimeError, "compatibility patch is partial"):
            tkinter_setup._patch_tcl9_compat_text(partial)

        ambiguous = legacy + "\n" + tkinter_setup.TCL9_COMPAT_PREAMBLE_REPLACEMENTS[0][0]
        with self.assertRaisesRegex(RuntimeError, "preamble expected one supported layout"):
            tkinter_setup._patch_tcl9_compat_text(ambiguous)

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

        legacy_signature = source.replace("_get_tcl_lib_path(void)", "_get_tcl_lib_path()")
        legacy_patched = tkinter_setup._patch_tkinter_text(legacy_signature)
        self.assertNotIn("_get_tcl_lib_path", legacy_patched)
        self.assertNotIn("TCL_LIBRARY", legacy_patched)

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
    if (Tk_Init(interp) == TCL_ERROR) {
        return TCL_ERROR;
    }
    return TCL_OK;
}
'''
        patched = tkinter_setup._patch_tkappinit_text(source)
        self.assertLess(
            patched.index("StaticPython_TkinterZipfsMount(interp)"),
            patched.index("Tcl_Init (interp)"),
        )
        self.assertLess(
            patched.index("Tcl_Init (interp)"),
            patched.index("StaticPython_TkinterZipfsRestrictAutoPath(interp)"),
        )
        self.assertLess(
            patched.index("StaticPython_TkinterZipfsRestrictAutoPath(interp)"),
            patched.index("Tk_Init(interp)"),
        )
        self.assertLess(
            patched.index("Tk_Init(interp)"),
            patched.index("StaticPython_TkinterZipfsRestrictTkPaths(interp)"),
        )
        self.assertEqual(tkinter_setup._patch_tkappinit_text(patched), patched)

    def test_tcl_appinit_supports_cpython_315_tk_init_wrapper(self) -> None:
        source = '''#include "tkinter.h"

int
Tcl_AppInit(Tcl_Interp *interp)
{
    if (Tcl_Init (interp) == TCL_ERROR)
        return TCL_ERROR;
    if (Tkinter_TkInit(interp) == TCL_ERROR) {
        return TCL_ERROR;
    }
    return TCL_OK;
}
'''
        patched = tkinter_setup._patch_tkappinit_text(source)
        self.assertLess(
            patched.index("Tkinter_TkInit(interp)"),
            patched.index("StaticPython_TkinterZipfsRestrictTkPaths(interp)"),
        )
        self.assertEqual(tkinter_setup._patch_tkappinit_text(patched), patched)

    def test_tcl_appinit_supports_cpython_311_protected_tk_init(self) -> None:
        source = '''#include "tkinter.h"

int
Tcl_AppInit(Tcl_Interp *interp)
{
    if (Tcl_Init (interp) == TCL_ERROR)
        return TCL_ERROR;
    if (Tk_Init(interp) == TCL_ERROR) {
#ifdef TKINTER_PROTECT_LOADTK
        tk_load_failed = 1;
        Tcl_SetVar(interp, "_tkinter_tk_failed", "1", TCL_GLOBAL_ONLY);
#endif
        return TCL_ERROR;
    }
    return TCL_OK;
}
'''
        patched = tkinter_setup._patch_tkappinit_text(source)
        self.assertLess(
            patched.index("Tk_Init(interp)"),
            patched.index("StaticPython_TkinterZipfsRestrictTkPaths(interp)"),
        )
        self.assertLess(
            patched.index("Tcl_SetVar(interp, \"_tkinter_tk_failed\""),
            patched.index("StaticPython_TkinterZipfsRestrictTkPaths(interp)"),
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
        self.assertIn(
            rf"..\externals\{tkinter_setup.TCL_SOURCE_NAME}\libtommath",
            tkinter_setup.TCLTK_INCLUDE_DIRECTORIES,
        )
        self.assertEqual(
            integration.license_expression,
            "Python-2.0 AND TCL AND Zlib AND Unlicense AND Info-ZIP",
        )
        self.assertEqual(len(integration.license_files), 6)
        self.assertEqual(
            integration.python_link_dependencies_release_x64[:4],
            [
                "_tkinter.lib",
                "staticpython_tk.lib",
                "staticpython_tclstub.lib",
                "staticpython_tcl.lib",
            ],
        )
        staged_names = {
            item["target_name"]
            for item in integration.staged_static_libraries_release_x64
        }
        self.assertEqual(
            staged_names,
            {
                "staticpython_tk.lib",
                "staticpython_tclstub.lib",
                "staticpython_tcl.lib",
            },
        )
        self.assertGreaterEqual(len(integration.smoke_tests), 2)
        smoke_code = "\n".join(step["code"] for step in integration.smoke_tests)
        for variable in (
            "TCL_LIBRARY",
            "TK_LIBRARY",
            "TCLLIBPATH",
            "TCL9.0_TM_PATH",
            "TCL9_0_TM_PATH",
        ):
            self.assertIn(variable, smoke_code)
        self.assertIn("clock format 0 -timezone :UTC", smoke_code)
        self.assertNotIn("tkinter", build.load_config(REPO_ROOT / "config.json")["profiles"]["full"]["third_party_libraries"])

    def test_artifact_build_produces_and_stages_tcl_stubs(self) -> None:
        source_root = self.root / "cpython"
        tcl_win = (
            source_root
            / "externals"
            / tkinter_setup.TCL_SOURCE_NAME
            / "win"
        )
        tk_win = (
            source_root
            / "externals"
            / tkinter_setup.TK_SOURCE_NAME
            / "win"
        )
        _write(tcl_win / "Release_AMD64_VC1944" / "tcl90sx.lib", b"tcl")
        _write(tcl_win / "Release_AMD64_VC1944" / "tclstub.lib", b"stubs")
        _write(tk_win / "Release_AMD64_VC1944" / "tcl9tk90sx.lib", b"tk")
        context = SimpleNamespace(
            source_root=source_root,
            configuration="Release",
            platform="x64",
            log=lambda _message: None,
        )

        with (
            mock.patch.object(tkinter_setup, "ensure_tool"),
            mock.patch.object(tkinter_setup, "run") as run,
        ):
            tkinter_setup.prepare_tcltk_artifacts(context)

        self.assertEqual(run.call_count, 2)
        self.assertEqual(run.call_args_list[0].args[1][4], "shell")
        self.assertEqual(run.call_args_list[1].args[1][4], "core")
        staged = source_root / "tkinter_builtin" / "lib"
        self.assertEqual(
            (staged / tkinter_setup.TCL_STUB_STAGED_LIBRARY).read_bytes(),
            b"stubs",
        )
        self.assertEqual(
            sorted(path.name for path in staged.iterdir()),
            [
                "staticpython_tcl.lib",
                "staticpython_tclstub.lib",
                "staticpython_tk.lib",
            ],
        )

    def test_ci_preserves_verifier_evidence_when_pack_validation_fails(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "tkinter-zipfs-experiment.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            'foreach ($series in @("3.11", "3.12", "3.13", "3.14", "3.15"))',
            workflow,
        )
        self.assertIn(
            "cpython_version: ${{ fromJSON(needs.resolve-cpython-matrix.outputs.versions) }}",
            workflow,
        )
        self.assertIn("VERIFY_CPYTHON_VERSION: ${{ matrix.cpython_version }}", workflow)
        build_step = workflow.split(
            "- name: Build static tkinter pack and verify against runtime SDK",
            1,
        )[1].split("- name: Assert no-extraction pack evidence", 1)[0]
        self.assertIn("finally {", build_step)
        for evidence in (
            "staticpython-pack-verify-report.json",
            "staticpython-pack-verify.exe",
            "staticpython-pack-verify.map",
            "staticpython-pack-verify.pdb",
        ):
            self.assertIn(evidence, build_step)

        audit_step = workflow.split(
            "- name: Assert no-extraction pack evidence",
            1,
        )[1].split("- name: Upload tkinter pack evidence", 1)[0]
        self.assertIn("Get-FileHash -LiteralPath $exePath", audit_step)
        self.assertIn("Get-FileHash -LiteralPath $mapPath", audit_step)
        self.assertIn("dumpbin /NOLOGO /DEPENDENTS $exePath", audit_step)
        self.assertIn("Compare-Object $reportedDependencies $observedDependencies", audit_step)
        self.assertIn("forbidden_entry_symbols", audit_step)
        self.assertIn("main_object_records", audit_step)

        upload_step = workflow.split(
            "- name: Upload tkinter pack evidence",
            1,
        )[1]
        self.assertIn("dist/tkinter/staticpython-pack-verify.exe", upload_step)

    def test_archive_manifest_uses_pinned_commit_without_git_checkout(self) -> None:
        source = self.root / "tcl-source"
        _write(source / "win" / "gitmanifest.in", b"git-")
        tkinter_setup._write_archive_manifest_uuid(
            source,
            tkinter_setup.TCL_COMMIT,
            component="Tcl",
        )
        self.assertEqual(
            (source / "manifest.uuid").read_text(encoding="ascii"),
            f"git-{tkinter_setup.TCL_COMMIT}\n",
        )
        (source / "win" / "gitmanifest.in").write_text("fossil-", encoding="ascii")
        with self.assertRaisesRegex(RuntimeError, "gitmanifest.in drifted"):
            tkinter_setup._write_archive_manifest_uuid(
                source,
                tkinter_setup.TCL_COMMIT,
                component="Tcl",
            )

    def test_project_keeps_generic_cpython_property_sheet(self) -> None:
        namespace = "http://schemas.microsoft.com/developer/msbuild/2003"
        root = ET.fromstring(
            f'''<Project xmlns="{namespace}">
  <ImportGroup Label="PropertySheets">
    <Import Project="tcltk.props" />
  </ImportGroup>
</Project>'''
        )
        tkinter_setup._replace_tcltk_props_import(root)
        imports = list(root.iter(tkinter_setup.msbuild_tag("Import")))
        self.assertEqual(len(imports), 1)
        self.assertEqual(imports[0].get("Project"), "pyproject.props")
        self.assertEqual(
            imports[0].get("Condition"),
            "$(__PyProject_Props_Imported) != 'true'",
        )


if __name__ == "__main__":
    unittest.main()
