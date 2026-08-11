from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass, field
import fnmatch
import hashlib
import importlib.util
import json
import os
import re
import shutil
import sys
import tarfile
import time
from pathlib import Path, PurePosixPath
import tokenize
from types import ModuleType
from typing import Callable, Iterator
from urllib.request import Request, urlopen
from zipfile import ZipFile


def _ensure_repo_packaging_on_path() -> None:
    repo_packaging = Path(__file__).resolve().parent / "Lib" / "packaging"
    if not repo_packaging.exists():
        return
    repo_packaging_text = str(repo_packaging)
    if repo_packaging_text not in sys.path:
        sys.path.insert(0, repo_packaging_text)


_ensure_repo_packaging_on_path()

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.utils import InvalidWheelFilename, parse_wheel_filename
from packaging.version import InvalidVersion, Version


Hook = Callable[["LibraryHookContext"], None]
PYPI_API_URL_TEMPLATE = "https://pypi.org/pypi/{project}/json"
PYPI_VERSION_API_URL_TEMPLATE = "https://pypi.org/pypi/{project}/{version}/json"
GITHUB_ARCHIVE_URL_TEMPLATE = "https://github.com/{repo}/archive/refs/{ref_kind}/{ref}.zip"
SOURCE_ROOT_CANDIDATES = (
    "",
    "src",
    "py_src",
    "src_py",
    "src_py2",
    "src_py3",
    "src-python",
    "src_python",
    "lib",
    "lib64",
    "python",
    "py",
)
REPO_ROOT = Path(__file__).resolve().parent
DOWNLOAD_CACHE_ROOT = REPO_ROOT / "downloads"
SIMPLE_LIBRARY_PROJECT_ALIASES = {
    "annotated_doc": "annotated-doc",
    "attr": "attrs",
    "bs4": "beautifulsoup4",
    "cattr": "cattrs",
    "dateutil": "python-dateutil",
    "dotenv": "python-dotenv",
    "markdown_it": "markdown-it-py",
}


@dataclass
class LibraryHookContext:
    repo_root: Path
    source_root: Path
    version_info: tuple[int, int, int]
    version_mm: str
    version_full: str
    download_cache_root: Path
    work_cache_root: Path
    asset_overlay_root: Path
    log: Callable[[str], None]
    configuration: str = "Release"
    platform: str = "x64"


@dataclass
class LibraryIntegration:
    name: str
    source_provider: str = "local"
    project_name: str | None = None
    release_version: str | None = None
    minimum_release_version: str | None = None
    dependencies: list[str] = field(default_factory=list)
    auto_resolve_dependencies: bool = False
    overlay_entries: list[str] = field(default_factory=list)
    materialized_paths: list[str] = field(default_factory=list)
    cleanup_paths: list[str] = field(default_factory=list)
    python_packages: list[str] = field(default_factory=list)
    static_library_projects_release_x64: list[str] = field(default_factory=list)
    native_static_projects: list[dict] = field(default_factory=list)
    builtin_module_registrations: list[dict] = field(default_factory=list)
    staged_static_libraries_release_x64: list[dict] = field(default_factory=list)
    python_link_dependencies_release_x64: list[str] = field(default_factory=list)
    suppressed_system_libraries_release_x64: list[str] = field(default_factory=list)
    python_link_wholearchive_release_x64: list[str] = field(default_factory=list)
    trusted_object_origins: list[dict] = field(default_factory=list)
    top_level_import_names: list[str] = field(default_factory=list)
    dependency_constraints: dict[str, str] = field(default_factory=dict)
    conflicts: list[str] = field(default_factory=list)
    patch_rules: list[dict] = field(default_factory=list)
    source_resolver: str | None = None
    resource_rules: list[dict] = field(default_factory=list)
    license_expression: str | None = None
    license_files: list[str] = field(default_factory=list)
    license_sources: list[dict] = field(default_factory=list)
    smoke_tests: list[dict] = field(default_factory=list)
    source_ignore_patterns: list[str] = field(default_factory=list)
    prepare_source_hooks: list[Hook] = field(default_factory=list)
    pre_patch_hooks: list[Hook] = field(default_factory=list)
    post_patch_hooks: list[Hook] = field(default_factory=list)
    pre_build_hooks: list[Hook] = field(default_factory=list)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def _build_materialized_paths(
    source_mapping: dict[str, str],
    overlay_entries: list[str],
    extra_paths: list[str] | None = None,
) -> list[str]:
    paths = [
        _normalized_relpath(target)
        for selector, target in source_mapping.items()
        if not _parse_source_selector(selector)[1]
    ]
    paths.extend(_normalized_relpath(path) for path in overlay_entries)
    paths.extend(_normalized_relpath(path) for path in (extra_paths or []))
    return _unique(paths)


def _build_optional_source_cleanup_paths(source_mapping: dict[str, str]) -> list[str]:
    return _unique(
        [
            _normalized_relpath(target)
            for selector, target in source_mapping.items()
            if _parse_source_selector(selector)[1]
        ]
    )


def _build_cleanup_paths(paths: list[str] | None = None) -> list[str]:
    return _unique([_normalized_relpath(path) for path in (paths or [])])


def source_path(context: LibraryHookContext, relative: str) -> Path:
    return context.source_root / _normalized_relpath(relative)


def read_text_file(path: Path) -> str:
    first_error: UnicodeDecodeError | None = None
    encodings = ["utf-8", "utf-8-sig"]
    try:
        with path.open("rb") as handle:
            detected_encoding, _ = tokenize.detect_encoding(handle.readline)
    except (OSError, SyntaxError, UnicodeDecodeError):
        detected_encoding = None
    if detected_encoding:
        encodings.append(detected_encoding)
    encodings.extend(["cp1252", "latin-1"])
    for encoding in _unique(encodings):
        try:
            return path.read_text(encoding=encoding)
        except UnicodeDecodeError as exc:
            if first_error is None:
                first_error = exc
            continue
    if first_error is not None:
        raise first_error
    return path.read_text(encoding="utf-8")


def read_source_text(context: LibraryHookContext, relative: str) -> str:
    return read_text_file(source_path(context, relative))


def write_source_text(context: LibraryHookContext, relative: str, text: str) -> None:
    path = source_path(context, relative)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    context.log(f"updated {path.relative_to(context.source_root)}")


def transform_source_text(
    context: LibraryHookContext,
    relative: str,
    transform: Callable[[str], str],
    *,
    allow_missing: bool = False,
) -> None:
    path = source_path(context, relative)
    if not path.exists():
        if allow_missing:
            original = ""
        else:
            raise RuntimeError(f"source file not found for transformation: {path}")
    else:
        original = read_text_file(path)

    updated = transform(original)
    if updated == original:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8", newline="\n")
    context.log(f"updated {path.relative_to(context.source_root)}")


def transform_first_existing_source_text(
    context: LibraryHookContext,
    relatives: list[str] | tuple[str, ...],
    transform: Callable[[str], str],
    *,
    allow_all_missing: bool = False,
) -> str | None:
    normalized_relatives = [_normalized_relpath(relative) for relative in relatives]
    for relative in normalized_relatives:
        path = source_path(context, relative)
        if not path.exists():
            continue
        original = read_text_file(path)
        updated = transform(original)
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
            context.log(f"updated {path.relative_to(context.source_root)}")
        return relative
    if allow_all_missing:
        return None
    searched = ", ".join(str(source_path(context, relative)) for relative in normalized_relatives)
    raise RuntimeError(f"source file not found for transformation: {searched}")


def replace_text_once(text: str, old: str, new: str, *, label: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"expected snippet not found in {label}: {old!r}")
    return text.replace(old, new, 1)


def replace_text_all(text: str, old: str, new: str) -> str:
    if old not in text:
        return text
    return text.replace(old, new)


def ensure_text_after(text: str, anchor: str, snippet: str, *, label: str) -> str:
    if snippet in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"expected anchor not found in {label}: {anchor!r}")
    return text.replace(anchor, anchor + snippet, 1)


def ensure_text_before(text: str, anchor: str, snippet: str, *, label: str) -> str:
    if snippet in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"expected anchor not found in {label}: {anchor!r}")
    return text.replace(anchor, snippet + anchor, 1)


def replace_regex_once(text: str, pattern: str, repl: str, *, label: str, flags: int = re.MULTILINE) -> str:
    if repl in text:
        return text
    updated, count = re.subn(pattern, repl, text, count=1, flags=flags)
    if count != 1:
        raise RuntimeError(f"expected regex not found in {label}: {pattern}")
    return updated


def replace_function_block_once(
    text: str,
    function_name: str,
    replacement: str,
    *,
    label: str,
    next_name: str | None = None,
) -> str:
    if replacement in text:
        return text
    start_match = re.search(rf"(?m)^(?P<indent>[ \t]*)def {re.escape(function_name)}\(", text)
    if start_match is None:
        raise RuntimeError(f"expected function not found in {label}: {function_name}")
    indent = start_match.group("indent")
    start = start_match.start()
    line_break = text.find("\n", start_match.start())
    search_start = len(text) if line_break == -1 else line_break + 1
    if indent:
        replacement_lines = replacement.splitlines(keepends=True)
        for line in replacement_lines:
            stripped = line.strip()
            if not stripped:
                continue
            if not line.startswith(indent):
                replacement = "".join(
                    indent + line if line.strip() else line
                    for line in replacement_lines
                )
            break
    if next_name is not None:
        end_match = re.search(
            rf"(?m)^{re.escape(indent)}def {re.escape(next_name)}\(",
            text[search_start:],
        )
        if end_match is None:
            raise RuntimeError(f"expected next function not found in {label}: {next_name}")
        end = search_start + end_match.start()
    else:
        end_match = re.search(
            rf"(?m)^(?:{re.escape(indent)}(?:def|class)\s+|[ \t]{{0,{len(indent) - 1 if indent else 0}}}\S)",
            text[search_start:],
        )
        end = len(text) if end_match is None else search_start + end_match.start()
    return text[:start] + replacement + text[end:]


def ensure_package_markers(text: str, package_name: str) -> str:
    package_line = f"__package__ = '{package_name}'"
    path_line = "__path__ = [__name__]"
    if package_line in text and path_line in text:
        return text

    header = f"{package_line}\n\n{path_line}\n\n"
    return header + text.lstrip("\ufeff")


def module_verification_step(
    name: str,
    module: str,
    *,
    args: list[str] | None = None,
    timeout: float = 240,
    skip_group: str | None = None,
) -> dict:
    step = {
        "name": name,
        "kind": "module",
        "module": module,
        "timeout": timeout,
    }
    if args:
        step["args"] = list(args)
    if skip_group:
        step["skip_group"] = skip_group
    return step


def script_verification_step(
    name: str,
    script: str,
    *,
    args: list[str] | None = None,
    timeout: float = 240,
    skip_group: str | None = None,
) -> dict:
    step = {
        "name": name,
        "kind": "script",
        "script": script,
        "timeout": timeout,
    }
    if args:
        step["args"] = list(args)
    if skip_group:
        step["skip_group"] = skip_group
    return step


def inline_verification_step(
    name: str,
    code: str,
    *,
    timeout: float = 240,
    skip_group: str | None = None,
) -> dict:
    step = {
        "name": name,
        "kind": "inline",
        "code": code,
        "timeout": timeout,
    }
    if skip_group:
        step["skip_group"] = skip_group
    return step


