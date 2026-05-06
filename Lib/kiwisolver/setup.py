from __future__ import annotations

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


def prepare_kiwisolver_project(context) -> None:
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
        "py/kiwisolver": "Lib/kiwisolver",
        "py/src": "kiwisolver_builtin/py/src",
        "kiwi": "kiwisolver_builtin/kiwi",
    },
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
