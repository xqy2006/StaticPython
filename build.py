from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zipfile import ZipFile

from libs import (
    LibraryHookContext,
    collect_builtin_module_registrations,
    collect_native_static_projects,
    collect_overlay_entries,
    collect_python_link_dependencies,
    collect_python_link_wholearchive,
    collect_staged_static_libraries,
    collect_static_library_projects,
    load_integrations,
    run_pre_build_hooks,
    run_pre_patch_hooks,
    run_prepare_source_hooks,
    run_post_patch_hooks,
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

ET.register_namespace("", MSBUILD_NS)


def log(message: str) -> None:
    print(f"[staticpython-builder] {message}", flush=True)


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def load_config(path: Path = CONFIG_PATH) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


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
        candidates = [*registrations, *collect_builtin_module_registrations(integrations)]
    else:
        candidates = [{"name": name, "pyinit": f"PyInit_{name}"} for name in manifest.get("python_builtin_modules", [])]

    available_projects = {Path(project).stem for project in iter_static_library_projects(source_root, manifest, integrations)}
    filtered = []
    for builtin in candidates:
        if builtin["name"] in available_projects:
            filtered.append(builtin)
        else:
            log(
                f"skip builtin registration {builtin['name']} because the corresponding project is unavailable "
                "in this CPython version"
            )
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


def build_python_link_dependencies(source_root: Path, manifest: dict, integrations: list) -> str:
    all_project_stems = {Path(project).stem for project in all_static_library_projects(manifest, integrations)}
    available_project_stems = {Path(project).stem for project in iter_static_library_projects(source_root, manifest, integrations)}
    dependencies = []
    combined = list(
        dict.fromkeys([*manifest["python_link_dependencies_release_x64"], *collect_python_link_dependencies(integrations)])
    )
    for dependency in combined:
        stem = Path(dependency).stem
        if dependency.lower().endswith(".lib") and stem in all_project_stems and stem not in available_project_stems:
            log(
                f"skip python link dependency {dependency} because project {stem}.vcxproj is unavailable "
                "in this CPython version"
            )
            continue
        dependencies.append(dependency)
    return ";".join([*dependencies, "%(AdditionalDependencies)"])


def build_python_link_options(source_root: Path, manifest: dict, integrations: list) -> str:
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
    prefixes = [f"/WHOLEARCHIVE:{name}" for name in wholearchive]
    prefixes.append("%(AdditionalOptions)")
    return " ".join(prefixes)


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
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", version)
    if not match:
        raise RuntimeError(
            f"unsupported CPython version string {raw_version!r}; expected format like 3.13.2 or 3.12.10"
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


def msbuild_args(configuration: str, platform: str, *extra_properties: str) -> list[str]:
    args = [
        "/m",
        "/nologo",
        f"/p:Configuration={configuration}",
        f"/p:Platform={platform}",
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
    return version_info, f"{major}.{minor}", f"{major}.{minor}.{micro}"


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

def patch_site_py(source_root: Path, version_mm: str) -> None:
    path = source_root / "Lib" / "site.py"
    text = path.read_text(encoding="utf-8")
    pattern = r'^(?P<indent>\s*)ver_nodot = .+$'
    desired_line = f'ver_nodot = "{version_mm}".replace(\'.\', \'\')'
    if desired_line in text:
        return
    text, count = re.subn(
        pattern,
        lambda match: f'{match.group("indent")}{desired_line}',
        text,
        count=1,
        flags=re.MULTILINE,
    )
    if count != 1:
        raise RuntimeError(f"expected regex not found in {path}: {pattern}")
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


def patch_pythoncore_vcxproj(source_root: Path) -> None:
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

    for item_group in find_direct_children(root, "ItemGroup"):
        for child in list(item_group):
            if child.tag == msbuild_tag("ClCompile") and child.get("Include") in {"..\\Modules\\challenge.c", "..\\Modules\\sandbox.c"}:
                item_group.remove(child)

    save_msbuild_project(path, tree)


def patch_freeze_module_vcxproj(source_root: Path) -> None:
    path = source_root / "PCbuild" / "_freeze_module.vcxproj"
    tree, root = load_msbuild_project(path)

    ensure_vcpkg_property_group(root)

    for target in root.iter(msbuild_tag("Target")):
        if target.get("Name") not in {"_RebuildFrozen", "_RebuildGetPath"}:
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

    for project in iter_native_static_projects(source_root, manifest, integrations):
        ensure_project_reference(root, project["project"], project["guid"])

    save_msbuild_project(path, tree)


def patch_pc_config(source_root: Path, manifest: dict, integrations: list) -> None:
    path = source_root / "PC" / "config.c"
    text = path.read_text(encoding="utf-8")

    for needle in (
        "extern PyObject* PyInit_challenge(void);",
        "extern PyObject* PyInit_sandbox(void);",
        '{"challenge", PyInit_challenge},',
        '{"sandbox", PyInit_sandbox},',
    ):
        text = remove_line_contains(text, needle)

    missing_externs = []
    missing_entries = []
    for builtin in iter_builtin_module_registrations(source_root, manifest, integrations):
        extern_line = f"extern PyObject* {builtin['pyinit']}(void);"
        table_line = f'{{"{builtin["name"]}", {builtin["pyinit"]}}},'
        if extern_line not in text:
            missing_externs.append(f"\n{extern_line}\n")
        if table_line not in text:
            missing_entries.append(f'\n    {table_line}\n')

    if missing_externs:
        text = ensure_after(
            text,
            "/* -- ADDMODULE MARKER 1 -- */\n",
            "".join(missing_externs),
            path=path,
        )
    if missing_entries:
        text = ensure_after(
            text,
            "/* -- ADDMODULE MARKER 2 -- */\n",
            "".join(missing_entries),
            path=path,
        )

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
) -> None:
    hook_context = make_library_hook_context(source_root, version_info, version_mm, version_full, configuration, platform)
    run_pre_patch_hooks(integrations, hook_context)
    patch_site_py(source_root, version_mm)
    patch_modules_getpath_py(source_root)
    patch_generate_sbom_py(source_root)
    patch_pc_config_minimal_c(source_root)
    patch_pc_dl_nt_c(source_root)
    patch_python_sysmodule_c(source_root, version_mm)
    patch_pythoncore_vcxproj(source_root)
    patch_freeze_module_vcxproj(source_root)
    patch_python_vcxproj(source_root, manifest, integrations)
    patch_static_library_projects(source_root, manifest, integrations)
    patch_pc_config(source_root, manifest, integrations)
    run_post_patch_hooks(integrations, hook_context)


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


def download_first_available(urls: list[str], destination: Path) -> str:
    if destination.exists():
        log(f"using cached download {destination}")
        return str(destination)

    errors: list[str] = []
    for url in urls:
        try:
            download_file(url, destination, force=True)
            return url
        except (HTTPError, URLError, OSError) as exc:
            errors.append(f"{url}: {exc}")
            if destination.exists():
                destination.unlink()
            temporary = Path(str(destination) + ".tmp")
            if temporary.exists():
                temporary.unlink()
            log(f"download failed from {url}: {exc}")
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


def extract_zip_archive(archive_path: Path, destination_root: Path) -> Path:
    with ZipFile(archive_path) as archive:
        top_level = archive_top_level_from_zip(archive)
        extracted_root = destination_root / top_level
        if extracted_root.exists():
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
) -> Path:
    download_root.mkdir(parents=True, exist_ok=True)
    archive_url = source_archive_url or CPYTHON_ARCHIVE_URL_TEMPLATE.format(version=version)
    archive_path = download_root / f"cpython-v{version}.zip"
    download_file(archive_url, archive_path)
    source_root = extract_zip_archive(archive_path, download_root)
    log(f"downloaded source tree to {source_root}")
    return source_root


def resolve_source_root(args: argparse.Namespace) -> tuple[Path, tuple[int, int, int] | None]:
    requested_version_info: tuple[int, int, int] | None = None
    if args.cpython_version:
        normalized_version, requested_version_info = parse_version_string(args.cpython_version)
        if args.source_root is None:
            download_root = (args.download_root or (REPO_ROOT / "downloads")).resolve()
            if args.source_archive_path is not None:
                source_root = extract_zip_archive(args.source_archive_path.resolve(), download_root)
                log(f"extracted local source archive to {source_root}")
                return source_root, requested_version_info
            source_root = download_cpython_source(
                normalized_version,
                download_root,
                args.source_archive_url,
            )
            return source_root, requested_version_info
    elif args.source_root is None and args.source_archive_path is not None:
        download_root = (args.download_root or (REPO_ROOT / "downloads")).resolve()
        source_root = extract_zip_archive(args.source_archive_path.resolve(), download_root)
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


def ensure_freeze_module_exe(source_root: Path, configuration: str, platform: str) -> Path:
    pcbuild = source_root / "PCbuild"
    output_exe = get_pcbuild_output_dir(source_root, platform) / "_freeze_module.exe"
    run(
        [
            "msbuild",
            str(pcbuild / "_freeze_module.vcxproj"),
            *msbuild_args(configuration, platform, "StaticPythonSkipRebuildFrozen=true"),
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
) -> None:
    freeze_exe = ensure_freeze_module_exe(source_root, configuration, platform)
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
) -> None:
    pcbuild = source_root / "PCbuild"
    run_pre_build_hooks(
        integrations,
        make_library_hook_context(source_root, version_info, version_mm, version_full, configuration, platform),
    )
    stage_static_libraries(source_root, platform, manifest, integrations)

    for target in iter_static_library_projects(source_root, manifest, integrations):
        run(
            [
                "msbuild",
                str(pcbuild / target),
                *msbuild_args(configuration, platform),
            ],
            cwd=source_root,
        )

    run(
        [
            "msbuild",
            str(pcbuild / "python.vcxproj"),
            *msbuild_args(configuration, platform),
        ],
        cwd=source_root,
    )


def verify_built_python(source_root: Path, platform: str, manifest: dict, host_python: str, profile: str) -> Path:
    exe = get_pcbuild_output_dir(source_root, platform) / "python.exe"
    if not exe.exists():
        raise RuntimeError(f"build did not produce {exe}")
    run(
        [
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
        ],
        cwd=REPO_ROOT,
        timeout=60 * 20,
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
        "--host-python",
        default=sys.executable,
        help="Python executable used to run helper scripts such as freeze_modules.py",
    )
    parser.add_argument("--configuration", default="Release")
    parser.add_argument("--platform", default="x64")
    parser.add_argument(
        "--profile",
        help="Build profile from config.json. Defaults to config.default_profile.",
    )
    parser.add_argument("--skip-get-externals", action="store_true")
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument(
        "--output-dir",
        type=Path,
        help="Copy the finished single-file python.exe to this directory with a versioned filename",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    source_root, requested_version_info = resolve_source_root(args)

    if not args.skip_build:
        ensure_tool("msbuild")
    verify_source_root(source_root)

    manifest = load_manifest()
    config = load_config()
    profile_name, profile = resolve_profile(config, args.profile)
    core_integrations = load_integrations(CORE_PATCH_ROOT, profile.get("core_libraries", "all"))
    third_party_integrations = load_integrations(LIB_PATCH_ROOT, profile.get("third_party_libraries", "all"))
    integrations = [*core_integrations, *third_party_integrations]
    version_info, version_mm, version_full = parse_cpython_version(source_root)
    if requested_version_info is not None and requested_version_info != version_info:
        raise RuntimeError(
            f"downloaded source version {version_full} does not match requested version {args.cpython_version}"
        )
    log(f"target CPython version: {version_full}")
    log(
        f"build profile: {profile_name} "
        f"({len(core_integrations)} core integration(s), {len(third_party_integrations)} third-party integration(s))"
    )
    DOWNLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    WORK_CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    if integrations:
        log(f"materializing configured integration sources into {source_root}")
        run_prepare_source_hooks(
            integrations,
            make_library_hook_context(source_root, version_info, version_mm, version_full, args.configuration, args.platform),
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
    )

    if not args.skip_get_externals:
        log("running get_externals.bat")
        maybe_get_externals(source_root)

    built_exe: Path | None = None
    if not args.skip_build:
        maybe_restore_getpath_header(source_root, version_info)
        log("building freeze tool and regenerating frozen modules")
        freeze_modules(source_root, args.host_python, args.configuration, args.platform, version_info)
        maybe_restore_getpath_header(source_root, version_info)
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
        )
        built_exe = get_pcbuild_output_dir(source_root, args.platform) / "python.exe"

    if not args.skip_build and not args.skip_verify:
        log("running post-build import verification")
        built_exe = verify_built_python(source_root, args.platform, manifest, args.host_python, profile_name)

    if not args.skip_build and args.output_dir:
        if built_exe is None:
            built_exe = get_pcbuild_output_dir(source_root, args.platform) / "python.exe"
        export_built_python(built_exe, args.output_dir.resolve(), version_full, args.platform, profile_name)

    log("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