def _normalized_project_name(project_name: str) -> str:
    return re.sub(r"[-_.]+", "-", project_name).lower()


def _normalized_relpath(relative_path: str) -> str:
    return relative_path.replace("\\", "/")


def _safe_cache_component(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value)


def _copy_entry(src: Path, dst: Path, ignore_patterns: list[str] | None = None) -> None:
    if dst.exists():
        if dst.is_dir() and not dst.is_symlink():
            _remove_tree(dst)
        else:
            dst.unlink()
    os.makedirs(_long_path(dst.parent), exist_ok=True)
    if src.is_dir():
        patterns = [
            "__pycache__",
            "*.pyc",
            "*.pyo",
            ".git",
            ".github",
            ".gitignore",
            ".gitattributes",
            ".gitmodules",
        ]
        patterns.extend(ignore_patterns or [])
        os.makedirs(_long_path(dst), exist_ok=True)
        for entry in os.listdir(_long_path(src)):
            if any(fnmatch.fnmatch(entry, pattern) for pattern in patterns):
                continue
            source_entry = src / entry
            dest_entry = dst / entry
            if source_entry.is_dir():
                _copy_entry(source_entry, dest_entry, ignore_patterns)
            else:
                os.makedirs(_long_path(dest_entry.parent), exist_ok=True)
                shutil.copy2(_long_path(source_entry), _long_path(dest_entry))
    else:
        shutil.copy2(_long_path(src), _long_path(dst))


def _http_get_json(url: str) -> dict:
    return json.loads(_read_url_bytes(url).decode("utf-8"))


