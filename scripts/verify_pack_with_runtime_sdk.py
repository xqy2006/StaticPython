from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tokenize
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools import resolve_tool_exe


RUNTIME_METADATA_PATH = "metadata/runtime-sdk.v1.json"
PACK_METADATA_PATH = "pack.json"
REQUIRED_WINDOWS_SYSTEM_LIBRARIES = (
    "advapi32.lib",
    "shell32.lib",
    "user32.lib",
)
FORBIDDEN_DEPENDENCY_PATTERNS = (
    re.compile(r"^python\d*\.dll$", re.IGNORECASE),
    re.compile(r"^vcruntime\d*\.dll$", re.IGNORECASE),
    re.compile(r"^msvcp\d*\.dll$", re.IGNORECASE),
    re.compile(r"^ucrtbase\.dll$", re.IGNORECASE),
)
FORBIDDEN_ENTRY_SYMBOLS = (
    "Py_Main",
    "Py_BytesMain",
    "Py_RunMain",
    "Py_SandboxMain",
)
FORBIDDEN_ASSET_SUFFIXES = (".dll", ".exe", ".pyd")
C_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
WINDOWS_LINK_LIBRARY_NAMES = {
    "advapi32.lib",
    "bcrypt.lib",
    "comctl32.lib",
    "comdlg32.lib",
    "crypt32.lib",
    "d2d1.lib",
    "d3d11.lib",
    "dwmapi.lib",
    "dwrite.lib",
    "dxgi.lib",
    "gdi32.lib",
    "gdiplus.lib",
    "glu32.lib",
    "imm32.lib",
    "iphlpapi.lib",
    "kernel32.lib",
    "legacy_stdio_definitions.lib",
    "msimg32.lib",
    "netapi32.lib",
    "odbccp32.lib",
    "odbc32.lib",
    "ole32.lib",
    "oleacc.lib",
    "oleaut32.lib",
    "opengl32.lib",
    "pathcch.lib",
    "pdh.lib",
    "powrprof.lib",
    "propsys.lib",
    "psapi.lib",
    "rpcrt4.lib",
    "secur32.lib",
    "setupapi.lib",
    "shell32.lib",
    "shlwapi.lib",
    "user32.lib",
    "userenv.lib",
    "uuid.lib",
    "uxtheme.lib",
    "version.lib",
    "wbemuuid.lib",
    "windowscodecs.lib",
    "winmm.lib",
    "winspool.lib",
    "ws2_32.lib",
    "wsock32.lib",
}


@dataclass(frozen=True)
class MaterializedPack:
    archive: Path
    root: Path
    metadata: dict


