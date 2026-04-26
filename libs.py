from __future__ import annotations

from dataclasses import dataclass, field
import importlib.util
import json
import re
import shutil
import tarfile
import time
from pathlib import Path
from types import ModuleType
from typing import Callable
from urllib.request import Request, urlopen
from zipfile import ZipFile

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version


Hook = Callable[["LibraryHookContext"], None]
PYPI_API_URL_TEMPLATE = "https://pypi.org/pypi/{project}/json"
GITHUB_ARCHIVE_URL_TEMPLATE = "https://github.com/{repo}/archive/refs/{ref_kind}/{ref}.zip"
SOURCE_ROOT_CANDIDATES = ("", "src", "lib", "python")
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
    overlay_entries: list[str] = field(default_factory=list)
    python_packages: list[str] = field(default_factory=list)
    verification_imports: list[str] = field(default_factory=list)
    static_library_projects_release_x64: list[str] = field(default_factory=list)
    native_static_projects: list[dict] = field(default_factory=list)
    builtin_module_registrations: list[dict] = field(default_factory=list)
    staged_static_libraries_release_x64: list[dict] = field(default_factory=list)
    python_link_dependencies_release_x64: list[str] = field(default_factory=list)
    python_link_wholearchive_release_x64: list[str] = field(default_factory=list)
    verification_steps: list[dict] = field(default_factory=list)
    prepare_source_hooks: list[Hook] = field(default_factory=list)
    pre_patch_hooks: list[Hook] = field(default_factory=list)
    post_patch_hooks: list[Hook] = field(default_factory=list)
    pre_build_hooks: list[Hook] = field(default_factory=list)


def _unique(items: list[str]) -> list[str]:
    return list(dict.fromkeys(items))


def source_path(context: LibraryHookContext, relative: str) -> Path:
    return context.source_root / _normalized_relpath(relative)


def read_source_text(context: LibraryHookContext, relative: str) -> str:
    return source_path(context, relative).read_text(encoding="utf-8")


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
        original = path.read_text(encoding="utf-8")

    updated = transform(original)
    if updated == original:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(updated, encoding="utf-8", newline="\n")
    context.log(f"updated {path.relative_to(context.source_root)}")


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
    timeout: float = 240,
    skip_group: str | None = None,
) -> dict:
    step = {
        "name": name,
        "kind": "module",
        "module": module,
        "timeout": timeout,
    }
    if skip_group:
        step["skip_group"] = skip_group
    return step