def _download_file(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(_read_url_bytes(url))


def _read_url_bytes(url: str, *, attempts: int = 5, initial_delay_seconds: float = 1.0) -> bytes:
    request = Request(url, headers={"User-Agent": "StaticPython/1.0"})
    delay = initial_delay_seconds
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urlopen(request) as response:
                return response.read()
        except Exception as exc:
            last_error = exc
            if attempt >= attempts:
                break
            time.sleep(delay)
            delay = min(delay * 2, 15.0)
    assert last_error is not None
    raise last_error


def _marker_environment(target_version: Version) -> dict[str, str]:
    environment = default_environment()
    major = target_version.release[0] if len(target_version.release) >= 1 else 0
    minor = target_version.release[1] if len(target_version.release) >= 2 else 0
    environment.update(
        {
            "python_version": f"{major}.{minor}",
            "python_full_version": ".".join(str(part) for part in target_version.release[:3]),
            "implementation_name": "cpython",
            "platform_system": "Windows",
            "sys_platform": "win32",
            "os_name": "nt",
            "platform_machine": "AMD64",
            "extra": "",
        }
    )
    return environment


def _supports_target_python(requires_python: str | None, target_version: Version) -> bool:
    if not requires_python:
        return True
    try:
        specifier = SpecifierSet(requires_python)
    except InvalidSpecifier:
        return True
    return target_version in specifier


def _sorted_release_versions(releases: dict[str, list[dict]]) -> list[str]:
    stable: list[tuple[Version, str]] = []
    for raw_version in releases:
        try:
            version = Version(raw_version)
        except InvalidVersion:
            continue
        if version.is_prerelease or version.is_devrelease:
            continue
        stable.append((version, raw_version))
    stable.sort(reverse=True)
    return [raw_version for _, raw_version in stable]


def _sdist_filename_rank(filename: str) -> tuple[int, str]:
    lower_name = filename.lower()
    if lower_name.endswith((".tar.gz", ".tar.bz2", ".tar.xz", ".tgz", ".tar")):
        return (0, lower_name)
    if lower_name.endswith(".zip"):
        return (1, lower_name)
    return (2, lower_name)


def _wheel_interpreter_rank(interpreter: str, target_version: Version) -> int:
    major = target_version.release[0] if len(target_version.release) >= 1 else 0
    minor = target_version.release[1] if len(target_version.release) >= 2 else 0
    exact = f"cp{major}{minor}"
    generic = f"py{major}"

    if interpreter == exact:
        return 0
    if interpreter == generic:
        return 1
    if interpreter.startswith(generic):
        return 2
    if interpreter.startswith("cp"):
        return 3
    if interpreter.startswith("py"):
        return 4
    return 5


def _wheel_abi_rank(abi: str) -> int:
    if abi == "none":
        return 0
    if abi == "abi3":
        return 1
    if abi.startswith("cp"):
        return 2
    return 3


def _wheel_kind_rank(platform: str, abi: str) -> int:
    # sdist is the only true source artifact.
    # For wheels, abi=none only means "no CPython ABI coupling"; it does not mean
    # "source distribution". We still prefer pure universal wheels before any
    # platform wheel because they are the least prebuilt/specialized fallback.
    if platform == "any" and abi == "none":
        return 0
    if abi == "none":
        return 1
    if abi == "abi3":
        return 2
    return 3


def _wheel_platform_rank(platform: str) -> int:
    if platform == "any":
        return 0
    if platform == "win_amd64":
        return 1
    if platform.startswith("win_"):
        return 2
    if platform.startswith("manylinux") or platform.startswith("musllinux"):
        return 3
    if platform.startswith("macosx"):
        return 4
    return 5


def _wheel_filename_rank(filename: str, target_version: Version) -> tuple[int, int, int, int, str]:
    try:
        _, _, _, tags = parse_wheel_filename(filename)
    except InvalidWheelFilename:
        return (9, 9, 9, 9, filename.lower())
    tag_ranks = sorted(
        (
            _wheel_kind_rank(tag.platform, tag.abi),
            _wheel_interpreter_rank(tag.interpreter, target_version),
            _wheel_abi_rank(tag.abi),
            _wheel_platform_rank(tag.platform),
        )
        for tag in tags
    )
    if not tag_ranks:
        return (9, 9, 9, 9, filename.lower())
    best_kind, best_interpreter, best_abi, best_platform = tag_ranks[0]
    return (best_kind, best_interpreter, best_abi, best_platform, filename.lower())


def _pypi_file_sort_key(file_info: dict, target_version: Version) -> tuple:
    filename = str(file_info.get("filename") or "")
    packagetype = file_info.get("packagetype")
    if packagetype == "sdist":
        return (0, *_sdist_filename_rank(filename))
    if packagetype == "bdist_wheel":
        return (1, *_wheel_filename_rank(filename, target_version))
    return (2, filename.lower())


def _is_pure_universal_wheel(file_info: dict) -> bool:
    filename = str(file_info.get("filename") or "")
    try:
        _dist, _version, _build, tags = parse_wheel_filename(filename)
    except InvalidWheelFilename:
        return False
    return any(tag.platform == "any" and tag.abi == "none" for tag in tags)


def _compatible_pypi_files(
    files: list[dict],
    *,
    project_requires_python: str | None,
    target_version: Version,
) -> list[dict]:
    compatible: list[dict] = []
    for file_info in files:
        if file_info.get("yanked"):
            continue
        packagetype = file_info.get("packagetype")
        if packagetype not in {"sdist", "bdist_wheel"}:
            continue
        requires_python = file_info.get("requires_python") or project_requires_python
        if not _supports_target_python(requires_python, target_version):
            continue
        compatible.append(file_info)
    source_distributions = [
        file_info for file_info in compatible if file_info.get("packagetype") == "sdist"
    ]
    pure_universal_wheels = [
        file_info
        for file_info in compatible
        if file_info.get("packagetype") == "bdist_wheel" and _is_pure_universal_wheel(file_info)
    ]
    # Native wheels are never valid static-build inputs.  A native-only
    # release must provide an explicit, verifiable upstream source mapping.
    compatible = [*source_distributions, *pure_universal_wheels]
    return sorted(compatible, key=lambda file_info: _pypi_file_sort_key(file_info, target_version))


def _iter_pypi_distribution_candidates(
    project_name: str,
    target_version: Version,
    release_version: str | None = None,
) -> list[tuple[str, dict]]:
    payload = _http_get_json(PYPI_API_URL_TEMPLATE.format(project=project_name))
    releases = payload.get("releases", {})
    project_requires_python = payload.get("info", {}).get("requires_python")

    candidate_versions = [release_version] if release_version else _sorted_release_versions(releases)
    candidates: list[tuple[str, dict]] = []
    for raw_version in candidate_versions:
        if raw_version not in releases:
            continue
        compatible = _compatible_pypi_files(
            releases.get(raw_version, []),
            project_requires_python=project_requires_python,
            target_version=target_version,
        )
        for file_info in compatible:
            candidates.append((raw_version, file_info))
        if release_version and compatible:
            break
    return candidates


def _select_pypi_file(
    project_name: str,
    target_version: Version,
    release_version: str | None = None,
) -> tuple[str, dict]:
    candidates = _iter_pypi_distribution_candidates(project_name, target_version, release_version)
    for raw_version, file_info in candidates:
        if file_info.get("url"):
            return raw_version, file_info

    if release_version is not None:
        raise RuntimeError(
            f"could not find a compatible PyPI distribution artifact for {project_name!r} release {release_version!r} "
            f"and target Python {target_version}"
        )
    raise RuntimeError(
        f"could not find a compatible PyPI distribution artifact for {project_name!r} and target Python {target_version}"
    )


def _effective_pypi_release_version(
    project_name: str,
    target_version: Version,
    release_version: str | None,
) -> str | None:
    if release_version is not None:
        return release_version

    candidates = _iter_pypi_distribution_candidates(project_name, target_version, None)
    if not candidates:
        return None
    return candidates[0][0]


def _find_cached_pypi_archive(
    download_cache_root: Path,
    normalized_project_name: str,
    release_version: str,
    target_version: Version,
) -> Path | None:
    release_root = download_cache_root / "pypi" / normalized_project_name / release_version
    if not release_root.exists():
        return None

    candidates = [
        path
        for path in sorted(release_root.iterdir())
        if path.is_file() and any(suffix in {".zip", ".whl", ".tar", ".gz", ".bz2", ".xz", ".tgz"} for suffix in path.suffixes)
    ]
    if not candidates:
        return None

    return sorted(
        candidates,
        key=lambda path: _pypi_file_sort_key(
            {
                "filename": path.name,
                "packagetype": "bdist_wheel" if path.name.lower().endswith(".whl") else "sdist",
            },
            target_version,
        ),
    )[0]


def _find_cached_pypi_archives(
    download_cache_root: Path,
    normalized_project_name: str,
    release_version: str,
    target_version: Version,
) -> list[Path]:
    release_root = download_cache_root / "pypi" / normalized_project_name / release_version
    if not release_root.exists():
        return []

    candidates = [
        path
        for path in sorted(release_root.iterdir())
        if path.is_file() and any(suffix in {".zip", ".whl", ".tar", ".gz", ".bz2", ".xz", ".tgz"} for suffix in path.suffixes)
    ]
    if not candidates:
        return []

    return sorted(
        candidates,
        key=lambda path: _pypi_file_sort_key(
            {
                "filename": path.name,
                "packagetype": "bdist_wheel" if path.name.lower().endswith(".whl") else "sdist",
            },
            target_version,
        ),
    )


def _candidate_pypi_archives(
    download_cache_root: Path,
    project_name: str,
    target_version: Version,
    release_version: str | None,
) -> list[tuple[str, Path, str | None, bool]]:
    normalized = _normalized_project_name(project_name)
    if release_version is not None:
        cached_archive_paths = _find_cached_pypi_archives(
            download_cache_root,
            normalized,
            release_version,
            target_version,
        )
        if cached_archive_paths:
            return [(release_version, path, None, True) for path in cached_archive_paths]

    discovered_candidates = _iter_pypi_distribution_candidates(
        project_name,
        target_version,
        release_version,
    )
    if release_version is None and discovered_candidates:
        newest_version = discovered_candidates[0][0]
        discovered_candidates = [
            (resolved_release_version, file_info)
            for resolved_release_version, file_info in discovered_candidates
            if resolved_release_version == newest_version
        ]

    candidates: list[tuple[str, Path, str | None, bool]] = []
    for resolved_release_version, file_info in discovered_candidates:
        filename = file_info["filename"]
        archive_path = download_cache_root / "pypi" / normalized / resolved_release_version / filename
        candidates.append((resolved_release_version, archive_path, file_info["url"], False))
    return candidates


def _resolve_extracted_root(destination_root: Path) -> Path:
    children = [path for path in destination_root.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return destination_root


def _long_path(path: Path) -> str:
    absolute = str(path.resolve())
    if os.name != "nt" or absolute.startswith("\\\\?\\"):
        return absolute
    if absolute.startswith("\\\\"):
        return "\\\\?\\UNC\\" + absolute.lstrip("\\")
    return "\\\\?\\" + absolute


def _remove_tree(path: Path) -> None:
    def onerror(func, name, exc_info) -> None:
        if isinstance(exc_info[1], FileNotFoundError):
            return
        raise exc_info[1]

    shutil.rmtree(_long_path(path), onerror=onerror)


@contextmanager
def temporary_pypi_release_cache(
    context: LibraryHookContext,
    integration: LibraryIntegration,
    release_version: str,
) -> Iterator[None]:
    """Discard one PyPI release's caches after a bounded validation scope."""

    release_roots: list[Path] = []
    project_name = integration.project_name or integration.name
    if integration.source_provider == "pypi":
        normalized = _normalized_project_name(project_name)
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", normalized):
            raise RuntimeError(
                f"unsafe normalized PyPI cache project name: {normalized!r}"
            )
        try:
            Version(release_version)
        except InvalidVersion as exc:
            raise RuntimeError(
                f"unsafe PyPI cache release version: {release_version!r}"
            ) from exc
        if (
            not release_version
            or release_version in {".", ".."}
            or "/" in release_version
            or "\\" in release_version
        ):
            raise RuntimeError(
                f"unsafe PyPI cache release version: {release_version!r}"
            )
        for cache_root in (context.download_cache_root, context.work_cache_root):
            cache_root = cache_root.resolve()
            project_root = (cache_root / "pypi" / normalized).resolve()
            release_root = (project_root / release_version).resolve()
            if (
                not release_root.is_relative_to(cache_root)
                or release_root.parent != project_root
            ):
                raise RuntimeError(
                    "refusing to clean a PyPI release cache outside its exact "
                    f"project root: {release_root}"
                )
            release_roots.append(release_root)

    try:
        yield
    finally:
        if integration.source_provider == "pypi":
            removed: list[Path] = []
            for release_root in release_roots:
                if release_root.exists():
                    _remove_tree(release_root)
                    removed.append(release_root)
            if removed:
                context.log(
                    f"discarded temporary PyPI cache for {project_name} {release_version} "
                    f"from {len(removed)} root(s)"
                )


def _archive_target_path(destination_root: Path, member_name: str) -> Path | None:
    normalized = PurePosixPath(member_name.replace("\\", "/"))
    if normalized.is_absolute() or any(part in {"", ".", ".."} for part in normalized.parts):
        return None
    return destination_root.joinpath(*normalized.parts)


def _extract_zip_archive(archive_path: Path, destination_root: Path) -> None:
    with ZipFile(archive_path) as archive:
        for member in archive.infolist():
            target = _archive_target_path(destination_root, member.filename)
            if target is None:
                continue
            if member.is_dir():
                os.makedirs(_long_path(target), exist_ok=True)
                continue
            os.makedirs(_long_path(target.parent), exist_ok=True)
            with archive.open(member) as src, open(_long_path(target), "wb") as dst:
                shutil.copyfileobj(src, dst)


def _extract_tar_archive(archive_path: Path, destination_root: Path) -> None:
    with tarfile.open(archive_path) as archive:
        for member in archive:
            target = _archive_target_path(destination_root, member.name)
            if target is None:
                continue
            if member.isdir():
                os.makedirs(_long_path(target), exist_ok=True)
                continue
            if not member.isfile():
                continue
            os.makedirs(_long_path(target.parent), exist_ok=True)
            source = archive.extractfile(member)
            if source is None:
                continue
            with source, open(_long_path(target), "wb") as dst:
                shutil.copyfileobj(source, dst)


def _extract_cache_marker_path(destination_root: Path) -> Path:
    return destination_root.with_name(f"{destination_root.name}.staticpython-extract.json")


def _archive_cache_identity(archive_path: Path) -> dict[str, int | str]:
    stat = archive_path.stat()
    return {
        "archive": str(archive_path.resolve()),
        "size": stat.st_size,
        "mtime_ns": stat.st_mtime_ns,
    }


def _read_extract_cache_marker(destination_root: Path) -> dict | None:
    marker = _extract_cache_marker_path(destination_root)
    if not marker.exists():
        return None
    try:
        return json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_extract_cache_marker(destination_root: Path, archive_path: Path) -> None:
    marker = _extract_cache_marker_path(destination_root)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(_archive_cache_identity(archive_path), sort_keys=True), encoding="utf-8")


def _directory_has_entries(path: Path) -> bool:
    try:
        next(path.iterdir())
    except StopIteration:
        return False
    except OSError:
        return False
    return True


def _extract_archive(
    archive_path: Path,
    destination_root: Path,
    log: Callable[[str], None] | None = None,
) -> Path:
    expected_identity = _archive_cache_identity(archive_path)
    existing_identity = _read_extract_cache_marker(destination_root)
    if destination_root.exists() and _directory_has_entries(destination_root):
        if existing_identity in (expected_identity, None):
            if existing_identity is None:
                _write_extract_cache_marker(destination_root, archive_path)
            if log is not None:
                log(f"reusing extracted source cache {destination_root}")
            return _resolve_extracted_root(destination_root)

    if destination_root.exists():
        if log is not None:
            log(f"refreshing extracted source cache {destination_root}")
        _remove_tree(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)

    suffixes = [suffix.lower() for suffix in archive_path.suffixes]
    started = time.monotonic()
    if log is not None:
        log(f"extracting {archive_path} -> {destination_root}")
    if ".zip" in suffixes or ".whl" in suffixes:
        _extract_zip_archive(archive_path, destination_root)
        _write_extract_cache_marker(destination_root, archive_path)
        if log is not None:
            log(f"extracted {archive_path.name} in {time.monotonic() - started:.1f}s")
        return _resolve_extracted_root(destination_root)

    if any(suffix in {".tar", ".gz", ".bz2", ".xz", ".tgz"} for suffix in suffixes):
        _extract_tar_archive(archive_path, destination_root)
        _write_extract_cache_marker(destination_root, archive_path)
        if log is not None:
            log(f"extracted {archive_path.name} in {time.monotonic() - started:.1f}s")
        return _resolve_extracted_root(destination_root)

    raise RuntimeError(f"unsupported archive format: {archive_path}")


def _candidate_source_roots(extracted_root: Path) -> list[Path]:
    roots: list[Path] = []
    seen: set[Path] = set()

    def add(candidate: Path) -> None:
        try:
            resolved = candidate.resolve()
        except OSError:
            resolved = candidate
        if resolved in seen or not candidate.exists():
            return
        seen.add(resolved)
        roots.append(candidate)

    for rel in SOURCE_ROOT_CANDIDATES:
        candidate = extracted_root / rel if rel else extracted_root
        add(candidate)

    try:
        children = list(extracted_root.iterdir())
    except OSError:
        children = []
    for child in children:
        if not child.is_dir() or not child.name.endswith(".data"):
            continue
        add(child / "purelib")
        add(child / "platlib")

    return roots


def _selector_variants(selector: str) -> list[str]:
    normalized = selector.replace("\\", "/").strip("/")
    variants = [normalized]
    seen = {normalized}
    pending = [normalized]
    while pending:
        current = pending.pop()
        for prefix in SOURCE_ROOT_CANDIDATES:
            if not prefix:
                continue
            prefix_text = prefix + "/"
            if not current.startswith(prefix_text):
                continue
            stripped = current[len(prefix_text) :]
            if not stripped or stripped in seen:
                continue
            seen.add(stripped)
            variants.append(stripped)
            pending.append(stripped)
    return variants


def _selector_lookup_keys(selector: str) -> set[str]:
    normalized = selector.replace("\\", "/").strip("/")
    basename = normalized.rsplit("/", 1)[-1]
    if basename.endswith(".py"):
        basename = basename[:-3]
    if not basename:
        return set()
    canonical = _normalized_project_name(basename).replace("-", "_")
    return {
        basename.casefold(),
        basename.casefold().replace("-", "_"),
        canonical,
    }


def _entry_lookup_keys(path: Path) -> set[str]:
    name = path.stem if path.is_file() else path.name
    canonical = _normalized_project_name(name).replace("-", "_")
    return {
        name.casefold(),
        name.casefold().replace("-", "_"),
        canonical,
    }


def _top_level_declared_entries(root: Path) -> list[str]:
    entries: list[str] = []
    try:
        top_level_files = sorted(root.rglob("top_level.txt"))
    except OSError:
        return entries
    for path in top_level_files:
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            normalized = line.strip().replace("\\", "/").strip("/")
            if not normalized:
                continue
            entries.append(normalized)
    return _unique(entries)


def _top_level_python_entries(root: Path) -> list[Path]:
    entries: list[Path] = []
    try:
        children = sorted(root.iterdir(), key=lambda path: path.name.casefold())
    except OSError:
        return entries
    for child in children:
        if child.name.startswith("."):
            continue
        if child.is_dir():
            if child.name.endswith((".egg-info", ".dist-info", "__pycache__")):
                continue
            if (child / "__init__.py").exists():
                entries.append(child)
            continue
        if child.suffix == ".py" and child.stem not in {"setup", "conftest"}:
            entries.append(child)
    return entries


def _resolve_declared_top_level_match(extracted_root: Path, selector: str) -> Path | None:
    selector_keys = _selector_lookup_keys(selector)
    matches: list[Path] = []
    for root in _candidate_source_roots(extracted_root):
        for entry in _top_level_declared_entries(root):
            candidate = root / entry
            if candidate.exists() and (_entry_lookup_keys(candidate) & selector_keys):
                matches.append(candidate)
            file_candidate = root / f"{entry}.py"
            if file_candidate.exists() and (_entry_lookup_keys(file_candidate) & selector_keys):
                matches.append(file_candidate)
    unique_matches = _unique([str(path.resolve()) for path in matches])
    if len(unique_matches) != 1:
        return None
    return Path(unique_matches[0])


def _resolve_unique_top_level_python_entry(extracted_root: Path, selector: str) -> Path | None:
    selector_keys = _selector_lookup_keys(selector)
    matches: list[Path] = []
    for root in _candidate_source_roots(extracted_root):
        for entry in _top_level_python_entries(root):
            if _entry_lookup_keys(entry) & selector_keys:
                matches.append(entry)
        if len(matches) > 1:
            break
    unique_matches = _unique([str(path.resolve()) for path in matches])
    if len(unique_matches) != 1:
        return None
    return Path(unique_matches[0])


def _resolve_unique_basename_match(extracted_root: Path, basename: str) -> Path | None:
    matches: list[Path] = []
    for root in _candidate_source_roots(extracted_root):
        try:
            for path in root.rglob(basename):
                if path.name != basename:
                    continue
                matches.append(path)
                if len(matches) > 1:
                    return None
        except OSError:
            continue
    if len(matches) == 1:
        return matches[0]
    return None


def _resolve_single_source_entry(extracted_root: Path, selector: str) -> Path:
    variants = _selector_variants(selector)
    candidate_roots = _candidate_source_roots(extracted_root)

    for normalized in variants:
        explicit = extracted_root / normalized
        if explicit.exists():
            return explicit

        for root in candidate_roots:
            direct = root / normalized
            if direct.exists():
                return direct

        if "/" not in normalized:
            for root in candidate_roots:
                file_candidate = root / f"{normalized}.py"
                if file_candidate.exists():
                    return file_candidate
                if "-" in normalized:
                    dashed_candidate = root / normalized.replace("-", "_")
                    if dashed_candidate.exists():
                        return dashed_candidate
                if "_" in normalized:
                    underscored_candidate = root / normalized.replace("_", "-")
                    if underscored_candidate.exists():
                        return underscored_candidate

    if all("/" not in variant for variant in variants):
        basename = variants[-1].rsplit("/", 1)[-1]
        unique_match = _resolve_unique_basename_match(extracted_root, basename)
        if unique_match is not None:
            return unique_match
        declared_top_level = _resolve_declared_top_level_match(extracted_root, selector)
        if declared_top_level is not None:
            return declared_top_level
        unique_top_level = _resolve_unique_top_level_python_entry(extracted_root, selector)
        if unique_top_level is not None:
            return unique_top_level

    raise RuntimeError(f"could not resolve {selector!r} inside extracted source tree {extracted_root}")


def _resolve_source_entry(extracted_root: Path, selector: str) -> Path:
    alternatives = [part.strip() for part in selector.split("||") if part.strip()]
    if not alternatives:
        alternatives = [selector]
    last_error: RuntimeError | None = None
    for alternative in alternatives:
        alternative, _optional = _parse_source_selector(alternative)
        try:
            return _resolve_single_source_entry(extracted_root, alternative)
        except RuntimeError as exc:
            last_error = exc
    assert last_error is not None
    raise last_error


def _parse_source_selector(selector: str) -> tuple[str, bool]:
    stripped = selector.strip()
    if stripped.startswith("?"):
        return stripped[1:].strip(), True
    return selector, False


def _materialize_source_mapping(
    context: LibraryHookContext,
    source_mapping: dict[str, str],
    resolver: Callable[[str], Path],
    ignore_patterns: list[str] | None = None,
) -> None:
    for selector, target_rel in source_mapping.items():
        resolved_selector, optional = _parse_source_selector(selector)
        try:
            src = resolver(resolved_selector)
        except RuntimeError as exc:
            if optional:
                context.log(f"skipping optional source mapping {selector} -> {target_rel}: {exc}")
                continue
            raise
        dst = context.source_root / _normalized_relpath(target_rel)
        started = time.monotonic()
        context.log(f"materializing {selector} -> {target_rel}")
        _copy_entry(src, dst, ignore_patterns)
        context.log(f"materialized {selector} -> {target_rel} in {time.monotonic() - started:.1f}s")


def _infer_license_expression(info: dict) -> str | None:
    expression = info.get("license_expression")
    if isinstance(expression, str) and expression.strip():
        return expression.strip()
    raw_license = info.get("license")
    normalized = re.sub(r"[^a-z0-9]+", " ", str(raw_license or "").casefold()).strip()
    known = {
        "mit": "MIT",
        "mit license": "MIT",
        "apache 2 0 and mit": "Apache-2.0 AND MIT",
        "mit or apache 2 0": "MIT OR Apache-2.0",
        "mpl 2 0 and mit": "MPL-2.0 AND MIT",
        "bsd 2 clause": "BSD-2-Clause",
        "bsd 2 clause license": "BSD-2-Clause",
        "bsd 3 clause": "BSD-3-Clause",
        "bsd 3 clause license": "BSD-3-Clause",
        "3 clause bsd license": "BSD-3-Clause",
        "apache": "Apache-2.0",
        "apache 2": "Apache-2.0",
        "apache 2 0": "Apache-2.0",
        "apache license 2 0": "Apache-2.0",
        "apache license version 2 0": "Apache-2.0",
        "apache software license": "Apache-2.0",
        "isc": "ISC",
        "isc license": "ISC",
        "mozilla public license 2 0": "MPL-2.0",
        "python software foundation license": "PSF-2.0",
        "unlicense": "Unlicense",
    }
    if normalized in known:
        return known[normalized]
    classifier_map = {
        "License :: OSI Approved :: MIT License": "MIT",
        "License :: OSI Approved :: Apache Software License": "Apache-2.0",
        "License :: OSI Approved :: BSD License": "BSD-3-Clause",
        "License :: OSI Approved :: ISC License (ISCL)": "ISC",
        "License :: OSI Approved :: Mozilla Public License 2.0 (MPL 2.0)": "MPL-2.0",
        "License :: OSI Approved :: Python Software Foundation License": "PSF-2.0",
        "License :: OSI Approved :: The Unlicense (Unlicense)": "Unlicense",
        "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)": "LGPL-3.0-only",
    }
    expressions = {
        classifier_map[classifier]
        for classifier in info.get("classifiers", [])
        if classifier in classifier_map
    }
    if len(expressions) == 1:
        return next(iter(expressions))
    return None


def _materialize_distribution_licenses(
    context: LibraryHookContext,
    integration: LibraryIntegration,
    extracted_root: Path,
) -> None:
    _materialize_license_candidates(
        context,
        integration,
        _distribution_license_candidates(extracted_root),
    )


def _distribution_license_candidates(root: Path, *, maximum_depth: int = 3) -> list[Path]:
    prefixes = ("license", "copying", "notice", "copyright", "authors")
    candidates: list[Path] = []
    if not root.is_dir():
        return candidates
    for path in root.rglob("*"):
        if not path.is_file() or not path.name.casefold().startswith(prefixes):
            continue
        try:
            relative = path.relative_to(root)
        except ValueError:
            continue
        if len(relative.parts) > maximum_depth or path.stat().st_size > 2 * 1024 * 1024:
            continue
        candidates.append(path)
    return candidates


def _materialize_license_candidates(
    context: LibraryHookContext,
    integration: LibraryIntegration,
    candidates: list[Path],
) -> None:
    # Source roots include runner-specific absolute paths.  Deduplicate and
    # order by basename plus content hash so collision names remain reproducible
    # for the same locked sources regardless of the build directory.
    candidate_records: dict[tuple[str, str], tuple[Path, str]] = {}
    for source in candidates:
        digest = hashlib.sha256(source.read_bytes()).hexdigest()
        candidate_records.setdefault((source.name.casefold(), digest), (source, digest))
    unique_candidates = sorted(
        candidate_records.values(),
        key=lambda record: (record[0].name.casefold(), record[1]),
    )
    if not unique_candidates:
        return
    target_root = context.source_root / "licenses" / re.sub(r"[^0-9A-Za-z_.-]+", "-", integration.name)
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True, exist_ok=True)
    used_names: set[str] = set()
    integration.license_files.clear()
    for source, digest in unique_candidates:
        target_name = source.name
        if target_name.casefold() in used_names:
            target_name = f"{digest[:12]}-{target_name}"
        used_names.add(target_name.casefold())
        target = target_root / target_name
        shutil.copy2(source, target)
        integration.license_files.append(target.relative_to(context.source_root).as_posix())
    context.log(f"materialized {len(integration.license_files)} license/notice file(s) for {integration.name}")