@dataclass(frozen=True)
class SmokeCase:
    integration: str
    name: str
    kind: str
    code: str
    timeout: float
    skip_group: str | None = None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative(value: object, *, description: str) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeError(f"invalid {description}: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or value.startswith("/") or any(part in {"", ".", ".."} for part in path.parts):
        raise RuntimeError(f"unsafe {description}: {value!r}")
    if path.parts and ":" in path.parts[0]:
        raise RuntimeError(f"unsafe {description}: {value!r}")
    return path


def _safe_file(root: Path, relative: object, *, description: str = "asset path") -> Path:
    path = _safe_relative(relative, description=description)
    candidate = (root / Path(*path.parts)).resolve()
    resolved_root = root.resolve()
    if resolved_root not in candidate.parents:
        raise RuntimeError(f"{description} escapes the asset root: {relative!r}")
    if not candidate.is_file():
        raise RuntimeError(f"{description} is missing: {relative!r}")
    return candidate


def _safe_directory(root: Path, relative: object, *, description: str) -> Path:
    path = _safe_relative(relative, description=description)
    candidate = (root / Path(*path.parts)).resolve()
    resolved_root = root.resolve()
    if resolved_root not in candidate.parents:
        raise RuntimeError(f"{description} escapes the asset root: {relative!r}")
    if not candidate.is_dir():
        raise RuntimeError(f"{description} is missing: {relative!r}")
    return candidate


def safe_extract_zip(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    try:
        archive = ZipFile(archive_path)
    except (OSError, BadZipFile) as exc:
        raise RuntimeError(f"could not open ZIP asset {archive_path}: {exc}") from exc
    with archive:
        for record in archive.infolist():
            normalized = record.filename.rstrip("/")
            if not normalized:
                continue
            relative = _safe_relative(normalized, description="ZIP member")
            collision_key = relative.as_posix().casefold()
            if collision_key in seen:
                raise RuntimeError(f"ZIP asset contains duplicate or case-colliding member: {normalized}")
            seen.add(collision_key)
            unix_mode = record.external_attr >> 16
            if stat.S_ISLNK(unix_mode):
                raise RuntimeError(f"ZIP asset contains a symbolic link: {normalized}")
            target = destination / Path(*relative.parts)
            if record.is_dir() or record.filename.endswith("/"):
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(record, "r") as source, target.open("xb") as output:
                shutil.copyfileobj(source, output)


def _read_json(path: Path, *, description: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read {description} {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{description} must be a JSON object: {path}")
    return payload


def _validate_recorded_files(
    root: Path,
    metadata: dict,
    *,
    allowed_unrecorded: set[str],
) -> None:
    records = metadata.get("files")
    if not isinstance(records, list):
        raise RuntimeError("asset metadata files must be a list")
    expected: dict[str, str] = {}
    expected_casefold: set[str] = set()
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError("asset metadata contains a non-object file record")
        relative = _safe_relative(record.get("path"), description="recorded file path").as_posix()
        if relative.casefold() in expected_casefold:
            raise RuntimeError(f"asset metadata repeats a file path: {relative}")
        expected_casefold.add(relative.casefold())
        expected[relative] = str(record.get("sha256", "")).lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected[relative]):
            raise RuntimeError(f"asset file has an invalid SHA-256 record: {relative}")
        path = _safe_file(root, relative, description="recorded file")
        if record.get("size") != path.stat().st_size:
            raise RuntimeError(f"asset file size does not match metadata: {relative}")
        actual = sha256_file(path)
        if actual != expected[relative]:
            raise RuntimeError(f"asset file SHA-256 does not match metadata: {relative}")

    actual_files = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
    }
    unexpected = sorted(actual_files - set(expected) - allowed_unrecorded, key=str.casefold)
    missing = sorted(set(expected) - actual_files, key=str.casefold)
    if unexpected:
        raise RuntimeError(f"asset contains unrecorded files: {unexpected}")
    if missing:
        raise RuntimeError(f"asset metadata names missing files: {missing}")


def _validate_no_dynamic_payloads(root: Path, *, owner: str) -> None:
    forbidden = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.suffix.casefold() in FORBIDDEN_ASSET_SUFFIXES
    )
    if forbidden:
        raise RuntimeError(f"{owner} contains dynamic or executable payloads: {forbidden}")


def _validate_no_links(root: Path, *, owner: str) -> None:
    links = sorted(
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_symlink()
        or (hasattr(path, "is_junction") and path.is_junction())
    )
    if links:
        raise RuntimeError(f"{owner} contains symbolic links or junctions: {links}")


def validate_runtime_sdk(root: Path) -> dict:
    metadata = _read_json(root / Path(*PurePosixPath(RUNTIME_METADATA_PATH).parts), description="runtime SDK metadata")
    if metadata.get("schema_version") != 1 or metadata.get("kind") != "staticpython-runtime-sdk":
        raise RuntimeError("runtime SDK has an unsupported schema or kind")
    for field in (
        "runtime_abi",
        "cpython_abi",
        "cpython_version",
        "cpython_commit",
        "cpython_tag",
        "staticpython_commit",
    ):
        if not isinstance(metadata.get(field), str) or not metadata[field]:
            raise RuntimeError(f"runtime SDK has no valid {field}")
    if metadata.get("platform") != "x64":
        raise RuntimeError("runtime SDK platform must be x64")
    if metadata.get("base_pack_symbol") != "StaticPython_BaseResourcePackV1":
        raise RuntimeError("runtime SDK has an unexpected base pack symbol")
    if metadata.get("pack_registration_function") != "StaticPython_RegisterPacks":
        raise RuntimeError("runtime SDK has an unexpected pack registration function")
    verification = metadata.get("verification")
    if not isinstance(verification, dict) or verification.get("status") != "passed":
        raise RuntimeError("runtime SDK is not verified")
    if verification.get("generic_executable_published") is not False:
        raise RuntimeError("runtime SDK does not prove that generic executables were excluded")
    _validate_no_links(root, owner="runtime SDK")
    _validate_recorded_files(
        root,
        metadata,
        allowed_unrecorded={RUNTIME_METADATA_PATH, "README.txt"},
    )
    _validate_no_dynamic_payloads(root, owner="runtime SDK")
    include_dir = _safe_directory(
        root,
        metadata.get("include_directory", "include"),
        description="runtime include directory",
    )
    library_dir = _safe_directory(
        root,
        metadata.get("library_directory", "lib"),
        description="runtime library directory",
    )
    if not (include_dir / "Python.h").is_file() or not (include_dir / "staticpython_pack.h").is_file():
        raise RuntimeError("runtime SDK is missing Python.h or staticpython_pack.h")
    link_libraries = metadata.get("link_libraries")
    if not isinstance(link_libraries, list) or not link_libraries:
        raise RuntimeError("runtime SDK link_libraries must be a non-empty list")
    for name in link_libraries:
        _validate_library_leaf(name, description="runtime link library")
        _safe_file(library_dir, name, description="runtime link library")
    toolchain = metadata.get("toolchain")
    if not isinstance(toolchain, dict):
        raise RuntimeError("runtime SDK toolchain metadata must be an object")
    for field in (
        "visual_studio_version",
        "vscmd_version",
        "vc_tools_version",
        "windows_sdk_version",
        "platform_toolset",
        "runtime_library",
    ):
        if not isinstance(toolchain.get(field), str) or not toolchain[field]:
            raise RuntimeError(f"runtime SDK toolchain has no valid {field}")
    if toolchain["platform_toolset"] != "v143" or toolchain["runtime_library"] != "MultiThreaded":
        raise RuntimeError("runtime SDK was not built with v143 and the static C runtime")
    return metadata


def _validate_library_leaf(value: object, *, description: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or Path(value).name != value
        or not value.casefold().endswith(".lib")
        or "/" in value
        or "\\" in value
    ):
        raise RuntimeError(f"invalid {description}: {value!r}")
    return value


def _validate_windows_link_library(value: object, *, description: str) -> str:
    name = _validate_library_leaf(value, description=description)
    if name.casefold() not in WINDOWS_LINK_LIBRARY_NAMES:
        raise RuntimeError(f"{description} is not an allowlisted Windows library: {name}")
    return name


def validate_pack(root: Path, runtime: dict) -> dict:
    metadata = _read_json(root / PACK_METADATA_PATH, description="pack metadata")
    owner = metadata.get("name")
    if metadata.get("schema_version") != 1 or metadata.get("kind") != "staticpython-library-pack":
        raise RuntimeError("library pack has an unsupported schema or kind")
    if not isinstance(owner, str) or not owner:
        raise RuntimeError("library pack has no valid name")
    _validate_no_links(root, owner=f"pack {owner}")
    _validate_recorded_files(root, metadata, allowed_unrecorded={PACK_METADATA_PATH})
    _validate_no_dynamic_payloads(root, owner=f"pack {owner}")
    for field in (
        "runtime_abi",
        "cpython_abi",
        "cpython_version",
        "cpython_commit",
        "cpython_tag",
        "staticpython_commit",
        "platform",
        "toolchain",
    ):
        if metadata.get(field) != runtime.get(field):
            raise RuntimeError(f"pack {owner} {field} does not match the runtime SDK")
    verification = metadata.get("verification")
    if not isinstance(verification, dict) or verification.get("status") not in {"not-run", "passed"}:
        raise RuntimeError(f"pack {owner} has invalid verification state")
    license_metadata = metadata.get("license")
    if not isinstance(license_metadata, dict) or license_metadata.get("status") != "complete":
        raise RuntimeError(f"pack {owner} has incomplete license metadata")

    descriptor = metadata.get("descriptor_symbol")
    if not isinstance(descriptor, str) or not C_IDENTIFIER_PATTERN.fullmatch(descriptor):
        raise RuntimeError(f"pack {owner} has an invalid descriptor symbol")
    sources = metadata.get("sources")
    if not isinstance(sources, list) or not sources:
        raise RuntimeError(f"pack {owner} has no C sources")
    for source in sources:
        path = _safe_file(root, source, description=f"pack {owner} source")
        if path.suffix.casefold() != ".c":
            raise RuntimeError(f"pack {owner} source is not C: {source}")

    libraries = metadata.get("libraries")
    if not isinstance(libraries, list):
        raise RuntimeError(f"pack {owner} libraries must be a list")
    library_names: set[str] = set()
    for library in libraries:
        name = _validate_library_leaf(library, description=f"pack {owner} library")
        if name.casefold() in library_names:
            raise RuntimeError(f"pack {owner} repeats native library {name}")
        library_names.add(name.casefold())
        _safe_file(root, f"lib/{name}", description=f"pack {owner} library")
    wholearchive = metadata.get("wholearchive")
    if not isinstance(wholearchive, list):
        raise RuntimeError(f"pack {owner} wholearchive must be a list")
    for library in wholearchive:
        name = _validate_library_leaf(library, description=f"pack {owner} wholearchive library")
        if name.casefold() not in library_names:
            raise RuntimeError(f"pack {owner} wholearchive library is missing: {name}")
    for key in ("system_libraries", "suppressed_system_libraries"):
        values = metadata.get(key, [])
        if not isinstance(values, list):
            raise RuntimeError(f"pack {owner} {key} must be a list")
        for value in values:
            _validate_windows_link_library(value, description=f"pack {owner} {key} entry")
    for key in ("dependencies", "conflicts", "frozen_modules", "top_level_import_names"):
        values = metadata.get(key, [])
        if not isinstance(values, list) or any(not isinstance(value, str) or not value for value in values):
            raise RuntimeError(f"pack {owner} {key} must be a list of non-empty strings")
    builtins = metadata.get("builtin_modules", [])
    if not isinstance(builtins, list) or any(
        not isinstance(record, dict)
        or not isinstance(record.get("name"), str)
        or not record["name"]
        for record in builtins
    ):
        raise RuntimeError(f"pack {owner} builtin_modules has invalid records")
    resources = metadata.get("resources", [])
    if not isinstance(resources, list) or any(
        not isinstance(record, dict)
        or not isinstance(record.get("path"), str)
        or not record["path"]
        for record in resources
    ):
        raise RuntimeError(f"pack {owner} resources has invalid records")
    smoke_tests = metadata.get("smoke_tests")
    if not isinstance(smoke_tests, list) or not smoke_tests or any(not isinstance(step, dict) for step in smoke_tests):
        raise RuntimeError(f"pack {owner} smoke_tests must be a non-empty list of objects")
    return metadata


def validate_composition(runtime: dict, packs: list[MaterializedPack]) -> None:
    selected: dict[str, str] = {}
    claimed: dict[str, dict[str, str]] = {
        "descriptor": {},
        "frozen module": {},
        "builtin module": {},
        "resource": {},
    }

    def claim(kind: str, value: str, owner: str) -> None:
        key = value.casefold()
        previous = claimed[kind].get(key)
        if previous is not None:
            raise RuntimeError(f"packs {previous} and {owner} both claim {kind} {value}")
        claimed[kind][key] = owner

    runtime_frozen = {
        str(name).casefold()
        for name in runtime.get("frozen_module_names", [])
        if isinstance(name, str)
    }
    runtime_builtins = {
        str(name).casefold()
        for name in runtime.get("builtin_module_names", [])
        if isinstance(name, str)
    }
    for pack in packs:
        metadata = pack.metadata
        owner = metadata["name"]
        key = owner.casefold()
        if key in selected:
            raise RuntimeError(f"duplicate selected pack name: {owner}")
        selected[key] = owner
        claim("descriptor", metadata["descriptor_symbol"], owner)
        for name in metadata.get("frozen_modules", []):
            if name.casefold() in runtime_frozen:
                raise RuntimeError(f"pack {owner} frozen module conflicts with the runtime SDK: {name}")
            claim("frozen module", name, owner)
        for record in metadata.get("builtin_modules", []):
            name = record["name"]
            if name.casefold() in runtime_builtins:
                raise RuntimeError(f"pack {owner} builtin module conflicts with the runtime SDK: {name}")
            claim("builtin module", name, owner)
        for record in metadata.get("resources", []):
            claim("resource", record["path"], owner)

    for pack in packs:
        metadata = pack.metadata
        owner = metadata["name"]
        missing = [name for name in metadata.get("dependencies", []) if name.casefold() not in selected]
        if missing:
            raise RuntimeError(f"pack {owner} dependencies are missing: {', '.join(missing)}")
        conflicts = [name for name in metadata.get("conflicts", []) if name.casefold() in selected]
        if conflicts:
            raise RuntimeError(f"pack {owner} conflicts with selected packs: {', '.join(conflicts)}")


def infer_namespace_packages(runtime: dict, packs: list[MaterializedPack]) -> tuple[str, ...]:
    known = {
        str(name)
        for field in ("frozen_module_names", "builtin_module_names")
        for name in runtime.get(field, [])
        if isinstance(name, str) and name
    }
    selected = {
        name
        for pack in packs
        for name in pack.metadata.get("frozen_modules", [])
    }
    selected.update(
        record["name"]
        for pack in packs
        for record in pack.metadata.get("builtin_modules", [])
    )
    all_modules = known | selected
    namespaces: set[str] = set()
    for name in selected:
        parts = name.split(".")
        for index in range(1, len(parts)):
            parent = ".".join(parts[:index])
            if parent not in all_modules:
                namespaces.add(parent)
    return tuple(sorted(namespaces, key=lambda name: (name.count("."), name.casefold())))


def _smoke_body(repo_root: Path, integration: str, index: int, step: dict) -> tuple[str, str, str, float, str | None]:
    kind = str(step.get("kind", "import"))
    name = str(step.get("name") or f"{kind}-{index}")
    skip_group = step.get("skip_group")
    if skip_group is not None and (not isinstance(skip_group, str) or not skip_group):
        raise RuntimeError(f"pack {integration} smoke {name} has an invalid skip_group")
    try:
        timeout = float(step.get("timeout", 240))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"pack {integration} smoke {name} has an invalid timeout") from exc
    if timeout <= 0:
        raise RuntimeError(f"pack {integration} smoke {name} timeout must be positive")
    args = [str(value) for value in step.get("args", [])]
    filename = f"<staticpython-smoke:{integration}:{name}>"
    if kind == "import":
        module = step.get("module")
        if not isinstance(module, str) or not module:
            raise RuntimeError(f"pack {integration} import smoke {name} requires module")
        body = f"import importlib, sys\nsys.argv = ['-c']\nimportlib.import_module({module!r})\n"
    elif kind == "inline":
        code = step.get("code")
        if not isinstance(code, str) or not code or "\0" in code:
            raise RuntimeError(f"pack {integration} inline smoke {name} requires code")
        body = f"import sys\nsys.argv = ['-c']\n{code}\n"
    elif kind == "module":
        module = step.get("module")
        if not isinstance(module, str) or not module:
            raise RuntimeError(f"pack {integration} module smoke {name} requires module")
        body = (
            "import runpy, sys\n"
            f"sys.argv = {[module, *args]!r}\n"
            f"runpy._run_module_as_main({module!r}, alter_argv=True)\n"
        )
    elif kind == "script":
        script = step.get("script")
        if not isinstance(script, str) or not script:
            raise RuntimeError(f"pack {integration} script smoke {name} requires script")
        script_path = Path(script)
        if not script_path.is_absolute():
            script_path = repo_root / script_path
        script_path = script_path.resolve()
        if not script_path.is_file():
            raise RuntimeError(f"pack {integration} smoke script is missing: {script_path}")
        with tokenize.open(script_path) as source_file:
            source = source_file.read()
        if "\0" in source:
            raise RuntimeError(f"pack {integration} smoke script contains NUL: {script_path}")
        try:
            relative = script_path.relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            relative = script_path.name
        filename = f"staticpython-smoke://repo/{relative}"
        body = (
            "import sys\n"
            f"sys.argv = {[filename, *args]!r}\n"
            f"__file__ = {filename!r}\n"
            "__package__ = None\n"
            "__spec__ = None\n"
            f"exec(compile({source!r}, {filename!r}, 'exec'), globals(), globals())\n"
        )
    else:
        raise RuntimeError(f"pack {integration} smoke {name} has unsupported kind {kind!r}")
    wrapped = (
        "try:\n"
        f"    exec(compile({body!r}, {filename!r}, 'exec'), globals(), globals())\n"
        "except SystemExit as _staticpython_exit:\n"
        "    if _staticpython_exit.code not in (None, 0):\n"
        "        raise\n"
    )
    return name, kind, wrapped, timeout, skip_group


