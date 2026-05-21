from __future__ import annotations

import shutil

from libs import pypi_library, source_path, write_source_text


KIWISOLVER_CEXT_PROJECT_GUID = "{54A1D593-E5C3-4203-A851-1C566E685B1D}"

KIWISOLVER_SOURCES = [
    "constraint.cpp",
    "expression.cpp",
    "kiwisolver.cpp",
    "solver.cpp",
    "strength.cpp",
    "term.cpp",
    "variable.cpp",
]

KIWISOLVER_LEGACY_STAGING_FILES = [
    *KIWISOLVER_SOURCES,
    "pythonhelpers.h",
    "symbolics.h",
    "types.h",
    "util.h",
    "version.h",
]


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _compile_items() -> str:
    return "\n".join(
        f'    <ClCompile Include="..\\kiwisolver_builtin\\py\\src\\{name}" />'
        for name in KIWISOLVER_SOURCES
    )


def _render_kiwisolver_project() -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{KIWISOLVER_CEXT_PROJECT_GUID}</ProjectGuid>
    <RootNamespace>kiwisolver_cext</RootNamespace>
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
    <TargetName>kiwisolver._cext</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>..\\kiwisolver_builtin;..\\kiwisolver_builtin\\py\\src;..\\Lib\\cppy\\include;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>Py_NO_ENABLE_SHARED;_CRT_SECURE_NO_WARNINGS;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <ExceptionHandling>Sync</ExceptionHandling>
      <AdditionalOptions>/bigobj /EHsc %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{_compile_items()}
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def _ensure_kiwisolver_package(context) -> None:
    package_root = source_path(context, "Lib/kiwisolver")
    package_root.mkdir(parents=True, exist_ok=True)
    package_init = package_root / "__init__.py"
    if package_init.exists():
        return
    write_source_text(
        context,
        "Lib/kiwisolver/__init__.py",
        "from ._cext import *  # noqa: F401,F403\n",
    )


def _materialize_legacy_kiwisolver_sources(context) -> None:
    legacy_root = source_path(context, "kiwisolver_builtin/legacy-root")
    target_root = source_path(context, "kiwisolver_builtin/py/src")
    copied_any = False
    for relative in KIWISOLVER_LEGACY_STAGING_FILES:
        source = legacy_root / relative
        if not source.exists():
            continue
        destination = target_root / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        copied_any = True
    if copied_any:
        context.log("prepared legacy kiwisolver source layout")


def prepare_kiwisolver_project(context) -> None:
    _ensure_kiwisolver_package(context)
    if not source_path(context, "kiwisolver_builtin/py/src/kiwisolver.cpp").exists():
        _materialize_legacy_kiwisolver_sources(context)
    missing = [
        source_path(context, f"kiwisolver_builtin/py/src/{name}")
        for name in KIWISOLVER_SOURCES
        if not source_path(context, f"kiwisolver_builtin/py/src/{name}").exists()
    ]
    missing.extend(
        path
        for path in (
            source_path(context, "kiwisolver_builtin/kiwi/kiwi.h"),
            source_path(context, "Lib/cppy/include/cppy/cppy.h"),
        )
        if not path.exists()
    )
    if missing:
        raise RuntimeError("kiwisolver source files are missing: " + ", ".join(str(path) for path in missing))
    write_source_text(context, "PCbuild/kiwisolver._cext.vcxproj", _render_kiwisolver_project())


LIBRARY_INTEGRATION = pypi_library(
    name="kiwisolver",
    dependencies=["cppy"],
    source_mapping={
        "?py/kiwisolver||?kiwisolver": "Lib/kiwisolver",
        "?py/src||?src||?py": "kiwisolver_builtin/py/src",
        "kiwi": "kiwisolver_builtin/kiwi",
        "?constraint.cpp": "kiwisolver_builtin/legacy-root/constraint.cpp",
        "?expression.cpp": "kiwisolver_builtin/legacy-root/expression.cpp",
        "?kiwisolver.cpp": "kiwisolver_builtin/legacy-root/kiwisolver.cpp",
        "?solver.cpp": "kiwisolver_builtin/legacy-root/solver.cpp",
        "?strength.cpp": "kiwisolver_builtin/legacy-root/strength.cpp",
        "?term.cpp": "kiwisolver_builtin/legacy-root/term.cpp",
        "?variable.cpp": "kiwisolver_builtin/legacy-root/variable.cpp",
        "?pythonhelpers.h": "kiwisolver_builtin/legacy-root/pythonhelpers.h",
        "?symbolics.h": "kiwisolver_builtin/legacy-root/symbolics.h",
        "?types.h": "kiwisolver_builtin/legacy-root/types.h",
        "?util.h": "kiwisolver_builtin/legacy-root/util.h",
        "?version.h": "kiwisolver_builtin/legacy-root/version.h",
    },
    materialized_paths=[
        "kiwisolver_builtin/py/src",
        "kiwisolver_builtin/kiwi",
    ],
    python_packages=["kiwisolver"],
    static_library_projects_release_x64=["kiwisolver._cext.vcxproj"],
    native_static_projects=[
        {
            "project": "kiwisolver._cext.vcxproj",
            "guid": KIWISOLVER_CEXT_PROJECT_GUID,
        }
    ],
    builtin_module_registrations=[
        {
            "name": "kiwisolver._cext",
            "pyinit": "PyInit__cext",
        }
    ],
    python_link_dependencies_release_x64=["kiwisolver._cext.lib"],
    prepare_source_hooks=[prepare_kiwisolver_project],
)