def _materialize_declared_license_sources(
    context: LibraryHookContext,
    integration: LibraryIntegration,
) -> None:
    if not integration.release_version:
        raise RuntimeError(
            f"{integration.name} declares license sources but does not have a resolved release version"
        )
    target_root = context.source_root / "licenses" / re.sub(
        r"[^0-9A-Za-z_.-]+",
        "-",
        integration.name,
    )
    target_root.mkdir(parents=True, exist_ok=True)
    for index, rule in enumerate(integration.license_sources, start=1):
        if not isinstance(rule, dict):
            raise RuntimeError(f"{integration.name} license source #{index} must be an object")
        unknown_keys = sorted(set(rule) - {"filename", "url", "sha256"})
        if unknown_keys:
            raise RuntimeError(
                f"{integration.name} license source #{index} has unsupported keys: "
                + ", ".join(unknown_keys)
            )
        filename = rule.get("filename")
        url_template = rule.get("url")
        expected_sha256 = str(rule.get("sha256") or "").casefold()
        if not isinstance(filename, str) or not filename:
            raise RuntimeError(f"{integration.name} license source #{index} is missing filename")
        normalized_filename = filename.replace("\\", "/")
        parsed_filename = PurePosixPath(normalized_filename)
        if (
            parsed_filename.is_absolute()
            or len(parsed_filename.parts) != 1
            or parsed_filename.name in {"", ".", ".."}
        ):
            raise RuntimeError(
                f"{integration.name} license source #{index} filename must be a basename"
            )
        if not isinstance(url_template, str) or not url_template.startswith("https://"):
            raise RuntimeError(
                f"{integration.name} license source #{index} must use an HTTPS URL"
            )
        if re.fullmatch(r"[0-9a-f]{64}", expected_sha256) is None:
            raise RuntimeError(
                f"{integration.name} license source #{index} must declare a SHA-256 digest"
            )
        try:
            url = url_template.format(
                release_version=integration.release_version,
                project_name=integration.project_name or integration.name,
            )
        except (KeyError, ValueError) as exc:
            raise RuntimeError(
                f"{integration.name} license source #{index} has an invalid URL template"
            ) from exc

        cache_path = (
            context.download_cache_root
            / "license-sources"
            / _normalized_project_name(integration.name)
            / integration.release_version
            / f"{expected_sha256}-{parsed_filename.name}"
        )
        if cache_path.exists():
            payload = cache_path.read_bytes()
        else:
            context.log(f"downloading {integration.name} license source from {url}")
            payload = _read_url_bytes(url)
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            cache_path.write_bytes(payload)
        observed_sha256 = hashlib.sha256(payload).hexdigest()
        if observed_sha256 != expected_sha256:
            raise RuntimeError(
                f"{integration.name} license source #{index} hash mismatch: "
                f"expected {expected_sha256}, observed {observed_sha256}"
            )

        target = target_root / parsed_filename.name
        if target.exists() and target.read_bytes() != payload:
            target = target_root / f"{observed_sha256[:12]}-{parsed_filename.name}"
        target.write_bytes(payload)
        relative = target.relative_to(context.source_root).as_posix()
        if relative not in integration.license_files:
            integration.license_files.append(relative)
    context.log(
        f"materialized {len(integration.license_files)} declared license source(s) for {integration.name}"
    )


