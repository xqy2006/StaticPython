from __future__ import annotations

import hashlib
import io
import re
from pathlib import Path, PurePosixPath
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
TCL_REQUIRED_PATHS = (
    "init.tcl",
    "auto.tcl",
    "tm.tcl",
    "encoding/ascii.enc",
    "encoding/cp1252.enc",
    "tzdata/UTC",
)
TK_REQUIRED_PATHS = (
    "tk.tcl",
    "ttk/ttk.tcl",
    "ttk/clamTheme.tcl",
    "ttk/vistaTheme.tcl",
    "ttk/xpTheme.tcl",
)
TCL_EXCLUDED_TOP_LEVEL = frozenset({"dde", "registry", "tcltest"})
TK_EXCLUDED_TOP_LEVEL = frozenset({"demos"})
VERSION_PATTERN = re.compile(r"^[0-9]+\.[0-9]+$")
TCL_TM_DEFAULTS_ANCHOR = b"if {![interp issafe]} {::tcl::tm::Defaults}"
TCL_TM_STATICPYTHON_INITIALIZATION = (
    b"# StaticPython keeps Tcl module lookup inside the linked ZipFS.\n"
    b"# Do not add executable-relative or TCL*_TM_PATH host directories."
)


def _validate_version(value: str, *, label: str) -> str:
    if not VERSION_PATTERN.fullmatch(value):
        raise ValueError(f"{label} must be a major.minor version, got {value!r}")
    return value


def _validate_library_root(root: Path, required: tuple[str, ...], *, label: str) -> Path:
    resolved = root.resolve()
    if not resolved.is_dir():
        raise RuntimeError(f"{label} library directory is missing: {resolved}")
    missing = [relative for relative in required if not (resolved / relative).is_file()]
    if missing:
        raise RuntimeError(
            f"{label} library is incomplete; missing required runtime files: "
            + ", ".join(missing)
        )
    return resolved


def _iter_library_files(root: Path, excluded_top_level: frozenset[str]):
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        if not path.is_file():
            continue
        if path.is_symlink():
            raise RuntimeError(f"Tcl/Tk ZipFS input must not contain symlinks: {path}")
        relative = path.relative_to(root).as_posix()
        pure = PurePosixPath(relative)
        if (
            pure.is_absolute()
            or not pure.parts
            or any(part in {"", ".", ".."} for part in pure.parts)
            or "\\" in relative
            or "\0" in relative
        ):
            raise RuntimeError(f"unsafe Tcl/Tk ZipFS path: {relative!r}")
        if pure.parts[0].casefold() in excluded_top_level:
            continue
        yield relative, path


def _zip_info(name: str) -> ZipInfo:
    info = ZipInfo(name, ZIP_TIMESTAMP)
    info.compress_type = ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (0o100444 & 0xFFFF) << 16
    return info


def _harden_tcl_tm_initialization(source: bytes) -> bytes:
    """Disable Tcl's host-derived module paths using a strict upstream anchor."""

    matches = source.count(TCL_TM_DEFAULTS_ANCHOR)
    if matches != 1:
        raise RuntimeError(
            "Tcl tm.tcl initialization anchor must match exactly once; "
            f"found {matches} matches"
        )
    return source.replace(
        TCL_TM_DEFAULTS_ANCHOR,
        TCL_TM_STATICPYTHON_INITIALIZATION,
        1,
    )