def script_verification_step(
    name: str,
    script: str,
    *,
    timeout: float = 240,
    skip_group: str | None = None,
) -> dict:
    step = {
        "name": name,
        "kind": "script",
        "script": script,
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


def _copy_entry(src: Path, dst: Path) -> None:
    if dst.exists():
        if dst.is_dir() and not dst.is_symlink():
            shutil.rmtree(dst)
        else:
            dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.is_dir():
        shutil.copytree(
            src,
            dst,
            ignore=shutil.ignore_patterns(
                "__pycache__",
                "*.pyc",
                "*.pyo",
                ".git",
                ".github",
                ".gitignore",
                ".gitattributes",
                ".gitmodules",
            ),
        )
    else:
        shutil.copy2(src, dst)


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
    prerelease: list[tuple[Version, str]] = []
    for raw_version in releases:
        try:
            version = Version(raw_version)
        except InvalidVersion:
            continue
        bucket = prerelease if version.is_prerelease or version.is_devrelease else stable
        bucket.append((version, raw_version))
    stable.sort(reverse=True)
    prerelease.sort(reverse=True)
    return [raw_version for _, raw_version in [*stable, *prerelease]]


def _select_pypi_file(
    project_name: str,
    target_version: Version,
    release_version: str | None = None,
) -> tuple[str, dict]:
    payload = _http_get_json(PYPI_API_URL_TEMPLATE.format(project=project_name))
    releases = payload.get("releases", {})
    project_requires_python = payload.get("info", {}).get("requires_python")

    candidate_versions = [release_version] if release_version else _sorted_release_versions(releases)

    for raw_version in candidate_versions:
        if raw_version not in releases:
            continue
        files = releases.get(raw_version, [])
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

        if not compatible:
            continue

        for packagetype in ("sdist", "bdist_wheel"):
            for file_info in compatible:
                if file_info.get("packagetype") == packagetype and file_info.get("url"):
                    return raw_version, file_info

    if release_version is not None:
        raise RuntimeError(
            f"could not find a compatible PyPI source artifact for {project_name!r} release {release_version!r} "
            f"and target Python {target_version}"
        )
    raise RuntimeError(
        f"could not find a compatible PyPI source artifact for {project_name!r} and target Python {target_version}"
    )


def _resolve_extracted_root(destination_root: Path) -> Path:
    children = [path for path in destination_root.iterdir()]
    if len(children) == 1 and children[0].is_dir():
        return children[0]
    return destination_root


def _extract_archive(archive_path: Path, destination_root: Path) -> Path:
    if destination_root.exists():
        shutil.rmtree(destination_root)
    destination_root.mkdir(parents=True, exist_ok=True)

    suffixes = [suffix.lower() for suffix in archive_path.suffixes]
    if ".zip" in suffixes:
        with ZipFile(archive_path) as archive:
            archive.extractall(destination_root)
        return _resolve_extracted_root(destination_root)

    if any(suffix in {".tar", ".gz", ".bz2", ".xz", ".tgz"} for suffix in suffixes):
        with tarfile.open(archive_path) as archive:
            archive.extractall(destination_root)
        return _resolve_extracted_root(destination_root)

    raise RuntimeError(f"unsupported archive format: {archive_path}")


def _candidate_source_roots(extracted_root: Path) -> list[Path]:
    roots: list[Path] = []
    for rel in SOURCE_ROOT_CANDIDATES:
        candidate = extracted_root / rel if rel else extracted_root
        if candidate.exists():
            roots.append(candidate)
    return roots


def _resolve_source_entry(extracted_root: Path, selector: str) -> Path:
    normalized = selector.replace("\\", "/")
    explicit = extracted_root / normalized
    if explicit.exists():
        return explicit

    for root in _candidate_source_roots(extracted_root):
        direct = root / normalized
        if direct.exists():
            return direct

    if "/" not in normalized:
        for root in _candidate_source_roots(extracted_root):
            file_candidate = root / f"{normalized}.py"
            if file_candidate.exists():
                return file_candidate

    raise RuntimeError(f"could not resolve {selector!r} inside extracted source tree {extracted_root}")


def _materialize_source_mapping(
    context: LibraryHookContext,
    source_mapping: dict[str, str],
    resolver: Callable[[str], Path],
) -> None:
    for selector, target_rel in source_mapping.items():
        src = resolver(selector)
        dst = context.source_root / _normalized_relpath(target_rel)
        _copy_entry(src, dst)
        context.log(f"materialized {selector} -> {target_rel}")


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
    project_name: str,
    source_mapping: dict[str, str],
    release_version: str | None = None,
) -> Hook:
    normalized = _normalized_project_name(project_name)

    def prepare_source(context: LibraryHookContext) -> None:
        target_version = Version(".".join(str(part) for part in context.version_info))
        resolved_release_version, file_info = _select_pypi_file(
            project_name,
            target_version,
            release_version,
        )
        filename = file_info["filename"]
        url = file_info["url"]

        archive_path = context.download_cache_root / "pypi" / normalized / resolved_release_version / filename
        extract_root = context.work_cache_root / "pypi" / normalized / resolved_release_version / "extracted"

        if not archive_path.exists():
            context.log(f"downloading {project_name} {resolved_release_version} from PyPI")
            _download_file(url, archive_path)
        else:
            context.log(f"reusing cached {project_name} {resolved_release_version} archive")

        extracted_root = _extract_archive(archive_path, extract_root)
        context.log(f"using {project_name} {resolved_release_version} source from {extracted_root}")
        _materialize_source_mapping(
            context,
            source_mapping,
            lambda selector: _resolve_source_entry(extracted_root, selector),
        )

    prepare_source.__name__ = f"prepare_{normalized}_source"
    return prepare_source