def build_smoke_cases(repo_root: Path, packs: list[MaterializedPack]) -> list[SmokeCase]:
    cases: list[SmokeCase] = []
    for pack in packs:
        integration = pack.metadata["name"]
        for index, step in enumerate(pack.metadata["smoke_tests"], start=1):
            name, kind, code, timeout, skip_group = _smoke_body(repo_root, integration, index, step)
            cases.append(SmokeCase(integration, name, kind, code, timeout, skip_group))
    return cases


def _c_bytes_literal(value: str) -> str:
    pieces: list[str] = []
    for byte in value.encode("utf-8"):
        if 32 <= byte <= 126 and byte not in {34, 92}:
            pieces.append(chr(byte))
        elif byte == 34:
            pieces.append(r'\"')
        elif byte == 92:
            pieces.append(r"\\")
        else:
            pieces.append(f"\\{byte:03o}")
    return '"' + "".join(pieces) + '"'


def _namespace_install_code(namespaces: tuple[str, ...]) -> str:
    if not namespaces:
        return ""
    return (
        "import importlib.machinery, sys, types\n"
        f"for _namespace_name in {namespaces!r}:\n"
        "    if _namespace_name in sys.modules:\n"
        "        continue\n"
        "    _namespace = types.ModuleType(_namespace_name)\n"
        "    _namespace.__package__ = _namespace_name\n"
        "    _namespace.__path__ = []\n"
        "    _namespace.__spec__ = importlib.machinery.ModuleSpec(_namespace_name, loader=None, is_package=True)\n"
        "    _namespace.__spec__.submodule_search_locations = []\n"
        "    sys.modules[_namespace_name] = _namespace\n"
    )


