from __future__ import annotations

import ast
import re
from pathlib import Path

from libs import pypi_library, source_path, write_source_text


PIL_IMAGING_PROJECT_GUID = "{0AC7C2D2-056F-464A-9297-0BF67EC9499A}"
PIL_IMAGINGMATH_PROJECT_GUID = "{B7A8FF28-707A-4F50-A0C1-D50E30E6BC6B}"
PIL_IMAGINGMORPH_PROJECT_GUID = "{E2259EA5-4DA5-4128-A2E6-2649577C51A9}"
CPYTHON_ZLIB_NG_PROJECT_GUID = "{FB91C8B2-6FBC-3A01-B644-1637111F902D}"

PIL_TOP_LEVEL_IMAGING_SOURCES = [
    "_imaging.c",
    "decode.c",
    "encode.c",
    "map.c",
    "display.c",
    "outline.c",
    "path.c",
]


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _object_file_name(source_file: str) -> str:
    stem = source_file.replace("/", "_").replace("\\", "_")
    return f"$(IntDir){stem}.obj"


def _compile_items(source_files: list[str]) -> str:
    items = []
    for name in source_files:
        windows_name = name.replace("/", "\\")
        include_path = f"..\\pillow_builtin\\src\\{windows_name}"
        items.append(
            "\n".join(
                [
                    f'    <ClCompile Include="{include_path}">',
                    f"      <ObjectFileName>{_object_file_name(name)}</ObjectFileName>",
                    "    </ClCompile>",
                ]
            )
        )
    return "\n".join(items)


def _render_pil_project(
    *,
    project_guid: str,
    root_namespace: str,
    target_name: str,
    source_files: list[str],
    extra_definitions: list[str],
    include_zlib: bool = False,
) -> str:
    include_dirs = [
        r"..\pillow_builtin\src",
        r"..\pillow_builtin\src\libImaging",
    ]
    if include_zlib:
        include_dirs.extend(
            [
                r"$(GeneratedZlibNgDir)",
                r"$(zlibNgDir)",
                r"..\PC",
                r"$(zlibDir)",
            ]
        )
    include_text = ";".join([*include_dirs, "%(AdditionalIncludeDirectories)"])
    definitions = ";".join([*extra_definitions, "Py_NO_ENABLE_SHARED", "_CRT_SECURE_NO_WARNINGS", "%(PreprocessorDefinitions)"])
    project_references = ""
    if include_zlib:
        project_references = f"""
  <ItemGroup>
    <ProjectReference Include="zlib-ng.vcxproj" Condition="Exists('zlib-ng.vcxproj')">
      <Project>{CPYTHON_ZLIB_NG_PROJECT_GUID}</Project>
      <ReferenceOutputAssembly>false</ReferenceOutputAssembly>
    </ProjectReference>
  </ItemGroup>"""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{project_guid}</ProjectGuid>
    <RootNamespace>{root_namespace}</RootNamespace>
    <Keyword>Win32Proj</Keyword>
    <SupportPGO>false</SupportPGO>
    <WindowsTargetPlatformVersion>$(DefaultWindowsSDKVersion)</WindowsTargetPlatformVersion>
  </PropertyGroup>
  <Import Project="python.props" />
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props" />
  <PropertyGroup Label="Configuration">
    <ConfigurationType>StaticLibrary</ConfigurationType>
    <CharacterSet>Unicode</CharacterSet>
    <PlatformToolset>$(DefaultPlatformToolset)</PlatformToolset>
  </PropertyGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.props" />
  <ImportGroup Label="PropertySheets">
    <Import Project="$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props" Condition="exists('$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props')" Label="LocalAppDataPlatform" />
    <Import Project="pyproject.props" />
  </ImportGroup>
  <PropertyGroup Label="UserMacros" />
  <PropertyGroup>
    <TargetName>{target_name}</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>{include_text}</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>{definitions}</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <AdditionalOptions>/bigobj %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{_compile_items(source_files)}
  </ItemGroup>
{project_references}
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def _parse_literal_module_attribute(path: Path, attribute_name: str) -> str | None:
    text = path.read_text(encoding="utf-8")
    try:
        module = ast.parse(text, filename=str(path))
    except SyntaxError:
        pattern = rf"(?m)^{re.escape(attribute_name)}\s*=\s*['\"]([^'\"]+)['\"]\s*$"
        match = re.search(pattern, text)
        return None if match is None else match.group(1)
    for node in module.body:
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(target, ast.Name) and target.id == attribute_name for target in node.targets):
            continue
        try:
            value = ast.literal_eval(node.value)
        except (SyntaxError, ValueError):
            return None
        if isinstance(value, str):
            return value
        return None
    return None


