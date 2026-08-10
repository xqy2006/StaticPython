from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zlib
import xml.etree.ElementTree as ET
from pathlib import Path, PurePosixPath
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

from packaging.version import Version

from libs import (
    LibraryHookContext,
    collect_builtin_module_registrations,
    collect_native_static_projects,
    collect_overlay_entries,
    collect_python_link_dependencies,
    collect_python_link_wholearchive,
    collect_suppressed_system_libraries,
    collect_staged_static_libraries,
    collect_static_library_projects,
    load_integration_definitions,
    load_integrations,
    run_pre_build_hooks,
    run_pre_patch_hooks,
    run_prepare_source_hooks,
    run_post_patch_hooks,
)
from tools import resolve_tool_exe
from pack_evidence import (
    bind_promoted_pack_evidence,
    pack_metadata_without_verification_sha256,
    pack_payload_manifest_sha256,
)


REPO_ROOT = Path(__file__).resolve().parent
CORE_PATCH_ROOT = REPO_ROOT / "Core"
LIB_PATCH_ROOT = REPO_ROOT / "Lib"
ASSET_ROOT = REPO_ROOT / "assets" / "overlay"
DOWNLOAD_ROOT = REPO_ROOT / "downloads"
WORK_CACHE_ROOT = REPO_ROOT / ".vendor-stage"
MANIFEST_PATH = REPO_ROOT / "manifest.json"
CONFIG_PATH = REPO_ROOT / "config.json"
CPYTHON_ARCHIVE_URL_TEMPLATE = "https://github.com/python/cpython/archive/refs/tags/v{version}.zip"
CPYTHON_SOURCE_PROVENANCE_RELATIVE_PATH = Path(".staticpython-cpython-source.json")
DEFAULT_CPYTHON_VERSION = "3.13.2"
WINDOWS_RESERVED_BASENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CONIN$",
    "CONOUT$",
    *{f"COM{index}" for index in range(1, 10)},
    *{f"LPT{index}" for index in range(1, 10)},
}
PYREPL_MIN_VERSION = (3, 13, 0)
MSBUILD_NS = "http://schemas.microsoft.com/developer/msbuild/2003"
MSBUILD_RELEASE_X64_CONDITION = "'$(Configuration)|$(Platform)'=='Release|x64'"
FROZEN_DATA_SOURCE_PREFIX = "staticpython_frozen_data_"
FROZEN_DATA_SHARD_BYTES = 2 * 1024 * 1024
FROZEN_DATA_SHARD_DIGITS = 6
BASELINE_PYTHON_PROJECT_REFERENCES = {"pythoncore.vcxproj"}
PROFILE_METADATA_RELATIVE_PATH = Path("PCbuild") / "staticpython-profile.json"
STATIC_LIB_SDK_SCHEMA_VERSION = 1
STATIC_LIB_SDK_METADATA_NAME = "staticpython-static-libs.json"
STATIC_LIB_SDK_METADATA_RELATIVE_PATH = Path("metadata") / STATIC_LIB_SDK_METADATA_NAME
STATIC_LIB_SDK_PROFILE_METADATA_RELATIVE_PATH = Path("metadata") / "staticpython-profile.json"
STATIC_LIB_SDK_README_RELATIVE_PATH = Path("README.txt")
STATIC_LIB_SDK_LIBRARY_DIR_RELATIVE_PATH = Path("lib")
RUNTIME_SDK_SCHEMA_VERSION = 1
RUNTIME_SDK_METADATA_RELATIVE_PATH = Path("metadata") / "runtime-sdk.v1.json"
RUNTIME_SDK_AUDIT_RELATIVE_PATH = Path("metadata") / "symbol-audit.json"
RUNTIME_SDK_LIBRARY_DIR_RELATIVE_PATH = Path("lib")
RUNTIME_SDK_INCLUDE_DIR_RELATIVE_PATH = Path("include")
RUNTIME_SDK_FORBIDDEN_SYMBOLS = (
    "Py_Main",
    "Py_BytesMain",
    "Py_RunMain",
    "Py_SandboxMain",
)
STATICPYTHON_PACK_SCHEMA_VERSION = 1
STATICPYTHON_PACK_METADATA_NAME = "pack.json"
STATICPYTHON_PACK_SOURCE_DIR = Path("src")
STATICPYTHON_PACK_LIBRARY_DIR = Path("lib")
STATICPYTHON_PACK_RELEASE_FAMILIES = (
    ("a-f", frozenset("abcdef")),
    ("g-l", frozenset("ghijkl")),
    ("m-r", frozenset("mnopqr")),
    ("s-z", frozenset("stuvwxyz")),
)
RUNTIME_RESOURCE_MODULE_BASENAME = "_staticpython_runtime_resources"
RUNTIME_RESOURCE_MODULE_RELATIVE_PATH = Path("Lib") / f"{RUNTIME_RESOURCE_MODULE_BASENAME}.py"
RUNTIME_RESOURCE_STORE_MODULE = "_staticpython_resource_store"
RUNTIME_RESOURCE_STORE_C_RELATIVE_PATH = Path("Python") / "staticpython_resource_store.c"
RUNTIME_RESOURCE_SHARD_TEXT_BYTES = 4 * 1024 * 1024
RUNTIME_RESOURCE_SHARD_DIGITS = 6
RUNTIME_RESOURCE_PYTHON_SUFFIXES = {".py", ".pyc", ".pyo"}
RUNTIME_RESOURCE_SKIP_DIR_NAMES = {
    "__pycache__",
    ".git",
    ".github",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    "node_modules",
}
WINDOWS_SYSTEM_LIBRARY_NAMES = {
    "advapi32.lib",
    "bcrypt.lib",
    "comctl32.lib",
    "comdlg32.lib",
    "crypt32.lib",
    "d3d11.lib",
    "d2d1.lib",
    "dwmapi.lib",
    "dwrite.lib",
    "dxgi.lib",
    "gdi32.lib",
    "gdiplus.lib",
    "iphlpapi.lib",
    "kernel32.lib",
    "legacy_stdio_definitions.lib",
    "odbccp32.lib",
    "odbc32.lib",
    "ole32.lib",
    "oleaut32.lib",
    "opengl32.lib",
    "pathcch.lib",
    "pdh.lib",
    "powrprof.lib",
    "propsys.lib",
    "psapi.lib",
    "rpcrt4.lib",
    "secur32.lib",
    "shell32.lib",
    "shlwapi.lib",
    "user32.lib",
    "userenv.lib",
    "uuid.lib",
    "uxtheme.lib",
    "version.lib",
    "wbemuuid.lib",
    "winmm.lib",
    "winspool.lib",
    "wsock32.lib",
    "ws2_32.lib",
}
WINDOWS_SDK_LIBRARY_NAMES = {
    "glu32.lib",
    "imm32.lib",
    "msimg32.lib",
    "netapi32.lib",
    "oleacc.lib",
    "setupapi.lib",
    "windowscodecs.lib",
    "wininet.lib",
}

ET.register_namespace("", MSBUILD_NS)


def log(message: str) -> None:
    print(f"[staticpython-builder] {message}", flush=True)


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def load_config(path: Path = CONFIG_PATH) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    if path.resolve() == CONFIG_PATH.resolve() or not CONFIG_PATH.exists():
        return config

    base_config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for key in ("core_library_catalog", "third_party_library_catalog", "verification"):
        if key in base_config and key not in config:
            config[key] = base_config[key]
    return config


def profile_metadata_path(source_root: Path) -> Path:
    return source_root / PROFILE_METADATA_RELATIVE_PATH


def integration_names(integrations: list) -> list[str]:
    return [integration.name for integration in integrations]


def resolved_license_sources(integration) -> list[dict]:
    records: list[dict] = []
    for rule in integration.license_sources:
        record = dict(rule)
        record["url"] = str(rule["url"]).format(
            release_version=integration.release_version,
            project_name=integration.project_name or integration.name,
        )
        records.append(record)
    return records


def integration_versions(integrations: list) -> dict[str, dict]:
    payload: dict[str, dict] = {}
    for integration in integrations:
        payload[integration.name] = {
            "source_provider": integration.source_provider,
            "source_resolver": integration.source_resolver,
            "project_name": integration.project_name,
            "release_version": integration.release_version,
            "top_level_import_names": integration.top_level_import_names or integration.python_packages,
            "dependencies": integration.dependencies,
            "dependency_constraints": integration.dependency_constraints,
            "conflicts": integration.conflicts,
            "resource_rules": integration.resource_rules,
            "license_expression": integration.license_expression,
            "license_files": integration.license_files,
            "license_sources": resolved_license_sources(integration),
            "smoke_tests": integration.smoke_tests,
        }
    return payload