def build_tcltk_zipfs(
    tcl_library: Path,
    tk_library: Path,
    *,
    tcl_version: str = "9.0",
    tk_version: str = "9.0",
) -> bytes:
    """Build the deterministic, read-only Tcl/Tk script archive mounted by _tkinter."""

    tcl_version = _validate_version(tcl_version, label="Tcl version")
    tk_version = _validate_version(tk_version, label="Tk version")
    tcl_root = _validate_library_root(tcl_library, TCL_REQUIRED_PATHS, label="Tcl")
    tk_root = _validate_library_root(tk_library, TK_REQUIRED_PATHS, label="Tk")

    entries: list[tuple[str, Path]] = []
    entries.extend(
        (f"tcl{tcl_version}/{relative}", path)
        for relative, path in _iter_library_files(tcl_root, TCL_EXCLUDED_TOP_LEVEL)
    )
    entries.extend(
        (f"tk{tk_version}/{relative}", path)
        for relative, path in _iter_library_files(tk_root, TK_EXCLUDED_TOP_LEVEL)
    )
    names = [name for name, _ in entries]
    if len(names) != len(set(names)):
        raise RuntimeError("Tcl/Tk ZipFS contains duplicate virtual paths")

    payload = io.BytesIO()
    with ZipFile(payload, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for name, path in entries:
            contents = path.read_bytes()
            if name == f"tcl{tcl_version}/tm.tcl":
                contents = _harden_tcl_tm_initialization(contents)
            archive.writestr(_zip_info(name), contents, compresslevel=9)

    result = payload.getvalue()
    with ZipFile(io.BytesIO(result)) as archive:
        archived = set(archive.namelist())
        expected = {
            *{f"tcl{tcl_version}/{relative}" for relative in TCL_REQUIRED_PATHS},
            *{f"tk{tk_version}/{relative}" for relative in TK_REQUIRED_PATHS},
        }
        missing = sorted(expected - archived)
        if missing:
            raise RuntimeError(
                "generated Tcl/Tk ZipFS omitted required runtime files: "
                + ", ".join(missing)
            )
        if archive.testzip() is not None:
            raise RuntimeError("generated Tcl/Tk ZipFS failed its CRC audit")
    return result


def _c_byte_rows(payload: bytes, *, width: int = 20) -> str:
    rows = []
    for offset in range(0, len(payload), width):
        rows.append("    " + ", ".join(str(value) for value in payload[offset : offset + width]) + ",")
    return "\n".join(rows or ["    0,"])


def render_tcltk_zipfs_c(
    payload: bytes,
    *,
    release_version: str,
    tcl_version: str = "9.0",
    tk_version: str = "9.0",
) -> str:
    """Render the native, no-extraction ZipFS mount used by Tcl_AppInit."""

    if not payload:
        raise ValueError("Tcl/Tk ZipFS payload must not be empty")
    tcl_version = _validate_version(tcl_version, label="Tcl version")
    tk_version = _validate_version(tk_version, label="Tk version")
    if not re.fullmatch(r"[0-9A-Za-z_.+-]+", release_version):
        raise ValueError(f"unsafe Tcl/Tk release version: {release_version!r}")

    mount_point = f"//zipfs:/staticpython/tcltk-{release_version}"
    tcl_library = f"{mount_point}/tcl{tcl_version}"
    tcl_tm_file = f"{tcl_library}/tm.tcl"
    tk_library = f"{mount_point}/tk{tk_version}"
    digest = hashlib.sha256(payload).hexdigest()
    return f'''/* Auto-generated by StaticPython. SPDX-License-Identifier: Apache-2.0 */
/* Tcl/Tk ZipFS SHA-256: {digest} */
#include <stddef.h>
#ifndef TCL_THREADS
#define TCL_THREADS 1
#endif
#include <tcl.h>

static const unsigned char staticpython_tkinter_zipfs_data[] = {{
{_c_byte_rows(payload)}
}};

static const char staticpython_tkinter_mount_point[] = "{mount_point}";
static const char staticpython_tcl_library[] = "{tcl_library}";
static const char staticpython_tcl_tm_file[] = "{tcl_tm_file}";
static const char staticpython_tk_library[] = "{tk_library}";
TCL_DECLARE_MUTEX(staticpython_tkinter_zipfs_mutex)
static int staticpython_tkinter_zipfs_mounted = 0;

int
StaticPython_TkinterZipfsMount(Tcl_Interp *interp)
{{
    int status = TCL_OK;
    Tcl_MutexLock(&staticpython_tkinter_zipfs_mutex);
    if (!staticpython_tkinter_zipfs_mounted) {{
        status = TclZipfs_MountBuffer(
            interp,
            staticpython_tkinter_zipfs_data,
            sizeof(staticpython_tkinter_zipfs_data),
            staticpython_tkinter_mount_point,
            0
        );
        if (status == TCL_OK) {{
            staticpython_tkinter_zipfs_mounted = 1;
        }}
    }}
    Tcl_MutexUnlock(&staticpython_tkinter_zipfs_mutex);
    if (status != TCL_OK) {{
        return status;
    }}
    if (Tcl_SetVar(interp, "tcl_library", staticpython_tcl_library, TCL_GLOBAL_ONLY) == NULL) {{
        return TCL_ERROR;
    }}
    if (Tcl_SetVar(interp, "tk_library", staticpython_tk_library, TCL_GLOBAL_ONLY) == NULL) {{
        return TCL_ERROR;
    }}
    if (Tcl_SetVar(interp, "auto_path", staticpython_tcl_library, TCL_GLOBAL_ONLY) == NULL) {{
        return TCL_ERROR;
    }}
    if (Tcl_SetVar(interp, "tcl_pkgPath", "", TCL_GLOBAL_ONLY) == NULL) {{
        return TCL_ERROR;
    }}
    if (Tcl_SetVar(
            interp,
            "staticpython_tkinter_zipfs",
            staticpython_tkinter_mount_point,
            TCL_GLOBAL_ONLY
        ) == NULL) {{
        return TCL_ERROR;
    }}
    return TCL_OK;
}}

int
StaticPython_TkinterZipfsRestrictAutoPath(Tcl_Interp *interp)
{{
    if (Tcl_SetVar(interp, "auto_path", staticpython_tcl_library, TCL_GLOBAL_ONLY) == NULL) {{
        return TCL_ERROR;
    }}
    if (Tcl_SetVar(interp, "tcl_pkgPath", "", TCL_GLOBAL_ONLY) == NULL) {{
        return TCL_ERROR;
    }}
    if (Tcl_EvalFile(interp, staticpython_tcl_tm_file) != TCL_OK) {{
        return TCL_ERROR;
    }}
    if (Tcl_SetVar(interp, "::tcl::tm::paths", "", TCL_GLOBAL_ONLY) == NULL) {{
        return TCL_ERROR;
    }}
    return TCL_OK;
}}
'''


def write_tcltk_zipfs_artifacts(
    tcl_library: Path,
    tk_library: Path,
    *,
    zip_path: Path,
    c_path: Path,
    release_version: str,
    tcl_version: str = "9.0",
    tk_version: str = "9.0",
) -> tuple[Path, Path]:
    payload = build_tcltk_zipfs(
        tcl_library,
        tk_library,
        tcl_version=tcl_version,
        tk_version=tk_version,
    )
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    c_path.parent.mkdir(parents=True, exist_ok=True)
    zip_path.write_bytes(payload)
    c_path.write_text(
        render_tcltk_zipfs_c(
            payload,
            release_version=release_version,
            tcl_version=tcl_version,
            tk_version=tk_version,
        ),
        encoding="utf-8",
        newline="\n",
    )
    return zip_path, c_path
