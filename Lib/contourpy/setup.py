from __future__ import annotations

import ast
import re
from pathlib import Path

from libs import pypi_library, source_path, write_source_text


CONTOURPY_CEXT_PROJECT_GUID = "{A0137B09-DC4A-432F-A4A3-3BD7838B7986}"
CONTOURPY_RELEASE_VERSION = "1.3.3"

def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _parse_meson_src_files(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"ext\s*=\s*py3\.extension_module\(\s*'_contourpy'\s*,\s*\[(?P<body>.*?)\]\s*,", text, re.S)
    if match is None:
        raise RuntimeError(f"could not locate contourpy extension module sources in {path}")
    body = match.group("body")
    sources = re.findall(r"'([^']+\.cpp)'", body)
    if not sources:
        raise RuntimeError(f"could not parse contourpy source list from {path}")
    return sources


def _parse_setup_py_src_files(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    match = re.search(r"_contourpy\s*=\s*Pybind11Extension\(\s*['\"]contourpy\._contourpy['\"]\s*,\s*sources=\[(?P<body>.*?)\]\s*,", text, re.S)
    if match is None:
        raise RuntimeError(f"could not locate contourpy Pybind11Extension sources in {path}")
    body = match.group("body")
    sources = re.findall(r"['\"]([^'\"]+\.cpp)['\"]", body)
    if not sources:
        raise RuntimeError(f"could not parse contourpy setup.py source list from {path}")
    normalized: list[str] = []
    for source in sources:
        if source.startswith("src/"):
            normalized.append(source.removeprefix("src/"))
        else:
            normalized.append(source)
    return normalized


def _parse_literal_module_attribute(path: Path, attribute_name: str) -> str | None:
    module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
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


def _parse_contourpy_version(context) -> str:
    path = source_path(context, "Lib/contourpy/_version.py")
    if not path.exists():
        raise RuntimeError("could not find Lib/contourpy/_version.py")
    version = _parse_literal_module_attribute(path, "__version__")
    if not version:
        raise RuntimeError("could not find a literal contourpy __version__ in Lib/contourpy/_version.py")
    return version


def _render_build_config(context, version: str) -> str:
    major, minor, patch = context.version_info
    return f"""from __future__ import annotations


def build_config() -> dict[str, str]:
    return {{
        "python_version": "{major}.{minor}.{patch}",
        "python_install_dir": "Lib",
        "python_path": "staticpython",
        "contourpy_version": "{version}",
        "meson_version": "staticpython",
        "mesonpy_version": "staticpython",
        "pybind11_version": "staticpython",
        "meson_backend": "msbuild",
        "build_dir": "staticpython",
        "source_dir": "staticpython",
        "cross_build": "False",
        "build_options": "staticpython",
        "buildtype": "release",
        "cpp_std": "c++17",
        "debug": "False",
        "optimization": "2",
        "vsenv": "False",
        "b_ndebug": "true",
        "b_vscrt": "mt",
        "compiler_name": "msvc",
        "compiler_version": "staticpython",
        "linker_id": "link",
        "compile_command": "cl",
        "host_cpu": "x86_64",
        "host_cpu_family": "x86_64",
        "host_cpu_endian": "little",
        "host_cpu_system": "windows",
        "build_cpu": "x86_64",
        "build_cpu_family": "x86_64",
        "build_cpu_endian": "little",
        "build_cpu_system": "windows",
    }}
"""


def _render_contourpy_project(version: str, source_files: list[str]) -> str:
    compile_items = "\n".join(
        f'    <ClCompile Include="..\\contourpy_builtin\\src\\{name}" />'
        for name in source_files
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{CONTOURPY_CEXT_PROJECT_GUID}</ProjectGuid>
    <RootNamespace>contourpy_contourpy</RootNamespace>
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
    <TargetName>contourpy._contourpy</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>..\\contourpy_builtin\\src;..\\pybind11_builtin\\include;..\\Lib\\numpy\\_core\\include;..\\numpy_builtin\\source\\.build-staticpython-x64\\numpy\\_core;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>Py_NO_ENABLE_SHARED;_CRT_SECURE_NO_WARNINGS;CONTOURPY_VERSION=&quot;{version}&quot;;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <ExceptionHandling>Sync</ExceptionHandling>
      <LanguageStandard>stdcpp17</LanguageStandard>
      <AdditionalOptions>/bigobj /EHsc /permissive- %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{compile_items}
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def prepare_contourpy_project(context) -> None:
    version = _parse_contourpy_version(context)
    meson_path = source_path(context, "contourpy_builtin/src/meson.build")
    if meson_path.exists():
        source_files = _parse_meson_src_files(meson_path)
    else:
        setup_py_path = source_path(context, "contourpy_builtin/setup.py")
        if not setup_py_path.exists():
            raise RuntimeError(
                f"could not find contourpy source list in either {meson_path} or {setup_py_path}"
            )
        source_files = _parse_setup_py_src_files(setup_py_path)
    missing = [source_path(context, f"contourpy_builtin/src/{name}") for name in source_files if not source_path(context, f"contourpy_builtin/src/{name}").exists()]
    missing.extend(
        path
        for path in (
            source_path(context, "pybind11_builtin/include/pybind11/pybind11.h"),
            source_path(context, "Lib/numpy/_core/include/numpy/arrayobject.h"),
        )
        if not path.exists()
    )
    if missing:
        raise RuntimeError("contourpy source files are missing: " + ", ".join(str(path) for path in missing))
    write_source_text(context, "Lib/contourpy/util/_build_config.py", _render_build_config(context, version))
    write_source_text(context, "PCbuild/contourpy._contourpy.vcxproj", _render_contourpy_project(version, source_files))


LIBRARY_INTEGRATION = pypi_library(
    name="contourpy",
    release_version=CONTOURPY_RELEASE_VERSION,
    dependencies=["numpy", "pybind11"],
    source_mapping={
        "lib/contourpy": "Lib/contourpy",
        "src": "contourpy_builtin/src",
        "?setup.py": "contourpy_builtin/setup.py",
    },
    python_packages=["contourpy"],
    static_library_projects_release_x64=["contourpy._contourpy.vcxproj"],
    native_static_projects=[
        {
            "project": "contourpy._contourpy.vcxproj",
            "guid": CONTOURPY_CEXT_PROJECT_GUID,
        }
    ],
    builtin_module_registrations=[
        {
            "name": "contourpy._contourpy",
            "pyinit": "PyInit__contourpy",
        }
    ],
    python_link_dependencies_release_x64=["contourpy._contourpy.lib"],
    prepare_source_hooks=[prepare_contourpy_project],
)