def _finalize_integration_license_metadata(
    context: LibraryHookContext,
    integration: LibraryIntegration,
) -> None:
    if integration.license_expression is None and integration.source_provider == "pypi":
        project_name = integration.project_name or integration.name
        release_payload = _load_pypi_release_payload(project_name, integration.release_version)
        integration.license_expression = _infer_license_expression(release_payload.get("info", {}))

    if not integration.license_files:
        candidates: list[Path] = []
        for relative in integration.materialized_paths:
            path = context.source_root / relative
            root = path if path.is_dir() else path.parent
            candidates.extend(_distribution_license_candidates(root, maximum_depth=4))

        if integration.source_provider == "pypi" and integration.release_version:
            project_name = integration.project_name or integration.name
            cached_distribution_root = (
                context.work_cache_root
                / "pypi"
                / _normalized_project_name(project_name)
                / integration.release_version
            )
            # Custom source hooks use slightly different extraction layouts. The
            # version-scoped cache root is stable across all of them and keeps the
            # scan bounded to the exact distribution selected for this pack.
            candidates.extend(
                _distribution_license_candidates(cached_distribution_root, maximum_depth=6)
            )

        _materialize_license_candidates(context, integration, candidates)

    if not integration.license_files and integration.license_sources:
        _materialize_declared_license_sources(context, integration)


def _version_format_args(context: LibraryHookContext) -> dict[str, int | str]:
    major, minor, micro = context.version_info
    return {
        "version": context.version_full,
        "version_mm": context.version_mm,
        "major": major,
        "minor": minor,
        "micro": micro,
    }


def _build_pypi_source_hook(
    integration: LibraryIntegration,
    project_name: str,
    source_mapping: dict[str, str],
    source_ignore_patterns: list[str] | None = None,
) -> Hook:
    normalized = _normalized_project_name(project_name)

    def prepare_source(context: LibraryHookContext) -> None:
        release_version = integration.release_version
        target_version = Version(".".join(str(part) for part in context.version_info))
        candidate_archives = _candidate_pypi_archives(
            context.download_cache_root,
            project_name,
            target_version,
            release_version,
        )

        if not candidate_archives:
            raise RuntimeError(
                f"could not find a compatible PyPI distribution artifact for {project_name!r}"
                + (
                    f" release {release_version!r}"
                    if release_version is not None
                    else ""
                )
                + f" and target Python {target_version}"
            )

        failures: list[str] = []
        for resolved_release_version, archive_path, url, cached in candidate_archives:
            extract_root = (
                context.work_cache_root
                / "pypi"
                / normalized
                / resolved_release_version
                / "extracted"
                / _safe_cache_component(archive_path.name)
            )

            if not archive_path.exists():
                context.log(f"downloading {project_name} {resolved_release_version} from PyPI")
                assert url is not None
                _download_file(url, archive_path)
            elif cached:
                context.log(
                    f"reusing cached {project_name} {resolved_release_version} archive without refreshing PyPI metadata"
                )
            else:
                context.log(f"reusing cached {project_name} {resolved_release_version} archive")

            try:
                extracted_root = _extract_archive(archive_path, extract_root, context.log)
                context.log(f"using {project_name} {resolved_release_version} source from {extracted_root}")
                _materialize_source_mapping(
                    context,
                    source_mapping,
                    lambda selector: _resolve_source_entry(extracted_root, selector),
                    source_ignore_patterns,
                )
                integration.release_version = resolved_release_version
                _materialize_distribution_licenses(context, integration, extracted_root)
                if integration.license_expression is None:
                    release_payload = _load_pypi_release_payload(project_name, resolved_release_version)
                    integration.license_expression = _infer_license_expression(release_payload.get("info", {}))
                return
            except RuntimeError as exc:
                failure = f"{archive_path.name}: {exc}"
                failures.append(failure)
                context.log(f"distribution candidate failed for {project_name} {resolved_release_version}: {failure}")

        raise RuntimeError(
            f"all compatible PyPI distribution artifacts failed for {project_name!r}"
            + (
                f" release {release_version!r}"
                if release_version is not None
                else ""
            )
            + f": {'; '.join(failures)}"
        )

    prepare_source.__name__ = f"prepare_{normalized}_source"
    return prepare_source


def _build_github_source_hook(
    integration: LibraryIntegration,
    repo: str,
    ref: str,
    ref_kind: str,
    source_mapping: dict[str, str],
    source_ignore_patterns: list[str] | None = None,
    archive_url_template: str | None = None,
) -> Hook:
    normalized_repo = _safe_cache_component(repo.replace("/", "__"))

    def prepare_source(context: LibraryHookContext) -> None:
        format_args = _version_format_args(context)
        resolved_ref = ref.format(**format_args)
        url_template = archive_url_template or GITHUB_ARCHIVE_URL_TEMPLATE
        url = url_template.format(repo=repo, ref=resolved_ref, ref_kind=ref_kind, **format_args)
        filename = Path(url.split("?", 1)[0]).name or f"{_safe_cache_component(resolved_ref)}.zip"

        archive_path = (
            context.download_cache_root
            / "github"
            / normalized_repo
            / _safe_cache_component(ref_kind)
            / _safe_cache_component(resolved_ref)
            / filename
        )
        extract_root = (
            context.work_cache_root
            / "github"
            / normalized_repo
            / _safe_cache_component(ref_kind)
            / _safe_cache_component(resolved_ref)
            / "extracted"
        )

        if not archive_path.exists():
            context.log(f"downloading {repo}@{resolved_ref} from GitHub")
            _download_file(url, archive_path)
        else:
            context.log(f"reusing cached GitHub archive {repo}@{resolved_ref}")

        extracted_root = _extract_archive(archive_path, extract_root, context.log)
        context.log(f"using GitHub source from {extracted_root}")
        _materialize_source_mapping(
            context,
            source_mapping,
            lambda selector: _resolve_source_entry(extracted_root, selector),
            source_ignore_patterns,
        )
        _materialize_distribution_licenses(context, integration, extracted_root)

    prepare_source.__name__ = f"prepare_{normalized_repo}_source"
    return prepare_source


def pypi_library(
    name: str,
    *,
    project_name: str | None = None,
    release_version: str | None = None,
    minimum_release_version: str | None = None,
    dependencies: list[str] | None = None,
    auto_resolve_dependencies: bool = True,
    source_entries: list[str] | None = None,
    source_mapping: dict[str, str] | None = None,
    source_ignore_patterns: list[str] | None = None,
    overlay_entries: list[str] | None = None,
    python_packages: list[str] | None = None,
    static_library_projects_release_x64: list[str] | None = None,
    native_static_projects: list[dict] | None = None,
    builtin_module_registrations: list[dict] | None = None,
    staged_static_libraries_release_x64: list[dict] | None = None,
    python_link_dependencies_release_x64: list[str] | None = None,
    suppressed_system_libraries_release_x64: list[str] | None = None,
    python_link_wholearchive_release_x64: list[str] | None = None,
    trusted_object_origins: list[dict] | None = None,
    top_level_import_names: list[str] | None = None,
    dependency_constraints: dict[str, str] | None = None,
    conflicts: list[str] | None = None,
    patch_rules: list[dict] | None = None,
    source_resolver: str | None = "pypi-sdist",
    resource_rules: list[dict] | None = None,
    license_expression: str | None = None,
    license_files: list[str] | None = None,
    license_sources: list[dict] | None = None,
    smoke_tests: list[dict] | None = None,
    materialized_paths: list[str] | None = None,
    cleanup_paths: list[str] | None = None,
    prepare_source_hooks: list[Hook] | None = None,
    pre_patch_hooks: list[Hook] | None = None,
    post_patch_hooks: list[Hook] | None = None,
    pre_build_hooks: list[Hook] | None = None,
) -> LibraryIntegration:
    resolved_mapping = dict(source_mapping or {})
    if source_entries:
        for entry in source_entries:
            normalized_entry = _normalized_relpath(entry)
            resolved_mapping.setdefault(normalized_entry, f"Lib/{normalized_entry}")
    if not resolved_mapping:
        raise RuntimeError(f"{name} must declare at least one source entry or source mapping")
    normalized_overlay_entries = [_normalized_relpath(entry) for entry in overlay_entries or []]

    integration = LibraryIntegration(
        name=name,
        source_provider="pypi",
        project_name=project_name or name,
        release_version=release_version,
        minimum_release_version=minimum_release_version,
        dependencies=list(dependencies or []),
        auto_resolve_dependencies=auto_resolve_dependencies,
        overlay_entries=normalized_overlay_entries,
        materialized_paths=_build_materialized_paths(
            resolved_mapping,
            normalized_overlay_entries,
            materialized_paths,
        ),
        cleanup_paths=_build_cleanup_paths(
            [
                *list(cleanup_paths or []),
                *_build_optional_source_cleanup_paths(resolved_mapping),
            ]
        ),
        python_packages=list(python_packages or [name]),
        static_library_projects_release_x64=list(static_library_projects_release_x64 or []),
        native_static_projects=list(native_static_projects or []),
        builtin_module_registrations=list(builtin_module_registrations or []),
        staged_static_libraries_release_x64=list(staged_static_libraries_release_x64 or []),
        python_link_dependencies_release_x64=list(python_link_dependencies_release_x64 or []),
        suppressed_system_libraries_release_x64=list(suppressed_system_libraries_release_x64 or []),
        python_link_wholearchive_release_x64=list(python_link_wholearchive_release_x64 or []),
        trusted_object_origins=list(trusted_object_origins or []),
        top_level_import_names=list(top_level_import_names or python_packages or [name]),
        dependency_constraints=dict(dependency_constraints or {}),
        conflicts=list(conflicts or []),
        patch_rules=list(patch_rules or []),
        source_resolver=source_resolver or "pypi-sdist",
        resource_rules=list(resource_rules or []),
        license_expression=license_expression,
        license_files=list(license_files or []),
        license_sources=list(license_sources or []),
        smoke_tests=list(smoke_tests or []),
        source_ignore_patterns=list(source_ignore_patterns or []),
        prepare_source_hooks=[],
        pre_patch_hooks=list(pre_patch_hooks or []),
        post_patch_hooks=list(post_patch_hooks or []),
        pre_build_hooks=list(pre_build_hooks or []),
    )
    integration.prepare_source_hooks = [
        _build_pypi_source_hook(integration, project_name or name, resolved_mapping, integration.source_ignore_patterns),
        *(prepare_source_hooks or []),
    ]
    return integration