def _build_github_source_hook(
    repo: str,
    ref: str,
    ref_kind: str,
    source_mapping: dict[str, str],
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

        extracted_root = _extract_archive(archive_path, extract_root)
        context.log(f"using GitHub source from {extracted_root}")
        _materialize_source_mapping(
            context,
            source_mapping,
            lambda selector: _resolve_source_entry(extracted_root, selector),
        )

    prepare_source.__name__ = f"prepare_{normalized_repo}_source"
    return prepare_source


def pypi_library(
    name: str,
    *,
    project_name: str | None = None,
    release_version: str | None = None,
    source_entries: list[str] | None = None,
    source_mapping: dict[str, str] | None = None,
    overlay_entries: list[str] | None = None,
    python_packages: list[str] | None = None,
    verification_imports: list[str] | None = None,
    verification_steps: list[dict] | None = None,
    static_library_projects_release_x64: list[str] | None = None,
    native_static_projects: list[dict] | None = None,
    builtin_module_registrations: list[dict] | None = None,
    staged_static_libraries_release_x64: list[dict] | None = None,
    python_link_dependencies_release_x64: list[str] | None = None,
    python_link_wholearchive_release_x64: list[str] | None = None,
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

    return LibraryIntegration(
        name=name,
        overlay_entries=[_normalized_relpath(entry) for entry in overlay_entries or []],
        python_packages=list(python_packages or [name]),
        verification_imports=list(verification_imports or []),
        static_library_projects_release_x64=list(static_library_projects_release_x64 or []),
        native_static_projects=list(native_static_projects or []),
        builtin_module_registrations=list(builtin_module_registrations or []),
        staged_static_libraries_release_x64=list(staged_static_libraries_release_x64 or []),
        python_link_dependencies_release_x64=list(python_link_dependencies_release_x64 or []),
        python_link_wholearchive_release_x64=list(python_link_wholearchive_release_x64 or []),
        verification_steps=list(verification_steps or []),
        prepare_source_hooks=[
            _build_pypi_source_hook(project_name or name, resolved_mapping, release_version),
            *(prepare_source_hooks or []),
        ],
        pre_patch_hooks=list(pre_patch_hooks or []),
        post_patch_hooks=list(post_patch_hooks or []),
        pre_build_hooks=list(pre_build_hooks or []),
    )


def github_library(
    name: str,
    *,
    repo: str,
    ref: str,
    ref_kind: str = "tags",
    archive_url_template: str | None = None,
    source_entries: list[str] | None = None,
    source_mapping: dict[str, str] | None = None,
    overlay_entries: list[str] | None = None,
    python_packages: list[str] | None = None,
    verification_imports: list[str] | None = None,
    verification_steps: list[dict] | None = None,
    static_library_projects_release_x64: list[str] | None = None,
    native_static_projects: list[dict] | None = None,
    builtin_module_registrations: list[dict] | None = None,
    staged_static_libraries_release_x64: list[dict] | None = None,
    python_link_dependencies_release_x64: list[str] | None = None,
    python_link_wholearchive_release_x64: list[str] | None = None,
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

    return LibraryIntegration(
        name=name,
        overlay_entries=[_normalized_relpath(entry) for entry in overlay_entries or []],
        python_packages=list(python_packages or [name]),
        verification_imports=list(verification_imports or []),
        static_library_projects_release_x64=list(static_library_projects_release_x64 or []),
        native_static_projects=list(native_static_projects or []),
        builtin_module_registrations=list(builtin_module_registrations or []),
        staged_static_libraries_release_x64=list(staged_static_libraries_release_x64 or []),
        python_link_dependencies_release_x64=list(python_link_dependencies_release_x64 or []),
        python_link_wholearchive_release_x64=list(python_link_wholearchive_release_x64 or []),
        verification_steps=list(verification_steps or []),
        prepare_source_hooks=[
            _build_github_source_hook(repo, ref, ref_kind, resolved_mapping, archive_url_template),
            *(prepare_source_hooks or []),
        ],
        pre_patch_hooks=list(pre_patch_hooks or []),
        post_patch_hooks=list(post_patch_hooks or []),
        pre_build_hooks=list(pre_build_hooks or []),
    )


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
    source_entries: list[str] | None = None,
    source_mapping: dict[str, str] | None = None,
    overlay_entries: list[str] | None = None,
    python_packages: list[str] | None = None,
    verification_imports: list[str] | None = None,
    verification_steps: list[dict] | None = None,
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
        "source_entries": source_entries,
        "source_mapping": resolved_mapping,
        "overlay_entries": passthrough_overlay_entries,
        "python_packages": python_packages,
        "verification_imports": verification_imports,
        "verification_steps": verification_steps,
        "prepare_source_hooks": prepare_source_hooks,
        "pre_patch_hooks": pre_patch_hooks,
        "post_patch_hooks": post_patch_hooks,
        "pre_build_hooks": pre_build_hooks,
    }
    if source_provider == "pypi":
        return pypi_library(project_name=resolved_project_name, **common_kwargs)
    if source_provider == "github":
        if not github_repo:
            raise RuntimeError(f"{name} uses source_provider='github' but github_repo is missing")
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


def select_integrations(
    integrations: list[LibraryIntegration],
    selected_libraries: str | list[str] | tuple[str, ...] | set[str],
) -> list[LibraryIntegration]:
    if selected_libraries == "all":
        return integrations
    if not isinstance(selected_libraries, (list, tuple, set)):
        raise RuntimeError('library selection must be "all" or a list of integration names')

    selected = {str(name).casefold() for name in selected_libraries}
    by_name = {integration.name.casefold(): integration for integration in integrations}
    missing = sorted(selected - set(by_name))
    if missing:
        raise RuntimeError("unknown libraries in config: " + ", ".join(missing))
    return [integration for integration in integrations if integration.name.casefold() in selected]


def load_integrations(library_root: Path, selected_libraries: str | list[str] | None = "all") -> list[LibraryIntegration]:
    integrations: list[LibraryIntegration] = []
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
        integrations.append(_normalize_integration(path, raw))
    return select_integrations(integrations, "all" if selected_libraries is None else selected_libraries)


def collect_overlay_entries(integrations: list[LibraryIntegration]) -> list[str]:
    return _unique([entry for integration in integrations for entry in integration.overlay_entries])


def collect_python_packages(integrations: list[LibraryIntegration]) -> list[str]:
    return _unique([package for integration in integrations for package in integration.python_packages])


def collect_verification_imports(integrations: list[LibraryIntegration]) -> list[str]:
    return _unique([name for integration in integrations for name in integration.verification_imports])


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


def collect_python_link_wholearchive(integrations: list[LibraryIntegration]) -> list[str]:
    return _unique(
        [library for integration in integrations for library in integration.python_link_wholearchive_release_x64]
    )


def collect_verification_steps(integrations: list[LibraryIntegration]) -> list[dict]:
    steps: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for integration in integrations:
        for step in integration.verification_steps:
            key = (step["name"], step["kind"])
            if key in seen:
                continue
            seen.add(key)
            steps.append(step)
    return steps


def _run_hooks(integrations: list[LibraryIntegration], context: LibraryHookContext, attr: str, label: str) -> None:
    for integration in integrations:
        for hook in getattr(integration, attr):
            context.log(f"running {integration.name} {label} hook {hook.__name__}")
            hook(context)


def run_prepare_source_hooks(integrations: list[LibraryIntegration], context: LibraryHookContext) -> None:
    _run_hooks(integrations, context, "prepare_source_hooks", "source")


def run_pre_patch_hooks(integrations: list[LibraryIntegration], context: LibraryHookContext) -> None:
    _run_hooks(integrations, context, "pre_patch_hooks", "pre-patch")


def run_post_patch_hooks(integrations: list[LibraryIntegration], context: LibraryHookContext) -> None:
    _run_hooks(integrations, context, "post_patch_hooks", "post-patch")


def run_pre_build_hooks(integrations: list[LibraryIntegration], context: LibraryHookContext) -> None:
    _run_hooks(integrations, context, "pre_build_hooks", "pre-build")