def write_launcher(
    path: Path,
    packs: list[MaterializedPack],
    smoke_cases: list[SmokeCase],
    namespaces: tuple[str, ...],
) -> Path:
    if not smoke_cases:
        raise RuntimeError("pack verification requires at least one smoke test")
    descriptor_symbols = [pack.metadata["descriptor_symbol"] for pack in packs]
    externs = [f"extern const StaticPythonPackV1 {symbol};" for symbol in descriptor_symbols]
    selected = ["    &StaticPython_BaseResourcePackV1,", *[f"    &{symbol}," for symbol in descriptor_symbols]]
    smoke_literals = [f"    {_c_bytes_literal(case.code)}," for case in smoke_cases]
    namespace_code = _c_bytes_literal(_namespace_install_code(namespaces))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "/* Auto-generated test-only launcher. SPDX-License-Identifier: Apache-2.0 */\n"
        "#define PY_SSIZE_T_CLEAN\n"
        "#include \"Python.h\"\n"
        "#include \"staticpython_pack.h\"\n"
        "#include <errno.h>\n"
        "#include <stdio.h>\n"
        "#include <stdlib.h>\n"
        "#include <wchar.h>\n\n"
        + "\n".join(externs)
        + "\n\nstatic const StaticPythonPackV1 *const verification_packs[] = {\n"
        + "\n".join(selected)
        + "\n};\n\n"
        + "static const char *const verification_smokes[] = {\n"
        + "\n".join(smoke_literals)
        + "\n};\n\n"
        + f"static const char verification_namespaces[] = {namespace_code};\n\n"
        + "static int\nverification_run(int argc, wchar_t **argv)\n{\n"
        + "    if (argc != 2) { fwprintf(stderr, L\"expected one smoke-test index\\n\"); return 64; }\n"
        + "    errno = 0; wchar_t *end = NULL; long index = wcstol(argv[1], &end, 10);\n"
        + f"    if (errno != 0 || end == argv[1] || *end != L'\\0' || index < 0 || index >= {len(smoke_cases)}) {{\n"
        + "        fwprintf(stderr, L\"invalid smoke-test index\\n\"); return 64;\n"
        + "    }\n"
        + "    if (StaticPython_RegisterPacks(verification_packs, sizeof(verification_packs) / sizeof(verification_packs[0])) < 0) {\n"
        + "        fprintf(stderr, \"StaticPython pack registration failed: %s\\n\", StaticPython_LastError()); return 120;\n"
        + "    }\n"
        + "    PyConfig config; PyStatus status; PyConfig_InitIsolatedConfig(&config);\n"
        + "    config.parse_argv = 0; config.use_environment = 0; config.user_site_directory = 0;\n"
        + "    config.safe_path = 1; config.write_bytecode = 0; config.pathconfig_warnings = 0;\n"
        + "    config.site_import = 1; config.module_search_paths_set = 1;\n"
        + "    status = PyWideStringList_Append(&config.module_search_paths, L\"staticpython-pack-verify://embedded\");\n"
        + "    if (!PyStatus_Exception(status)) status = PyConfig_SetString(&config, &config.stdio_encoding, L\"utf-8\");\n"
        + "    if (!PyStatus_Exception(status)) status = PyConfig_SetString(&config, &config.stdio_errors, L\"strict\");\n"
        + "    if (!PyStatus_Exception(status)) status = PyConfig_SetArgv(&config, argc, argv);\n"
        + "    if (!PyStatus_Exception(status)) status = PyConfig_SetString(&config, &config.program_name, argv[0]);\n"
        + "    if (!PyStatus_Exception(status)) status = PyConfig_SetString(&config, &config.executable, argv[0]);\n"
        + "    if (PyStatus_Exception(status)) { PyConfig_Clear(&config); Py_ExitStatusException(status); }\n"
        + "    status = Py_InitializeFromConfig(&config); PyConfig_Clear(&config);\n"
        + "    if (PyStatus_Exception(status)) Py_ExitStatusException(status);\n"
        + "    PyObject *runtime = PyImport_ImportModule(\"_staticpython_runtime\");\n"
        + "    PyObject *installed = runtime != NULL ? PyObject_CallMethod(runtime, \"install\", NULL) : NULL;\n"
        + "    Py_XDECREF(installed); Py_XDECREF(runtime);\n"
        + "    if (PyErr_Occurred()) { PyErr_Print(); Py_FinalizeEx(); return 121; }\n"
        + "    if (verification_namespaces[0] != '\\0' && PyRun_SimpleString(verification_namespaces) < 0) {\n"
        + "        PyErr_Print(); Py_FinalizeEx(); return 122;\n"
        + "    }\n"
        + "    int result = 0;\n"
        + "    if (PyRun_SimpleString(verification_smokes[index]) < 0) { PyErr_Print(); result = 1; }\n"
        + "    if (Py_FinalizeEx() < 0 && result == 0) result = 120;\n"
        + "    return result;\n}\n\n"
        + "int\nwmain(int argc, wchar_t **argv)\n{\n    return verification_run(argc, argv);\n}\n",
        encoding="utf-8",
        newline="\n",
    )
    return path