def _parse_pillow_version(context) -> str:
    for candidate, attribute_names in (
        ("Lib/PIL/_version.py", ("__version__",)),
        ("Lib/PIL/version.py", ("__version__",)),
        ("Lib/PIL/__init__.py", ("__version__", "PILLOW_VERSION", "VERSION")),
        ("pillow_builtin/src/setup.py", ("VERSION",)),
    ):
        path = source_path(context, candidate)
        if not path.exists():
            continue
        for attribute_name in attribute_names:
            version = _parse_literal_module_attribute(path, attribute_name)
            if version:
                return version
    raise RuntimeError(
        "could not find a literal Pillow version in "
        "Lib/PIL/_version.py, Lib/PIL/version.py, Lib/PIL/__init__.py, or pillow_builtin/src/setup.py"
    )


def _optional_top_level_source_files(context) -> list[str]:
    root = source_path(context, "pillow_builtin/src")
    return [name for name in PIL_TOP_LEVEL_IMAGING_SOURCES if (root / name).exists()]


def _discover_imaging_sources(context) -> list[str]:
    root = source_path(context, "pillow_builtin/src")
    source_files = _optional_top_level_source_files(context)
    source_files.extend(
        f"libImaging/{path.name}"
        for path in sorted((root / "libImaging").glob("*.c"))
    )
    missing = [name for name in source_files if not (root / name).exists()]
    if missing:
        raise RuntimeError("Pillow _imaging source files are missing: " + ", ".join(missing))
    return source_files


def _has_optional_pillow_source(context, relative: str) -> bool:
    return source_path(context, relative).exists()


def prepare_pillow_projects(context) -> None:
    version = _parse_pillow_version(context)
    common_definitions = [f'PILLOW_VERSION=&quot;{version}&quot;']
    imagingmath_source = "_imagingmath.c" if _has_optional_pillow_source(context, "pillow_builtin/src/_imagingmath.c") else ""
    imagingmorph_source = "_imagingmorph.c" if _has_optional_pillow_source(context, "pillow_builtin/src/_imagingmorph.c") else ""
    imagingmath_project_path = source_path(context, "PCbuild/PIL._imagingmath.vcxproj")
    imagingmorph_project_path = source_path(context, "PCbuild/PIL._imagingmorph.vcxproj")
    write_source_text(
        context,
        "PCbuild/PIL._imaging.vcxproj",
        _render_pil_project(
            project_guid=PIL_IMAGING_PROJECT_GUID,
            root_namespace="PIL__imaging",
            target_name="PIL._imaging",
            source_files=_discover_imaging_sources(context),
            extra_definitions=[*common_definitions, "HAVE_LIBZ"],
            include_zlib=True,
        ),
    )
    if imagingmath_source:
        write_source_text(
            context,
            "PCbuild/PIL._imagingmath.vcxproj",
            _render_pil_project(
                project_guid=PIL_IMAGINGMATH_PROJECT_GUID,
                root_namespace="PIL__imagingmath",
                target_name="PIL._imagingmath",
                source_files=[imagingmath_source],
                extra_definitions=common_definitions,
            ),
        )
    elif imagingmath_project_path.exists():
        imagingmath_project_path.unlink()
    if imagingmorph_source:
        write_source_text(
            context,
            "PCbuild/PIL._imagingmorph.vcxproj",
            _render_pil_project(
                project_guid=PIL_IMAGINGMORPH_PROJECT_GUID,
                root_namespace="PIL__imagingmorph",
                target_name="PIL._imagingmorph",
                source_files=[imagingmorph_source],
                extra_definitions=common_definitions,
            ),
        )
    elif imagingmorph_project_path.exists():
        imagingmorph_project_path.unlink()


LIBRARY_INTEGRATION = pypi_library(
    name="PIL",
    project_name="pillow",
    source_mapping={
        "src/PIL||PIL": "Lib/PIL",
        "src||.": "pillow_builtin/src",
    },
    materialized_paths=[
        "Lib/PIL/__init__.py",
        "pillow_builtin/src/_imaging.c",
        "pillow_builtin/src/libImaging/Access.c",
        "pillow_builtin/src/libImaging/Storage.c",
    ],
    python_packages=["PIL"],
    static_library_projects_release_x64=[
        "PIL._imaging.vcxproj",
        "PIL._imagingmath.vcxproj",
        "PIL._imagingmorph.vcxproj",
    ],
    native_static_projects=[
        {"project": "PIL._imaging.vcxproj", "guid": PIL_IMAGING_PROJECT_GUID},
        {"project": "PIL._imagingmath.vcxproj", "guid": PIL_IMAGINGMATH_PROJECT_GUID},
        {"project": "PIL._imagingmorph.vcxproj", "guid": PIL_IMAGINGMORPH_PROJECT_GUID},
    ],
    builtin_module_registrations=[
        {"name": "PIL._imaging", "pyinit": "PyInit__imaging"},
        {"name": "PIL._imagingmath", "pyinit": "PyInit__imagingmath"},
        {"name": "PIL._imagingmorph", "pyinit": "PyInit__imagingmorph"},
    ],
    python_link_dependencies_release_x64=[
        "PIL._imaging.lib",
        "PIL._imagingmath.lib",
        "PIL._imagingmorph.lib",
        "user32.lib",
        "gdi32.lib",
    ],
    prepare_source_hooks=[prepare_pillow_projects],
)