def github_library(
    name: str,
    *,
    repo: str,
    ref: str,
    ref_kind: str = "tags",
    archive_url_template: str | None = None,
    minimum_release_version: str | None = None,
    dependencies: list[str] | None = None,
    auto_resolve_dependencies: bool = False,
    source_entries: list[str] | None = None,
    source_mapping: dict[str, str] | None = None,
    source_ignore_patterns: list[str] | None = None,
    overlay_entries: list[str] | None = None,
    python_packages: list[str] | None = None,
    static_library_projects_release_x64: list[str] | None = None,
    native_static_projects: list[dict] | None = None,
    builtin_module_registrations: list[dict] | None = None,
    staged_static_libraries_release_x64: list[dict] | None = None,
    python_link_dependencies_release_x64: list[str] | None = None,
    suppressed_system_libraries_release_x64: list[str] | None = None,
    python_link_wholearchive_release_x64: list[str] | None = None,
    trusted_object_origins: list[dict] | None = None,
    top_level_import_names: list[str] | None = None,
    dependency_constraints: dict[str, str] | None = None,
    conflicts: list[str] | None = None,
    patch_rules: list[dict] | None = None,
    source_resolver: str | None = "github-source",
    resource_rules: list[dict] | None = None,
    license_expression: str | None = None,
    license_files: list[str] | None = None,
    license_sources: list[dict] | None = None,
    smoke_tests: list[dict] | None = None,
    materialized_paths: list[str] | None = None,
    cleanup_paths: list[str] | None = None,
    prepare_source_hooks: list[Hook] | None = None,
    pre_patch_hooks: list[Hook] | None = None,
    post_patch_hooks: list[Hook] | None = None,
    pre_build_hooks: list[Hook] | None = None,
) -> LibraryIntegration:
    resolved_mapping = dict(source_mapping or {})
    if source_entries:
        for entry in source_entries:
            normalized_entry = _normalized_relpath(entry)
            resolved_mapping.setdefault(normalized_entry, f"Lib/{normalized_entry}")
    if not resolved_mapping:
        raise RuntimeError(f"{name} must declare at least one source entry or source mapping")
    normalized_overlay_entries = [_normalized_relpath(entry) for entry in overlay_entries or []]

    integration = LibraryIntegration(
        name=name,
        source_provider="github",
        project_name=repo,
        release_version=ref,
        minimum_release_version=minimum_release_version,
        dependencies=list(dependencies or []),
        auto_resolve_dependencies=auto_resolve_dependencies,
        overlay_entries=normalized_overlay_entries,
        materialized_paths=_build_materialized_paths(
            resolved_mapping,
            normalized_overlay_entries,
            materialized_paths,
        ),
        cleanup_paths=_build_cleanup_paths(
            [
                *list(cleanup_paths or []),
                *_build_optional_source_cleanup_paths(resolved_mapping),
            ]
        ),
        python_packages=list(python_packages or [name]),
        static_library_projects_release_x64=list(static_library_projects_release_x64 or []),
        native_static_projects=list(native_static_projects or []),
        builtin_module_registrations=list(builtin_module_registrations or []),
        staged_static_libraries_release_x64=list(staged_static_libraries_release_x64 or []),
        python_link_dependencies_release_x64=list(python_link_dependencies_release_x64 or []),
        suppressed_system_libraries_release_x64=list(suppressed_system_libraries_release_x64 or []),
        python_link_wholearchive_release_x64=list(python_link_wholearchive_release_x64 or []),
        trusted_object_origins=list(trusted_object_origins or []),
        top_level_import_names=list(top_level_import_names or python_packages or [name]),
        dependency_constraints=dict(dependency_constraints or {}),
        conflicts=list(conflicts or []),
        patch_rules=list(patch_rules or []),
        source_resolver=source_resolver or "github-source",
        resource_rules=list(resource_rules or []),
        license_expression=license_expression,
        license_files=list(license_files or []),
        license_sources=list(license_sources or []),
        smoke_tests=list(smoke_tests or []),
        source_ignore_patterns=list(source_ignore_patterns or []),
        prepare_source_hooks=[],
        pre_patch_hooks=list(pre_patch_hooks or []),
        post_patch_hooks=list(post_patch_hooks or []),
        pre_build_hooks=list(pre_build_hooks or []),
    )
    integration.prepare_source_hooks = [
        _build_github_source_hook(
            integration,
            repo,
            ref,
            ref_kind,
            resolved_mapping,
            source_ignore_patterns,
            archive_url_template,
        ),
        *(prepare_source_hooks or []),
    ]
    return integration


def _derive_source_mapping_from_overlay_entries(overlay_entries: list[str]) -> tuple[dict[str, str], list[str]]:
    derived_mapping: dict[str, str] = {}
    passthrough_overlay: list[str] = []
    for entry in overlay_entries:
        normalized = _normalized_relpath(entry)
        if normalized.startswith("Lib/"):
            derived_mapping.setdefault(normalized.removeprefix("Lib/"), normalized)
        else:
            passthrough_overlay.append(normalized)
    return derived_mapping, passthrough_overlay


def simple_library(
    name: str,
    *,
    project_name: str | None = None,
    release_version: str | None = None,
    minimum_release_version: str | None = None,
    dependencies: list[str] | None = None,
    auto_resolve_dependencies: bool | None = None,
    source_entries: list[str] | None = None,
    source_mapping: dict[str, str] | None = None,
    source_ignore_patterns: list[str] | None = None,
    overlay_entries: list[str] | None = None,
    python_packages: list[str] | None = None,
    top_level_import_names: list[str] | None = None,
    dependency_constraints: dict[str, str] | None = None,
    conflicts: list[str] | None = None,
    patch_rules: list[dict] | None = None,
    source_resolver: str | None = None,
    resource_rules: list[dict] | None = None,
    license_expression: str | None = None,
    license_files: list[str] | None = None,
    license_sources: list[dict] | None = None,
    smoke_tests: list[dict] | None = None,
    materialized_paths: list[str] | None = None,
    cleanup_paths: list[str] | None = None,
    prepare_source_hooks: list[Hook] | None = None,
    pre_patch_hooks: list[Hook] | None = None,
    post_patch_hooks: list[Hook] | None = None,
    pre_build_hooks: list[Hook] | None = None,
    source_provider: str = "pypi",
    github_repo: str | None = None,
    github_ref: str = "main",
    github_ref_kind: str = "heads",
) -> LibraryIntegration:
    derived_mapping, passthrough_overlay_entries = _derive_source_mapping_from_overlay_entries(list(overlay_entries or []))
    resolved_mapping = dict(derived_mapping)
    if source_mapping:
        resolved_mapping.update(source_mapping)

    resolved_project_name = project_name or SIMPLE_LIBRARY_PROJECT_ALIASES.get(name, name)

    common_kwargs = {
        "name": name,
        "minimum_release_version": minimum_release_version,
        "dependencies": dependencies,
        "source_entries": source_entries,
        "source_mapping": resolved_mapping,
        "source_ignore_patterns": source_ignore_patterns,
        "overlay_entries": passthrough_overlay_entries,
        "python_packages": python_packages,
        "top_level_import_names": top_level_import_names,
        "dependency_constraints": dependency_constraints,
        "conflicts": conflicts,
        "patch_rules": patch_rules,
        "source_resolver": source_resolver,
        "resource_rules": resource_rules,
        "license_expression": license_expression,
        "license_files": license_files,
        "license_sources": license_sources,
        "smoke_tests": smoke_tests,
        "materialized_paths": materialized_paths,
        "cleanup_paths": cleanup_paths,
        "prepare_source_hooks": prepare_source_hooks,
        "pre_patch_hooks": pre_patch_hooks,
        "post_patch_hooks": post_patch_hooks,
        "pre_build_hooks": pre_build_hooks,
    }
    if source_provider == "pypi":
        common_kwargs["auto_resolve_dependencies"] = True if auto_resolve_dependencies is None else auto_resolve_dependencies
        common_kwargs["release_version"] = release_version
        return pypi_library(project_name=resolved_project_name, **common_kwargs)
    if source_provider == "github":
        if not github_repo:
            raise RuntimeError(f"{name} uses source_provider='github' but github_repo is missing")
        common_kwargs["auto_resolve_dependencies"] = False if auto_resolve_dependencies is None else auto_resolve_dependencies
        return github_library(
            repo=github_repo,
            ref=github_ref,
            ref_kind=github_ref_kind,
            **common_kwargs,
        )
    raise RuntimeError(f"unsupported simple_library source provider: {source_provider!r}")


def _load_module(module_name: str, path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load integration module from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _normalize_integration(path: Path, raw: object) -> LibraryIntegration:
    if isinstance(raw, LibraryIntegration):
        return raw
    if isinstance(raw, dict):
        return LibraryIntegration(**raw)
    raise RuntimeError(f"{path} must define LIBRARY_INTEGRATION as LibraryIntegration or dict")


def _catalog_entries(library_catalog: object | None) -> list[dict]:
    if library_catalog is None:
        return []
    if isinstance(library_catalog, dict):
        entries = library_catalog.get("libraries", [])
    else:
        entries = library_catalog
    if not isinstance(entries, list):
        raise RuntimeError("library catalog must be a list or an object with a 'libraries' list")
    normalized_entries: list[dict] = []
    for index, entry in enumerate(entries):
        if not isinstance(entry, dict):
            raise RuntimeError(f"library catalog entry #{index + 1} must be an object")
        normalized_entries.append(dict(entry))
    return normalized_entries


def _integration_from_catalog_entry(entry: dict) -> LibraryIntegration:
    allowed_keys = {
        "name",
        "project_name",
        "release_version",
        "minimum_release_version",
        "dependencies",
        "auto_resolve_dependencies",
        "source_entries",
        "source_mapping",
        "source_ignore_patterns",
        "overlay_entries",
        "python_packages",
        "top_level_import_names",
        "dependency_constraints",
        "conflicts",
        "patch_rules",
        "source_resolver",
        "resource_rules",
        "license_expression",
        "license_files",
        "license_sources",
        "smoke_tests",
        "materialized_paths",
        "source_provider",
        "github_repo",
        "github_ref",
        "github_ref_kind",
        "description",
        "notes",
    }
    unknown_keys = sorted(set(entry) - allowed_keys)
    if unknown_keys:
        name = entry.get("name", "<unnamed>")
        raise RuntimeError(f"library catalog entry {name!r} has unsupported keys: {', '.join(unknown_keys)}")
    kwargs = {key: value for key, value in entry.items() if key not in {"description", "notes"}}
    if "name" not in kwargs:
        raise RuntimeError("library catalog entry is missing required key 'name'")
    return simple_library(**kwargs)


def _load_pypi_release_payload(project_name: str, release_version: str | None) -> dict:
    normalized = _normalized_project_name(project_name)
    version_key = release_version or "__latest__"
    cache_path = DOWNLOAD_CACHE_ROOT / "pypi-metadata" / normalized / f"{version_key}.json"
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))

    if release_version:
        payload = _http_get_json(PYPI_VERSION_API_URL_TEMPLATE.format(project=project_name, version=release_version))
    else:
        payload = _http_get_json(PYPI_API_URL_TEMPLATE.format(project=project_name))
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    return payload