def _write_response(path: Path, arguments: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [subprocess.list2cmdline([argument]) for argument in arguments]
    path.write_text("\n".join(lines) + "\n", encoding="utf-16", newline="\n")
    return path


def _run_tool(command: list[str], *, cwd: Path, timeout: float | None = None) -> str:
    result = subprocess.run(
        command,
        cwd=cwd,
        env=os.environ.copy(),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"command failed with exit code {result.returncode}: "
            f"{subprocess.list2cmdline(command)}\n{result.stdout[-12000:]}"
        )
    return result.stdout


def _compile_source(
    cl: str,
    source: Path,
    object_path: Path,
    response_path: Path,
    include_dir: Path,
    pathmap_root: Path,
    work_dir: Path,
) -> tuple[Path, str]:
    arguments = [
        "/nologo",
        "/c",
        "/O2",
        "/Ob2",
        "/GL",
        "/Gy",
        "/Gw",
        "/MT",
        "/DNDEBUG",
        "/DPy_NO_ENABLE_SHARED",
        "/utf-8",
        "/bigobj",
        "/Brepro",
        "/Z7",
        f"/pathmap:{pathmap_root}=.staticpython/pack-verify",
        f"/I{include_dir}",
        f"/Fo{object_path}",
        str(source),
    ]
    _write_response(response_path, arguments)
    output = _run_tool([cl, f"@{response_path}"], cwd=work_dir)
    if not object_path.is_file():
        raise RuntimeError(f"compiler did not produce {object_path}")
    return object_path, output


def _dedupe_libraries(packs: list[MaterializedPack]) -> tuple[list[Path], list[Path]]:
    libraries: list[Path] = []
    by_name: dict[str, tuple[Path, str]] = {}
    wholearchive: list[Path] = []
    for pack in packs:
        local: dict[str, Path] = {}
        for name in pack.metadata.get("libraries", []):
            path = _safe_file(pack.root, f"lib/{name}", description=f"pack {pack.metadata['name']} library")
            digest = sha256_file(path)
            key = name.casefold()
            previous = by_name.get(key)
            if previous is not None and previous[1] != digest:
                raise RuntimeError(f"selected packs contain different payloads for native library {name}")
            if previous is None:
                by_name[key] = (path, digest)
                libraries.append(path)
                local[key] = path
            else:
                local[key] = previous[0]
        for name in pack.metadata.get("wholearchive", []):
            wholearchive.append(local[name.casefold()])
    return libraries, list(dict.fromkeys(wholearchive))


def _resolve_system_libraries(runtime: dict, packs: list[MaterializedPack]) -> list[str]:
    libraries = [
        *[str(name) for pack in packs for name in pack.metadata.get("system_libraries", [])],
        *[str(name) for name in runtime.get("system_libraries", [])],
        *REQUIRED_WINDOWS_SYSTEM_LIBRARIES,
    ]
    suppressed = {
        str(name).casefold()
        for pack in packs
        for name in pack.metadata.get("suppressed_system_libraries", [])
    }
    resolved: list[str] = []
    seen: set[str] = set()
    for library in libraries:
        _validate_windows_link_library(library, description="system library")
        key = library.casefold()
        if key in suppressed or key in seen:
            continue
        seen.add(key)
        resolved.append(library)
    return resolved


def build_harness(
    runtime_root: Path,
    runtime: dict,
    packs: list[MaterializedPack],
    smoke_cases: list[SmokeCase],
    work_dir: Path,
    *,
    build_workers: int | None = None,
) -> tuple[Path, Path, dict]:
    work_dir.mkdir(parents=True, exist_ok=True)
    source_dir = work_dir / "src"
    object_dir = work_dir / "obj"
    response_dir = work_dir / "rsp"
    for directory in (source_dir, object_dir, response_dir):
        directory.mkdir(parents=True, exist_ok=True)
    include_dir = _safe_directory(
        runtime_root,
        runtime.get("include_directory", "include"),
        description="runtime include directory",
    )
    library_dir = _safe_directory(
        runtime_root,
        runtime.get("library_directory", "lib"),
        description="runtime library directory",
    )
    launcher = write_launcher(
        source_dir / "pack_verification_launcher.c",
        packs,
        smoke_cases,
        infer_namespace_packages(runtime, packs),
    )
    sources = [launcher]
    sources.extend(
        _safe_file(pack.root, relative, description=f"pack {pack.metadata['name']} source")
        for pack in packs
        for relative in pack.metadata["sources"]
    )
    cl = resolve_tool_exe("cl")
    link = resolve_tool_exe("link")
    dumpbin = resolve_tool_exe("dumpbin")
    max_workers = build_workers or max(1, min(8, (os.cpu_count() or 2) - 1))
    max_workers = max(1, min(max_workers, len(sources)))
    jobs = []
    for index, source in enumerate(sources):
        digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:12]
        label = "launcher" if index == 0 else f"pack-source-{index:06d}"
        jobs.append(
            (
                source,
                object_dir / f"{label}-{digest}.obj",
                response_dir / f"{label}-{digest}.rsp",
            )
        )
    objects: list[Path] = []
    compile_logs: dict[str, str] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                _compile_source,
                cl,
                source,
                object_path,
                response_path,
                include_dir,
                work_dir.parent,
                work_dir,
            ): object_path.name
            for source, object_path, response_path in jobs
        }
        for future in concurrent.futures.as_completed(futures):
            object_path, output = future.result()
            objects.append(object_path)
            compile_logs[futures[future]] = output
    objects.sort(key=lambda path: path.name.casefold())

    pack_libraries, wholearchive = _dedupe_libraries(packs)
    runtime_libraries = [
        _safe_file(library_dir, name, description="runtime link library")
        for name in runtime["link_libraries"]
    ]
    executable = work_dir / "staticpython-pack-verify.exe"
    map_path = work_dir / "staticpython-pack-verify.map"
    pdb_path = work_dir / "staticpython-pack-verify.pdb"
    link_arguments = [
        "/NOLOGO",
        f"/OUT:{executable}",
        f"/MAP:{map_path}",
        f"/PDB:{pdb_path}",
        "/PDBALTPATH:%_PDB%",
        "/DEBUG:FULL",
        "/LTCG",
        "/OPT:REF",
        "/OPT:ICF",
        "/INCREMENTAL:NO",
        "/MANIFEST:EMBED",
        "/DYNAMICBASE",
        "/NXCOMPAT",
        "/HIGHENTROPYVA",
        "/Brepro",
        "/MACHINE:X64",
        "/SUBSYSTEM:CONSOLE",
        *[str(path) for path in objects],
        *[str(path) for path in pack_libraries],
        *[str(path) for path in runtime_libraries],
        *[f"/WHOLEARCHIVE:{path}" for path in wholearchive],
        *_resolve_system_libraries(runtime, packs),
    ]
    link_response = _write_response(response_dir / "link.rsp", link_arguments)
    link_log = _run_tool([link, f"@{link_response}"], cwd=work_dir)
    if not executable.is_file() or not map_path.is_file():
        raise RuntimeError("linker did not produce the verification executable and map")
    return executable, map_path, {
        "cl": cl,
        "link": link,
        "dumpbin": dumpbin,
        "compile_logs": compile_logs,
        "link_log": link_log,
        "pdb": str(pdb_path),
    }


