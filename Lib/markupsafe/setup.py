from __future__ import annotations

from libs import pypi_library, source_path, write_source_text


MARKUPSAFE_SPEEDUPS_PROJECT_GUID = "{C4AA1B51-433E-472A-931B-1E2B5C752D5D}"


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _render_markupsafe_speedups_project() -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{MARKUPSAFE_SPEEDUPS_PROJECT_GUID}</ProjectGuid>
    <RootNamespace>markupsafe_speedups</RootNamespace>
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
    <TargetName>markupsafe._speedups</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>..\\Lib\\markupsafe;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>Py_NO_ENABLE_SHARED;_CRT_SECURE_NO_WARNINGS;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
    <ClCompile Include="..\\Lib\\markupsafe\\_speedups.c" />
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def prepare_markupsafe_speedups_project(context) -> None:
    source = source_path(context, "Lib/markupsafe/_speedups.c")
    if not source.exists():
        raise RuntimeError(f"MarkupSafe speedups source file is missing: {source}")
    write_source_text(context, "PCbuild/markupsafe._speedups.vcxproj", _render_markupsafe_speedups_project())


LIBRARY_INTEGRATION = pypi_library(
    name="markupsafe",
    source_mapping={
        "src/markupsafe": "Lib/markupsafe",
    },
    python_packages=["markupsafe"],
    static_library_projects_release_x64=["markupsafe._speedups.vcxproj"],
    native_static_projects=[
        {
            "project": "markupsafe._speedups.vcxproj",
            "guid": MARKUPSAFE_SPEEDUPS_PROJECT_GUID,
        }
    ],
    builtin_module_registrations=[
        {
            "name": "markupsafe._speedups",
            "pyinit": "PyInit__speedups",
        }
    ],
    python_link_dependencies_release_x64=["markupsafe._speedups.lib"],
    prepare_source_hooks=[prepare_markupsafe_speedups_project],
)