def _integration_lookup_keys(integration: LibraryIntegration) -> list[str]:
    keys = [
        integration.name.casefold(),
        _normalized_project_name(integration.name),
        _normalized_project_name(integration.name).replace("-", "_"),
    ]
    if integration.project_name:
        keys.extend(
            [
                integration.project_name.casefold(),
                _normalized_project_name(integration.project_name),
                _normalized_project_name(integration.project_name).replace("-", "_"),
            ]
        )
    for package_name in integration.python_packages:
        keys.extend(
            [
                package_name.casefold(),
                _normalized_project_name(package_name),
                _normalized_project_name(package_name).replace("-", "_"),
            ]
        )
    return _unique(keys)


def _build_dependency_aliases(integrations: list[LibraryIntegration]) -> dict[str, str]:
    alias_to_name: dict[str, str] = {}
    for integration in integrations:
        canonical = integration.name.casefold()
        exact_keys = [
            integration.name.casefold(),
            _normalized_project_name(integration.name),
            _normalized_project_name(integration.name).replace("-", "_"),
        ]
        if integration.project_name:
            exact_keys.extend(
                [
                    integration.project_name.casefold(),
                    _normalized_project_name(integration.project_name),
                    _normalized_project_name(integration.project_name).replace("-", "_"),
                ]
            )
        for key in exact_keys:
            alias_to_name[key] = canonical
    for integration in integrations:
        canonical = integration.name.casefold()
        for key in _integration_lookup_keys(integration):
            alias_to_name.setdefault(key, canonical)
    return alias_to_name


def _resolve_dependency_name(requirement_name: str, alias_to_name: dict[str, str]) -> str | None:
    normalized = _normalized_project_name(requirement_name)
    candidates = [
        requirement_name.casefold(),
        normalized,
        normalized.replace("-", "_"),
    ]
    for candidate in candidates:
        resolved = alias_to_name.get(candidate)
        if resolved is not None:
            return resolved
    return None


def _pypi_dependency_requirements(
    integration: LibraryIntegration,
    target_version: Version,
) -> list[tuple[str, str]]:
    project_name = integration.project_name or integration.name
    effective_release_version = _effective_pypi_release_version(
        project_name,
        target_version,
        integration.release_version,
    )
    if effective_release_version is None:
        return []
    integration.release_version = effective_release_version
    payload = _load_pypi_release_payload(project_name, effective_release_version)
    info = payload.get("info", {})
    raw_requirements = info.get("requires_dist") or []
    if not raw_requirements:
        return []

    environment = _marker_environment(target_version)
    resolved: list[tuple[str, str]] = []
    for raw in raw_requirements:
        try:
            requirement = Requirement(raw)
        except InvalidRequirement:
            continue
        if requirement.marker is not None and not requirement.marker.evaluate(environment):
            continue
        resolved.append((requirement.name, str(requirement.specifier)))
    return list(dict.fromkeys(resolved))


def _integration_dependency_requirements(
    integration: LibraryIntegration,
    target_version: Version | None,
) -> list[tuple[str, str]]:
    declared_constraints: dict[str, list[str]] = {}
    constraint_names: dict[str, str] = {}
    for name, specifier in integration.dependency_constraints.items():
        key = _normalized_project_name(name)
        constraint_names.setdefault(key, name)
        if specifier:
            values = declared_constraints.setdefault(key, [])
            if specifier not in values:
                values.append(specifier)
    requirements = [
        (name, ",".join(declared_constraints.get(_normalized_project_name(name), [])))
        for name in integration.dependencies
    ]
    known_dependency_keys = {_normalized_project_name(name) for name in integration.dependencies}
    for key, name in constraint_names.items():
        if key not in known_dependency_keys:
            requirements.append((name, ",".join(declared_constraints.get(key, []))))
    if integration.auto_resolve_dependencies:
        if target_version is not None and integration.source_provider == "pypi":
            requirements.extend(_pypi_dependency_requirements(integration, target_version))
    return list(dict.fromkeys(requirements))


def _order_integrations_by_dependency(
    selected_names: list[str],
    by_name: dict[str, LibraryIntegration],
    dependency_graph: dict[str, list[str]],
) -> list[LibraryIntegration]:
    catalog_order = {name: index for index, name in enumerate(by_name)}
    reachable: set[str] = set()

    def collect(name: str) -> None:
        if name in reachable:
            return
        reachable.add(name)
        for dependency in dependency_graph.get(name, []):
            collect(dependency)

    for selected_name in selected_names:
        collect(selected_name)

    # Python package metadata may contain legitimate dependency cycles.  For
    # example, Beautiful Soup depends on Soup Sieve while Soup Sieve imports
    # Beautiful Soup at module initialization.  Pack descriptors are all
    # registered before Python starts, so order strongly connected components
    # dependency-first and keep members of a cycle in stable catalog order.
    next_index = 0
    indices: dict[str, int] = {}
    lowlinks: dict[str, int] = {}
    stack: list[str] = []
    on_stack: set[str] = set()
    components: list[list[str]] = []

    def strong_connect(name: str) -> None:
        nonlocal next_index
        indices[name] = next_index
        lowlinks[name] = next_index
        next_index += 1
        stack.append(name)
        on_stack.add(name)

        for dependency in dependency_graph.get(name, []):
            if dependency not in reachable:
                continue
            if dependency not in indices:
                strong_connect(dependency)
                lowlinks[name] = min(lowlinks[name], lowlinks[dependency])
            elif dependency in on_stack:
                lowlinks[name] = min(lowlinks[name], indices[dependency])

        if lowlinks[name] != indices[name]:
            return
        component: list[str] = []
        while True:
            member = stack.pop()
            on_stack.remove(member)
            component.append(member)
            if member == name:
                break
        component.sort(key=catalog_order.__getitem__)
        components.append(component)

    for name in sorted(reachable, key=catalog_order.__getitem__):
        if name not in indices:
            strong_connect(name)

    component_by_name = {
        name: component_index
        for component_index, component in enumerate(components)
        for name in component
    }
    ordered_components: list[int] = []
    visited_components: set[int] = set()

    def visit_component(component_index: int) -> None:
        if component_index in visited_components:
            return
        visited_components.add(component_index)
        dependency_components: list[int] = []
        for name in components[component_index]:
            for dependency in dependency_graph.get(name, []):
                dependency_component = component_by_name[dependency]
                if dependency_component != component_index:
                    dependency_components.append(dependency_component)
        for dependency_component in dict.fromkeys(dependency_components):
            visit_component(dependency_component)
        ordered_components.append(component_index)

    for selected_name in selected_names:
        visit_component(component_by_name[selected_name])

    return [
        by_name[name]
        for component_index in ordered_components
        for name in components[component_index]
    ]


def _select_compatible_pypi_release_version(
    integration: LibraryIntegration,
    target_version: Version,
    constraint: SpecifierSet,
) -> str:
    project_name = integration.project_name or integration.name
    for raw_version, _file_info in _iter_pypi_distribution_candidates(project_name, target_version, None):
        try:
            candidate = Version(raw_version)
        except InvalidVersion:
            continue
        if candidate in constraint:
            return raw_version
    raise RuntimeError(
        f"no buildable stable source release of {integration.name!r} satisfies {constraint} "
        f"for target Python {target_version}"
    )


def _resolve_selected_integrations(
    integrations: list[LibraryIntegration],
    selected_libraries: str | list[str] | tuple[str, ...] | set[str],
    *,
    target_version: Version | None,
) -> list[LibraryIntegration]:
    by_name = {integration.name.casefold(): integration for integration in integrations}
    alias_to_name = _build_dependency_aliases(integrations)
    if selected_libraries == "all":
        selected_names = [integration.name.casefold() for integration in integrations]
    else:
        if not isinstance(selected_libraries, (list, tuple, set)):
            raise RuntimeError('library selection must be "all" or a list of integration names')
        selected_names = [str(name).casefold() for name in selected_libraries]
        missing = sorted(set(selected_names) - set(by_name))
        if missing:
            raise RuntimeError("unknown libraries in config: " + ", ".join(missing))

    declared_dependencies = {
        name: list(integration.dependencies)
        for name, integration in by_name.items()
    }
    declared_constraints = {
        name: dict(integration.dependency_constraints)
        for name, integration in by_name.items()
    }
    release_version_pinned = {
        name: integration.release_version is not None
        for name, integration in by_name.items()
    }

    for _round in range(len(integrations) + 2):
        for name, integration in by_name.items():
            integration.dependencies = list(declared_dependencies[name])
            integration.dependency_constraints = dict(declared_constraints[name])

        dependency_graph: dict[str, list[str]] = {}
        resolved_selected: set[str] = set()
        stack = list(dict.fromkeys(selected_names))
        while stack:
            name = stack.pop()
            if name in resolved_selected:
                continue
            integration = by_name[name]
            dependencies: list[str] = []
            dependency_constraints: dict[str, list[str]] = {}
            for dependency_name, raw_specifier in _integration_dependency_requirements(integration, target_version):
                dependency_key = _resolve_dependency_name(dependency_name, alias_to_name)
                if dependency_key is None or dependency_key not in by_name:
                    continue
                dependencies.append(dependency_key)
                if raw_specifier:
                    values = dependency_constraints.setdefault(by_name[dependency_key].name, [])
                    if raw_specifier not in values:
                        values.append(raw_specifier)
                if dependency_key not in resolved_selected:
                    stack.append(dependency_key)
            dependency_graph[name] = list(dict.fromkeys(dependencies))
            integration.dependencies = [by_name[key].name for key in dependency_graph[name]]
            integration.dependency_constraints = {
                dependency_name: ",".join(specifiers)
                for dependency_name, specifiers in dependency_constraints.items()
            }
            resolved_selected.add(name)

        constraints_by_dependency: dict[str, list[tuple[str, str]]] = {}
        for name in sorted(resolved_selected):
            integration = by_name[name]
            for dependency_name, raw_specifier in integration.dependency_constraints.items():
                dependency_key = _resolve_dependency_name(dependency_name, alias_to_name)
                if dependency_key is None or dependency_key not in resolved_selected or not raw_specifier:
                    continue
                constraints_by_dependency.setdefault(dependency_key, []).append(
                    (integration.name, raw_specifier)
                )

        changed = False
        for dependency_key, requirements in sorted(constraints_by_dependency.items()):
            dependency = by_name[dependency_key]
            specifiers = [raw_specifier for _owner, raw_specifier in requirements]
            if dependency.minimum_release_version:
                specifiers.append(f">={dependency.minimum_release_version}")
            constraint_text = ",".join(specifiers)
            try:
                constraint = SpecifierSet(constraint_text)
                current_version = (
                    Version(dependency.release_version)
                    if dependency.release_version is not None
                    else None
                )
            except (InvalidSpecifier, InvalidVersion) as exc:
                raise RuntimeError(
                    f"invalid combined dependency constraint for {dependency.name!r}: {constraint_text!r}"
                ) from exc
            if current_version is not None and current_version in constraint:
                continue
            owners = ", ".join(owner for owner, _specifier in requirements)
            if release_version_pinned[dependency_key]:
                raise RuntimeError(
                    f"{owners} require {dependency.name}{constraint}, "
                    f"but pinned version {dependency.release_version} is selected"
                )
            if target_version is None or dependency.source_provider != "pypi":
                raise RuntimeError(
                    f"cannot resolve {dependency.name}{constraint} for dependencies of {owners}"
                )
            selected_version = _select_compatible_pypi_release_version(
                dependency,
                target_version,
                constraint,
            )
            if dependency.release_version != selected_version:
                dependency.release_version = selected_version
                changed = True
        if not changed:
            break
    else:
        raise RuntimeError("dependency version resolution did not converge")

    for name in sorted(resolved_selected):
        integration = by_name[name]
        for conflict in integration.conflicts:
            conflict_key = _resolve_dependency_name(conflict, alias_to_name)
            if conflict_key in resolved_selected:
                raise RuntimeError(
                    f"library conflict: {integration.name!r} cannot be selected with {by_name[conflict_key].name!r}"
                )
        for dependency_name, raw_specifier in integration.dependency_constraints.items():
            dependency_key = _resolve_dependency_name(dependency_name, alias_to_name)
            if dependency_key is None or dependency_key not in resolved_selected:
                continue
            dependency = by_name[dependency_key]
            if dependency.release_version is None:
                raise RuntimeError(
                    f"cannot validate {integration.name!r} dependency constraint for {dependency.name!r}: "
                    "the dependency version is not pinned"
                )
            try:
                constraint = SpecifierSet(raw_specifier)
                dependency_version = Version(dependency.release_version)
            except (InvalidSpecifier, InvalidVersion) as exc:
                raise RuntimeError(
                    f"invalid dependency constraint {dependency_name!r}: {raw_specifier!r}"
                ) from exc
            if dependency_version not in constraint:
                raise RuntimeError(
                    f"{integration.name!r} requires {dependency.name}{raw_specifier}, "
                    f"but {dependency.release_version} is selected"
                )

    ordered = _order_integrations_by_dependency(
        [name for name in selected_names if name in resolved_selected],
        by_name,
        dependency_graph,
    )
    ordered_names = {integration.name.casefold() for integration in ordered}
    for name in sorted(resolved_selected):
        if name in ordered_names:
            continue
        for integration in _order_integrations_by_dependency([name], by_name, dependency_graph):
            key = integration.name.casefold()
            if key in ordered_names:
                continue
            ordered.append(integration)
            ordered_names.add(key)
    return ordered