def _dependency_names(dumpbin_output: str) -> list[str]:
    names: list[str] = []
    in_dependencies = False
    for line in dumpbin_output.splitlines():
        stripped = line.strip()
        if stripped == "Image has the following dependencies:":
            in_dependencies = True
            continue
        if in_dependencies and not stripped:
            if names:
                break
            continue
        if in_dependencies and stripped.casefold().endswith(".dll"):
            names.append(stripped)
    return sorted(set(names), key=str.casefold)


def audit_executable(executable: Path, map_path: Path, dumpbin: str) -> dict:
    dependents = _run_tool([dumpbin, "/NOLOGO", "/DEPENDENTS", str(executable)], cwd=executable.parent)
    dependencies = _dependency_names(dependents)
    forbidden_dependencies = [
        name
        for name in dependencies
        if any(pattern.match(name) for pattern in FORBIDDEN_DEPENDENCY_PATTERNS)
        or name.casefold().endswith(".pyd")
    ]
    system32 = Path(os.environ.get("WINDIR", r"C:\Windows")) / "System32"
    non_system_dependencies = [
        name
        for name in dependencies
        if not name.casefold().startswith(("api-ms-win-", "ext-ms-win-"))
        and not (system32 / name).is_file()
    ]
    map_text = map_path.read_text(encoding="utf-8", errors="replace")
    forbidden_symbols = [
        symbol
        for symbol in FORBIDDEN_ENTRY_SYMBOLS
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", map_text)
    ]
    main_objects = sorted(set(re.findall(r"(?im)^.*\bmain\.obj\b.*$", map_text)))
    report = {
        "status": "passed",
        "dependencies": dependencies,
        "forbidden_dependencies": forbidden_dependencies,
        "non_system_dependencies": non_system_dependencies,
        "forbidden_entry_symbols": forbidden_symbols,
        "main_object_records": main_objects,
        "executable_sha256": sha256_file(executable),
        "map_sha256": sha256_file(map_path),
    }
    failures = []
    if forbidden_dependencies:
        failures.append("forbidden DLLs: " + ", ".join(forbidden_dependencies))
    if non_system_dependencies:
        failures.append("non-system DLLs: " + ", ".join(non_system_dependencies))
    if forbidden_symbols:
        failures.append("generic Python entry symbols: " + ", ".join(forbidden_symbols))
    if main_objects:
        failures.append("main.obj was linked")
    if failures:
        report["status"] = "failed"
        report["failures"] = failures
    return report