def write_profile_metadata(
    source_root: Path,
    profile_name: str,
    config_path: Path,
    version_full: str,
    core_integrations: list,
    third_party_integrations: list,
) -> None:
    payload = {
        "schema_version": 1,
        "profile_name": profile_name,
        "config_path": str(config_path),
        "version_full": version_full,
        "core_libraries": integration_names(core_integrations),
        "third_party_libraries": integration_names(third_party_integrations),
        "core_library_versions": integration_versions(core_integrations),
        "third_party_library_versions": integration_versions(third_party_integrations),
    }
    path = profile_metadata_path(source_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    log(f"wrote build profile metadata to {path.relative_to(source_root)}")


def static_lib_sdk_asset_name(version_full: str, platform: str, profile: str) -> str:
    return f"python-{version_full}-static-libs-{profile}-{platform.lower()}.zip"


def runtime_sdk_asset_name(version_full: str, platform: str) -> str:
    return f"staticpython-runtime-sdk-{version_full}-{platform.lower()}.zip"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_commit_or_none(path: Path) -> str | None:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=path,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        return None
    value = result.stdout.strip()
    return value or None


def resolve_cpython_tag_commit(version: str) -> str:
    tag_ref = f"refs/tags/v{version}"
    result = subprocess.run(
        ["git", "ls-remote", "https://github.com/python/cpython.git", tag_ref, f"{tag_ref}^{{}}"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        timeout=60,
    )
    if result.returncode != 0:
        raise RuntimeError(f"could not resolve CPython v{version} commit: {result.stderr.strip()}")
    direct = None
    peeled = None
    for line in result.stdout.splitlines():
        sha, separator, ref = line.partition("\t")
        if not separator or not re.fullmatch(r"[0-9a-fA-F]{40}", sha):
            continue
        if ref == f"{tag_ref}^{{}}":
            peeled = sha.lower()
        elif ref == tag_ref:
            direct = sha.lower()
    commit = peeled or direct
    if commit is None:
        raise RuntimeError(f"could not find CPython tag v{version} in python/cpython")
    return commit


def write_cpython_source_provenance(
    source_root: Path,
    *,
    version: str,
    archive_url: str,
    archive_path: Path,
    commit: str | None,
) -> None:
    payload = {
        "schema_version": 1,
        "repository": "python/cpython",
        "version": version,
        "tag": f"v{version}" if commit is not None else None,
        "commit": commit,
        "archive_url": archive_url,
        "archive_sha256": sha256_file(archive_path),
    }
    path = source_root / CPYTHON_SOURCE_PROVENANCE_RELATIVE_PATH
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")


def cpython_source_provenance(source_root: Path, version_full: str) -> dict:
    path = source_root / CPYTHON_SOURCE_PROVENANCE_RELATIVE_PATH
    if path.is_file():
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("version") != version_full:
            raise RuntimeError(
                f"CPython source provenance version {payload.get('version')!r} does not match {version_full}"
            )
        return payload
    return {
        "schema_version": 1,
        "repository": "python/cpython",
        "version": version_full,
        "tag": None,
        "commit": git_commit_or_none(source_root),
        "archive_url": None,
        "archive_sha256": None,
    }


def write_deterministic_zip(source_root: Path, destination: Path) -> None:
    """Create a byte-stable ZIP from a staged directory."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        destination.unlink()
    with ZipFile(destination, "w", compression=ZIP_DEFLATED, compresslevel=9) as archive:
        for path in sorted((item for item in source_root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
            relative = path.relative_to(source_root).as_posix()
            info = ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            info.create_system = 3
            archive.writestr(info, path.read_bytes(), compress_type=ZIP_DEFLATED, compresslevel=9)


def normalize_library_name(library_name: str) -> str:
    return Path(library_name.replace("$(PyDebugExt)", "")).name.lower()


def is_windows_system_library(library_name: str) -> bool:
    return normalize_library_name(library_name) in WINDOWS_SYSTEM_LIBRARY_NAMES


def is_windows_sdk_library(library_name: str) -> bool:
    return normalize_library_name(library_name) in WINDOWS_SDK_LIBRARY_NAMES


def is_python_host_library(library_name: str) -> bool:
    stem = Path(normalize_library_name(library_name)).stem
    return stem in {"python", "python3", "pythoncore"} or re.fullmatch(r"python\d{2,3}", stem) is not None


def is_packaged_static_library(library_name: str) -> bool:
    normalized = normalize_library_name(library_name)
    return (
        normalized.endswith(".lib")
        and normalized != "%(additionaldependencies)"
        and not is_windows_system_library(normalized)
        and not is_windows_sdk_library(normalized)
        and not is_python_host_library(normalized)
    )


def resolve_profile(config: dict, profile_name: str | None) -> tuple[str, dict]:
    profiles = config.get("profiles", {})
    selected_name = profile_name or config.get("default_profile") or "full"
    if selected_name not in profiles:
        available = ", ".join(sorted(profiles)) or "<none>"
        raise RuntimeError(f"unknown profile {selected_name!r}; available profiles: {available}")
    profile = profiles[selected_name]
    if not isinstance(profile, dict):
        raise RuntimeError(f"profile {selected_name!r} must be an object")
    return selected_name, profile


def profile_library_catalog(config: dict, profile: dict, key: str) -> object | None:
    return profile.get(key, config.get(key))


def profile_verification_config(config: dict, profile: dict) -> dict:
    root_config = config.get("verification", {})
    if root_config is None:
        root_config = {}
    if not isinstance(root_config, dict):
        raise RuntimeError("config verification must be an object")
    profile_config = profile.get("verification")
    if profile_config is None:
        return dict(root_config)
    if not isinstance(profile_config, dict):
        raise RuntimeError("profile verification must be an object")
    merged = dict(root_config)
    merged.update(profile_config)
    return merged


def project_exists(source_root: Path, project_name: str) -> bool:
    return (source_root / "PCbuild" / project_name).exists()


def iter_native_static_projects(source_root: Path, manifest: dict, integrations: list) -> list[dict]:
    available = []
    for project in [*manifest.get("native_static_projects", []), *collect_native_static_projects(integrations)]:
        if project_exists(source_root, project["project"]):
            available.append(project)
        else:
            log(f"skip native static project {project['project']} because it does not exist in this CPython version")
    return available


def all_static_library_projects(manifest: dict, integrations: list) -> list[str]:
    manifest_projects = manifest.get(
        "static_library_projects_release_x64",
        [project["project"] for project in manifest.get("native_static_projects", [])],
    )
    return list(dict.fromkeys([*manifest_projects, *collect_static_library_projects(integrations)]))


def iter_static_library_projects(source_root: Path, manifest: dict, integrations: list) -> list[str]:
    available = []
    for project in all_static_library_projects(manifest, integrations):
        if project_exists(source_root, project):
            available.append(project)
        else:
            log(f"skip static library project {project} because it does not exist in this CPython version")
    return available


def iter_patchable_static_library_projects(source_root: Path, manifest: dict, integrations: list) -> list[str]:
    custom_projects = {project["project"] for project in iter_native_static_projects(source_root, manifest, integrations)}
    return [project for project in iter_static_library_projects(source_root, manifest, integrations) if project not in custom_projects]


def static_library_project_patches(manifest: dict) -> dict:
    return manifest.get("static_library_project_patches", {})


def iter_staged_static_libraries(manifest: dict, integrations: list) -> list[dict]:
    return [
        *manifest.get("staged_static_libraries_release_x64", []),
        *collect_staged_static_libraries(integrations),
    ]


def iter_builtin_module_registrations(source_root: Path, manifest: dict, integrations: list) -> list[dict]:
    registrations = manifest.get("builtin_module_registrations")
    if registrations:
        manifest_candidates = list(registrations)
    else:
        manifest_candidates = [{"name": name, "pyinit": f"PyInit_{name}"} for name in manifest.get("python_builtin_modules", [])]
    integration_candidates = collect_builtin_module_registrations(integrations)

    available_projects = {Path(project).stem for project in iter_static_library_projects(source_root, manifest, integrations)}
    available_libraries = {
        Path(library).stem
        for library in [
            *iter_python_link_dependencies(source_root, manifest, integrations),
            *iter_python_link_wholearchive_libraries(source_root, manifest, integrations),
        ]
    }

    def builtin_is_available(builtin: dict) -> bool:
        library = builtin.get("library")
        if library and Path(library).stem in available_libraries:
            return True
        return builtin["name"] in available_projects or builtin["name"] in available_libraries

    filtered = []
    seen: set[str] = set()
    for builtin in manifest_candidates:
        if builtin_is_available(builtin):
            filtered.append(builtin)
            seen.add(builtin["name"])
        else:
            log(
                f"skip builtin registration {builtin['name']} because the corresponding project is unavailable "
                "in this CPython version"
            )
    for builtin in integration_candidates:
        if builtin["name"] in seen:
            continue
        if not builtin_is_available(builtin):
            log(
                f"skip builtin registration {builtin['name']} because the corresponding integration project is unavailable "
                "in this CPython version"
            )
            continue
        filtered.append(builtin)
        seen.add(builtin["name"])
    return filtered


def render_project_reference(project: dict) -> str:
    return (
        f'    <ProjectReference Include="{project["project"]}">\n'
        f'      <Project>{project["guid"]}</Project>\n'
        "      <ReferenceOutputAssembly>false</ReferenceOutputAssembly>\n"
        "    </ProjectReference>\n"
    )


def read_project_guid(project_path: Path) -> str:
    text = project_path.read_text(encoding="utf-8")
    match = re.search(r"<ProjectGuid>\s*({[^}]+})\s*</ProjectGuid>", text, flags=re.IGNORECASE)
    if not match:
        raise RuntimeError(f"could not find ProjectGuid in {project_path}")
    return match.group(1)


def msbuild_tag(name: str) -> str:
    return f"{{{MSBUILD_NS}}}{name}"


def load_msbuild_project(path: Path) -> tuple[ET.ElementTree, ET.Element]:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(path, parser=parser)
    root = tree.getroot()
    if root.tag != msbuild_tag("Project"):
        raise RuntimeError(f"{path} is not an MSBuild project")
    return tree, root


def save_msbuild_project(path: Path, tree: ET.ElementTree) -> None:
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _matches_condition(element: ET.Element, condition: str | None) -> bool:
    actual = element.get("Condition")
    if condition is None:
        return actual is None
    return actual == condition


def find_direct_child(parent: ET.Element, tag: str, *, condition: str | None = None) -> ET.Element | None:
    qname = msbuild_tag(tag)
    for child in parent:
        if child.tag != qname:
            continue
        if _matches_condition(child, condition):
            return child
    return None


def find_direct_children(parent: ET.Element, tag: str, *, condition: str | None = None) -> list[ET.Element]:
    qname = msbuild_tag(tag)
    return [child for child in parent if child.tag == qname and _matches_condition(child, condition)]


def ensure_direct_child(parent: ET.Element, tag: str, *, condition: str | None = None) -> ET.Element:
    child = find_direct_child(parent, tag, condition=condition)
    if child is not None:
        return child
    child = ET.Element(msbuild_tag(tag))
    if condition is not None:
        child.set("Condition", condition)
    parent.append(child)
    return child


def set_frozen_data_compile_options(clcompile: ET.Element) -> None:
    include_dirs = ensure_direct_child(clcompile, "AdditionalIncludeDirectories")
    include_dirs.text = "$(GeneratedFrozenModulesDir)Python;%(AdditionalIncludeDirectories)"
    # Frozen module headers are giant byte arrays. They do not benefit from
    # LTCG, and letting them participate in /GL can exhaust MSVC/link heap once
    # large pure-Python packages are frozen into the executable.
    additional_options = ensure_direct_child(
        clcompile,
        "AdditionalOptions",
        condition=MSBUILD_RELEASE_X64_CONDITION,
    )
    additional_options.text = "/bigobj /GL- %(AdditionalOptions)"
    optimization = ensure_direct_child(
        clcompile,
        "Optimization",
        condition=MSBUILD_RELEASE_X64_CONDITION,
    )
    optimization.text = "Disabled"
    inline_expansion = ensure_direct_child(
        clcompile,
        "InlineFunctionExpansion",
        condition=MSBUILD_RELEASE_X64_CONDITION,
    )
    inline_expansion.text = "Disabled"
    whole_program_optimization = ensure_direct_child(
        clcompile,
        "WholeProgramOptimization",
        condition=MSBUILD_RELEASE_X64_CONDITION,
    )
    whole_program_optimization.text = "false"
    debug_information = ensure_direct_child(
        clcompile,
        "DebugInformationFormat",
        condition=MSBUILD_RELEASE_X64_CONDITION,
    )
    debug_information.text = "None"


def _insert_before_predicate(root: ET.Element, element: ET.Element, predicate: callable) -> None:
    for index, child in enumerate(list(root)):
        if predicate(child):
            root.insert(index, element)
            return
    root.append(element)


def _is_targets_import(element: ET.Element) -> bool:
    return element.tag == msbuild_tag("Import") and element.get("Project") == r"$(VCTargetsPath)\Microsoft.Cpp.targets"


def ensure_property_group(root: ET.Element, *, label: str | None = None) -> ET.Element:
    for child in root:
        if child.tag != msbuild_tag("PropertyGroup"):
            continue
        if label is None:
            if child.get("Label") is None and child.get("Condition") is None:
                return child
            continue
        if child.get("Label") == label:
            return child
    group = ET.Element(msbuild_tag("PropertyGroup"))
    if label is not None:
        group.set("Label", label)
    _insert_before_predicate(
        root,
        group,
        lambda child: child.tag in {msbuild_tag("ItemDefinitionGroup"), msbuild_tag("ItemGroup")} or _is_targets_import(child),
    )
    return group


def ensure_item_definition_group(root: ET.Element, *, condition: str | None = None) -> ET.Element:
    for child in root:
        if child.tag != msbuild_tag("ItemDefinitionGroup"):
            continue
        if _matches_condition(child, condition):
            return child
    group = ET.Element(msbuild_tag("ItemDefinitionGroup"))
    if condition is not None:
        group.set("Condition", condition)
    _insert_before_predicate(root, group, lambda child: child.tag == msbuild_tag("ItemGroup") or _is_targets_import(child))
    return group


def ensure_item_group_with_tag(root: ET.Element, tag: str) -> ET.Element:
    qname = msbuild_tag(tag)
    for child in root:
        if child.tag != msbuild_tag("ItemGroup"):
            continue
        if any(grandchild.tag == qname for grandchild in child):
            return child
    group = ET.Element(msbuild_tag("ItemGroup"))
    _insert_before_predicate(root, group, _is_targets_import)
    return group


def iter_item_definition_clcompile_nodes(root: ET.Element) -> list[ET.Element]:
    nodes: list[ET.Element] = []
    for group in find_direct_children(root, "ItemDefinitionGroup"):
        for child in group:
            if child.tag == msbuild_tag("ClCompile"):
                nodes.append(child)
    return nodes


def iter_item_definition_link_nodes(root: ET.Element) -> list[ET.Element]:
    nodes: list[ET.Element] = []
    for group in find_direct_children(root, "ItemDefinitionGroup"):
        for child in group:
            if child.tag == msbuild_tag("Link"):
                nodes.append(child)
    return nodes


def merge_msbuild_semicolon_list(current: str | None, additions: list[str], placeholder: str) -> str:
    tokens = [token for token in (current or "").split(";") if token]
    has_placeholder = placeholder in tokens
    tokens = [token for token in tokens if token != placeholder]
    for token in additions:
        if token not in tokens:
            tokens.append(token)
    if has_placeholder or not tokens or placeholder:
        tokens.append(placeholder)
    return ";".join(tokens)


def ensure_clcompile_preprocessor_token(root: ET.Element, token: str) -> None:
    clcompile_nodes = [node for node in iter_item_definition_clcompile_nodes(root) if any(child.tag == msbuild_tag("PreprocessorDefinitions") for child in node)]
    if not clcompile_nodes:
        clcompile = ensure_direct_child(ensure_item_definition_group(root), "ClCompile")
        preprocessor = ensure_direct_child(clcompile, "PreprocessorDefinitions")
        preprocessor.text = merge_msbuild_semicolon_list(preprocessor.text, [token], "%(PreprocessorDefinitions)")
        return

    for clcompile in clcompile_nodes:
        for child in find_direct_children(clcompile, "PreprocessorDefinitions"):
            child.text = merge_msbuild_semicolon_list(child.text, [token], "%(PreprocessorDefinitions)")


def ensure_release_x64_runtime_library(root: ET.Element) -> None:
    target = None
    for clcompile in iter_item_definition_clcompile_nodes(root):
        matching = find_direct_children(clcompile, "RuntimeLibrary", condition=MSBUILD_RELEASE_X64_CONDITION)
        for child in matching[1:]:
            clcompile.remove(child)
        for child in matching[:1]:
            if child.get("Condition") == MSBUILD_RELEASE_X64_CONDITION:
                child.text = "MultiThreaded"
                return
        if target is None:
            target = clcompile

    if target is None:
        target = ensure_direct_child(ensure_item_definition_group(root), "ClCompile")
    runtime = ET.Element(msbuild_tag("RuntimeLibrary"))
    runtime.set("Condition", MSBUILD_RELEASE_X64_CONDITION)
    runtime.text = "MultiThreaded"
    target.append(runtime)


def ensure_link_child_text(
    root: ET.Element,
    tag: str,
    text: str,
    *,
    condition: str | None = None,
) -> None:
    link_nodes = iter_item_definition_link_nodes(root)
    if not link_nodes:
        link_nodes = [ensure_direct_child(ensure_item_definition_group(root), "Link")]

    existing = None
    for link in link_nodes:
        candidate = find_direct_child(link, tag, condition=condition)
        if candidate is not None:
            existing = candidate
            break
    if existing is None:
        existing = ensure_direct_child(link_nodes[0], tag, condition=condition)
    existing.text = text


def remove_redundant_release_x64_link_groups(root: ET.Element) -> None:
    for group in list(find_direct_children(root, "ItemDefinitionGroup", condition=MSBUILD_RELEASE_X64_CONDITION)):
        non_comment_children = [child for child in list(group) if isinstance(child.tag, str)]
        if len(non_comment_children) != 1 or non_comment_children[0].tag != msbuild_tag("Link"):
            continue
        link = non_comment_children[0]
        child_tags = {child.tag for child in list(link) if isinstance(child.tag, str)}
        allowed = {msbuild_tag("AdditionalDependencies"), msbuild_tag("AdditionalOptions")}
        if child_tags and child_tags.issubset(allowed):
            root.remove(group)


def ensure_vcpkg_property_group(root: ET.Element) -> None:
    group = ensure_property_group(root, label="Vcpkg")
    enabled = ensure_direct_child(group, "VcpkgEnabled")
    enabled.text = "false"


def ensure_project_reference(root: ET.Element, project_name: str, guid: str) -> None:
    qname = msbuild_tag("ProjectReference")
    for item_group in find_direct_children(root, "ItemGroup"):
        for project_ref in item_group:
            if project_ref.tag == qname and project_ref.get("Include") == project_name:
                project = ensure_direct_child(project_ref, "Project")
                project.text = guid
                reference = ensure_direct_child(project_ref, "ReferenceOutputAssembly")
                reference.text = "false"
                return

    item_group = ensure_item_group_with_tag(root, "ProjectReference")
    project_ref = ET.SubElement(item_group, qname)
    project_ref.set("Include", project_name)
    project = ET.SubElement(project_ref, msbuild_tag("Project"))
    project.text = guid
    reference = ET.SubElement(project_ref, msbuild_tag("ReferenceOutputAssembly"))
    reference.text = "false"


def sync_python_project_references(root: ET.Element, desired_projects: list[dict]) -> None:
    allowed = {project["project"] for project in desired_projects}
    allowed.update(BASELINE_PYTHON_PROJECT_REFERENCES)
    qname = msbuild_tag("ProjectReference")

    for item_group in list(find_direct_children(root, "ItemGroup")):
        removed = False
        for project_ref in list(item_group):
            if project_ref.tag != qname:
                continue
            if project_ref.get("Include") in allowed:
                continue
            item_group.remove(project_ref)
            removed = True

        if removed and not any(isinstance(child.tag, str) for child in item_group):
            root.remove(item_group)


def iter_python_link_dependencies(source_root: Path, manifest: dict, integrations: list) -> list[str]:
    all_project_stems = {Path(project).stem for project in all_static_library_projects(manifest, integrations)}
    available_project_stems = {Path(project).stem for project in iter_static_library_projects(source_root, manifest, integrations)}
    dependencies = []
    combined = list(
        dict.fromkeys([*manifest["python_link_dependencies_release_x64"], *collect_python_link_dependencies(integrations)])
    )
    suppressed = {
        normalize_library_name(name)
        for name in collect_suppressed_system_libraries(integrations)
    }
    invalid_suppressions = sorted(
        name
        for name in suppressed
        if not is_windows_system_library(name) and not is_windows_sdk_library(name)
    )
    if invalid_suppressions:
        raise RuntimeError(
            "link suppressions may only name Windows system libraries: "
            + ", ".join(invalid_suppressions)
        )
    if (source_root / "PCbuild" / "zlib-ng.vcxproj").exists():
        combined.append("zlib-ng$(PyDebugExt).lib")
    for dependency in combined:
        if normalize_library_name(dependency) in suppressed:
            log(f"suppress python system link dependency {dependency}")
            continue
        stem = Path(dependency).stem
        if dependency.lower().endswith(".lib") and stem in all_project_stems and stem not in available_project_stems:
            log(
                f"skip python link dependency {dependency} because project {stem}.vcxproj is unavailable "
                "in this CPython version"
            )
            continue
        dependencies.append(dependency)
    return dependencies


def build_python_link_dependencies(source_root: Path, manifest: dict, integrations: list) -> str:
    dependencies = iter_python_link_dependencies(source_root, manifest, integrations)
    return ";".join([*dependencies, "%(AdditionalDependencies)"])


def iter_python_link_wholearchive_libraries(source_root: Path, manifest: dict, integrations: list) -> list[str]:
    all_project_stems = {Path(project).stem for project in all_static_library_projects(manifest, integrations)}
    available_project_stems = {Path(project).stem for project in iter_static_library_projects(source_root, manifest, integrations)}
    wholearchive = []
    combined = list(
        dict.fromkeys([*manifest.get("python_link_wholearchive_release_x64", []), *collect_python_link_wholearchive(integrations)])
    )
    for library in combined:
        stem = Path(library).stem
        if stem in all_project_stems and stem not in available_project_stems:
            log(
                f"skip link option /WHOLEARCHIVE:{library} because project {stem}.vcxproj is unavailable "
                "in this CPython version"
            )
            continue
        wholearchive.append(library)
    return wholearchive


def build_python_link_options(source_root: Path, manifest: dict, integrations: list) -> str:
    wholearchive = iter_python_link_wholearchive_libraries(source_root, manifest, integrations)
    prefixes = [f"/WHOLEARCHIVE:{name}" for name in wholearchive]
    prefixes.append("%(AdditionalOptions)")
    return " ".join(prefixes)


def try_relative_to(path: Path, root: Path) -> Path | None:
    try:
        return path.relative_to(root)
    except ValueError:
        return None


def display_path(path: Path, root: Path) -> str:
    relative = try_relative_to(path, root)
    if relative is not None:
        return relative.as_posix()
    return str(path)


def library_search_roots(source_root: Path, platform: str) -> list[Path]:
    roots: list[Path] = []
    for candidate in (
        get_pcbuild_output_dir(source_root, platform),
        source_root / "PCbuild",
        source_root / "externals",
    ):
        if not candidate.exists():
            continue
        if any(candidate == existing for existing in roots):
            continue
        roots.append(candidate)
    return roots


def library_candidate_sort_key(source_root: Path, platform: str, path: Path) -> tuple[int, int, int, str]:
    relative = try_relative_to(path, source_root)
    relative_text = relative.as_posix().lower() if relative is not None else str(path).lower()
    parts = [part.lower() for part in relative.parts] if relative is not None else [part.lower() for part in path.parts]
    outdir_parts = ["pcbuild", platform_output_dir_name(platform).lower()]
    if parts[:2] == outdir_parts:
        bucket = 0
    elif parts[:1] == ["externals"]:
        bucket = 1
    elif parts[:1] == ["pcbuild"]:
        bucket = 2
    else:
        bucket = 3
    return (bucket, len(parts), len(relative_text), relative_text)


def index_library_files(source_root: Path, platform: str) -> dict[str, list[Path]]:
    indexed: dict[str, list[Path]] = {}
    seen_paths: set[str] = set()
    for root in library_search_roots(source_root, platform):
        for path in root.rglob("*.lib"):
            key = str(path.resolve())
            if key in seen_paths:
                continue
            seen_paths.add(key)
            indexed.setdefault(path.name.lower(), []).append(path)
    for candidates in indexed.values():
        candidates.sort(key=lambda item: library_candidate_sort_key(source_root, platform, item))
    return indexed


def collect_static_lib_sdk_library_specs(source_root: Path, platform: str, manifest: dict, integrations: list) -> list[dict]:
    specs: list[dict] = []
    by_name: dict[str, dict] = {}

    def add_library(library_name: str, reason: str) -> None:
        normalized = normalize_library_name(library_name)
        if not is_packaged_static_library(normalized):
            return
        record = by_name.get(normalized)
        if record is None:
            record = {"logical_name": normalized, "reasons": []}
            by_name[normalized] = record
            specs.append(record)
        if reason not in record["reasons"]:
            record["reasons"].append(reason)

    for dependency in iter_python_link_dependencies(source_root, manifest, integrations):
        add_library(dependency, "link_dependency")
    for library in iter_python_link_wholearchive_libraries(source_root, manifest, integrations):
        add_library(library, "wholearchive")
    for project in iter_static_library_projects(source_root, manifest, integrations):
        add_library(f"{Path(project).stem}.lib", "static_library_project")
    for entry in iter_staged_static_libraries(manifest, integrations):
        target_name = entry.get("target_name")
        if isinstance(target_name, str):
            add_library(target_name, "staged_static_library")

    return specs


def resolve_static_lib_sdk_records(
    source_root: Path,
    platform: str,
    manifest: dict,
    integrations: list,
) -> list[dict]:
    library_index = index_library_files(source_root, platform)
    records: list[dict] = []
    missing: list[str] = []
    skipped_link_only: list[str] = []

    for spec in collect_static_lib_sdk_library_specs(source_root, platform, manifest, integrations):
        logical_name = spec["logical_name"]
        candidates = library_index.get(logical_name, [])
        if not candidates:
            reasons = set(spec["reasons"])
            if reasons.issubset({"link_dependency", "wholearchive"}):
                skipped_link_only.append(logical_name)
                continue
            missing.append(logical_name)
            continue
        source_path = candidates[0]
        records.append(
            {
                "logical_name": logical_name,
                "archive_path": (STATIC_LIB_SDK_LIBRARY_DIR_RELATIVE_PATH / logical_name).as_posix(),
                "source_name": source_path.name,
                "source_relative_path": display_path(source_path, source_root),
                "reasons": list(spec["reasons"]),
                "source_path": source_path,
            }
        )

    if skipped_link_only:
        preview = ", ".join(skipped_link_only[:12])
        suffix = " ..." if len(skipped_link_only) > 12 else ""
        log(
            "skip static library SDK export for unresolved link-only libraries that do not have packaged build "
            f"artifacts: {preview}{suffix}"
        )

    if missing:
        preview = ", ".join(missing[:12])
        suffix = " ..." if len(missing) > 12 else ""
        raise RuntimeError(
            "could not locate built static library file(s) required for SDK export: "
            f"{preview}{suffix}"
        )

    return records


def static_lib_sdk_metadata_path(root: Path) -> Path:
    return root / STATIC_LIB_SDK_METADATA_RELATIVE_PATH


def load_static_lib_sdk_metadata(root: Path) -> dict:
    path = static_lib_sdk_metadata_path(root)
    if not path.exists():
        raise RuntimeError(f"static library SDK metadata not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def write_static_lib_sdk_readme(destination: Path, version_full: str, platform: str, profile_name: str) -> None:
    lines = [
        "StaticPython native static library SDK",
        "",
        f"CPython version: {version_full}",
        f"Platform: {platform}",
        f"Source profile: {profile_name}",
        "",
        "This package contains prebuilt native .lib files for StaticPython.",
        "pythoncore/python.exe are intentionally not included.",
        "",
        "You must still build your own CPython source tree locally so StaticPython can:",
        "- regenerate frozen modules",
        "- regenerate runtime resource data",
        "- relink python.exe/pythoncore for your chosen library set",
        "",
        "Typical reuse flow:",
        "python .\\build.py <source_root> --profile <profile> --prebuilt-static-lib-sdk <this zip or extracted dir>",
        "",
        "build.py will install these .lib files into PCbuild output and skip rebuilding the packaged native static libraries.",
    ]
    path = destination / STATIC_LIB_SDK_README_RELATIVE_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def export_static_library_sdk(
    source_root: Path,
    output_dir: Path,
    version_full: str,
    platform: str,
    profile_name: str,
    manifest: dict,
    integrations: list,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = resolve_static_lib_sdk_records(source_root, platform, manifest, integrations)
    filtered_link_dependencies = [
        normalize_library_name(name)
        for name in iter_python_link_dependencies(source_root, manifest, integrations)
        if is_packaged_static_library(name)
    ]
    filtered_wholearchive = [
        normalize_library_name(name)
        for name in iter_python_link_wholearchive_libraries(source_root, manifest, integrations)
        if is_packaged_static_library(name)
    ]
    metadata = {
        "schema_version": STATIC_LIB_SDK_SCHEMA_VERSION,
        "version_full": version_full,
        "platform": platform,
        "profile_name": profile_name,
        "packaged_link_dependencies_release_x64": list(dict.fromkeys(filtered_link_dependencies)),
        "packaged_link_wholearchive_release_x64": list(dict.fromkeys(filtered_wholearchive)),
        "builtin_module_registrations": iter_builtin_module_registrations(source_root, manifest, integrations),
        "static_library_projects_release_x64": iter_static_library_projects(source_root, manifest, integrations),
        "libraries": [
            {
                "logical_name": record["logical_name"],
                "archive_path": record["archive_path"],
                "source_name": record["source_name"],
                "source_relative_path": record["source_relative_path"],
                "reasons": record["reasons"],
            }
            for record in records
        ],
    }

    destination = output_dir / static_lib_sdk_asset_name(version_full, platform, profile_name)
    if destination.exists():
        destination.unlink()

    with tempfile.TemporaryDirectory(prefix="staticpython-static-libs-export-") as temp_dir:
        staging_root = Path(temp_dir)
        library_dir = staging_root / STATIC_LIB_SDK_LIBRARY_DIR_RELATIVE_PATH
        library_dir.mkdir(parents=True, exist_ok=True)

        for record in records:
            shutil.copy2(record["source_path"], library_dir / record["logical_name"])

        metadata_path = staging_root / STATIC_LIB_SDK_METADATA_RELATIVE_PATH
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

        profile_path = profile_metadata_path(source_root)
        if profile_path.exists():
            copied_profile_path = staging_root / STATIC_LIB_SDK_PROFILE_METADATA_RELATIVE_PATH
            copied_profile_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(profile_path, copied_profile_path)

        write_static_lib_sdk_readme(staging_root, version_full, platform, profile_name)

        archive_base = destination.with_suffix("")
        archive_path = shutil.make_archive(str(archive_base), "zip", root_dir=staging_root)
        if Path(archive_path) != destination:
            shutil.move(archive_path, destination)

    log(f"copied static library SDK to {destination}")
    return destination


def _runtime_sdk_library_records(
    source_root: Path,
    platform: str,
    version_info: tuple[int, int, int],
    manifest: dict,
    integrations: list,
) -> list[dict]:
    records = resolve_static_lib_sdk_records(source_root, platform, manifest, integrations)
    by_name = {record["logical_name"]: record for record in records}
    output_dir = get_pcbuild_output_dir(source_root, platform)
    required = [
        (f"python{version_info[0]}{version_info[1]}.lib", "cpython_core"),
        ("staticpython_runtime.lib", "pack_runtime"),
    ]
    for logical_name, reason in required:
        normalized = logical_name.lower()
        if normalized in by_name:
            if reason not in by_name[normalized]["reasons"]:
                by_name[normalized]["reasons"].append(reason)
            continue
        source_path = output_dir / logical_name
        if not source_path.exists():
            raise RuntimeError(f"runtime SDK build did not produce required library: {source_path}")
        record = {
            "logical_name": normalized,
            "archive_path": (RUNTIME_SDK_LIBRARY_DIR_RELATIVE_PATH / normalized).as_posix(),
            "source_name": source_path.name,
            "source_relative_path": display_path(source_path, source_root),
            "reasons": [reason],
            "source_path": source_path,
        }
        records.append(record)
        by_name[normalized] = record
    return records


def audit_runtime_sdk(
    source_root: Path,
    version_info: tuple[int, int, int],
    platform: str,
) -> dict:
    project_path = source_root / "PCbuild" / "pythoncore.vcxproj"
    tree, root = load_msbuild_project(project_path)
    compiled_sources = [
        (node.get("Include") or "").replace("/", "\\")
        for node in root.iter(msbuild_tag("ClCompile"))
    ]
    forbidden_sources = [
        source for source in compiled_sources
        if source.casefold() == "..\\modules\\main.c"
    ]

    frozen_path = source_root / "Python" / "frozen.c"
    frozen_text = frozen_path.read_text(encoding="utf-8", errors="replace")
    idle_entries = sorted(set(re.findall(r'"(idlelib(?:\.[^"]*)?)"', frozen_text)))

    core_path = get_pcbuild_output_dir(source_root, platform) / f"python{version_info[0]}{version_info[1]}.lib"
    if not core_path.exists():
        raise RuntimeError(f"runtime SDK core library is missing: {core_path}")
    dumpbin = resolve_tool_exe("dumpbin")
    result = subprocess.run(
        [dumpbin, "/NOLOGO", "/LINKERMEMBER:1", str(core_path)],
        cwd=source_root,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"dumpbin failed while auditing {core_path}:\n{result.stdout[-4000:]}")
    symbols = result.stdout
    forbidden_symbols = [
        symbol for symbol in RUNTIME_SDK_FORBIDDEN_SYMBOLS
        if re.search(rf"(?<![A-Za-z0-9_]){re.escape(symbol)}(?![A-Za-z0-9_])", symbols)
    ]
    main_objects = sorted(set(re.findall(r"(?im)^.*\bmain\.obj\b.*$", symbols)))
    report = {
        "schema_version": 1,
        "status": "passed",
        "core_library": display_path(core_path, source_root),
        "pythoncore_compiled_sources": compiled_sources,
        "forbidden_sources": forbidden_sources,
        "forbidden_symbols": forbidden_symbols,
        "main_object_records": main_objects,
        "idlelib_frozen_entries": idle_entries,
        "dumpbin_sha256": hashlib.sha256(symbols.encode("utf-8")).hexdigest(),
    }
    failures = [
        ("Modules/main.c remains in pythoncore", forbidden_sources),
        ("generic Python entry symbols remain in pythoncore", forbidden_symbols),
        ("main.obj remains in pythoncore", main_objects),
        ("idlelib remains in the frozen module registry", idle_entries),
    ]
    active_failures = [f"{label}: {values[:8]}" for label, values in failures if values]
    if active_failures:
        report["status"] = "failed"
        raise RuntimeError("runtime SDK audit failed:\n" + "\n".join(active_failures))
    return report


def runtime_frozen_module_names(source_root: Path) -> list[str]:
    """Return the modules actually linked into the runtime SDK frozen tables."""
    frozen_path = source_root / "Python" / "frozen.c"
    text = frozen_path.read_text(encoding="utf-8", errors="replace")
    names: set[str] = set()
    for table_name, sentinel in (
        ("bootstrap_modules", "bootstrap sentinel"),
        ("stdlib_modules", "stdlib sentinel"),
    ):
        pattern = re.compile(
            rf"static const struct _frozen\s+{table_name}\[\]\s*=\s*\{{"
            rf"(?P<body>.*?)\/\*\s*{re.escape(sentinel)}\s*\*\/",
            re.DOTALL,
        )
        match = pattern.search(text)
        if match is None:
            raise RuntimeError(f"could not locate {table_name} in {frozen_path}")
        for name in re.findall(r'^\s*\{"([^"]+)"\s*,', match.group("body"), re.MULTILINE):
            if name:
                names.add(name)
    alias_pattern = re.compile(
        r"const struct _module_alias\s+aliases\[\]\s*=\s*\{"
        r"(?P<body>.*?)\/\*\s*aliases sentinel\s*\*\/",
        re.DOTALL,
    )
    alias_match = alias_pattern.search(text)
    if alias_match is not None:
        names.update(
            name
            for name in re.findall(r'^\s*\{"([^"]+)"\s*,', alias_match.group("body"), re.MULTILINE)
            if name
        )
    return sorted(names, key=str.casefold)


def runtime_builtin_module_names(source_root: Path) -> list[str]:
    """Return the exact names registered in the target CPython inittab."""
    config_path = source_root / "PC" / "config.c"
    text = config_path.read_text(encoding="utf-8", errors="replace")
    table = re.search(
        r"struct\s+_inittab\s+_PyImport_Inittab\s*\[\s*\]\s*=\s*\{",
        text,
    )
    if table is None:
        raise RuntimeError(f"could not locate _PyImport_Inittab in {config_path}")
    tail = text[table.end():]
    sentinel = re.search(
        r"^\s*\{\s*(?:0|NULL)\s*,\s*(?:0|NULL)\s*\}\s*,?",
        tail,
        re.MULTILINE,
    )
    if sentinel is None:
        raise RuntimeError(f"could not locate _PyImport_Inittab sentinel in {config_path}")
    names = {
        name
        for name in re.findall(r'^\s*\{\s*"([^"]+)"\s*,', tail[:sentinel.start()], re.MULTILINE)
        if name
    }
    if not names:
        raise RuntimeError(f"_PyImport_Inittab contains no modules in {config_path}")
    return sorted(names, key=str.casefold)


def resolve_runtime_sdk_pyconfig_header(source_root: Path, platform: str) -> Path:
    candidates = [
        get_pcbuild_output_dir(source_root, platform) / "pyconfig.h",
        source_root / "PC" / "pyconfig.h",
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    rendered = "\n".join(f"- {candidate}" for candidate in candidates)
    raise RuntimeError(
        "runtime SDK build did not produce a usable pyconfig.h; checked:\n"
        + rendered
    )


def export_runtime_sdk(
    source_root: Path,
    output_dir: Path,
    version_info: tuple[int, int, int],
    version_full: str,
    platform: str,
    profile_name: str,
    manifest: dict,
    integrations: list,
) -> Path:
    if profile_name != "runtime-sdk":
        raise RuntimeError("runtime SDK export requires the runtime-sdk profile")
    output_dir.mkdir(parents=True, exist_ok=True)
    records = _runtime_sdk_library_records(source_root, platform, version_info, manifest, integrations)
    audit = audit_runtime_sdk(source_root, version_info, platform)
    destination = output_dir / runtime_sdk_asset_name(version_full, platform)

    with tempfile.TemporaryDirectory(prefix="staticpython-runtime-sdk-export-") as temp_dir:
        staging_root = Path(temp_dir)
        library_dir = staging_root / RUNTIME_SDK_LIBRARY_DIR_RELATIVE_PATH
        include_dir = staging_root / RUNTIME_SDK_INCLUDE_DIR_RELATIVE_PATH
        library_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_root / "Include", include_dir, dirs_exist_ok=True)
        shutil.copy2(resolve_runtime_sdk_pyconfig_header(source_root, platform), include_dir / "pyconfig.h")
        for record in records:
            shutil.copy2(record["source_path"], library_dir / record["logical_name"])

        licenses_dir = staging_root / "licenses"
        licenses_dir.mkdir(parents=True, exist_ok=True)
        license_sources = [
            (source_root / "LICENSE", "CPython-LICENSE.txt"),
            (REPO_ROOT / "LICENSE", "StaticPython-LICENSE.txt"),
            (REPO_ROOT / "NOTICE", "StaticPython-NOTICE.txt"),
            (REPO_ROOT / "THIRD_PARTY_NOTICES.md", "THIRD_PARTY_NOTICES.md"),
        ]
        for source, target_name in license_sources:
            if source.exists():
                shutil.copy2(source, licenses_dir / target_name)

        audit_path = staging_root / RUNTIME_SDK_AUDIT_RELATIVE_PATH
        audit_path.parent.mkdir(parents=True, exist_ok=True)
        audit_path.write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")

        profile_path = profile_metadata_path(source_root)
        if profile_path.exists():
            profile_target = staging_root / "metadata" / "staticpython-profile.json"
            profile_target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(profile_path, profile_target)

        link_dependencies = iter_python_link_dependencies(source_root, manifest, integrations)
        system_libraries = [
            normalize_library_name(name)
            for name in link_dependencies
            if is_windows_system_library(name) or is_windows_sdk_library(name)
        ]
        packaged_libraries = [record["logical_name"] for record in records]
        core_library = f"python{version_info[0]}{version_info[1]}.lib"
        ordered_libraries = [
            "staticpython_runtime.lib",
            *[
                normalize_library_name(name)
                for name in link_dependencies
                if is_packaged_static_library(name)
            ],
            core_library,
        ]
        ordered_libraries = [name for name in dict.fromkeys(ordered_libraries) if name in packaged_libraries]

        file_records = []
        for path in sorted((item for item in staging_root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
            relative = path.relative_to(staging_root).as_posix()
            file_records.append({
                "path": relative,
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            })
        cpython_source = cpython_source_provenance(source_root, version_full)
        builtin_registrations = iter_builtin_module_registrations(source_root, manifest, integrations)
        builtin_module_names = runtime_builtin_module_names(source_root)
        frozen_module_names = runtime_frozen_module_names(source_root)
        stdlib_top_level_import_names = sorted(
            {
                name.split(".", 1)[0]
                for name in [
                    *frozen_module_names,
                    *builtin_module_names,
                    *(registration["name"] for registration in builtin_registrations),
                ]
                if name
            },
            key=str.casefold,
        )
        metadata = {
            "schema_version": RUNTIME_SDK_SCHEMA_VERSION,
            "kind": "staticpython-runtime-sdk",
            "runtime_abi": f"staticpython-pack-v1-cp{version_info[0]}{version_info[1]}",
            "cpython_version": version_full,
            "cpython_abi": f"cp{version_info[0]}{version_info[1]}",
            "platform": platform.lower(),
            "profile_name": profile_name,
            "staticpython_commit": git_commit_or_none(REPO_ROOT),
            "cpython_commit": cpython_source.get("commit"),
            "cpython_tag": cpython_source.get("tag"),
            "cpython_source": cpython_source,
            "toolchain": {
                "visual_studio_version": os.environ.get("VisualStudioVersion"),
                "vscmd_version": os.environ.get("VSCMD_VER"),
                "vc_tools_version": os.environ.get("VCToolsVersion"),
                "windows_sdk_version": os.environ.get("WindowsSDKVersion"),
                "platform_toolset": "v143",
                "runtime_library": "MultiThreaded",
            },
            "base_pack_symbol": "StaticPython_BaseResourcePackV1",
            "pack_registration_function": "StaticPython_RegisterPacks",
            "include_directory": RUNTIME_SDK_INCLUDE_DIR_RELATIVE_PATH.as_posix(),
            "library_directory": RUNTIME_SDK_LIBRARY_DIR_RELATIVE_PATH.as_posix(),
            "core_library": core_library,
            "runtime_library": "staticpython_runtime.lib",
            "link_libraries": ordered_libraries,
            "system_libraries": list(dict.fromkeys(system_libraries)),
            "builtin_module_registrations": builtin_registrations,
            "builtin_module_names": builtin_module_names,
            "frozen_module_names": frozen_module_names,
            "stdlib_top_level_import_names": stdlib_top_level_import_names,
            "libraries": [
                {
                    "logical_name": record["logical_name"],
                    "archive_path": record["archive_path"],
                    "reasons": record["reasons"],
                }
                for record in records
            ],
            "verification": {
                "status": audit["status"],
                "symbol_audit": RUNTIME_SDK_AUDIT_RELATIVE_PATH.as_posix(),
                "generic_executable_published": False,
            },
            "files": file_records,
        }
        metadata_path = staging_root / RUNTIME_SDK_METADATA_RELATIVE_PATH
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
        (staging_root / "README.txt").write_text(
            "StaticPython runtime SDK for PySuture\n\n"
            f"CPython: {version_full} ({metadata['cpython_abi']})\n"
            f"Runtime ABI: {metadata['runtime_abi']}\n"
            "This SDK contains no generic python.exe, REPL, IDLE, or script runner.\n"
            "Call StaticPython_RegisterPacks before Py_InitializeFromConfig.\n",
            encoding="utf-8",
            newline="\n",
        )
        write_deterministic_zip(staging_root, destination)

    log(f"copied runtime SDK to {destination}")
    return destination


def _pack_slug(value: str) -> str:
    slug = re.sub(r"[^0-9A-Za-z_.-]+", "-", value).strip("-.").lower()
    if not slug:
        raise RuntimeError(f"could not derive a safe pack name from {value!r}")
    return slug


def staticpython_pack_release_family(name: str) -> str:
    first = name[:1].casefold()
    for family, initials in STATICPYTHON_PACK_RELEASE_FAMILIES:
        if first in initials:
            return family
    return "other"


def _c_identifier(value: str) -> str:
    identifier = re.sub(r"[^0-9A-Za-z_]", "_", value)
    if not identifier or identifier[0].isdigit():
        identifier = "_" + identifier
    return identifier


def staticpython_pack_asset_name(
    name: str,
    version: str,
    version_info: tuple[int, int, int],
    platform: str,
) -> str:
    return (
        f"staticpython-pack-{_pack_slug(name)}-{_pack_slug(version)}-"
        f"cp{version_info[0]}{version_info[1]}-{platform.lower()}.zip"
    )


def _integration_frozen_modules(source_root: Path, integration) -> list[dict]:
    builtin_names = {
        registration.get("name")
        for registration in integration.builtin_module_registrations
        if isinstance(registration, dict) and isinstance(registration.get("name"), str)
    }
    prefixes = [
        name
        for name in integration.python_packages
        if isinstance(name, str) and name and name not in builtin_names
    ]
    frozen_dir = source_root / "Python" / "frozen_modules"
    records: list[dict] = []
    for header in sorted(frozen_dir.glob("*.h"), key=lambda path: path.name.casefold()):
        module_name = header.stem
        if not any(module_name == prefix or module_name.startswith(prefix + ".") for prefix in prefixes):
            continue
        symbol, size = parse_frozen_header_info(header)
        module_path = source_root / "Lib" / Path(*module_name.split("."))
        records.append({
            "name": module_name,
            "symbol": symbol,
            "size": size,
            "is_package": (module_path / "__init__.py").exists(),
            "header": header,
        })
    if prefixes and not records:
        raise RuntimeError(
            f"no frozen modules were found for {integration.name}: {', '.join(prefixes)}"
        )
    return records


def _integration_native_libraries(source_root: Path, platform: str, integration) -> tuple[list[dict], list[str], list[str]]:
    logical_names: list[str] = []
    wholearchive = [normalize_library_name(name) for name in integration.python_link_wholearchive_release_x64]
    combined = [
        *integration.python_link_dependencies_release_x64,
        *[f"{Path(project).stem}.lib" for project in integration.static_library_projects_release_x64],
        *[
            entry["target_name"]
            for entry in integration.staged_static_libraries_release_x64
            if isinstance(entry, dict) and isinstance(entry.get("target_name"), str)
        ],
    ]
    system_libraries: list[str] = []
    for name in combined:
        normalized = normalize_library_name(name)
        if is_windows_system_library(normalized) or is_windows_sdk_library(normalized):
            system_libraries.append(normalized)
        elif is_packaged_static_library(normalized):
            logical_names.append(normalized)
    logical_names = list(dict.fromkeys(logical_names))
    index = index_library_files(source_root, platform)
    records: list[dict] = []
    missing: list[str] = []
    for logical_name in logical_names:
        candidates = index.get(logical_name, [])
        if not candidates:
            missing.append(logical_name)
            continue
        records.append({
            "logical_name": logical_name,
            "source_path": candidates[0],
            "archive_path": (STATICPYTHON_PACK_LIBRARY_DIR / logical_name).as_posix(),
        })
    if missing:
        raise RuntimeError(
            f"could not locate native libraries for pack {integration.name}: {', '.join(missing)}"
        )
    return records, list(dict.fromkeys(wholearchive)), list(dict.fromkeys(system_libraries))


def _integration_suppressed_system_libraries(integration) -> list[str]:
    suppressed = [
        normalize_library_name(name)
        for name in integration.suppressed_system_libraries_release_x64
    ]
    invalid = sorted(
        name
        for name in suppressed
        if not is_windows_system_library(name) and not is_windows_sdk_library(name)
    )
    if invalid:
        raise RuntimeError(
            f"pack {integration.name} suppresses non-system libraries: "
            + ", ".join(invalid)
        )
    return list(dict.fromkeys(suppressed))


def _integration_trusted_object_origins(
    integration,
    native_records: list[dict],
) -> list[dict]:
    declarations = integration.trusted_object_origins
    if not isinstance(declarations, list):
        raise RuntimeError(f"pack {integration.name} trusted_object_origins must be a list")
    owned_libraries = {
        record["logical_name"].casefold(): record["logical_name"]
        for record in native_records
    }
    origins: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for declaration in declarations:
        if not isinstance(declaration, dict) or set(declaration) != {"library", "object"}:
            raise RuntimeError(
                f"pack {integration.name} trusted object origins must contain only library and object"
            )
        library = declaration.get("library")
        object_name = declaration.get("object")
        if (
            not isinstance(library, str)
            or re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.+-]*\.lib", library, re.IGNORECASE) is None
        ):
            raise RuntimeError(f"pack {integration.name} has an invalid trusted object library: {library!r}")
        owned_library = owned_libraries.get(library.casefold())
        if owned_library is None:
            raise RuntimeError(
                f"pack {integration.name} trusted object library is not owned by the pack: {library}"
            )
        if not isinstance(object_name, str) or object_name.casefold() != "main.obj":
            raise RuntimeError(
                f"pack {integration.name} trusted object must currently be the exact basename main.obj"
            )
        key = (owned_library.casefold(), "main.obj")
        if key in seen:
            raise RuntimeError(
                f"pack {integration.name} repeats trusted object origin {owned_library}(main.obj)"
            )
        seen.add(key)
        origins.append({"library": owned_library, "object": "main.obj"})
    return origins


def _integration_source_hash(source_root: Path, integration) -> tuple[str, list[dict]]:
    hasher = hashlib.sha256()
    records: list[dict] = []
    paths: list[Path] = []
    for relative in integration.materialized_paths:
        target = source_root / relative
        if target.is_file():
            paths.append(target)
        elif target.is_dir():
            paths.extend(path for path in target.rglob("*") if path.is_file())
    for path in sorted(set(paths), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(source_root).as_posix()
        digest = sha256_file(path)
        hasher.update(relative.encode("utf-8"))
        hasher.update(b"\0")
        hasher.update(digest.encode("ascii"))
        hasher.update(b"\n")
        records.append({"path": relative, "sha256": digest, "size": path.stat().st_size})
    return hasher.hexdigest(), records


def _integration_license_files(source_root: Path, integration) -> tuple[list[Path], str]:
    candidates: list[Path] = []
    if integration.license_files:
        for relative in integration.license_files:
            path = source_root / relative
            if not path.is_file():
                raise RuntimeError(f"declared license file for {integration.name} is missing: {path}")
            candidates.append(path)
    else:
        license_prefixes = ("license", "copying", "notice", "copyright")
        for relative in integration.materialized_paths:
            root = source_root / relative
            if root.is_file():
                root = root.parent
            if not root.is_dir():
                continue
            for path in root.rglob("*"):
                if path.is_file() and path.name.casefold().startswith(license_prefixes) and path.stat().st_size <= 2 * 1024 * 1024:
                    candidates.append(path)
    unique = sorted(set(candidates), key=lambda item: item.as_posix().casefold())
    expression = integration.license_expression
    complete = bool(unique and expression and not expression.casefold().startswith("licenseref-unresolved"))
    return unique, "complete" if complete else "missing"


def _write_pack_descriptor_source(
    staging_root: Path,
    integration,
    version_info: tuple[int, int, int],
    frozen_records: list[dict],
    resource_records: list[dict],
    native_records: list[dict],
    system_libraries: list[str],
) -> str:
    source_dir = staging_root / STATICPYTHON_PACK_SOURCE_DIR
    frozen_dir = source_dir / "frozen"
    source_dir.mkdir(parents=True, exist_ok=True)
    frozen_dir.mkdir(parents=True, exist_ok=True)
    for record in frozen_records:
        shutil.copy2(record["header"], frozen_dir / record["header"].name)

    include_lines = [f'#include "frozen/{record["header"].name}"' for record in frozen_records]
    frozen_lines = [
        "    STATICPYTHON_FROZEN_ENTRY("
        f"{_c_bytes_literal(record['name'])}, {record['symbol']}, {record['size']}, "
        f"{1 if record['is_package'] else 0}),"
        for record in frozen_records
    ]
    builtin_lines = []
    builtin_externs = []
    for registration in integration.builtin_module_registrations:
        builtin_externs.append(f"extern PyObject *{registration['pyinit']}(void);")
        builtin_lines.append(
            f"    {{{_c_bytes_literal(registration['name'])}, {registration['pyinit']}}},"
        )

    resource_lines = []
    for record in resource_records:
        resource_lines.append(
            "    {"
            f"{_c_bytes_literal(record['path'])}, NULL, NULL, {record['symbol']}, "
            f"{record['compressed_size']}, {record['size']}, STATICPYTHON_RESOURCE_ZLIB"
            "},"
        )
    dependency_lines = [f"    {_c_bytes_literal(name)}," for name in integration.dependencies]
    library_lines = [f"    {_c_bytes_literal(record['logical_name'])}," for record in native_records]
    system_lines = [f"    {_c_bytes_literal(name)}," for name in system_libraries]
    symbol = f"StaticPython_Pack_{_c_identifier(integration.name)}"

    def array_or_dummy(lines: list[str], dummy: str) -> str:
        return "\n".join(lines or [f"    {dummy},"])

    descriptor = source_dir / "pack.c"
    descriptor.write_text(
        "/* Auto-generated by StaticPython. SPDX-License-Identifier: Apache-2.0 */\n"
        "#include \"Python.h\"\n"
        "#include \"staticpython_pack.h\"\n\n"
        + ("\n".join(include_lines) + "\n\n" if include_lines else "")
        + ("\n".join(builtin_externs) + "\n\n" if builtin_externs else "")
        + "#if PY_VERSION_HEX < 0x030D0000\n"
        + "#  define STATICPYTHON_FROZEN_ENTRY(name, code, size, package) {name, code, size, package, NULL}\n"
        + "#else\n"
        + "#  define STATICPYTHON_FROZEN_ENTRY(name, code, size, package) {name, code, size, package}\n"
        + "#endif\n\n"
        + "#define STATICPYTHON_STRINGIFY_INNER(value) #value\n"
        + "#define STATICPYTHON_STRINGIFY(value) STATICPYTHON_STRINGIFY_INNER(value)\n"
        + "#define STATICPYTHON_CPYTHON_ABI \\\n"
        + "    \"cp\" STATICPYTHON_STRINGIFY(PY_MAJOR_VERSION) STATICPYTHON_STRINGIFY(PY_MINOR_VERSION)\n\n"
        + "static const StaticPythonFrozenModuleV1 staticpython_frozen_modules[] = {\n"
        + array_or_dummy(frozen_lines, "{0}")
        + "\n};\n\n"
        + "static const StaticPythonBuiltinModuleV1 staticpython_builtin_modules[] = {\n"
        + array_or_dummy(builtin_lines, "{0}")
        + "\n};\n\n"
        + "static const StaticPythonResourceV1 staticpython_resources[] = {\n"
        + array_or_dummy(resource_lines, "{0}")
        + "\n};\n\n"
        + "static const char *const staticpython_dependencies[] = {\n"
        + array_or_dummy(dependency_lines, "NULL")
        + "\n};\n\n"
        + "static const char *const staticpython_link_libraries[] = {\n"
        + array_or_dummy(library_lines, "NULL")
        + "\n};\n\n"
        + "static const char *const staticpython_system_libraries[] = {\n"
        + array_or_dummy(system_lines, "NULL")
        + "\n};\n\n"
        + f"const StaticPythonPackV1 {symbol} = {{\n"
        + "    sizeof(StaticPythonPackV1),\n"
        + "    STATICPYTHON_PACK_ABI_VERSION,\n"
        + f"    {_c_bytes_literal(integration.name)},\n"
        + f"    {_c_bytes_literal(integration.release_version)},\n"
        + "    STATICPYTHON_CPYTHON_ABI,\n"
        + f"    staticpython_frozen_modules, {len(frozen_records)},\n"
        + f"    staticpython_builtin_modules, {len(builtin_lines)},\n"
        + f"    staticpython_resources, {len(resource_records)},\n"
        + f"    staticpython_dependencies, {len(dependency_lines)},\n"
        + f"    staticpython_link_libraries, {len(library_lines)},\n"
        + f"    staticpython_system_libraries, {len(system_lines)},\n"
        + "    NULL\n"
        + "};\n",
        encoding="utf-8",
        newline="\n",
    )
    return symbol


def export_library_pack(
    source_root: Path,
    output_dir: Path,
    version_info: tuple[int, int, int],
    version_full: str,
    platform: str,
    integration,
    *,
    verification_status: str = "not-run",
    verification_report: dict | None = None,
) -> Path:
    if integration.release_version is None:
        raise RuntimeError(f"pack {integration.name} does not have a resolved release version")
    frozen_records = _integration_frozen_modules(source_root, integration)
    native_records, wholearchive, system_libraries = _integration_native_libraries(source_root, platform, integration)
    suppressed_system_libraries = _integration_suppressed_system_libraries(integration)
    trusted_object_origins = _integration_trusted_object_origins(integration, native_records)
    resource_files = collect_runtime_resource_files(source_root, [integration])
    source_tree_hash, source_file_records = _integration_source_hash(source_root, integration)
    license_files, license_status = _integration_license_files(source_root, integration)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / staticpython_pack_asset_name(
        integration.name,
        integration.release_version,
        version_info,
        platform,
    )

    with tempfile.TemporaryDirectory(prefix=f"staticpython-pack-{_pack_slug(integration.name)}-") as temp_dir:
        staging_root = Path(temp_dir)
        pack_symbol_prefix = _c_identifier(integration.name)
        library_dir = staging_root / STATICPYTHON_PACK_LIBRARY_DIR
        library_dir.mkdir(parents=True, exist_ok=True)
        for record in native_records:
            shutil.copy2(record["source_path"], library_dir / record["logical_name"])

        resource_records: list[dict] = []
        resource_source_dir = staging_root / STATICPYTHON_PACK_SOURCE_DIR / "resources"
        resource_source_dir.mkdir(parents=True, exist_ok=True)
        for index, (relative, path) in enumerate(sorted(resource_files.items()), start=1):
            payload = path.read_bytes()
            compressed = zlib.compress(payload, level=9)
            symbol = (
                f"staticpython_pack_{pack_symbol_prefix}_resource_"
                f"{index:06d}_{hashlib.sha256(payload).hexdigest()[:16]}"
            )
            values = [str(value) for value in compressed]
            rows = ["    " + ", ".join(values[offset : offset + 24]) + "," for offset in range(0, len(values), 24)]
            resource_path = resource_source_dir / f"resource_{index:06d}.c"
            resource_path.write_text(
                "/* Auto-generated by StaticPython. */\n"
                "#include <stddef.h>\n\n"
                f"const unsigned char {symbol}[] = {{\n"
                + ("\n".join(rows) if rows else "    0,")
                + "\n};\n",
                encoding="utf-8",
                newline="\n",
            )
            resource_records.append({
                "path": relative,
                "symbol": symbol,
                "size": len(payload),
                "compressed_size": len(compressed),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "source": resource_path.relative_to(staging_root).as_posix(),
            })

        descriptor_symbol = _write_pack_descriptor_source(
            staging_root,
            integration,
            version_info,
            frozen_records,
            resource_records,
            native_records,
            system_libraries,
        )
        descriptor_path = staging_root / STATICPYTHON_PACK_SOURCE_DIR / "pack.c"
        descriptor_text = descriptor_path.read_text(encoding="utf-8")
        extern_lines = [f"extern const unsigned char {record['symbol']}[];" for record in resource_records]
        if extern_lines:
            descriptor_text = descriptor_text.replace(
                '#include "staticpython_pack.h"\n',
                '#include "staticpython_pack.h"\n\n' + "\n".join(extern_lines) + "\n",
                1,
            )
            descriptor_path.write_text(descriptor_text, encoding="utf-8", newline="\n")

        licenses_dir = staging_root / "licenses"
        licenses_dir.mkdir(parents=True, exist_ok=True)
        license_records = []
        used_names: set[str] = set()
        license_source_records: dict[tuple[str, str], tuple[Path, str]] = {}
        for source in license_files:
            digest = sha256_file(source)
            license_source_records.setdefault(
                (source.name.casefold(), digest),
                (source, digest),
            )
        for source, digest in sorted(
            license_source_records.values(),
            key=lambda record: (record[0].name.casefold(), record[1]),
        ):
            name = source.name
            if name.casefold() in used_names:
                name = f"{digest[:12]}-{name}"
            used_names.add(name.casefold())
            target = licenses_dir / name
            shutil.copy2(source, target)
            license_records.append(target.relative_to(staging_root).as_posix())

        artifact_files = []
        for path in sorted((item for item in staging_root.rglob("*") if item.is_file()), key=lambda item: item.as_posix()):
            artifact_files.append({
                "path": path.relative_to(staging_root).as_posix(),
                "size": path.stat().st_size,
                "sha256": sha256_file(path),
            })
        cpython_source = cpython_source_provenance(source_root, version_full)
        smoke_test_records = []
        if isinstance(verification_report, dict):
            for record in verification_report.get("integration_smoke_tests", []):
                if not isinstance(record, dict) or record.get("integration") != integration.name:
                    continue
                smoke_test_records.append({
                    key: record[key]
                    for key in ("name", "kind", "status", "skip_group")
                    if key in record
                })
        pack_verification_evidence: dict[str, str] = {}
        if (
            verification_status == "passed"
            and isinstance(verification_report, dict)
            and verification_report.get("kind") == "staticpython-pack-sdk-verification"
        ):
            if verification_report.get("status") != "passed":
                raise RuntimeError("cannot promote a pack from a failed SDK verification report")
            provisional_records = verification_report.get("packs")
            if not isinstance(provisional_records, list):
                raise RuntimeError("SDK verification report has no provisional pack records")
            matching_records = [
                record
                for record in provisional_records
                if isinstance(record, dict)
                and record.get("name") == integration.name
                and record.get("version") == integration.release_version
            ]
            if len(matching_records) != 1:
                raise RuntimeError(
                    f"pack {integration.name} {integration.release_version} has "
                    f"{len(matching_records)} matching provisional verification records"
                )
            provisional_record = matching_records[0]
            evidence_fields = {
                "provisional_pack_sha256": "sha256",
                "payload_manifest_sha256": "payload_manifest_sha256",
                "metadata_without_verification_sha256": "metadata_without_verification_sha256",
            }
            for output_name, report_name in evidence_fields.items():
                value = provisional_record.get(report_name)
                if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
                    raise RuntimeError(
                        f"pack {integration.name} provisional verification record has invalid {report_name}"
                    )
                pack_verification_evidence[output_name] = value
        metadata = {
            "schema_version": STATICPYTHON_PACK_SCHEMA_VERSION,
            "kind": "staticpython-library-pack",
            "name": integration.name,
            "version": integration.release_version,
            "project_name": integration.project_name,
            "source_provider": integration.source_provider,
            "source_resolver": integration.source_resolver,
            "source_tree_sha256": source_tree_hash,
            "source_files": source_file_records,
            "staticpython_commit": git_commit_or_none(REPO_ROOT),
            "cpython_version": version_full,
            "cpython_commit": cpython_source.get("commit"),
            "cpython_tag": cpython_source.get("tag"),
            "cpython_source": cpython_source,
            "cpython_abi": f"cp{version_info[0]}{version_info[1]}",
            "runtime_abi": f"staticpython-pack-v1-cp{version_info[0]}{version_info[1]}",
            "platform": platform.lower(),
            "descriptor_symbol": descriptor_symbol,
            "descriptor_source": (STATICPYTHON_PACK_SOURCE_DIR / "pack.c").as_posix(),
            "sources": [
                (STATICPYTHON_PACK_SOURCE_DIR / "pack.c").as_posix(),
                *[record["source"] for record in resource_records],
            ],
            "frozen_modules": [record["name"] for record in frozen_records],
            "top_level_import_names": integration.top_level_import_names or integration.python_packages,
            "builtin_modules": integration.builtin_module_registrations,
            "resources": resource_records,
            "dependencies": integration.dependencies,
            "dependency_constraints": integration.dependency_constraints,
            "conflicts": integration.conflicts,
            "libraries": [record["logical_name"] for record in native_records],
            "wholearchive": wholearchive,
            "system_libraries": system_libraries,
            "suppressed_system_libraries": suppressed_system_libraries,
            "trusted_object_origins": trusted_object_origins,
            "link_order": [record["logical_name"] for record in native_records],
            "toolchain": {
                "platform_toolset": "v143",
                "runtime_library": "MultiThreaded",
                "visual_studio_version": os.environ.get("VisualStudioVersion"),
                "vscmd_version": os.environ.get("VSCMD_VER"),
                "vc_tools_version": os.environ.get("VCToolsVersion"),
                "windows_sdk_version": os.environ.get("WindowsSDKVersion"),
            },
            "license": {
                "expression": integration.license_expression,
                "status": license_status,
                "files": license_records,
                "sources": resolved_license_sources(integration),
            },
            "smoke_tests": integration.smoke_tests or [
                {"kind": "import", "module": name}
                for name in (integration.top_level_import_names or integration.python_packages)
            ],
            "verification": {
                "status": verification_status,
                "smoke_tests": smoke_test_records,
                **pack_verification_evidence,
            },
            "files": artifact_files,
        }
        (staging_root / STATICPYTHON_PACK_METADATA_NAME).write_text(
            json.dumps(metadata, ensure_ascii=False, indent=2),
            encoding="utf-8",
            newline="\n",
        )
        write_deterministic_zip(staging_root, destination)

    log(f"copied library pack {integration.name} {integration.release_version} to {destination}")
    return destination


def export_library_packs(
    source_root: Path,
    output_dir: Path,
    version_info: tuple[int, int, int],
    version_full: str,
    platform: str,
    integrations: list,
    *,
    verification_status: str = "not-run",
    verification_report: dict | None = None,
) -> list[Path]:
    return [
        export_library_pack(
            source_root,
            output_dir,
            version_info,
            version_full,
            platform,
            integration,
            verification_status=verification_status,
            verification_report=verification_report,
        )
        for integration in integrations
    ]


def select_output_pack_integrations(integrations: list, requested_names: list[str]) -> list:
    if not requested_names:
        return list(integrations)
    by_name = {integration.name.casefold(): integration for integration in integrations}
    selected = []
    missing = []
    seen: set[str] = set()
    for requested_name in requested_names:
        key = requested_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        integration = by_name.get(key)
        if integration is None:
            missing.append(requested_name)
            continue
        selected.append(integration)
    if missing:
        raise RuntimeError(
            "--output-pack-name did not match a selected integration: "
            + ", ".join(sorted(missing, key=str.casefold))
        )
    return selected


def detect_static_lib_sdk_root(path: Path) -> Path:
    if static_lib_sdk_metadata_path(path).exists():
        return path

    children = [child for child in path.iterdir() if child.is_dir()]
    if len(children) == 1 and static_lib_sdk_metadata_path(children[0]).exists():
        return children[0]

    raise RuntimeError(
        "could not locate a StaticPython static library SDK root; expected "
        f"{STATIC_LIB_SDK_METADATA_RELATIVE_PATH.as_posix()} under {path}"
    )


def prepare_static_lib_sdk(path: Path) -> tuple[Path, tempfile.TemporaryDirectory | None]:
    resolved = path.resolve()
    if resolved.is_dir():
        return detect_static_lib_sdk_root(resolved), None
    if resolved.is_file() and resolved.suffix.lower() == ".zip":
        temp_dir = tempfile.TemporaryDirectory(prefix="staticpython-static-libs-sdk-")
        extract_root = Path(temp_dir.name)
        with ZipFile(resolved) as archive:
            safe_extract_zip(archive, extract_root)
        return detect_static_lib_sdk_root(extract_root), temp_dir
    raise RuntimeError(f"prebuilt static library SDK must be a .zip archive or directory: {path}")


def install_prebuilt_static_library_sdk(
    source_root: Path,
    platform: str,
    manifest: dict,
    integrations: list,
    version_full: str,
    profile_name: str,
    sdk_root: Path,
) -> dict:
    metadata = load_static_lib_sdk_metadata(sdk_root)
    if int(metadata.get("schema_version", 0)) != STATIC_LIB_SDK_SCHEMA_VERSION:
        raise RuntimeError(
            f"unsupported static library SDK schema version {metadata.get('schema_version')!r}; "
            f"expected {STATIC_LIB_SDK_SCHEMA_VERSION}"
        )
    if metadata.get("version_full") != version_full:
        raise RuntimeError(
            f"static library SDK version {metadata.get('version_full')!r} does not match build version {version_full!r}"
        )
    if str(metadata.get("platform", "")).lower() != platform.lower():
        raise RuntimeError(
            f"static library SDK platform {metadata.get('platform')!r} does not match build platform {platform!r}"
        )

    sdk_profile = metadata.get("profile_name")
    if sdk_profile and sdk_profile != profile_name:
        log(f"using static library SDK built from profile {sdk_profile!r} for current profile {profile_name!r}")

    available = {
        str(record["logical_name"]).lower(): record
        for record in metadata.get("libraries", [])
        if isinstance(record, dict) and record.get("logical_name")
    }
    required = list(
        dict.fromkeys(
            [
                normalize_library_name(name)
                for name in iter_python_link_dependencies(source_root, manifest, integrations)
                if is_packaged_static_library(name)
            ]
            + [
                normalize_library_name(name)
                for name in iter_python_link_wholearchive_libraries(source_root, manifest, integrations)
                if is_packaged_static_library(name)
            ]
        )
    )
    missing = [name for name in required if name not in available]
    if missing:
        raise RuntimeError(
            "static library SDK is missing library file(s) required by the current build profile: "
            + ", ".join(missing)
        )

    output_dir = get_pcbuild_output_dir(source_root, platform)
    output_dir.mkdir(parents=True, exist_ok=True)
    for logical_name, record in available.items():
        archive_path = record.get("archive_path")
        if not isinstance(archive_path, str):
            raise RuntimeError(f"static library SDK record for {logical_name} is missing archive_path")
        source_path = sdk_root / Path(archive_path)
        if not source_path.exists():
            raise RuntimeError(f"static library SDK file is missing: {source_path}")
        shutil.copy2(source_path, output_dir / logical_name)

    log(
        f"installed {len(available)} prebuilt static library file(s) into "
        f"{display_path(output_dir, source_root)}"
    )
    return metadata


def set_or_create_property(root: ET.Element, name: str, value: str) -> None:
    existing = next(root.iter(msbuild_tag(name)), None)
    if existing is not None:
        existing.text = value
        return
    property_group = ensure_property_group(root)
    child = ensure_direct_child(property_group, name)
    child.text = value
def parse_version_string(raw_version: str) -> tuple[str, tuple[int, int, int]]:
    version = raw_version.strip()
    if version.startswith("v"):
        version = version[1:]
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)(?:(?:a|b|rc)\d+)?", version)
    if not match:
        raise RuntimeError(
            f"unsupported CPython version string {raw_version!r}; expected format like 3.13.2, 3.12.10, or 3.15.0a8"
        )
    parts = tuple(int(group) for group in match.groups())
    return version, parts


def supports_pyrepl(version_info: tuple[int, int, int]) -> bool:
    return version_info >= PYREPL_MIN_VERSION


def run(cmd: list[str], cwd: Path, *, timeout: float | None = None) -> None:
    display = subprocess.list2cmdline([str(part) for part in cmd])
    log(f"RUN {display}")
    subprocess.run(cmd, cwd=str(cwd), check=True, timeout=timeout)


def run_with_env(cmd: list[str], cwd: Path, env: dict[str, str], *, timeout: float | None = None) -> None:
    display = subprocess.list2cmdline([str(part) for part in cmd])
    log(f"RUN {display}")
    subprocess.run(cmd, cwd=str(cwd), check=True, timeout=timeout, env=env)


def resolve_msbuild_exe() -> str:
    return resolve_tool_exe("msbuild")


def resolve_build_workers(raw_value: str | int | None = None) -> int:
    if raw_value is None:
        raw_value = os.environ.get("STATICPYTHON_BUILD_WORKERS")

    if raw_value not in (None, ""):
        try:
            workers = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(f"invalid build worker count: {raw_value!r}") from exc
        if workers < 1:
            raise RuntimeError(f"build worker count must be at least 1, got {workers}")
        return workers

    cpu_count = os.cpu_count() or 4
    return max(1, cpu_count - 2)


def msbuild_args(
    configuration: str,
    platform: str,
    *extra_properties: str,
    workers: int | None = None,
) -> list[str]:
    build_workers = resolve_build_workers(workers)
    args = [
        f"/m:{build_workers}",
        "/nologo",
        f"/p:Configuration={configuration}",
        f"/p:Platform={platform}",
        "/p:PreferredToolArchitecture=x64",
        f"/p:CL_MPCount={build_workers}",
        f"/p:MultiProcMaxCount={build_workers}",
        "/p:EnforceProcessCountAcrossBuilds=true",
        "/p:VcpkgEnabled=false",
    ]
    args.extend(f"/p:{prop}" for prop in extra_properties)
    return args


def replace_once(text: str, old: str, new: str, *, path: Path) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"expected snippet not found in {path}: {old!r}")
    return text.replace(old, new, 1)


def sub_once(pattern: str, repl: str, text: str, *, path: Path) -> str:
    if repl in text:
        return text
    new_text, count = re.subn(pattern, repl, text, count=1, flags=re.MULTILINE)
    if count != 1:
        raise RuntimeError(f"expected regex not found in {path}: {pattern}")
    return new_text


def ensure_after(text: str, anchor: str, snippet: str, *, path: Path) -> str:
    if snippet in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"expected anchor not found in {path}: {anchor!r}")
    return text.replace(anchor, anchor + snippet, 1)


def ensure_before(text: str, anchor: str, snippet: str, *, path: Path) -> str:
    if snippet in text:
        return text
    if anchor not in text:
        raise RuntimeError(f"expected anchor not found in {path}: {anchor!r}")
    return text.replace(anchor, snippet + anchor, 1)


def remove_line_contains(text: str, needle: str) -> str:
    lines = text.splitlines(keepends=True)
    kept = [line for line in lines if needle not in line]
    return "".join(kept)


def replace_section_between_anchors(text: str, start_anchor: str, end_anchor: str, body: str, *, path: Path) -> str:
    start_index = text.find(start_anchor)
    if start_index < 0:
        raise RuntimeError(f"expected start anchor not found in {path}: {start_anchor!r}")
    start_index += len(start_anchor)
    end_index = text.find(end_anchor, start_index)
    if end_index < 0:
        raise RuntimeError(f"expected end anchor not found in {path}: {end_anchor!r}")
    return text[:start_index] + body + text[end_index:]


def ensure_clcompile_preprocessor_definition(text: str, definition: str, *, path: Path) -> str:
    pattern = r"(<ClCompile(?: [^>]*)?>)(.*?)(</ClCompile>)"
    match = re.search(pattern, text, flags=re.DOTALL)
    if not match:
        snippet = (
            "    <ClCompile>\n"
            f"      <PreprocessorDefinitions>{definition};%(PreprocessorDefinitions)</PreprocessorDefinitions>\n"
            "    </ClCompile>\n"
        )
        if "  </ItemDefinitionGroup>\n" in text:
            return ensure_before(text, "  </ItemDefinitionGroup>\n", snippet, path=path)
        item_group_anchor = "  <ItemGroup>\n"
        wrapper = f"  <ItemDefinitionGroup>\n{snippet}  </ItemDefinitionGroup>\n"
        return ensure_before(text, item_group_anchor, wrapper, path=path)

    block = match.group(2)
    if definition in block:
        return text

    if "<PreprocessorDefinitions>" in block:
        def repl(inner_match: re.Match[str]) -> str:
            body = inner_match.group(1)
            if definition in body:
                return inner_match.group(0)
            if "%(PreprocessorDefinitions)" in body:
                body = body.replace("%(PreprocessorDefinitions)", f"{definition};%(PreprocessorDefinitions)", 1)
            else:
                body = f"{body.rstrip(';')};{definition}"
            return f"<PreprocessorDefinitions>{body}</PreprocessorDefinitions>"

        block, count = re.subn(
            r"<PreprocessorDefinitions>(.*?)</PreprocessorDefinitions>",
            repl,
            block,
            count=1,
            flags=re.DOTALL,
        )
        if count != 1:
            raise RuntimeError(f"expected <PreprocessorDefinitions> block not found in first <ClCompile> of {path}")
    else:
        block = f"{block}\n      <PreprocessorDefinitions>{definition};%(PreprocessorDefinitions)</PreprocessorDefinitions>"

    return text[: match.start(2)] + block + text[match.end(2) :]


def ensure_vcpkg_disabled(text: str, *, path: Path) -> str:
    vcpkg_snippet = "  <PropertyGroup Label=\"Vcpkg\">\n    <VcpkgEnabled>false</VcpkgEnabled>\n  </PropertyGroup>\n"
    return ensure_before(text, "  <ItemDefinitionGroup>\n", vcpkg_snippet, path=path)


def patch_static_library_project(path: Path, options: dict) -> None:
    tree, root = load_msbuild_project(path)

    configuration_types = list(root.iter(msbuild_tag("ConfigurationType")))
    if not configuration_types:
        raise RuntimeError(f"expected <ConfigurationType> block not found in {path}")
    for configuration_type in configuration_types:
        configuration_type.text = "StaticLibrary"

    target_ext = next(root.iter(msbuild_tag("TargetExt")), None)
    if target_ext is None:
        target_ext = ensure_direct_child(ensure_property_group(root), "TargetExt")
    target_ext.text = ".lib"

    ensure_clcompile_preprocessor_token(root, "Py_NO_ENABLE_SHARED")
    for definition in options.get("extra_preprocessor_definitions", []):
        ensure_clcompile_preprocessor_token(root, definition)
    ensure_release_x64_runtime_library(root)

    if options.get("disable_vcpkg"):
        ensure_vcpkg_property_group(root)

    if options.get("ensure_openssl_applink"):
        item_group = ensure_item_group_with_tag(root, "ClCompile")
        applink = None
        for child in item_group:
            if child.tag == msbuild_tag("ClCompile") and child.get("Include") == r"$(opensslIncludeDir)\applink.c":
                applink = child
                break
        if applink is None:
            applink = ET.SubElement(item_group, msbuild_tag("ClCompile"))
            applink.set("Include", r"$(opensslIncludeDir)\applink.c")
        preprocessor = ensure_direct_child(applink, "PreprocessorDefinitions")
        preprocessor.text = merge_msbuild_semicolon_list(
            preprocessor.text,
            ["_CRT_SECURE_NO_WARNINGS"],
            "$(PreprocessorDefinitions)",
        )

    save_msbuild_project(path, tree)


def patch_static_library_projects(source_root: Path, manifest: dict, integrations: list) -> None:
    patch_options = static_library_project_patches(manifest)
    for project in iter_patchable_static_library_projects(source_root, manifest, integrations):
        patch_static_library_project(source_root / "PCbuild" / project, patch_options.get(project, {}))


def make_library_hook_context(
    source_root: Path,
    version_info: tuple[int, int, int],
    version_mm: str,
    version_full: str,
    configuration: str = "Release",
    platform: str = "x64",
) -> LibraryHookContext:
    return LibraryHookContext(
        repo_root=REPO_ROOT,
        source_root=source_root,
        version_info=version_info,
        version_mm=version_mm,
        version_full=version_full,
        download_cache_root=DOWNLOAD_ROOT,
        work_cache_root=WORK_CACHE_ROOT,
        asset_overlay_root=ASSET_ROOT,
        log=log,
        configuration=configuration,
        platform=platform,
    )


def parse_cpython_version(source_root: Path) -> tuple[tuple[int, int, int], str, str]:
    patchlevel = source_root / "Include" / "patchlevel.h"
    text = patchlevel.read_text(encoding="utf-8")

    def define(name: str) -> str:
        match = re.search(rf"^#define {name}\s+(\d+)", text, flags=re.MULTILINE)
        if not match:
            raise RuntimeError(f"could not find {name} in {patchlevel}")
        return match.group(1)

    major = define("PY_MAJOR_VERSION")
    minor = define("PY_MINOR_VERSION")
    micro = define("PY_MICRO_VERSION")
    version_info = (int(major), int(minor), int(micro))
    version_match = re.search(r'^#define PY_VERSION\s+"([^"]+)"', text, flags=re.MULTILINE)
    if not version_match:
        raise RuntimeError(f"could not find PY_VERSION in {patchlevel}")
    version_full, parsed_version_info = parse_version_string(version_match.group(1))
    if parsed_version_info != version_info:
        raise RuntimeError(
            f"PY_VERSION {version_full!r} does not match numeric version macros {version_info}"
        )
    return version_info, f"{major}.{minor}", version_full


def iter_overlay_entries(manifest: dict, integrations: list, version_info: tuple[int, int, int]) -> list[str]:
    entries: list[str] = []
    for rel in [*manifest["overlay_entries"], *collect_overlay_entries(integrations)]:
        if rel == "Lib/_pyrepl/__main__.py" and not supports_pyrepl(version_info):
            log(f"skip overlay {rel} for CPython < 3.13")
            continue
        if rel not in entries:
            entries.append(rel)
    return entries


def copy_overlay_entries(
    source_root: Path,
    overlay_root: Path,
    manifest: dict,
    integrations: list,
    version_info: tuple[int, int, int],
) -> None:
    for rel in iter_overlay_entries(manifest, integrations, version_info):
        src = overlay_root / rel
        dst = source_root / rel
        if not src.exists():
            raise RuntimeError(f"overlay entry missing: {src}")
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            log(f"copy tree {rel}")
            shutil.copytree(
                src,
                dst,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            log(f"copy file {rel}")
            shutil.copy2(src, dst)


def cleanup_unselected_third_party_sources(
    source_root: Path,
    all_integrations: list,
    selected_integrations: list,
) -> None:
    desired = {
        path.replace("\\", "/")
        for integration in selected_integrations
        for path in integration.materialized_paths
    }
    candidates = {
        path.replace("\\", "/")
        for integration in all_integrations
        for path in integration.materialized_paths
    }

    for relative in sorted(candidates - desired, key=lambda value: (value.count("/"), len(value)), reverse=True):
        if any(desired_path.startswith(relative + "/") for desired_path in desired):
            continue
        target = source_root / relative
        if not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target)
            log(f"removed stale third-party tree {relative}")
        else:
            target.unlink()
            log(f"removed stale third-party file {relative}")


def cleanup_integration_legacy_paths(source_root: Path, integrations: list) -> None:
    stale_paths = {
        path.replace("\\", "/")
        for integration in integrations
        for path in getattr(integration, "cleanup_paths", [])
    }
    for relative in sorted(stale_paths, key=lambda value: (value.count("/"), len(value)), reverse=True):
        target = source_root / relative
        if not target.exists():
            continue
        if target.is_dir():
            shutil.rmtree(target)
            log(f"removed stale integration tree {relative}")
        else:
            target.unlink()
            log(f"removed stale integration file {relative}")


def _runtime_resource_module_paths(source_root: Path) -> list[Path]:
    return sorted((source_root / "Lib").glob(f"{RUNTIME_RESOURCE_MODULE_BASENAME}*.py"))


def _cleanup_runtime_resource_modules(source_root: Path) -> None:
    for path in _runtime_resource_module_paths(source_root):
        path.unlink(missing_ok=True)


def _skip_runtime_resource_path(relative: str) -> bool:
    parts = [part for part in relative.replace("\\", "/").split("/") if part]
    lowered_parts = [part.lower() for part in parts]
    if not parts:
        return True
    if any(part in RUNTIME_RESOURCE_SKIP_DIR_NAMES for part in lowered_parts[:-1]):
        return True
    basename = lowered_parts[-1]
    return any(basename.endswith(suffix) for suffix in RUNTIME_RESOURCE_PYTHON_SUFFIXES)


def _is_runtime_resource_file(path: Path, relative: str) -> bool:
    return not _skip_runtime_resource_path(relative) and path.is_file()


def _runtime_resource_candidate_paths(integration) -> list[str]:
    resource_rules = getattr(integration, "resource_rules", [])
    if resource_rules:
        candidates: list[str] = []
        for index, rule in enumerate(resource_rules, start=1):
            if not isinstance(rule, dict):
                raise RuntimeError(
                    f"{integration.name} resource rule #{index} must be an object"
                )
            unknown = sorted(set(rule) - {"action", "path"})
            if unknown:
                raise RuntimeError(
                    f"{integration.name} resource rule #{index} has unsupported keys: "
                    + ", ".join(unknown)
                )
            if rule.get("action") != "include":
                raise RuntimeError(
                    f"{integration.name} resource rule #{index} action must be 'include'"
                )
            relative = rule.get("path")
            if not isinstance(relative, str) or not relative:
                raise RuntimeError(
                    f"{integration.name} resource rule #{index} requires a non-empty path"
                )
            normalized = relative.replace("\\", "/")
            parts = PurePosixPath(normalized)
            if parts.is_absolute() or any(part in {"", ".", ".."} for part in parts.parts):
                raise RuntimeError(
                    f"{integration.name} resource rule #{index} has an unsafe path: {relative!r}"
                )
            candidates.append(normalized)
        return list(dict.fromkeys(candidates))

    candidates: list[str] = []
    for relative in getattr(integration, "materialized_paths", []):
        candidates.append(relative)
    for relative in getattr(integration, "source_entries", []):
        candidates.append(relative)
    for relative in getattr(integration, "source_mapping", {}).values():
        candidates.append(relative)
    for relative in getattr(integration, "overlay_entries", []):
        candidates.append(relative)
    return candidates


def _iter_runtime_resource_roots(source_root: Path, integrations: list) -> list[Path]:
    roots: dict[str, Path] = {}
    for integration in integrations:
        for relative in _runtime_resource_candidate_paths(integration):
            normalized = relative.replace("\\", "/")
            if normalized.startswith("Lib/_staticpython_runtime_resources"):
                continue
            target = source_root / normalized
            if target.exists():
                roots[target.resolve().as_posix().lower()] = target
    return sorted(roots.values(), key=lambda path: path.as_posix().lower())


def collect_runtime_resource_files(source_root: Path, integrations: list) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for root in _iter_runtime_resource_roots(source_root, integrations):
        candidates = sorted(root.rglob("*")) if root.is_dir() else [root]
        for path in candidates:
            if not path.is_file():
                continue
            try:
                relative = path.relative_to(source_root).as_posix()
            except ValueError:
                continue
            if _is_runtime_resource_file(path, relative):
                files.setdefault(relative, path)
    return files


def _chunk_ascii(text: str, width: int = 96) -> list[str]:
    if not text:
        return [""]
    return [text[index : index + width] for index in range(0, len(text), width)]


def _chunk_runtime_resource_blobs(blob_records: list[dict[str, str]]) -> list[list[dict[str, str]]]:
    chunks: list[list[dict[str, str]]] = []
    current_chunk: list[dict[str, str]] = []
    current_size = 0

    for record in blob_records:
        record_size = max(len(record["encoded"]), 1)
        if current_chunk and current_size + record_size > RUNTIME_RESOURCE_SHARD_TEXT_BYTES:
            chunks.append(current_chunk)
            current_chunk = []
            current_size = 0
        current_chunk.append(record)
        current_size += record_size

    if current_chunk:
        chunks.append(current_chunk)
    return chunks


def _runtime_resource_group_prefix(relative: str) -> str:
    parts = [part for part in relative.replace("\\", "/").split("/") if part]
    if not parts:
        return ""
    if parts[0] in {"Lib", "share", "etc"} and len(parts) >= 2:
        return "/".join(parts[:2])
    return parts[0]


def _runtime_resource_group_suffix(prefix: str) -> str:
    digest = hashlib.sha1(prefix.encode("utf-8")).hexdigest()[:8]
    safe = re.sub(r"[^0-9A-Za-z_]+", "_", prefix.lower()).strip("_")
    if not safe:
        safe = "root"
    return f"{safe}_{digest}"


def _runtime_resource_child_index(paths: list[str]) -> dict[str, tuple[str, ...]]:
    if not paths:
        return {}
    child_index: dict[str, set[str]] = {"": set()}
    for relative in paths:
        parts = relative.split("/")
        for index in range(len(parts)):
            parent = "/".join(parts[:index])
            child_index.setdefault(parent, set()).add(parts[index])
    return {parent: tuple(sorted(children)) for parent, children in sorted(child_index.items())}


def _fnv1a64(text: str) -> int:
    value = 1469598103934665603
    for byte in text.encode("utf-8"):
        value ^= byte
        value = (value * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return value


def _runtime_resource_hash_table(paths: list[str]) -> list[int]:
    size = 1
    while size < max(2, len(paths) * 2):
        size *= 2
    table = [0] * size
    for index, path in enumerate(paths):
        slot = _fnv1a64(path) & (size - 1)
        while table[slot]:
            slot = (slot + 1) & (size - 1)
        table[slot] = index + 1
    return table


def _c_bytes_literal(text: str) -> str:
    pieces: list[str] = []
    for byte in text.encode("utf-8"):
        if 32 <= byte <= 126 and byte not in {34, 92}:
            pieces.append(chr(byte))
        elif byte == 34:
            pieces.append(r"\"")
        elif byte == 92:
            pieces.append(r"\\")
        else:
            pieces.append(f"\\{byte:03o}")
    return '"' + "".join(pieces) + '"'


def _c_array_u32(name: str, values: list[int]) -> str:
    lines = [f"static const unsigned int {name}[] = {{"]
    for index in range(0, len(values), 12):
        lines.append("    " + ", ".join(str(value) for value in values[index : index + 12]) + ",")
    lines.append("};")
    return "\n".join(lines)


def _write_staticpython_resource_store_c(
    source_root: Path,
    *,
    target_records: list[tuple[str, str, str, int]],
) -> None:
    store_path = source_root / RUNTIME_RESOURCE_STORE_C_RELATIVE_PATH
    store_path.parent.mkdir(parents=True, exist_ok=True)

    sorted_targets = sorted(target_records, key=lambda item: item[0])
    file_paths = [relative for relative, _module_name, _blob_id, _size in sorted_targets]
    children_by_dir = _runtime_resource_child_index(file_paths)
    dir_paths = list(children_by_dir)

    child_literals: list[str] = []
    dir_records: list[tuple[str, int, int]] = []
    for directory in dir_paths:
        first_child = len(child_literals)
        children = children_by_dir[directory]
        child_literals.extend(children)
        dir_records.append((directory, first_child, len(children)))

    file_table = _runtime_resource_hash_table(file_paths)
    dir_table = _runtime_resource_hash_table(dir_paths)

    file_entries = []
    for relative, module_name, blob_id, size in sorted_targets:
        file_entries.append(
            "    {"
            f"{_c_bytes_literal(relative)}, "
            f"{size}, "
            f"{_c_bytes_literal(module_name)}, "
            f"{_c_bytes_literal(blob_id)}"
            "},"
        )
    dir_entries = [
        "    {"
        f"{_c_bytes_literal(directory)}, "
        f"{first_child}, "
        f"{child_count}"
        "},"
        for directory, first_child, child_count in dir_records
    ]
    child_entries = [f"    {_c_bytes_literal(child)}," for child in child_literals]
    file_entries_for_c = file_entries or [
        f"    {{{_c_bytes_literal('')}, 0, {_c_bytes_literal('')}, {_c_bytes_literal('')}}},"
    ]
    dir_entries_for_c = dir_entries or [
        f"    {{{_c_bytes_literal('')}, 0, 0}},"
    ]
    child_entries_for_c = child_entries or [f"    {_c_bytes_literal('')},"]

    store_path.write_text(
        "/* Auto-generated by StaticPython. Do not edit. */\n"
        "#include \"Python.h\"\n"
        "#include <stdint.h>\n"
        "#include <stddef.h>\n"
        "#include <string.h>\n\n"
        "typedef struct {\n"
        "    const char *path;\n"
        "    Py_ssize_t size;\n"
        "    const char *module_name;\n"
        "    const char *blob_id;\n"
        "} StaticPythonFileEntry;\n\n"
        "typedef struct {\n"
        "    const char *path;\n"
        "    Py_ssize_t first_child;\n"
        "    Py_ssize_t child_count;\n"
        "} StaticPythonDirEntry;\n\n"
        "static const StaticPythonFileEntry staticpython_files[] = {\n"
        + "\n".join(file_entries_for_c)
        + "\n};\n\n"
        "static const StaticPythonDirEntry staticpython_dirs[] = {\n"
        + "\n".join(dir_entries_for_c)
        + "\n};\n\n"
        "static const char *staticpython_child_names[] = {\n"
        + "\n".join(child_entries_for_c)
        + "\n};\n\n"
        + _c_array_u32("staticpython_file_hash", file_table)
        + "\n\n"
        + _c_array_u32("staticpython_dir_hash", dir_table)
        + "\n\n"
        f"#define STATICPYTHON_FILE_COUNT ((Py_ssize_t){len(file_entries)})\n"
        f"#define STATICPYTHON_DIR_COUNT ((Py_ssize_t){len(dir_entries)})\n"
        "#define STATICPYTHON_FILE_HASH_SIZE (sizeof(staticpython_file_hash) / sizeof(staticpython_file_hash[0]))\n"
        "#define STATICPYTHON_DIR_HASH_SIZE (sizeof(staticpython_dir_hash) / sizeof(staticpython_dir_hash[0]))\n\n"
        "static uint64_t\n"
        "staticpython_hash_bytes(const char *text, Py_ssize_t length)\n"
        "{\n"
        "    uint64_t value = UINT64_C(1469598103934665603);\n"
        "    for (Py_ssize_t index = 0; index < length; index++) {\n"
        "        value ^= (unsigned char)text[index];\n"
        "        value *= UINT64_C(1099511628211);\n"
        "    }\n"
        "    return value;\n"
        "}\n\n"
        "static int\n"
        "staticpython_lookup_file(const char *key, Py_ssize_t key_length)\n"
        "{\n"
        "    if (STATICPYTHON_FILE_COUNT == 0) {\n"
        "        return -1;\n"
        "    }\n"
        "    size_t slot = (size_t)(staticpython_hash_bytes(key, key_length) & (STATICPYTHON_FILE_HASH_SIZE - 1));\n"
        "    for (size_t probe = 0; probe < STATICPYTHON_FILE_HASH_SIZE; probe++) {\n"
        "        unsigned int stored = staticpython_file_hash[slot];\n"
        "        if (stored == 0) {\n"
        "            return -1;\n"
        "        }\n"
        "        const StaticPythonFileEntry *entry = &staticpython_files[stored - 1];\n"
        "        if ((Py_ssize_t)strlen(entry->path) == key_length && memcmp(entry->path, key, (size_t)key_length) == 0) {\n"
        "            return (int)(stored - 1);\n"
        "        }\n"
        "        slot = (slot + 1) & (STATICPYTHON_FILE_HASH_SIZE - 1);\n"
        "    }\n"
        "    return -1;\n"
        "}\n\n"
        "static int\n"
        "staticpython_lookup_dir(const char *key, Py_ssize_t key_length)\n"
        "{\n"
        "    if (STATICPYTHON_DIR_COUNT == 0) {\n"
        "        return -1;\n"
        "    }\n"
        "    size_t slot = (size_t)(staticpython_hash_bytes(key, key_length) & (STATICPYTHON_DIR_HASH_SIZE - 1));\n"
        "    for (size_t probe = 0; probe < STATICPYTHON_DIR_HASH_SIZE; probe++) {\n"
        "        unsigned int stored = staticpython_dir_hash[slot];\n"
        "        if (stored == 0) {\n"
        "            return -1;\n"
        "        }\n"
        "        const StaticPythonDirEntry *entry = &staticpython_dirs[stored - 1];\n"
        "        if ((Py_ssize_t)strlen(entry->path) == key_length && memcmp(entry->path, key, (size_t)key_length) == 0) {\n"
        "            return (int)(stored - 1);\n"
        "        }\n"
        "        slot = (slot + 1) & (STATICPYTHON_DIR_HASH_SIZE - 1);\n"
        "    }\n"
        "    return -1;\n"
        "}\n\n"
        "static int\n"
        "staticpython_unicode_key(PyObject *arg, const char **key, Py_ssize_t *key_length)\n"
        "{\n"
        "    *key = PyUnicode_AsUTF8AndSize(arg, key_length);\n"
        "    return *key != NULL;\n"
        "}\n\n"
        "static PyObject *\n"
        "staticpython_file_info(PyObject *self, PyObject *arg)\n"
        "{\n"
        "    const char *key;\n"
        "    Py_ssize_t key_length;\n"
        "    if (!staticpython_unicode_key(arg, &key, &key_length)) {\n"
        "        return NULL;\n"
        "    }\n"
        "    int index = staticpython_lookup_file(key, key_length);\n"
        "    if (index < 0) {\n"
        "        Py_RETURN_NONE;\n"
        "    }\n"
        "    const StaticPythonFileEntry *entry = &staticpython_files[index];\n"
        "    return Py_BuildValue(\"ssn\", entry->module_name, entry->blob_id, entry->size);\n"
        "}\n\n"
        "static PyObject *\n"
        "staticpython_children_func(PyObject *self, PyObject *arg)\n"
        "{\n"
        "    const char *key;\n"
        "    Py_ssize_t key_length;\n"
        "    if (!staticpython_unicode_key(arg, &key, &key_length)) {\n"
        "        return NULL;\n"
        "    }\n"
        "    int index = staticpython_lookup_dir(key, key_length);\n"
        "    if (index < 0) {\n"
        "        Py_RETURN_NONE;\n"
        "    }\n"
        "    const StaticPythonDirEntry *entry = &staticpython_dirs[index];\n"
        "    PyObject *tuple = PyTuple_New(entry->child_count);\n"
        "    if (tuple == NULL) {\n"
        "        return NULL;\n"
        "    }\n"
        "    for (Py_ssize_t offset = 0; offset < entry->child_count; offset++) {\n"
        "        PyObject *child = PyUnicode_FromString(staticpython_child_names[entry->first_child + offset]);\n"
        "        if (child == NULL) {\n"
        "            Py_DECREF(tuple);\n"
        "            return NULL;\n"
        "        }\n"
        "        PyTuple_SET_ITEM(tuple, offset, child);\n"
        "    }\n"
        "    return tuple;\n"
        "}\n\n"
        "static PyObject *\n"
        "staticpython_kind(PyObject *self, PyObject *arg)\n"
        "{\n"
        "    const char *key;\n"
        "    Py_ssize_t key_length;\n"
        "    if (!staticpython_unicode_key(arg, &key, &key_length)) {\n"
        "        return NULL;\n"
        "    }\n"
        "    if (staticpython_lookup_file(key, key_length) >= 0) {\n"
        "        return PyLong_FromLong(1);\n"
        "    }\n"
        "    if (staticpython_lookup_dir(key, key_length) >= 0) {\n"
        "        return PyLong_FromLong(2);\n"
        "    }\n"
        "    return PyLong_FromLong(0);\n"
        "}\n\n"
        "static PyMethodDef staticpython_resource_store_methods[] = {\n"
        "    {\"file_info\", staticpython_file_info, METH_O, NULL},\n"
        "    {\"children\", staticpython_children_func, METH_O, NULL},\n"
        "    {\"kind\", staticpython_kind, METH_O, NULL},\n"
        "    {NULL, NULL, 0, NULL}\n"
        "};\n\n"
        "static struct PyModuleDef staticpython_resource_store_module = {\n"
        "    PyModuleDef_HEAD_INIT,\n"
        f"    \"{RUNTIME_RESOURCE_STORE_MODULE}\",\n"
        "    NULL,\n"
        "    0,\n"
        "    staticpython_resource_store_methods,\n"
        "    NULL,\n"
        "    NULL,\n"
        "    NULL,\n"
        "    NULL,\n"
        "};\n\n"
        "PyMODINIT_FUNC\n"
        "PyInit__staticpython_resource_store(void)\n"
        "{\n"
        "    return PyModule_Create(&staticpython_resource_store_module);\n"
        "}\n",
        encoding="utf-8",
        newline="\n",
    )


def _write_runtime_resource_group_module(
    source_root: Path,
    *,
    group_prefix: str,
    group_module_name: str,
    resource_files: dict[str, Path],
) -> tuple[int, int, int, str, list[tuple[str, str, str, int]]]:
    index_module_name = f"{group_module_name}_index"
    blob_records: list[dict[str, str]] = []
    blob_ids_by_hash: dict[str, dict[str, str]] = {}
    target_records: list[tuple[str, str, int]] = []
    child_index: dict[str, set[str]] = {"": set()}
    basename_index: dict[str, set[str]] = {}
    dir_basename_index: dict[str, set[str]] = {}

    for relative, path in resource_files.items():
        payload = path.read_bytes()
        payload_hash = hashlib.sha256(payload).hexdigest()
        blob_id = f"sha256:{payload_hash}"
        record = blob_ids_by_hash.get(blob_id)
        if record is None:
            record = {
                "blob_id": blob_id,
                "encoded": base64.b85encode(zlib.compress(payload, level=9)).decode("ascii"),
            }
            blob_ids_by_hash[blob_id] = record
            blob_records.append(record)

        target_records.append((relative, blob_id, len(payload)))
        parts = relative.split("/")
        basename_index.setdefault(parts[-1].lower(), set()).add(relative)
        for index in range(len(parts)):
            parent = "/".join(parts[:index])
            child_index.setdefault(parent, set()).add(parts[index])
            if parent:
                dir_basename_index.setdefault(parts[index - 1].lower(), set()).add(parent)

    blob_to_module: dict[str, str] = {}
    shard_module_names: list[str] = []
    for index, chunk in enumerate(_chunk_runtime_resource_blobs(blob_records)):
        shard_module_name = f"{group_module_name}_shard_{index:0{RUNTIME_RESOURCE_SHARD_DIGITS}d}"
        shard_module_names.append(shard_module_name)
        shard_path = source_root / "Lib" / f"{shard_module_name}.py"

        blob_lines: list[str] = []
        for record in chunk:
            wrapped = "\n".join(f'        "{chunk_text}",' for chunk_text in _chunk_ascii(record["encoded"]))
            blob_lines.append(
                "    "
                + repr(record["blob_id"])
                + ": (\n"
                + wrapped
                + "\n"
                + "    ),"
            )
            blob_to_module[record["blob_id"]] = shard_module_name

        shard_path.write_text(
            "# Auto-generated by StaticPython. Do not edit.\n"
            "RESOURCE_BLOBS = {\n"
            + ("\n".join(blob_lines) if blob_lines else "")
            + "\n}\n",
            encoding="utf-8",
            newline="\n",
        )

    target_lines = [
        "    " + repr(relative) + f": ({blob_to_module[blob_id]!r}, {blob_id!r}, {size}),"
        for relative, blob_id, size in target_records
    ]
    file_size_lines = [
        "    " + repr(relative) + f": {size},"
        for relative, _blob_id, size in target_records
    ]
    child_lines = [
        "    " + repr(parent) + ": " + repr(tuple(sorted(children))) + ","
        for parent, children in sorted(child_index.items())
    ]
    basename_lines = [
        "    " + repr(basename) + ": " + repr(tuple(sorted(paths))) + ","
        for basename, paths in sorted(basename_index.items())
    ]
    dir_basename_lines = [
        "    " + repr(basename) + ": " + repr(tuple(sorted(paths))) + ","
        for basename, paths in sorted(dir_basename_index.items())
    ]
    group_path = source_root / "Lib" / f"{group_module_name}.py"
    group_path.write_text(
        "# Auto-generated by StaticPython. Do not edit.\n"
        f"RESOURCE_GROUP_PREFIX = {group_prefix!r}\n"
        'RESOURCE_PAYLOAD_ENCODING = "zlib+b85"\n'
        f"RESOURCE_SHARDS = {tuple(shard_module_names)!r}\n"
        f"RESOURCE_INDEX_MODULE = {index_module_name!r}\n"
        "RESOURCE_TARGETS = {\n"
        + ("\n".join(target_lines) if target_lines else "")
        + "\n}\n"
        "RESOURCE_FILE_SIZES = {\n"
        + ("\n".join(file_size_lines) if file_size_lines else "")
        + "\n}\n"
        "RESOURCE_CHILDREN = {}\n\n"
        "RESOURCE_BASENAME_INDEX = {\n"
        + ("\n".join(basename_lines) if basename_lines else "")
        + "\n}\n\n"
        "RESOURCE_DIR_BASENAME_INDEX = {}\n\n"
        "def iter_resource_payloads():\n"
        "    import importlib\n\n"
        "    shard_cache = {}\n"
        "    for relative, value in RESOURCE_TARGETS.items():\n"
        "        module_name, blob_id = value[:2]\n"
        "        shard_module = shard_cache.get(module_name)\n"
        "        if shard_module is None:\n"
        "            shard_module = importlib.import_module(module_name)\n"
        "            shard_cache[module_name] = shard_module\n"
        "        yield relative, shard_module.RESOURCE_BLOBS[blob_id]\n"
        "\n"
        "def get_resource_payload(module_name, blob_id):\n"
        "    import importlib\n\n"
        "    shard_module = importlib.import_module(module_name)\n"
        "    return shard_module.RESOURCE_BLOBS[blob_id]\n",
        encoding="utf-8",
        newline="\n",
    )

    index_path = source_root / "Lib" / f"{index_module_name}.py"
    index_path.write_text(
        "# Auto-generated by StaticPython. Do not edit.\n"
        f"RESOURCE_GROUP_PREFIX = {group_prefix!r}\n"
        "RESOURCE_TARGETS = {}\n"
        "RESOURCE_FILE_SIZES = {\n"
        + ("\n".join(file_size_lines) if file_size_lines else "")
        + "\n}\n"
        "RESOURCE_CHILDREN = {\n"
        + ("\n".join(child_lines) if child_lines else "")
        + "\n}\n\n"
        "RESOURCE_BASENAME_INDEX = {\n"
        + ("\n".join(basename_lines) if basename_lines else "")
        + "\n}\n\n"
        "RESOURCE_DIR_BASENAME_INDEX = {\n"
        + ("\n".join(dir_basename_lines) if dir_basename_lines else "")
        + "\n}\n",
        encoding="utf-8",
        newline="\n",
    )
    store_records = [
        (relative, blob_to_module[blob_id], blob_id, size)
        for relative, blob_id, size in target_records
    ]
    return len(target_records), len(blob_records), len(shard_module_names), index_module_name, store_records


def _write_staticpython_pack_resource_store_c(
    source_root: Path,
    *,
    target_records: list[tuple[str, str, str, int]],
) -> None:
    """Write the runtime-sdk base resource descriptor.

    Payloads remain in the frozen resource shard modules.  The descriptor is
    compiled into staticpython_runtime.lib and lets the common C provider
    resolve resources across the base SDK and every selected library pack.
    """
    store_path = source_root / RUNTIME_RESOURCE_STORE_C_RELATIVE_PATH
    store_path.parent.mkdir(parents=True, exist_ok=True)
    entries = [
        "    {"
        f"{_c_bytes_literal(relative)}, "
        f"{_c_bytes_literal(module_name)}, "
        f"{_c_bytes_literal(blob_id)}, "
        "NULL, 0, "
        f"{size}, STATICPYTHON_RESOURCE_RAW"
        "},"
        for relative, module_name, blob_id, size in sorted(target_records, key=lambda item: item[0])
    ]
    entries_for_c = entries or [
        f"    {{{_c_bytes_literal('')}, NULL, NULL, NULL, 0, 0, STATICPYTHON_RESOURCE_RAW}},"
    ]
    store_path.write_text(
        "/* Auto-generated by StaticPython. Do not edit. */\n"
        "#include \"Python.h\"\n"
        "#include \"staticpython_pack.h\"\n\n"
        "#define STATICPYTHON_STRINGIFY_INNER(value) #value\n"
        "#define STATICPYTHON_STRINGIFY(value) STATICPYTHON_STRINGIFY_INNER(value)\n"
        "#define STATICPYTHON_CPYTHON_ABI \\\n"
        "    \"cp\" STATICPYTHON_STRINGIFY(PY_MAJOR_VERSION) STATICPYTHON_STRINGIFY(PY_MINOR_VERSION)\n\n"
        "static const StaticPythonResourceV1 staticpython_base_resources[] = {\n"
        + "\n".join(entries_for_c)
        + "\n};\n\n"
        "const StaticPythonPackV1 StaticPython_BaseResourcePackV1 = {\n"
        "    sizeof(StaticPythonPackV1),\n"
        "    STATICPYTHON_PACK_ABI_VERSION,\n"
        "    \"staticpython-runtime-sdk\",\n"
        "    PY_VERSION,\n"
        "    STATICPYTHON_CPYTHON_ABI,\n"
        "    NULL, 0,\n"
        "    NULL, 0,\n"
        "    staticpython_base_resources,\n"
        f"    {len(entries)},\n"
        "    NULL, 0,\n"
        "    NULL, 0,\n"
        "    NULL, 0,\n"
        "    NULL\n"
        "};\n",
        encoding="utf-8",
        newline="\n",
    )


def write_runtime_resource_module(
    source_root: Path,
    integrations: list,
    *,
    pack_descriptor: bool = False,
) -> None:
    module_path = source_root / RUNTIME_RESOURCE_MODULE_RELATIVE_PATH
    module_path.parent.mkdir(parents=True, exist_ok=True)
    _cleanup_runtime_resource_modules(source_root)

    resource_files = collect_runtime_resource_files(source_root, integrations)
    if not resource_files:
        if pack_descriptor:
            _write_staticpython_pack_resource_store_c(source_root, target_records=[])
        else:
            _write_staticpython_resource_store_c(source_root, target_records=[])
        module_path.write_text(
            "# Auto-generated by StaticPython. Do not edit.\n"
            'RESOURCE_MANIFEST_HASH = "0" * 64\n'
            'RESOURCE_PAYLOAD_ENCODING = "zlib+b85"\n'
            "RESOURCE_SHARDS = ()\n"
            "RESOURCE_GROUPS = ()\n"
            "RESOURCE_GROUP_INDEXES = {}\n"
            "RESOURCE_TARGETS = {}\n"
            "RESOURCE_CHILDREN = {}\n\n"
            "RESOURCE_BASENAME_INDEX = {}\n\n"
            "RESOURCE_DIR_BASENAME_INDEX = {}\n\n"
            "def iter_resource_payloads():\n"
            "    return ()\n",
            encoding="utf-8",
            newline="\n",
        )
        log(f"wrote empty runtime resource module to {module_path.relative_to(source_root)}")
        return

    grouped_files: dict[str, dict[str, Path]] = {}
    manifest_hasher = hashlib.sha256()
    for relative, path in resource_files.items():
        prefix = _runtime_resource_group_prefix(relative)
        grouped_files.setdefault(prefix, {})[relative] = path
        manifest_hasher.update(relative.encode("utf-8"))
        manifest_hasher.update(b"\0")
        manifest_hasher.update(hashlib.sha256(path.read_bytes()).hexdigest().encode("ascii"))
        manifest_hasher.update(b"\n")

    group_records: list[tuple[str, str, str]] = []
    store_target_records: list[tuple[str, str, str, int]] = []
    target_count = 0
    blob_count = 0
    shard_count = 0
    for group_prefix, group_resource_files in sorted(grouped_files.items()):
        group_module_name = f"{RUNTIME_RESOURCE_MODULE_BASENAME}_group_{_runtime_resource_group_suffix(group_prefix)}"
        targets, blobs, shards, index_module_name, store_records = _write_runtime_resource_group_module(
            source_root,
            group_prefix=group_prefix,
            group_module_name=group_module_name,
            resource_files=group_resource_files,
        )
        group_records.append((group_prefix, group_module_name, index_module_name))
        target_count += targets
        blob_count += blobs
        shard_count += shards
        store_target_records.extend(store_records)

    if pack_descriptor:
        _write_staticpython_pack_resource_store_c(source_root, target_records=store_target_records)
    else:
        _write_staticpython_resource_store_c(source_root, target_records=store_target_records)

    group_lines = [
        "    " + repr(prefix) + f": {module_name!r},"
        for prefix, module_name, _index_module_name in group_records
    ]
    group_index_lines = [
        "    " + repr(prefix) + f": {index_module_name!r},"
        for prefix, _module_name, index_module_name in group_records
    ]
    manifest_hash = manifest_hasher.hexdigest()
    module_path.write_text(
        "# Auto-generated by StaticPython. Do not edit.\n"
        f"RESOURCE_MANIFEST_HASH = {manifest_hash!r}\n"
        'RESOURCE_PAYLOAD_ENCODING = "zlib+b85"\n'
        "RESOURCE_SHARDS = ()\n"
        "RESOURCE_GROUPS = {\n"
        + ("\n".join(group_lines) if group_lines else "")
        + "\n}\n"
        "RESOURCE_GROUP_INDEXES = {\n"
        + ("\n".join(group_index_lines) if group_index_lines else "")
        + "\n}\n"
        "RESOURCE_TARGETS = {}\n"
        "RESOURCE_CHILDREN = {}\n\n"
        "RESOURCE_BASENAME_INDEX = {}\n\n"
        "RESOURCE_DIR_BASENAME_INDEX = {}\n\n"
        "def iter_resource_payloads():\n"
        "    import importlib\n\n"
        "    for module_name in RESOURCE_GROUPS.values():\n"
        "        module = importlib.import_module(module_name)\n"
        "        yield from module.iter_resource_payloads()\n",
        encoding="utf-8",
        newline="\n",
    )
    total_bytes = sum(path.stat().st_size for path in resource_files.values())
    log(
        "wrote runtime resource module with "
        f"{target_count} file target(s), "
        f"{blob_count} unique payload(s), "
        f"{len(group_records)} group(s), "
        f"{shard_count} shard(s), "
        f"{total_bytes // 1024} KiB total to {module_path.relative_to(source_root)}"
    )


def patch_site_py(source_root: Path, version_mm: str) -> None:
    path = source_root / "Lib" / "site.py"
    text = path.read_text(encoding="utf-8")
    pattern = r'^(?P<indent>\s*)ver_nodot = .+$'
    desired_line = f'ver_nodot = "{version_mm}".replace(\'.\', \'\')'
    if desired_line not in text:
        text, count = re.subn(
            pattern,
            lambda match: f'{match.group("indent")}{desired_line}',
            text,
            count=1,
            flags=re.MULTILINE,
        )
        if count != 1:
            raise RuntimeError(f"expected regex not found in {path}: {pattern}")

    runtime_patch = (
        "\n"
        "def _staticpython_install_runtime_resources():\n"
        "    try:\n"
        "        import _staticpython_runtime as _staticpython_runtime\n"
        "    except Exception:\n"
        "        return\n"
        "    _staticpython_runtime.install()\n\n"
        "_staticpython_install_runtime_resources()\n\n"
    )
    start_marker = "def _staticpython_install_runtime_resources():\n"
    end_marker = "_staticpython_install_runtime_resources()\n"
    if start_marker in text:
        start_index = text.index(start_marker)
        end_index = text.index(end_marker, start_index) + len(end_marker)
        while end_index < len(text) and text[end_index] == "\n":
            end_index += 1
        text = text[:start_index] + runtime_patch.lstrip("\n") + text[end_index:]
    else:
        anchor = "PREFIXES = [sys.prefix, sys.exec_prefix]\n"
        if anchor not in text:
            raise RuntimeError(f"expected anchor not found in {path}: {anchor!r}")
        text = text.replace(anchor, anchor + runtime_patch, 1)
    path.write_text(text, encoding="utf-8", newline="\n")


def patch_modules_getpath_py(source_root: Path) -> None:
    path = source_root / "Modules" / "getpath.py"
    if not path.exists():
        log("skip getpath.py patch because Modules/getpath.py is missing")
        return

    text = path.read_text(encoding="utf-8")
    replacement = r"\g<indent>pass  # single-file build suppresses missing <prefix> warning"
    text, count = re.subn(
        r"^(?P<indent>\s*)warn\('Could not find platform independent libraries <prefix>'\)\s*$",
        replacement,
        text,
        flags=re.MULTILINE,
    )
    if count == 0:
        log("skip getpath.py warning patch because the target warning lines were not found")
        return

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_generate_sbom_py(source_root: Path) -> None:
    path = source_root / "Tools" / "build" / "generate_sbom.py"
    if not path.exists():
        log("skip generate_sbom.py patch because the file does not exist")
        return

    text = path.read_text(encoding="utf-8")
    old = '''def is_root_directory_git_index() -> bool:
    """Checks if the root directory is a git index"""
    try:
        subprocess.check_call(
            ["git", "-C", str(CPYTHON_ROOT_DIR), "rev-parse"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except subprocess.CalledProcessError:
        return False
    return True
'''
    new = '''def is_root_directory_git_index() -> bool:
    """Checks if the CPython root directory is itself a git checkout root."""
    try:
        completed = subprocess.run(
            ["git", "-C", str(CPYTHON_ROOT_DIR), "rev-parse", "--show-toplevel"],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except OSError:
        return False
    if completed.returncode != 0:
        return False
    git_root = Path(completed.stdout.decode(errors="replace").strip()).resolve()
    return git_root == CPYTHON_ROOT_DIR.resolve()
'''
    if new in text:
        return
    if old not in text:
        log("skip generate_sbom.py git-root patch because the target function was not found")
        return
    path.write_text(text.replace(old, new, 1), encoding="utf-8", newline="\n")


def patch_pc_config_minimal_c(source_root: Path) -> None:
    path = source_root / "PC" / "config_minimal.c"
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8")
    guarded_block = (
        "#ifdef Py_ENABLE_SHARED\n"
        "/* Define extern variables omitted from minimal builds */\n"
        "void *PyWin_DLLhModule = NULL;\n"
        "#endif\n"
    )
    unguarded_block = (
        "/* Define extern variables omitted from minimal builds */\n"
        "void *PyWin_DLLhModule = NULL;\n"
    )
    if guarded_block in text:
        text = text.replace(guarded_block, unguarded_block, 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_pc_dl_nt_c(source_root: Path) -> None:
    path = source_root / "PC" / "dl_nt.c"
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8")
    if "#ifdef Py_ENABLE_SHARED\n" in text:
        text = text.replace("#ifdef Py_ENABLE_SHARED\n\n", "", 1)
    if "\n#endif /* Py_ENABLE_SHARED */\n" in text:
        text = text.replace("\n#endif /* Py_ENABLE_SHARED */\n", "\n", 1)
    if "BOOL    WINAPI  DllMain" in text:
        text = text.replace("BOOL    WINAPI  DllMain", "BOOL    WINAPI  PythonDllMain", 1)

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_python_sysmodule_c(source_root: Path, version_mm: str) -> None:
    path = source_root / "Python" / "sysmodule.c"
    text = path.read_text(encoding="utf-8")

    guarded_externs = (
        "#ifdef MS_COREDLL\n"
        "extern void *PyWin_DLLhModule;\n"
        "/* A string loaded from the DLL at startup: */\n"
        "extern const char *PyWin_DLLVersionString;\n"
        "#endif\n"
    )
    unguarded_externs = (
        "extern void *PyWin_DLLhModule;\n"
        "/* A string loaded from the DLL at startup: */\n"
        "extern const char *PyWin_DLLVersionString;\n"
    )
    if guarded_externs in text:
        text = text.replace(guarded_externs, unguarded_externs, 1)

    desired_attrs = (
        "    if (PyWin_DLLhModule == NULL) {\n"
        "        PyWin_DLLhModule = GetModuleHandle(NULL);\n"
        "    }\n"
        "    SET_SYS(\"dllhandle\", PyLong_FromVoidPtr(PyWin_DLLhModule));\n"
        f"    SET_SYS_FROM_STRING(\"winver\", \"{version_mm}\");\n"
    )
    guarded_attrs = (
        "#ifdef MS_COREDLL\n"
        "    SET_SYS(\"dllhandle\", PyLong_FromVoidPtr(PyWin_DLLhModule));\n"
        "    SET_SYS_FROM_STRING(\"winver\", PyWin_DLLVersionString);\n"
        "#endif\n"
    )
    old_unguarded_attrs = (
        "    SET_SYS(\"dllhandle\", PyLong_FromVoidPtr(PyWin_DLLhModule));\n"
        "    SET_SYS_FROM_STRING(\"winver\", PyWin_DLLVersionString);\n"
    )
    old_versioned_attrs = (
        "    SET_SYS(\"dllhandle\", PyLong_FromVoidPtr(PyWin_DLLhModule));\n"
        f"    SET_SYS_FROM_STRING(\"winver\", \"{version_mm}\");\n"
    )
    if desired_attrs in text:
        pass
    elif guarded_attrs in text:
        text = text.replace(guarded_attrs, desired_attrs, 1)
    elif old_unguarded_attrs in text:
        text = text.replace(old_unguarded_attrs, desired_attrs, 1)
    elif old_versioned_attrs in text:
        text = text.replace(old_versioned_attrs, desired_attrs, 1)
    elif "    SET_SYS_FROM_STRING(\"winver\", PyWin_DLLVersionString);\n" in text:
        text = text.replace(
            old_unguarded_attrs,
            desired_attrs,
            1,
        )

    path.write_text(text, encoding="utf-8", newline="\n")


def patch_pyproject_props(source_root: Path) -> None:
    path = source_root / "PCbuild" / "pyproject.props"
    tree, root = load_msbuild_project(path)

    changed = False
    for item_definition_group in find_direct_children(root, "ItemDefinitionGroup"):
        for clcompile in find_direct_children(item_definition_group, "ClCompile"):
            if clcompile.get("Condition") is not None:
                continue
            whole_program_optimization = find_direct_child(clcompile, "WholeProgramOptimization")
            if whole_program_optimization is not None and (whole_program_optimization.text or "").strip().lower() == "false":
                whole_program_optimization.text = "true"
                changed = True

        for link in find_direct_children(item_definition_group, "Link"):
            for item in find_direct_children(link, "LinkTimeCodeGeneration"):
                if item.get("Condition") == "$(Configuration) == 'Release'" and (item.text or "").strip() == "Default":
                    item.text = "UseLinkTimeCodeGeneration"
                    changed = True

        for lib in find_direct_children(item_definition_group, "Lib"):
            for item in find_direct_children(lib, "LinkTimeCodeGeneration"):
                if item.get("Condition") == "$(Configuration) == 'Release'" and (item.text or "").strip().lower() == "false":
                    item.text = "true"
                    changed = True

    if changed:
        save_msbuild_project(path, tree)


def patch_pythoncore_vcxproj(source_root: Path, *, runtime_sdk: bool = False) -> None:
    path = source_root / "PCbuild" / "pythoncore.vcxproj"
    tree, root = load_msbuild_project(path)

    configuration_types = list(root.iter(msbuild_tag("ConfigurationType")))
    if not configuration_types:
        raise RuntimeError(f"expected <ConfigurationType> block not found in {path}")
    for configuration_type in configuration_types:
        configuration_type.text = "StaticLibrary"

    ensure_release_x64_runtime_library(root)
    ensure_vcpkg_property_group(root)
    ensure_clcompile_preprocessor_token(root, "Py_NO_ENABLE_SHARED")

    frozen_c = None
    for item_group in find_direct_children(root, "ItemGroup"):
        for child in item_group:
            if child.tag == msbuild_tag("ClCompile") and child.get("Include") == "..\\Python\\frozen.c":
                frozen_c = child
                break
        if frozen_c is not None:
            break
    if frozen_c is None:
        raise RuntimeError(f"expected ..\\Python\\frozen.c entry not found in {path}")

    set_frozen_data_compile_options(frozen_c)

    # Leave file-specific getpath.c definitions alone. Earlier builds may have
    # appended Py_NO_ENABLE_SHARED here by mistake, which breaks the multiline block.
    for item_group in find_direct_children(root, "ItemGroup"):
        for child in item_group:
            if child.tag != msbuild_tag("ClCompile") or child.get("Include") != "..\\Modules\\getpath.c":
                continue
            preprocessor = find_direct_child(child, "PreprocessorDefinitions")
            if preprocessor is None or preprocessor.text is None:
                continue
            preprocessor.text = re.sub(
                r"\s*;Py_NO_ENABLE_SHARED;%\(PreprocessorDefinitions\)",
                "",
                preprocessor.text,
                count=1,
            )

    removable_sources = {"..\\Modules\\challenge.c", "..\\Modules\\sandbox.c"}
    if runtime_sdk:
        removable_sources.add("..\\Modules\\main.c")
    for item_group in find_direct_children(root, "ItemGroup"):
        for child in list(item_group):
            include = (child.get("Include") or "").replace("/", "\\")
            if child.tag == msbuild_tag("ClCompile") and include in removable_sources:
                item_group.remove(child)

    resource_store_include = "..\\Python\\staticpython_resource_store.c"
    resource_store_compile = None
    for item_group in find_direct_children(root, "ItemGroup"):
        for child in item_group:
            if child.tag == msbuild_tag("ClCompile") and child.get("Include") == resource_store_include:
                resource_store_compile = child
                break
        if resource_store_compile is not None:
            break
    if runtime_sdk and resource_store_compile is not None:
        for item_group in find_direct_children(root, "ItemGroup"):
            if resource_store_compile in list(item_group):
                item_group.remove(resource_store_compile)
                break
    elif not runtime_sdk and resource_store_compile is None:
        item_group = ensure_item_group_with_tag(root, "ClCompile")
        resource_store_compile = ET.SubElement(item_group, msbuild_tag("ClCompile"))
        resource_store_compile.set("Include", resource_store_include)
    if not runtime_sdk and resource_store_compile is not None:
        set_frozen_data_compile_options(resource_store_compile)

    save_msbuild_project(path, tree)


def patch_freeze_module_vcxproj(source_root: Path) -> None:
    path = source_root / "PCbuild" / "_freeze_module.vcxproj"
    tree, root = load_msbuild_project(path)

    ensure_vcpkg_property_group(root)

    for target in root.iter(msbuild_tag("Target")):
        if target.get("Name") not in {"_RebuildFrozen", "_RebuildDeepFrozen", "_RebuildGetPath"}:
            continue
        condition = target.get("Condition") or ""
        skip_guard = "'$(StaticPythonSkipRebuildFrozen)' != 'true'"
        if skip_guard in condition:
            continue
        if condition.strip():
            target.set("Condition", f"{condition} and {skip_guard}")
        else:
            target.set("Condition", skip_guard)

    save_msbuild_project(path, tree)


def patch_python_vcxproj(source_root: Path, manifest: dict, integrations: list) -> None:
    path = source_root / "PCbuild" / "python.vcxproj"
    tree, root = load_msbuild_project(path)
    desired_projects = iter_native_static_projects(source_root, manifest, integrations)

    ensure_clcompile_preprocessor_token(root, "Py_NO_ENABLE_SHARED")
    ensure_release_x64_runtime_library(root)
    ensure_vcpkg_property_group(root)
    remove_redundant_release_x64_link_groups(root)
    ensure_link_child_text(
        root,
        "AdditionalDependencies",
        build_python_link_dependencies(source_root, manifest, integrations),
        condition=MSBUILD_RELEASE_X64_CONDITION,
    )
    ensure_link_child_text(
        root,
        "AdditionalOptions",
        build_python_link_options(source_root, manifest, integrations),
        condition=MSBUILD_RELEASE_X64_CONDITION,
    )
    sync_python_project_references(root, desired_projects)

    for project in desired_projects:
        ensure_project_reference(root, project["project"], project["guid"])

    save_msbuild_project(path, tree)


def patch_pc_config(
    source_root: Path,
    manifest: dict,
    integrations: list,
    *,
    runtime_sdk: bool = False,
) -> None:
    path = source_root / "PC" / "config.c"
    text = path.read_text(encoding="utf-8")

    for needle in (
        "extern PyObject* PyInit_challenge(void);",
        "extern PyObject* PyInit_sandbox(void);",
        '{"challenge", PyInit_challenge},',
        '{"sandbox", PyInit_sandbox},',
    ):
        text = remove_line_contains(text, needle)

    registrations = list(
        dict.fromkeys(
            (builtin["name"], builtin["pyinit"])
            for builtin in iter_builtin_module_registrations(source_root, manifest, integrations)
        )
    )
    baseline_extern_lines = [
        "extern PyObject* PyMarshal_Init(void);",
        "extern PyObject* PyInit__imp(void);",
    ]
    if not runtime_sdk:
        baseline_extern_lines.append("extern PyObject* PyInit__staticpython_resource_store(void);")
    extern_lines = [*baseline_extern_lines, *[f"extern PyObject* {pyinit}(void);" for _, pyinit in registrations]]
    table_lines = [f'    {{"{name}", {pyinit}}},' for name, pyinit in registrations]
    if not runtime_sdk:
        table_lines.insert(0, f'    {{"{RUNTIME_RESOURCE_STORE_MODULE}", PyInit__staticpython_resource_store}},')
    extern_body = "\n" if not extern_lines else "\n" + "\n\n".join(extern_lines) + "\n\n"
    table_body = "\n" if not table_lines else "\n" + "\n\n".join(table_lines) + "\n\n"
    marker_1 = "/* -- ADDMODULE MARKER 1 -- */\n"
    marker_2 = "/* -- ADDMODULE MARKER 2 -- */\n"
    inittab_anchor = "struct _inittab _PyImport_Inittab[] = {\n"
    builtin_entries_anchor = '    /* This module "lives in" with marshal.c */\n'
    text = replace_section_between_anchors(text, marker_1, inittab_anchor, extern_body, path=path)
    text = replace_section_between_anchors(text, marker_2, builtin_entries_anchor, table_body, path=path)

    path.write_text(text, encoding="utf-8", newline="\n")


def apply_patches(
    source_root: Path,
    version_info: tuple[int, int, int],
    version_mm: str,
    version_full: str,
    manifest: dict,
    integrations: list,
    platform: str,
    configuration: str,
    *,
    runtime_sdk: bool = False,
) -> None:
    hook_context = make_library_hook_context(source_root, version_info, version_mm, version_full, configuration, platform)
    run_pre_patch_hooks(integrations, hook_context)
    patch_site_py(source_root, version_mm)
    patch_modules_getpath_py(source_root)
    patch_generate_sbom_py(source_root)
    patch_pc_config_minimal_c(source_root)
    patch_pc_dl_nt_c(source_root)
    patch_python_sysmodule_c(source_root, version_mm)
    patch_pyproject_props(source_root)
    patch_pythoncore_vcxproj(source_root, runtime_sdk=runtime_sdk)
    patch_freeze_module_vcxproj(source_root)
    patch_python_vcxproj(source_root, manifest, integrations)
    patch_static_library_projects(source_root, manifest, integrations)
    patch_pc_config(source_root, manifest, integrations, runtime_sdk=runtime_sdk)
    run_post_patch_hooks(integrations, hook_context)
    write_runtime_resource_module(source_root, integrations, pack_descriptor=runtime_sdk)


def verify_source_root(source_root: Path) -> None:
    required = [
        source_root / "PCbuild" / "python.vcxproj",
        source_root / "PCbuild" / "pythoncore.vcxproj",
        source_root / "PC" / "config.c",
        source_root / "Lib" / "site.py",
        source_root / "PCbuild" / "pcbuild.sln",
        source_root / "Include" / "patchlevel.h",
    ]
    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("source root does not look like a CPython tree:\n" + "\n".join(missing))


def ensure_tool(name: str) -> None:
    if name.lower() == "msbuild":
        resolve_msbuild_exe()
        return
    if shutil.which(name) is None:
        raise RuntimeError(
            f"required tool not found on PATH: {name}. Run this inside the VS2022 Developer PowerShell / DevShell."
        )


def download_file(url: str, destination: Path, *, force: bool = False) -> None:
    if destination.exists() and not force:
        log(f"using cached download {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    log(f"downloading {url}")
    temporary = Path(str(destination) + ".tmp")
    with urlopen(url) as response, temporary.open("wb") as out_file:
        shutil.copyfileobj(response, out_file)
    temporary.replace(destination)


def validate_source_archive(archive_path: Path) -> None:
    suffixes = "".join(archive_path.suffixes).lower()
    if suffixes.endswith(".zip"):
        with ZipFile(archive_path) as archive:
            archive_top_level_from_zip(archive)
            bad_member = archive.testzip()
            if bad_member is not None:
                raise RuntimeError(f"corrupt zip archive member: {bad_member}")
        return
    if suffixes.endswith((".tar.gz", ".tgz", ".tar")):
        mode = "r:gz" if suffixes.endswith((".tar.gz", ".tgz")) else "r:"
        with tarfile.open(archive_path, mode) as archive:
            archive_top_level_from_tar(archive)
        return


def _cleanup_failed_download(destination: Path) -> None:
    if destination.exists():
        destination.unlink()
    temporary = Path(str(destination) + ".tmp")
    if temporary.exists():
        temporary.unlink()


def download_first_available(urls: list[str], destination: Path) -> str:
    if destination.exists():
        try:
            validate_source_archive(destination)
        except (BadZipFile, EOFError, OSError, RuntimeError, tarfile.TarError) as exc:
            log(f"discarding invalid cached download {destination}: {exc}")
            _cleanup_failed_download(destination)
        else:
            log(f"using cached download {destination}")
            return str(destination)

    errors: list[str] = []
    for url in urls:
        for attempt in range(1, 3):
            try:
                download_file(url, destination, force=True)
                validate_source_archive(destination)
                return url
            except (BadZipFile, EOFError, HTTPError, OSError, RuntimeError, tarfile.TarError, URLError) as exc:
                errors.append(f"{url} (attempt {attempt}/2): {exc}")
                _cleanup_failed_download(destination)
                log(f"download failed from {url} on attempt {attempt}/2: {exc}")
    raise RuntimeError("all download sources failed:\n" + "\n".join(errors))


def archive_top_level_from_zip(archive: ZipFile) -> str:
    top_level = {
        name.split("/", 1)[0]
        for name in archive.namelist()
        if name and "/" in name
    }
    if len(top_level) != 1:
        raise RuntimeError("unexpected zip archive layout")
    return next(iter(top_level))


def archive_top_level_from_tar(archive: tarfile.TarFile) -> str:
    top_level = {
        name.split("/", 1)[0]
        for name in archive.getnames()
        if name and "/" in name
    }
    if len(top_level) != 1:
        raise RuntimeError("unexpected tar archive layout")
    return next(iter(top_level))


def is_windows_reserved_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    for part in normalized.split("/"):
        if not part or part in {".", ".."}:
            continue
        basename = part.split(".", 1)[0].rstrip(" ").upper()
        if basename in WINDOWS_RESERVED_BASENAMES:
            return True
    return False


def ensure_safe_archive_member(destination_root: Path, member_name: str) -> bool:
    if is_windows_reserved_path(member_name):
        log(f"skip archive member with Windows reserved name: {member_name}")
        return False
    target = (destination_root / member_name).resolve()
    root = destination_root.resolve()
    if target != root and root not in target.parents:
        raise RuntimeError(f"archive member escapes destination: {member_name}")
    return True


def safe_extract_zip(archive: ZipFile, destination_root: Path) -> None:
    for info in archive.infolist():
        if ensure_safe_archive_member(destination_root, info.filename):
            archive.extract(info, destination_root)


def safe_extract_tar(archive: tarfile.TarFile, destination_root: Path) -> None:
    for member in archive.getmembers():
        if ensure_safe_archive_member(destination_root, member.name):
            archive.extract(member, destination_root)


def extract_zip_archive(archive_path: Path, destination_root: Path, *, reuse_existing: bool = False) -> Path:
    with ZipFile(archive_path) as archive:
        top_level = archive_top_level_from_zip(archive)
        extracted_root = destination_root / top_level
        if extracted_root.exists():
            if reuse_existing and (extracted_root / "Include" / "patchlevel.h").exists():
                log(f"reusing existing extracted source tree at {extracted_root}")
                return extracted_root
            shutil.rmtree(extracted_root)
        safe_extract_zip(archive, destination_root)
    return extracted_root


def extract_source_archive(archive_path: Path, destination_root: Path, *, final_name: str | None = None) -> Path:
    destination_root.mkdir(parents=True, exist_ok=True)
    suffixes = "".join(archive_path.suffixes).lower()
    if suffixes.endswith(".zip"):
        with ZipFile(archive_path) as archive:
            extracted_name = archive_top_level_from_zip(archive)
            extracted_root = destination_root / extracted_name
            if extracted_root.exists():
                shutil.rmtree(extracted_root)
            safe_extract_zip(archive, destination_root)
    elif suffixes.endswith((".tar.gz", ".tgz", ".tar")):
        mode = "r:gz" if suffixes.endswith((".tar.gz", ".tgz")) else "r:"
        with tarfile.open(archive_path, mode) as archive:
            extracted_name = archive_top_level_from_tar(archive)
            extracted_root = destination_root / extracted_name
            if extracted_root.exists():
                shutil.rmtree(extracted_root)
            safe_extract_tar(archive, destination_root)
    else:
        raise RuntimeError(f"unsupported source archive format: {archive_path}")

    if final_name is None or extracted_root.name == final_name:
        return extracted_root

    final_root = destination_root / final_name
    if final_root.exists():
        shutil.rmtree(final_root)
    extracted_root.rename(final_root)
    return final_root


def download_cpython_source(
    version: str,
    download_root: Path,
    source_archive_url: str | None,
    *,
    reuse_existing: bool = False,
) -> Path:
    download_root.mkdir(parents=True, exist_ok=True)
    archive_url = source_archive_url or CPYTHON_ARCHIVE_URL_TEMPLATE.format(version=version)
    archive_path = download_root / f"cpython-v{version}.zip"
    download_file(archive_url, archive_path)
    source_root = extract_zip_archive(archive_path, download_root, reuse_existing=reuse_existing)
    commit = resolve_cpython_tag_commit(version) if source_archive_url is None else None
    write_cpython_source_provenance(
        source_root,
        version=version,
        archive_url=archive_url,
        archive_path=archive_path,
        commit=commit,
    )
    log(f"downloaded source tree to {source_root}")
    return source_root


def resolve_source_root(args: argparse.Namespace) -> tuple[Path, tuple[int, int, int] | None]:
    requested_version_info: tuple[int, int, int] | None = None
    requested_version_text = args.cpython_version
    if requested_version_text is None and args.source_root is None and args.source_archive_path is None:
        requested_version_text = DEFAULT_CPYTHON_VERSION
    if requested_version_text:
        normalized_version, requested_version_info = parse_version_string(requested_version_text)
        if args.source_root is None:
            download_root = (args.download_root or (REPO_ROOT / "downloads")).resolve()
            if args.source_archive_path is not None:
                source_root = extract_zip_archive(
                    args.source_archive_path.resolve(),
                    download_root,
                    reuse_existing=args.reuse_source_tree,
                )
                log(f"extracted local source archive to {source_root}")
                return source_root, requested_version_info
            source_root = download_cpython_source(
                normalized_version,
                download_root,
                args.source_archive_url,
                reuse_existing=args.reuse_source_tree,
            )
            return source_root, requested_version_info
    elif args.source_root is None and args.source_archive_path is not None:
        download_root = (args.download_root or (REPO_ROOT / "downloads")).resolve()
        source_root = extract_zip_archive(
            args.source_archive_path.resolve(),
            download_root,
            reuse_existing=args.reuse_source_tree,
        )
        log(f"extracted local source archive to {source_root}")
        return source_root, requested_version_info
    if args.source_root is None:
        raise RuntimeError("provide a CPython source_root, --cpython-version, or --source-archive-path")
    return args.source_root.resolve(), requested_version_info


def platform_output_dir_name(platform: str) -> str:
    return {
        "x64": "amd64",
        "Win32": "win32",
        "ARM64": "arm64",
        "ARM": "arm",
    }.get(platform, platform)


def get_pcbuild_output_dir(source_root: Path, platform: str) -> Path:
    return source_root / "PCbuild" / platform_output_dir_name(platform)


def find_external_source(source_root: Path, prefix: str, *, require_file: str) -> Path | None:
    externals = source_root / "externals"
    if not externals.exists():
        return None
    candidates = sorted(
        path
        for path in externals.iterdir()
        if path.is_dir() and path.name.startswith(prefix) and (path / require_file).exists()
    )
    if not candidates:
        return None
    return candidates[-1]


def ensure_freeze_module_exe(
    source_root: Path,
    configuration: str,
    platform: str,
    build_workers: int | None = None,
) -> Path:
    pcbuild = source_root / "PCbuild"
    output_exe = get_pcbuild_output_dir(source_root, platform) / "_freeze_module.exe"
    run(
        [
            resolve_msbuild_exe(),
            str(pcbuild / "_freeze_module.vcxproj"),
            *msbuild_args(
                configuration,
                platform,
                "StaticPythonSkipRebuildFrozen=true",
                workers=build_workers,
            ),
        ],
        cwd=source_root,
    )
    if output_exe.exists():
        return output_exe

    obj_candidates = sorted(
        (source_root / "PCbuild" / "obj").rglob("_freeze_module.exe"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    if obj_candidates:
        output_exe.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(obj_candidates[0], output_exe)
        log(f"restored {output_exe.relative_to(source_root)} from {obj_candidates[0].relative_to(source_root)}")

    if not output_exe.exists():
        raise RuntimeError(f"build did not produce {output_exe}")
    return output_exe


def stage_static_libraries(source_root: Path, platform: str, manifest: dict, integrations: list) -> None:
    output_dir = get_pcbuild_output_dir(source_root, platform)
    output_dir.mkdir(parents=True, exist_ok=True)
    substitutions = {
        "platform_output_dir": platform_output_dir_name(platform),
        "vcpkg_root": os.environ.get("VCPKG_ROOT", ""),
        "vcpkg_static_triplet": f"{platform.lower()}-windows-static" if platform.lower() != "win32" else "x86-windows-static",
    }

    for entry in iter_staged_static_libraries(manifest, integrations):
        patterns = [entry["source_glob"], *entry.get("fallback_globs", [])]
        source_path: Path | None = None
        attempted: list[str] = []
        for pattern_template in patterns:
            pattern = pattern_template.format(**substitutions)
            attempted.append(pattern)
            if any(token in pattern for token in "*?[]"):
                matches = sorted(source_root.glob(pattern))
                if matches:
                    source_path = matches[-1]
                    break
                continue

            candidate = Path(pattern)
            if not candidate.is_absolute():
                candidate = source_root / candidate
            if candidate.exists():
                source_path = candidate
                break

        if source_path is None:
            raise RuntimeError(
                f"no files matched any staging source for {entry['target_name']}: {attempted}"
            )
        destination = output_dir / entry["target_name"]
        shutil.copy2(source_path, destination)
        try:
            source_label = str(source_path.relative_to(source_root))
        except ValueError:
            source_label = str(source_path)
        log(f"staged {destination.relative_to(source_root)} from {source_label}")


def freeze_modules(
    source_root: Path,
    host_python: str,
    configuration: str,
    platform: str,
    version_info: tuple[int, int, int],
    build_workers: int | None = None,
) -> None:
    freeze_exe = ensure_freeze_module_exe(source_root, configuration, platform, build_workers)
    run([host_python, str(source_root / "Tools" / "build" / "freeze_modules.py"), "--step=0"], cwd=source_root)
    run([host_python, str(source_root / "Tools" / "build" / "freeze_modules.py"), "--step=1"], cwd=source_root)
    maybe_freeze_getpath_header(source_root, freeze_exe)
    if supports_pyrepl(version_info):
        run(
            [
                str(freeze_exe),
                "_pyrepl",
                str(source_root / "Lib" / "_pyrepl" / "__main__.py"),
                str(source_root / "Python" / "frozen_modules" / "_pyrepl.h"),
            ],
            cwd=source_root,
        )
    else:
        log("skip standalone _pyrepl freezing for CPython < 3.13")


def verify_runtime_resource_modules_frozen(source_root: Path) -> None:
    module_paths = _runtime_resource_module_paths(source_root)
    if not module_paths:
        raise RuntimeError(
            "runtime resource module generation did not produce any Lib/_staticpython_runtime_resources*.py files"
        )

    frozen_dir = source_root / "Python" / "frozen_modules"
    frozen_c = source_root / "Python" / "frozen.c"
    frozen_c_text = frozen_c.read_text(encoding="utf-8") if frozen_c.exists() else ""
    missing_headers: list[str] = []
    missing_registry: list[str] = []
    module_names = ["_staticpython_runtime", *[path.stem for path in module_paths]]

    for module_name in module_names:
        if not (frozen_dir / f"{module_name}.h").exists():
            missing_headers.append(f"Python/frozen_modules/{module_name}.h")
        if f'"{module_name}"' not in frozen_c_text:
            missing_registry.append(module_name)

    if missing_headers or missing_registry:
        details = []
        if missing_headers:
            details.append("missing frozen headers:")
            details.extend(missing_headers)
        if missing_registry:
            details.append("missing frozen registry entries:")
            details.extend(missing_registry)
        raise RuntimeError(
            "runtime resource modules were generated but not frozen into the CPython build:\n"
            + "\n".join(details)
        )

    log(f"verified {len(module_names)} runtime resource module(s) are present in frozen_modules and frozen.c")


FROZEN_INCLUDE_RE = re.compile(r'^#include "frozen_modules/([^"\r\n]+\.h)"\r?$', re.MULTILINE)
FROZEN_HEADER_SYMBOL_RE = re.compile(rb"const\s+unsigned\s+char\s+([A-Za-z0-9_]+)\[\]\s*=")
FROZEN_SIZEOF_RE = re.compile(r"\(int\)sizeof\((_Py_M_[A-Za-z0-9_]+)\)")


def parse_frozen_header_info(path: Path) -> tuple[str, int]:
    data = path.read_bytes()
    match = FROZEN_HEADER_SYMBOL_RE.search(data)
    if match is None:
        raise RuntimeError(f"could not find frozen data symbol in {path}")

    initializer_start = data.find(b"{", match.end())
    initializer_end = data.find(b"};", initializer_start)
    if initializer_start < 0 or initializer_end < 0:
        raise RuntimeError(f"could not find frozen data initializer in {path}")

    symbol = match.group(1).decode("ascii")
    size = data[initializer_start + 1 : initializer_end].count(b",")
    return symbol, size


def frozen_module_name_from_include(include_name: str) -> str:
    if not include_name.endswith(".h"):
        raise RuntimeError(f"unexpected frozen header include name: {include_name!r}")
    return include_name[:-2]


def unique_frozen_symbol(symbol: str, include_name: str, used_symbols: set[str]) -> str:
    if symbol not in used_symbols:
        used_symbols.add(symbol)
        return symbol

    module_name = frozen_module_name_from_include(include_name)
    stem = re.sub(r"[^0-9A-Za-z_]", "_", module_name)
    candidate = f"_Py_M__staticpython_{stem}"
    suffix = 2
    while candidate in used_symbols:
        candidate = f"_Py_M__staticpython_{stem}_{suffix}"
        suffix += 1
    used_symbols.add(candidate)
    return candidate


def rewrite_frozen_header_symbol(path: Path, old_symbol: str, new_symbol: str) -> None:
    if old_symbol == new_symbol:
        return
    old_bytes = old_symbol.encode("ascii")
    new_bytes = new_symbol.encode("ascii")
    data = path.read_bytes()
    if old_bytes not in data:
        raise RuntimeError(f"could not find frozen data symbol {old_symbol} in {path}")
    path.write_bytes(data.replace(old_bytes, new_bytes))


def patch_frozen_registry_symbol(text: str, module_name: str, old_symbol: str, new_symbol: str) -> str:
    if old_symbol == new_symbol:
        return text
    old_entry = f'{{"{module_name}", {old_symbol}, (int)sizeof({old_symbol}),'
    new_entry = f'{{"{module_name}", {new_symbol}, (int)sizeof({new_symbol}),'
    if old_entry not in text:
        raise RuntimeError(f"could not find frozen registry entry for {module_name}")
    return text.replace(old_entry, new_entry, 1)


def chunk_frozen_headers(records: list[dict]) -> list[list[dict]]:
    chunks: list[list[dict]] = []
    chunk_sizes: list[int] = []

    for record in sorted(records, key=lambda item: (-item["file_bytes"], item["source_index"])):
        file_bytes = record["file_bytes"]
        placed = False
        for index, current_bytes in enumerate(chunk_sizes):
            if current_bytes + file_bytes > FROZEN_DATA_SHARD_BYTES:
                continue
            chunks[index].append(record)
            chunk_sizes[index] += file_bytes
            placed = True
            break
        if placed:
            continue
        chunks.append([record])
        chunk_sizes.append(file_bytes)

    for chunk in chunks:
        chunk.sort(key=lambda item: item["source_index"])
    return chunks


def existing_frozen_data_sources(source_root: Path) -> list[Path]:
    python_dir = source_root / "Python"
    return sorted(python_dir.glob(f"{FROZEN_DATA_SOURCE_PREFIX}*.c"))


def pythoncore_references_legacy_deepfreeze(source_root: Path) -> bool:
    path = source_root / "PCbuild" / "pythoncore.vcxproj"
    if not path.exists():
        return False
    tree, root = load_msbuild_project(path)
    for item_group in find_direct_children(root, "ItemGroup"):
        for child in item_group:
            if child.tag != msbuild_tag("ClCompile"):
                continue
            include = (child.get("Include") or "").replace("/", "\\")
            if include == "..\\Python\\deepfreeze\\deepfreeze.c":
                return True
    return False


def write_legacy_deepfreeze_stub(source_root: Path) -> None:
    target = source_root / "Python" / "deepfreeze" / "deepfreeze.c"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "\n".join(
            [
                "/* Auto-generated by StaticPython. Do not edit. */",
                "",
                "#include \"Python.h\"",
                "#include <stdint.h>",
                "",
                "int",
                "_Py_Deepfreeze_Init(void)",
                "{",
                "    return 0;",
                "}",
                "",
                "void",
                "_Py_Deepfreeze_Fini(void)",
                "{",
                "}",
                "",
                "uint32_t _Py_next_func_version = 1;",
                "",
            ]
        ),
        encoding="utf-8",
        newline="\n",
    )


def patch_pythoncore_frozen_data_sources(source_root: Path, shard_names: list[str]) -> None:
    path = source_root / "PCbuild" / "pythoncore.vcxproj"
    tree, root = load_msbuild_project(path)

    frozen_item_group = None
    frozen_index = None
    for item_group in find_direct_children(root, "ItemGroup"):
        for child in list(item_group):
            if child.tag != msbuild_tag("ClCompile"):
                continue
            include = child.get("Include") or ""
            normalized = include.replace("/", "\\")
            if normalized.startswith(f"..\\Python\\{FROZEN_DATA_SOURCE_PREFIX}") and normalized.endswith(".c"):
                item_group.remove(child)
                continue
            if normalized == "..\\Python\\frozen.c":
                frozen_item_group = item_group
                frozen_index = list(item_group).index(child) + 1

    if not shard_names:
        save_msbuild_project(path, tree)
        return

    if frozen_item_group is None:
        raise RuntimeError(f"expected ..\\Python\\frozen.c entry not found in {path}")

    insert_at = frozen_index if frozen_index is not None else len(frozen_item_group)
    for offset, shard_name in enumerate(shard_names):
        clcompile = ET.Element(msbuild_tag("ClCompile"))
        clcompile.set("Include", f"..\\Python\\{shard_name}")
        set_frozen_data_compile_options(clcompile)
        frozen_item_group.insert(insert_at + offset, clcompile)

    save_msbuild_project(path, tree)


def split_frozen_modules(source_root: Path) -> None:
    frozen_c = source_root / "Python" / "frozen.c"
    if not frozen_c.exists():
        raise RuntimeError(f"expected frozen module registry not found: {frozen_c}")

    text = frozen_c.read_text(encoding="utf-8")
    include_matches = list(FROZEN_INCLUDE_RE.finditer(text))
    if not include_matches:
        shards = existing_frozen_data_sources(source_root)
        if shards:
            if pythoncore_references_legacy_deepfreeze(source_root):
                write_legacy_deepfreeze_stub(source_root)
            patch_pythoncore_frozen_data_sources(source_root, [path.name for path in shards])
            log(f"frozen module data already split across {len(shards)} shard(s)")
        else:
            log("skip frozen module data split because no frozen module includes were found")
        return

    records = []
    symbol_sizes: dict[str, int] = {}
    used_symbols: set[str] = set()
    renamed_symbols: list[tuple[str, str, str]] = []
    frozen_modules_dir = source_root / "Python" / "frozen_modules"
    for source_index, match in enumerate(include_matches):
        include_name = match.group(1)
        header_path = frozen_modules_dir / include_name
        if not header_path.exists():
            raise RuntimeError(f"frozen module include has no generated header: {header_path}")
        symbol, size = parse_frozen_header_info(header_path)
        unique_symbol = unique_frozen_symbol(symbol, include_name, used_symbols)
        if unique_symbol != symbol:
            rewrite_frozen_header_symbol(header_path, symbol, unique_symbol)
            renamed_symbols.append((frozen_module_name_from_include(include_name), symbol, unique_symbol))
        symbol_sizes[unique_symbol] = size
        records.append(
            {
                "include_name": include_name,
                "module_name": frozen_module_name_from_include(include_name),
                "symbol": unique_symbol,
                "size": size,
                "file_bytes": header_path.stat().st_size,
                "source_index": source_index,
            }
        )

    python_dir = source_root / "Python"
    for stale in existing_frozen_data_sources(source_root):
        stale.unlink()

    shard_names = []
    for index, chunk in enumerate(chunk_frozen_headers(records)):
        shard_name = f"{FROZEN_DATA_SOURCE_PREFIX}{index:0{FROZEN_DATA_SHARD_DIGITS}d}.c"
        shard_names.append(shard_name)
        lines = [
            "/* Auto-generated by StaticPython. Do not edit. */",
            "",
        ]
        lines.extend(f'#include "frozen_modules/{record["include_name"]}"' for record in chunk)
        lines.append("")
        (python_dir / shard_name).write_text("\n".join(lines), encoding="utf-8", newline="\n")

    extern_lines = [
        "/* Frozen module bytecode data is compiled in StaticPython shards. */",
    ]
    extern_lines.extend(f"extern const unsigned char {record['symbol']}[];" for record in records)
    extern_block = "\n".join(extern_lines) + "\n"

    include_start = include_matches[0].start()
    include_end = include_matches[-1].end()
    if text[include_end : include_end + 2] == "\r\n":
        include_end += 2
    elif text[include_end : include_end + 1] == "\n":
        include_end += 1
    text = text[:include_start] + extern_block + text[include_end:]

    for module_name, old_symbol, new_symbol in renamed_symbols:
        text = patch_frozen_registry_symbol(text, module_name, old_symbol, new_symbol)

    for symbol, size in symbol_sizes.items():
        text = text.replace(f"(int)sizeof({symbol})", str(size))

    unresolved_sizeof = sorted(set(FROZEN_SIZEOF_RE.findall(text)))
    if unresolved_sizeof:
        raise RuntimeError(
            "could not resolve frozen module sizes for: "
            + ", ".join(unresolved_sizeof[:20])
            + (" ..." if len(unresolved_sizeof) > 20 else "")
        )

    frozen_c.write_text(text, encoding="utf-8", newline="\n")
    if pythoncore_references_legacy_deepfreeze(source_root):
        write_legacy_deepfreeze_stub(source_root)
    patch_pythoncore_frozen_data_sources(source_root, shard_names)
    total_bytes = sum(record["file_bytes"] for record in records)
    log(
        "split frozen module data into "
        f"{len(shard_names)} shard(s) from {len(records)} module header(s), "
        f"{total_bytes // (1024 * 1024)} MiB total"
    )
    if renamed_symbols:
        log(f"renamed {len(renamed_symbols)} duplicate frozen symbol(s)")


def getpath_header_required(source_root: Path) -> bool:
    getpath_c = source_root / "Modules" / "getpath.c"
    if not getpath_c.exists():
        return False
    text = getpath_c.read_text(encoding="utf-8", errors="ignore")
    return "Python/frozen_modules/getpath.h" in text


def maybe_freeze_getpath_header(source_root: Path, freeze_exe: Path) -> None:
    if not getpath_header_required(source_root):
        return

    source = source_root / "Modules" / "getpath.py"
    target = source_root / "Python" / "frozen_modules" / "getpath.h"
    if not source.exists():
        raise RuntimeError(f"getpath header is required but {source.relative_to(source_root)} is missing")

    target.parent.mkdir(parents=True, exist_ok=True)
    run([str(freeze_exe), "getpath", str(source), str(target)], cwd=source_root)


def maybe_restore_getpath_header(source_root: Path, version_info: tuple[int, int, int]) -> None:
    search_root = source_root / "PCbuild" / "obj"
    source_target = source_root / "Python" / "frozen_modules" / "getpath.h"
    candidate_paths: list[Path] = []

    if search_root.exists():
        candidate_paths.extend(search_root.rglob("getpath.g.h"))
        candidate_paths.extend(search_root.rglob("getpath.h"))

    if source_target.exists():
        candidate_paths.append(source_target)

    if not candidate_paths:
        log("skip getpath.h restore because no getpath header candidate was found")
        return

    candidate = max(candidate_paths, key=lambda item: item.stat().st_mtime)

    if candidate.resolve() != source_target.resolve():
        source_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, source_target)
        log(f"restored {source_target.relative_to(source_root)} from {candidate.relative_to(source_root)}")

    source_frozen_dir = source_root / "Python" / "frozen_modules"
    generated_target_dir = (
        source_root
        / "PCbuild"
        / "obj"
        / f"{version_info[0]}{version_info[1]}_frozen"
        / "Python"
        / "frozen_modules"
    )
    generated_target_dir.mkdir(parents=True, exist_ok=True)

    copied = 0
    for path in source_frozen_dir.rglob("*"):
        if not path.is_file():
            continue
        target = generated_target_dir / path.relative_to(source_frozen_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, target)
        copied += 1

    log(
        "synced "
        f"{copied} frozen module files to "
        f"{generated_target_dir.relative_to(source_root)}"
    )


def build_python(
    source_root: Path,
    configuration: str,
    platform: str,
    manifest: dict,
    integrations: list,
    version_info: tuple[int, int, int],
    version_mm: str,
    version_full: str,
    static_project_filter: set[str] | None = None,
    static_project_start: str | None = None,
    use_prebuilt_static_libraries: bool = False,
    build_workers: int | None = None,
    *,
    runtime_sdk: bool = False,
) -> None:
    pcbuild = source_root / "PCbuild"
    run_pre_build_hooks(
        integrations,
        make_library_hook_context(source_root, version_info, version_mm, version_full, configuration, platform),
    )
    stage_static_libraries(source_root, platform, manifest, integrations)

    available_projects = iter_static_library_projects(source_root, manifest, integrations)
    if use_prebuilt_static_libraries:
        selected_projects = []
    elif static_project_filter is None:
        selected_projects = available_projects
    else:
        requested_projects = set()
        for requested in static_project_filter:
            requested_projects.add(requested.lower())
            if not requested.lower().endswith(".vcxproj"):
                requested_projects.add(f"{requested.lower()}.vcxproj")

        selected_projects = []
        matched_requests = set()
        for project in available_projects:
            keys = {project.lower(), Path(project).stem.lower()}
            if keys & requested_projects:
                selected_projects.append(project)
                matched_requests.update(keys & requested_projects)

        missing_projects = []
        for requested in static_project_filter:
            keys = {requested.lower()}
            if not requested.lower().endswith(".vcxproj"):
                keys.add(f"{requested.lower()}.vcxproj")
            if not keys & matched_requests:
                missing_projects.append(requested)

        if missing_projects:
            available = ", ".join(sorted(available_projects)) or "<none>"
            raise RuntimeError(
                "unknown static project(s) for incremental build: "
                + ", ".join(missing_projects)
                + f"; available projects: {available}"
            )

    if static_project_start:
        start_keys = {static_project_start.lower()}
        if not static_project_start.lower().endswith(".vcxproj"):
            start_keys.add(f"{static_project_start.lower()}.vcxproj")
        start_index = None
        for index, project in enumerate(selected_projects):
            if {project.lower(), Path(project).stem.lower()} & start_keys:
                start_index = index
                break
        if start_index is None:
            available = ", ".join(selected_projects) or "<none>"
            raise RuntimeError(
                f"static project start {static_project_start!r} was not found; selected projects: {available}"
            )
        selected_projects = selected_projects[start_index:]

    if use_prebuilt_static_libraries:
        log("skipping native static library project builds because prebuilt static libraries were installed")
    else:
        log(f"building {len(selected_projects)} static library project(s)")
        for target in selected_projects:
            run(
                [
                    resolve_msbuild_exe(),
                    str(pcbuild / target),
                    *msbuild_args(configuration, platform, workers=build_workers),
                ],
                cwd=source_root,
            )

    final_build_properties = []
    if runtime_sdk or use_prebuilt_static_libraries or static_project_filter is not None or static_project_start is not None:
        run(
            [
                resolve_msbuild_exe(),
                str(pcbuild / "pythoncore.vcxproj"),
                *msbuild_args(
                    configuration,
                    platform,
                    "BuildProjectReferences=false",
                    workers=build_workers,
                ),
            ],
            cwd=source_root,
        )
        final_build_properties.append("BuildProjectReferences=false")

    if runtime_sdk:
        run(
            [
                resolve_msbuild_exe(),
                str(pcbuild / "staticpython_runtime.vcxproj"),
                *msbuild_args(
                    configuration,
                    platform,
                    "BuildProjectReferences=false",
                    workers=build_workers,
                ),
            ],
            cwd=source_root,
        )
        log("runtime-sdk build intentionally skipped python.vcxproj")
        return

    run(
        [
            resolve_msbuild_exe(),
            str(pcbuild / "python.vcxproj"),
            *msbuild_args(configuration, platform, *final_build_properties, workers=build_workers),
        ],
        cwd=source_root,
    )


def build_pack_static_libraries(
    source_root: Path,
    configuration: str,
    platform: str,
    integrations: list,
    version_info: tuple[int, int, int],
    version_mm: str,
    version_full: str,
    build_workers: int | None = None,
) -> None:
    """Build only native projects owned by selected third-party packs."""
    pcbuild = source_root / "PCbuild"
    run_pre_build_hooks(
        integrations,
        make_library_hook_context(
            source_root,
            version_info,
            version_mm,
            version_full,
            configuration,
            platform,
        ),
    )
    # Runtime/core libraries come from the separately audited runtime SDK.
    # An empty manifest prevents this candidate build from rebuilding the
    # CPython core project set while preserving integration-owned projects.
    stage_static_libraries(source_root, platform, {}, integrations)
    projects = iter_static_library_projects(source_root, {}, integrations)
    log(f"building {len(projects)} pack-owned static library project(s)")
    for target in projects:
        run(
            [
                resolve_msbuild_exe(),
                str(pcbuild / target),
                *msbuild_args(
                    configuration,
                    platform,
                    "BuildProjectReferences=false",
                    workers=build_workers,
                ),
            ],
            cwd=source_root,
        )
    log("pack-only build intentionally skipped pythoncore.vcxproj and python.vcxproj")


def verify_pack_only_with_runtime_sdk(
    source_root: Path,
    runtime_sdk: Path,
    provisional_packs: list[Path],
    host_python: str,
    build_workers: int | None,
) -> dict:
    report_path = source_root / "PCbuild" / "staticpython-pack-verify-report.json"
    work_dir = source_root / "PCbuild" / "staticpython-pack-verify"
    command = [
        host_python,
        str(REPO_ROOT / "scripts" / "verify_pack_with_runtime_sdk.py"),
        "--runtime-sdk",
        str(runtime_sdk),
        "--repo-root",
        str(REPO_ROOT),
        "--work-dir",
        str(work_dir),
        "--report-json",
        str(report_path),
    ]
    for pack in provisional_packs:
        command.extend(["--pack", str(pack)])
    if build_workers is not None:
        command.extend(["--build-workers", str(build_workers)])
    run(command, cwd=REPO_ROOT)
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not isinstance(report, dict) or report.get("status") != "passed":
        raise RuntimeError("runtime SDK pack verification did not produce a passed report")
    return report


def verify_built_python(
    source_root: Path,
    platform: str,
    manifest: dict,
    host_python: str,
    profile: str,
    config_path: Path,
    report_json: Path | None = None,
) -> Path:
    exe = get_pcbuild_output_dir(source_root, platform) / "python.exe"
    if not exe.exists():
        raise RuntimeError(f"build did not produce {exe}")
    config = load_config(config_path)
    _, selected_profile = resolve_profile(config, profile)
    verification_config = profile_verification_config(config, selected_profile)
    script_config = verification_config.get("script") if isinstance(verification_config, dict) else None
    verify_timeout = 60 * 20
    if isinstance(script_config, dict):
        verify_timeout = max(verify_timeout, int(float(script_config.get("timeout", 600))) + 300)
    command = [
        host_python,
        str(REPO_ROOT / "verify.py"),
        "--python-exe",
        str(exe),
        "--manifest",
        str(MANIFEST_PATH),
        "--repo-root",
        str(REPO_ROOT),
        "--source-root",
        str(source_root),
        "--profile",
        profile,
        "--config",
        str(config_path),
    ]
    if report_json is not None:
        command.extend(["--report-json", str(report_json)])
    run(
        command,
        cwd=REPO_ROOT,
        timeout=verify_timeout,
    )
    return exe


def export_built_python(exe_path: Path, output_dir: Path, version_full: str, platform: str, profile: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    asset_name = f"python-{version_full}-singlefile-{profile}-{platform.lower()}.exe"
    destination = output_dir / asset_name
    shutil.copy2(exe_path, destination)
    log(f"copied artifact to {destination}")
    return destination


def maybe_get_externals(source_root: Path) -> None:
    script = source_root / "PCbuild" / "get_externals.bat"
    text = script.read_text(encoding="utf-8", errors="ignore")
    args = ["cmd", "/c", "get_externals.bat"]
    if "--no-openssl" in text:
        args.append("--no-openssl")
    if "--no-libffi" in text:
        args.append("--no-libffi")
    run(args, cwd=source_root / "PCbuild")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Patch a CPython source tree and build a single-file static python.exe."
    )
    parser.add_argument("source_root", nargs="?", type=Path, help="Path to the CPython source tree")
    parser.add_argument(
        "--cpython-version",
        help="Download an official CPython tag by version, for example 3.13.2 or 3.12.10",
    )
    parser.add_argument(
        "--download-root",
        type=Path,
        help="Where downloaded CPython archives and extracted trees should be placed when using --cpython-version",
    )
    parser.add_argument(
        "--source-archive-url",
        help="Override the CPython source archive URL when using --cpython-version",
    )
    parser.add_argument(
        "--source-archive-path",
        type=Path,
        help="Use a local CPython source zip archive instead of downloading one",
    )
    parser.add_argument(
        "--reuse-source-tree",
        action="store_true",
        help=(
            "When downloading or extracting a CPython archive, reuse an existing extracted "
            "source tree instead of deleting it. Useful for incremental local builds."
        ),
    )
    parser.add_argument(
        "--host-python",
        default=sys.executable,
        help="Python executable used to run helper scripts such as freeze_modules.py",
    )
    parser.add_argument("--configuration", default="Release")
    parser.add_argument("--platform", default="x64")
    parser.add_argument(
        "--build-workers",
        type=int,
        help=(
            "MSBuild and cl.exe worker count. Defaults to STATICPYTHON_BUILD_WORKERS, "
            "or CPU count minus two."
        ),
    )
    parser.add_argument(
        "--profile",
        help="Build profile from config.json. Defaults to config.default_profile.",
    )
    parser.add_argument(
        "--config",
        type=Path,
        help="Use an alternate config JSON file. This is useful for incremental library-only test profiles.",
    )
    parser.add_argument("--skip-get-externals", action="store_true")
    parser.add_argument(
        "--skip-freeze",
        action="store_true",
        help="Skip freeze_modules.py and rebuild only native projects plus python.exe. Intended for incremental tests.",
    )
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument(
        "--pack-only",
        action="store_true",
        help=(
            "Freeze and build only selected third-party pack projects, without pythoncore or python.exe. "
            "Requires --output-pack-dir and, unless --skip-verify is used, --pack-runtime-sdk."
        ),
    )
    parser.add_argument(
        "--pack-runtime-sdk",
        type=Path,
        help=(
            "Audited runtime-sdk ZIP or extracted directory used to link and execute provisional "
            "packs in --pack-only mode before they can be exported as verification=passed."
        ),
    )
    parser.add_argument(
        "--build-static-project",
        action="append",
        default=[],
        metavar="PROJECT",
        help=(
            "Only build the named static library project before relinking python.exe. "
            "May be repeated and accepts either a project stem or a .vcxproj file name."
        ),
    )
    parser.add_argument(
        "--build-static-project-from",
        metavar="PROJECT",
        help=(
            "Build static library projects starting from this project in manifest order. "
            "Useful for resuming an interrupted incremental build."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Copy the finished single-file python.exe to this directory with a versioned filename",
    )
    parser.add_argument(
        "--output-static-lib-dir",
        type=Path,
        help=(
            "Export a reusable native static-library SDK zip to this directory. "
            "The package excludes pythoncore/python.exe and is meant for later local freeze + relink builds."
        ),
    )
    parser.add_argument(
        "--output-runtime-sdk-dir",
        type=Path,
        help=(
            "Export the PySuture runtime SDK. This is only valid with --profile runtime-sdk; "
            "the archive includes static CPython, headers, frozen stdlib, registration runtime, and link metadata."
        ),
    )
    parser.add_argument(
        "--output-pack-dir",
        type=Path,
        help=(
            "Export one StaticPythonPackV1 ZIP for each selected third-party integration. "
            "Packs contain only that integration's frozen modules, resources, native libraries, and metadata."
        ),
    )
    parser.add_argument(
        "--output-pack-name",
        action="append",
        default=[],
        metavar="NAME",
        help=(
            "Export only the named root integration from --output-pack-dir. May be repeated. "
            "Selected dependency integrations remain linked for verification but are not duplicated in this shard."
        ),
    )
    parser.add_argument(
        "--prebuilt-static-lib-sdk",
        type=Path,
        help=(
            "Reuse a previously exported static-library SDK (.zip or extracted directory). "
            "build.py will still regenerate frozen modules/resources locally, but it will skip rebuilding the packaged native static libraries."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    build_workers = resolve_build_workers(args.build_workers)
    source_root, requested_version_info = resolve_source_root(args)
    export_static_lib_only = (
        args.skip_build
        and args.output_static_lib_dir is not None
        and args.output_dir is None
        and args.prebuilt_static_lib_sdk is None
    )
    install_prebuilt_static_lib_only = (
        args.skip_build
        and args.prebuilt_static_lib_sdk is not None
        and args.output_dir is None
        and args.output_static_lib_dir is None
    )

    if not args.skip_build:
        ensure_tool("msbuild")
    verify_source_root(source_root)

    version_info, version_mm, version_full = parse_cpython_version(source_root)
    manifest = load_manifest()
    config_path = (args.config or CONFIG_PATH).resolve()
    config = load_config(config_path)
    profile_name, profile = resolve_profile(config, args.profile)
    runtime_sdk_mode = profile.get("build_type") == "runtime-sdk"
    pack_only_mode = bool(args.pack_only)
    if args.output_runtime_sdk_dir is not None and not runtime_sdk_mode:
        raise RuntimeError("--output-runtime-sdk-dir requires --profile runtime-sdk")
    if runtime_sdk_mode and args.output_dir is not None:
        raise RuntimeError("runtime-sdk does not produce a generic executable; remove --output-dir")
    if runtime_sdk_mode and args.output_pack_dir is not None:
        raise RuntimeError("runtime-sdk contains no optional libraries; use a library profile with --output-pack-dir")
    if args.output_pack_name and args.output_pack_dir is None:
        raise RuntimeError("--output-pack-name requires --output-pack-dir")
    if pack_only_mode and args.output_pack_dir is None:
        raise RuntimeError("--pack-only requires --output-pack-dir")
    if pack_only_mode and runtime_sdk_mode:
        raise RuntimeError("--pack-only requires a library profile, not runtime-sdk")
    if pack_only_mode and args.skip_build:
        raise RuntimeError("--pack-only cannot be combined with --skip-build")
    if args.pack_runtime_sdk is not None and not pack_only_mode:
        raise RuntimeError("--pack-runtime-sdk is only valid with --pack-only")
    if pack_only_mode and not args.skip_verify and args.pack_runtime_sdk is None:
        raise RuntimeError("verified --pack-only builds require --pack-runtime-sdk")
    if pack_only_mode and args.skip_verify and args.pack_runtime_sdk is not None:
        raise RuntimeError("--pack-runtime-sdk cannot be combined with --skip-verify")
    if pack_only_mode and any(
        value is not None
        for value in (
            args.output_dir,
            args.output_static_lib_dir,
            args.output_runtime_sdk_dir,
            args.prebuilt_static_lib_sdk,
        )
    ):
        raise RuntimeError(
            "--pack-only cannot export an executable or SDK and cannot consume a full static-library SDK"
        )
    target_version = Version(version_full)
    core_version_overrides = profile.get("core_library_version_overrides")
    third_party_version_overrides = profile.get("third_party_library_version_overrides")
    core_library_catalog = profile_library_catalog(config, profile, "core_library_catalog")
    third_party_library_catalog = profile_library_catalog(config, profile, "third_party_library_catalog")
    core_integrations = load_integrations(
        CORE_PATCH_ROOT,
        profile.get("core_libraries", "all"),
        target_version=target_version,
        version_overrides=core_version_overrides,
        library_catalog=core_library_catalog,
    )
    third_party_integrations = load_integrations(
        LIB_PATCH_ROOT,
        profile.get("third_party_libraries", "all"),
        target_version=target_version,
        version_overrides=third_party_version_overrides,
        library_catalog=third_party_library_catalog,
    )
    if runtime_sdk_mode:
        # A runtime SDK is deliberately independent from the optional package
        # catalog.  Loading every integration here resolves PyPI releases even
        # though none of them can participate in this build.
        all_third_party_integrations = []
    elif profile.get("third_party_libraries") == "all":
        all_third_party_integrations = third_party_integrations
    else:
        all_third_party_integrations = load_integration_definitions(
            LIB_PATCH_ROOT,
            version_overrides=third_party_version_overrides,
            library_catalog=third_party_library_catalog,
        )
    integrations = [*core_integrations, *third_party_integrations]
    if requested_version_info is not None and requested_version_info != version_info:
        raise RuntimeError(
            f"downloaded source version {version_full} does not match requested version {args.cpython_version}"
        )
    log(f"target CPython version: {version_full}")
    log(
        f"build profile: {profile_name} "
        f"({len(core_integrations)} core integration(s), {len(third_party_integrations)} third-party integration(s))"
    )
    log(f"build workers: {build_workers}")
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    WORK_CACHE_ROOT.mkdir(parents=True, exist_ok=True)

    if export_static_lib_only or install_prebuilt_static_lib_only:
        if export_static_lib_only:
            log("skip source materialization and patching because only static library SDK export was requested")
        else:
            log("skip source materialization and patching because only prebuilt static library installation was requested")
    else:
        if integrations:
            if not runtime_sdk_mode and profile.get("third_party_libraries") != "all":
                log("pruning stale third-party source paths for the selected incremental profile")
                cleanup_unselected_third_party_sources(
                    source_root,
                    all_third_party_integrations,
                    third_party_integrations,
                )
            cleanup_integration_legacy_paths(source_root, integrations)
            log(f"materializing configured integration sources into {source_root}")
            run_prepare_source_hooks(
                integrations,
                make_library_hook_context(
                    source_root,
                    version_info,
                    version_mm,
                    version_full,
                    args.configuration,
                    args.platform,
                ),
            )
        else:
            log("skipping integration source materialization for this profile")
        log(f"copying overlay assets into {source_root}")
        copy_overlay_entries(source_root, ASSET_ROOT, manifest, integrations, version_info)
        log("applying in-place patches")
        apply_patches(
            source_root,
            version_info,
            version_mm,
            version_full,
            manifest,
            integrations,
            args.platform,
            args.configuration,
            runtime_sdk=runtime_sdk_mode,
        )
        write_profile_metadata(
            source_root,
            profile_name,
            config_path,
            version_full,
            core_integrations,
            third_party_integrations,
        )

        if not args.skip_get_externals:
            log("running get_externals.bat")
            maybe_get_externals(source_root)

    sdk_temp_dir: tempfile.TemporaryDirectory | None = None
    use_prebuilt_static_libraries = args.prebuilt_static_lib_sdk is not None
    if use_prebuilt_static_libraries:
        sdk_root, sdk_temp_dir = prepare_static_lib_sdk(args.prebuilt_static_lib_sdk)
        install_prebuilt_static_library_sdk(
            source_root,
            args.platform,
            manifest,
            integrations,
            version_full,
            profile_name,
            sdk_root,
        )

    built_exe: Path | None = None
    verification_report: dict | None = None
    try:
        if not args.skip_build:
            maybe_restore_getpath_header(source_root, version_info)
            if args.skip_freeze:
                log("skipping frozen module regeneration for incremental build")
            else:
                log("building freeze tool and regenerating frozen modules")
                freeze_modules(
                    source_root,
                    args.host_python,
                    args.configuration,
                    args.platform,
                    version_info,
                    build_workers,
                )
                maybe_restore_getpath_header(source_root, version_info)
                verify_runtime_resource_modules_frozen(source_root)
            if pack_only_mode:
                log("building only third-party pack-owned static libraries")
                build_pack_static_libraries(
                    source_root,
                    args.configuration,
                    args.platform,
                    third_party_integrations,
                    version_info,
                    version_mm,
                    version_full,
                    build_workers,
                )
            else:
                log("splitting frozen module bytecode data for MSVC")
                split_frozen_modules(source_root)
                log("building custom static libraries and python.exe")
                build_python(
                    source_root,
                    args.configuration,
                    args.platform,
                    manifest,
                    integrations,
                    version_info,
                    version_mm,
                    version_full,
                    set(args.build_static_project) if args.build_static_project else None,
                    args.build_static_project_from,
                    use_prebuilt_static_libraries,
                    build_workers,
                    runtime_sdk=runtime_sdk_mode,
                )
            if not runtime_sdk_mode and not pack_only_mode:
                built_exe = get_pcbuild_output_dir(source_root, args.platform) / "python.exe"

        if not runtime_sdk_mode and not pack_only_mode and not args.skip_build and not args.skip_verify:
            log("running post-build profile verification")
            verification_report_path = source_root / "PCbuild" / "staticpython-verify-report.json"
            built_exe = verify_built_python(
                source_root,
                args.platform,
                manifest,
                args.host_python,
                profile_name,
                config_path,
                report_json=verification_report_path,
            )
            verification_report = json.loads(verification_report_path.read_text(encoding="utf-8"))

        if not args.skip_build and args.output_dir:
            if built_exe is None:
                built_exe = get_pcbuild_output_dir(source_root, args.platform) / "python.exe"
            export_built_python(built_exe, args.output_dir.resolve(), version_full, args.platform, profile_name)

        if args.output_static_lib_dir:
            export_static_library_sdk(
                source_root,
                args.output_static_lib_dir.resolve(),
                version_full,
                args.platform,
                profile_name,
                manifest,
                integrations,
            )
        if args.output_runtime_sdk_dir:
            export_runtime_sdk(
                source_root,
                args.output_runtime_sdk_dir.resolve(),
                version_info,
                version_full,
                args.platform,
                profile_name,
                manifest,
                integrations,
            )
        if args.output_pack_dir:
            if not third_party_integrations:
                raise RuntimeError("the selected profile has no third-party integrations to export")
            output_pack_integrations = select_output_pack_integrations(
                third_party_integrations,
                args.output_pack_name,
            )
            if pack_only_mode and not args.skip_verify:
                with tempfile.TemporaryDirectory(prefix="staticpython-provisional-packs-") as temporary:
                    provisional_packs = export_library_packs(
                        source_root,
                        Path(temporary),
                        version_info,
                        version_full,
                        args.platform,
                        third_party_integrations,
                        verification_status="not-run",
                    )
                    verification_report = verify_pack_only_with_runtime_sdk(
                        source_root,
                        args.pack_runtime_sdk.resolve(),
                        provisional_packs,
                        args.host_python,
                        build_workers,
                    )
            exported_packs = export_library_packs(
                source_root,
                args.output_pack_dir.resolve(),
                version_info,
                version_full,
                args.platform,
                output_pack_integrations,
                verification_status=(
                    "passed"
                    if not args.skip_build and not args.skip_verify
                    else "not-run"
                ),
                verification_report=verification_report,
            )
            if pack_only_mode and not args.skip_verify:
                verification_report = bind_promoted_pack_evidence(
                    verification_report,
                    exported_packs,
                )
                verification_report_path = (
                    source_root / "PCbuild" / "staticpython-pack-verify-report.json"
                )
                verification_report_path.write_text(
                    json.dumps(verification_report, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                    newline="\n",
                )
    finally:
        if sdk_temp_dir is not None:
            sdk_temp_dir.cleanup()

    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