def select_integrations(
    integrations: list[LibraryIntegration],
    selected_libraries: str | list[str] | tuple[str, ...] | set[str],
) -> list[LibraryIntegration]:
    return _resolve_selected_integrations(integrations, selected_libraries, target_version=None)


def _apply_version_overrides(
    integrations: list[LibraryIntegration],
    version_overrides: dict[str, str] | None,
) -> None:
    if not version_overrides:
        return
    by_name = {integration.name.casefold(): integration for integration in integrations}
    alias_to_name = _build_dependency_aliases(integrations)
    unresolved: list[str] = []
    resolved_overrides: dict[str, str] = {}
    for raw_name, raw_version in version_overrides.items():
        if not isinstance(raw_name, str):
            raise RuntimeError("library version override names must be strings")
        if not isinstance(raw_version, str):
            raise RuntimeError(f"library version override for {raw_name!r} must be a string")
        dependency_key = _resolve_dependency_name(raw_name, alias_to_name)
        if dependency_key is None or dependency_key not in by_name:
            unresolved.append(raw_name)
            continue
        resolved_overrides[dependency_key] = raw_version
    if unresolved:
        raise RuntimeError(
            "unknown libraries in library_version_overrides: " + ", ".join(sorted(unresolved))
        )
    for dependency_key, release_version in resolved_overrides.items():
        by_name[dependency_key].release_version = release_version


def load_integration_definitions(
    library_root: Path,
    *,
    version_overrides: dict[str, str] | None = None,
    library_catalog: object | None = None,
) -> list[LibraryIntegration]:
    by_name: dict[str, LibraryIntegration] = {}
    for entry in _catalog_entries(library_catalog):
        integration = _integration_from_catalog_entry(entry)
        by_name[integration.name.casefold()] = integration

    for library_dir in sorted((path for path in library_root.iterdir() if path.is_dir()), key=lambda item: item.name.casefold()):
        path = library_dir / "setup.py"
        if not path.exists():
            legacy_path = library_dir / "integration.py"
            if not legacy_path.exists():
                continue
            path = legacy_path
        module_name = f"_staticpython_library_setup_{library_dir.name}"
        module = _load_module(module_name, path)
        raw = getattr(module, "LIBRARY_INTEGRATION", None)
        if raw is None:
            raise RuntimeError(f"{path} does not define LIBRARY_INTEGRATION")
        integration = _normalize_integration(path, raw)
        by_name[integration.name.casefold()] = integration
    integrations = list(by_name.values())
    _apply_version_overrides(integrations, version_overrides)
    return integrations


def load_integrations(
    library_root: Path,
    selected_libraries: str | list[str] | None = "all",
    *,
    target_version: Version | None = None,
    version_overrides: dict[str, str] | None = None,
    library_catalog: object | None = None,
) -> list[LibraryIntegration]:
    integrations = load_integration_definitions(
        library_root,
        version_overrides=version_overrides,
        library_catalog=library_catalog,
    )
    return _resolve_selected_integrations(
        integrations,
        "all" if selected_libraries is None else selected_libraries,
        target_version=target_version,
    )


def collect_overlay_entries(integrations: list[LibraryIntegration]) -> list[str]:
    return _unique([entry for integration in integrations for entry in integration.overlay_entries])


def collect_python_packages(integrations: list[LibraryIntegration]) -> list[str]:
    return _unique([package for integration in integrations for package in integration.python_packages])


def collect_static_library_projects(integrations: list[LibraryIntegration]) -> list[str]:
    return _unique(
        [project for integration in integrations for project in integration.static_library_projects_release_x64]
    )


def collect_native_static_projects(integrations: list[LibraryIntegration]) -> list[dict]:
    projects: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for integration in integrations:
        for project in integration.native_static_projects:
            key = (project["project"], project["guid"])
            if key in seen:
                continue
            seen.add(key)
            projects.append(project)
    return projects


def collect_builtin_module_registrations(integrations: list[LibraryIntegration]) -> list[dict]:
    registrations: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for integration in integrations:
        for builtin in integration.builtin_module_registrations:
            key = (builtin["name"], builtin["pyinit"])
            if key in seen:
                continue
            seen.add(key)
            registrations.append(builtin)
    return registrations


def collect_staged_static_libraries(integrations: list[LibraryIntegration]) -> list[dict]:
    libraries: list[dict] = []
    seen: set[str] = set()
    for integration in integrations:
        for entry in integration.staged_static_libraries_release_x64:
            key = entry["target_name"]
            if key in seen:
                continue
            seen.add(key)
            libraries.append(entry)
    return libraries


def collect_python_link_dependencies(integrations: list[LibraryIntegration]) -> list[str]:
    return _unique(
        [dependency for integration in integrations for dependency in integration.python_link_dependencies_release_x64]
    )


def collect_suppressed_system_libraries(integrations: list[LibraryIntegration]) -> list[str]:
    return _unique(
        [
            library
            for integration in integrations
            for library in integration.suppressed_system_libraries_release_x64
        ]
    )


def collect_python_link_wholearchive(integrations: list[LibraryIntegration]) -> list[str]:
    return _unique(
        [library for integration in integrations for library in integration.python_link_wholearchive_release_x64]
    )


def _run_hooks(integrations: list[LibraryIntegration], context: LibraryHookContext, attr: str, label: str) -> None:
    for integration in integrations:
        for hook in getattr(integration, attr):
            context.log(f"running {integration.name} {label} hook {hook.__name__}")
            hook(context)


def _rule_matches(rule: dict, integration: LibraryIntegration, context: LibraryHookContext) -> bool:
    python_specifier = rule.get("python")
    if python_specifier:
        try:
            if Version(context.version_full) not in SpecifierSet(str(python_specifier)):
                return False
        except (InvalidSpecifier, InvalidVersion) as exc:
            raise RuntimeError(
                f"{integration.name} has invalid patch rule Python selector {python_specifier!r}"
            ) from exc
    package_specifier = rule.get("package")
    if package_specifier:
        if integration.release_version is None:
            raise RuntimeError(
                f"{integration.name} patch rule requires a pinned package version"
            )
        try:
            if Version(integration.release_version) not in SpecifierSet(str(package_specifier)):
                return False
        except (InvalidSpecifier, InvalidVersion) as exc:
            raise RuntimeError(
                f"{integration.name} has invalid patch rule package selector {package_specifier!r}"
            ) from exc
    return True


def _apply_versioned_patch_rules(integration: LibraryIntegration, context: LibraryHookContext) -> None:
    for rule_index, rule in enumerate(integration.patch_rules, start=1):
        if not isinstance(rule, dict):
            raise RuntimeError(f"{integration.name} patch rule #{rule_index} must be an object")
        if not _rule_matches(rule, integration, context):
            continue
        relative_path = rule.get("path")
        replacements = rule.get("replacements")
        if not isinstance(relative_path, str) or not relative_path:
            raise RuntimeError(f"{integration.name} patch rule #{rule_index} is missing path")
        if not isinstance(replacements, list) or not replacements:
            raise RuntimeError(f"{integration.name} patch rule #{rule_index} is missing replacements")
        path = source_path(context, relative_path)
        if not path.exists():
            raise RuntimeError(f"{integration.name} patch target does not exist: {path}")
        original = read_text_file(path)
        updated = original
        for replacement_index, replacement in enumerate(replacements, start=1):
            if not isinstance(replacement, dict):
                raise RuntimeError(
                    f"{integration.name} patch rule #{rule_index} replacement #{replacement_index} must be an object"
                )
            old = replacement.get("old")
            new = replacement.get("new")
            expected = replacement.get("count", 1)
            if not isinstance(old, str) or not isinstance(new, str) or not isinstance(expected, int) or expected < 1:
                raise RuntimeError(
                    f"{integration.name} patch rule #{rule_index} replacement #{replacement_index} is invalid"
                )
            actual = updated.count(old)
            if actual == expected:
                updated = updated.replace(old, new, expected)
                continue
            if actual == 0 and updated.count(new) >= expected:
                continue
            raise RuntimeError(
                f"{integration.name} patch anchor mismatch in {relative_path}: "
                f"expected {expected}, found {actual} for {old!r}"
            )
        if updated != original:
            path.write_text(updated, encoding="utf-8", newline="\n")
            context.log(f"applied {integration.name} strict patch rule #{rule_index} to {relative_path}")


def run_prepare_source_hooks(integrations: list[LibraryIntegration], context: LibraryHookContext) -> None:
    for integration in integrations:
        for hook in integration.prepare_source_hooks:
            context.log(f"running {integration.name} source hook {hook.__name__}")
            hook(context)
        _finalize_integration_license_metadata(context, integration)


def run_pre_patch_hooks(integrations: list[LibraryIntegration], context: LibraryHookContext) -> None:
    for integration in integrations:
        _apply_versioned_patch_rules(integration, context)
    _run_hooks(integrations, context, "pre_patch_hooks", "pre-patch")


def run_post_patch_hooks(integrations: list[LibraryIntegration], context: LibraryHookContext) -> None:
    _run_hooks(integrations, context, "post_patch_hooks", "post-patch")


def run_pre_build_hooks(integrations: list[LibraryIntegration], context: LibraryHookContext) -> None:
    _run_hooks(integrations, context, "pre_build_hooks", "pre-build")