def run_smoke_cases(
    executable: Path,
    smoke_cases: list[SmokeCase],
    runtime_cwd: Path,
    *,
    skipped_groups: set[str],
) -> tuple[list[dict], list[dict]]:
    runtime_cwd.mkdir(parents=True, exist_ok=True)
    records: list[dict] = []
    failures: list[dict] = []
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.upper().startswith("PYTHON")
    }
    environment.update({"PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"})
    for index, case in enumerate(smoke_cases):
        record = {
            "integration": case.integration,
            "name": case.name,
            "kind": case.kind,
        }
        if case.skip_group and case.skip_group in skipped_groups:
            record.update({"status": "skipped", "skip_group": case.skip_group})
            records.append(record)
            continue
        before = {
            path.relative_to(runtime_cwd).as_posix()
            for path in runtime_cwd.rglob("*")
            if path.is_file()
        }
        started = time.monotonic()
        try:
            result = subprocess.run(
                [str(executable), str(index)],
                cwd=runtime_cwd,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=case.timeout,
                check=False,
            )
            returncode = result.returncode
            stdout = result.stdout
            stderr = result.stderr
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            returncode = None
            stdout = (exc.stdout or b"").decode("utf-8", "replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
            stderr = (exc.stderr or b"").decode("utf-8", "replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
            timed_out = True
        after = {
            path.relative_to(runtime_cwd).as_posix()
            for path in runtime_cwd.rglob("*")
            if path.is_file()
        }
        released_files = sorted(after - before, key=str.casefold)
        passed = returncode == 0 and not timed_out and not released_files
        record.update(
            {
                "status": "passed" if passed else "failed",
                "returncode": returncode,
                "duration_seconds": round(time.monotonic() - started, 3),
                "timed_out": timed_out,
                "released_files": released_files,
                "stdout": stdout[-12000:],
                "stderr": stderr[-12000:],
            }
        )
        records.append(record)
        if not passed:
            failures.append(
                {
                    "integration": case.integration,
                    "name": case.name,
                    "kind": case.kind,
                    "returncode": returncode,
                    "timed_out": timed_out,
                    "released_files": released_files,
                    "stdout": stdout[-12000:],
                    "stderr": stderr[-12000:],
                }
            )
    return records, failures


def _write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def verify_assets(args: argparse.Namespace) -> int:
    report: dict = {
        "schema_version": 1,
        "kind": "staticpython-pack-sdk-verification",
        "status": "failed",
    }
    with tempfile.TemporaryDirectory(prefix="staticpython-pack-sdk-") as temporary:
        materialized_root = Path(temporary)
        runtime_input = args.runtime_sdk.resolve()
        if runtime_input.is_dir():
            runtime_root = runtime_input
            runtime_archive_sha = None
        elif runtime_input.is_file():
            runtime_root = materialized_root / "runtime"
            safe_extract_zip(runtime_input, runtime_root)
            runtime_archive_sha = sha256_file(runtime_input)
        else:
            raise RuntimeError(f"runtime SDK does not exist: {runtime_input}")
        runtime = validate_runtime_sdk(runtime_root)

        packs: list[MaterializedPack] = []
        for index, archive in enumerate(args.pack):
            archive = archive.resolve()
            if not archive.is_file():
                raise RuntimeError(f"pack archive does not exist: {archive}")
            root = materialized_root / f"pack-{index:04d}"
            safe_extract_zip(archive, root)
            metadata = validate_pack(root, runtime)
            packs.append(MaterializedPack(archive, root, metadata))
        if not packs:
            raise RuntimeError("at least one --pack is required")
        validate_composition(runtime, packs)
        smoke_cases = build_smoke_cases(args.repo_root.resolve(), packs)
        executable, map_path, toolchain = build_harness(
            runtime_root,
            runtime,
            packs,
            smoke_cases,
            args.work_dir.resolve(),
            build_workers=args.build_workers,
        )
        pe_audit = audit_executable(executable, map_path, toolchain["dumpbin"])
        smoke_records, smoke_failures = run_smoke_cases(
            executable,
            smoke_cases,
            args.work_dir.resolve() / "runtime-cwd",
            skipped_groups=set(args.skip_group),
        )
        failures = list(smoke_failures)
        if pe_audit["status"] != "passed":
            failures.append({"kind": "pe-audit", "details": pe_audit.get("failures", [])})
        report.update(
            {
                "status": "passed" if not failures else "failed",
                "runtime_sdk": {
                    "path": str(runtime_input),
                    "archive_sha256": runtime_archive_sha,
                    "runtime_abi": runtime["runtime_abi"],
                    "cpython_version": runtime["cpython_version"],
                    "staticpython_commit": runtime["staticpython_commit"],
                },
                "packs": [
                    {
                        "name": pack.metadata["name"],
                        "version": pack.metadata["version"],
                        "path": str(pack.archive),
                        "sha256": sha256_file(pack.archive),
                    }
                    for pack in packs
                ],
                "namespace_packages": list(infer_namespace_packages(runtime, packs)),
                "executable": str(executable),
                "executable_sha256": sha256_file(executable),
                "map": str(map_path),
                "pe_audit": pe_audit,
                "integration_smoke_tests": smoke_records,
                "failures": failures,
                "toolchain": toolchain,
            }
        )
    _write_report(args.report_json.resolve(), report)
    if report["status"] != "passed":
        print(f"[pack-sdk-verify] failed with {len(report['failures'])} issue(s)", file=sys.stderr)
        return 1
    print(
        f"[pack-sdk-verify] verified {len(report['packs'])} pack(s) and "
        f"{len(report['integration_smoke_tests'])} smoke test(s)"
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Link provisional StaticPython packs to an audited runtime SDK and run behavior smokes."
    )
    parser.add_argument("--runtime-sdk", type=Path, required=True)
    parser.add_argument("--pack", type=Path, action="append", default=[], required=True)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--report-json", type=Path, required=True)
    parser.add_argument("--build-workers", type=int)
    parser.add_argument("--skip-group", action="append", default=[])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return verify_assets(args)
    except Exception as exc:
        report = {
            "schema_version": 1,
            "kind": "staticpython-pack-sdk-verification",
            "status": "failed",
            "error_type": type(exc).__name__,
            "error": str(exc),
        }
        _write_report(args.report_json.resolve(), report)
        print(f"[pack-sdk-verify] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
