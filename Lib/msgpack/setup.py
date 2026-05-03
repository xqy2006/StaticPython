from __future__ import annotations

from libs import pypi_library, source_path, write_source_text


MSGPACK_CMSGPACK_PROJECT_GUID = "{B7D41B25-C32D-4E38-BFD5-4DD5650AC49E}"


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _render_msgpack_cmsgpack_project() -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{MSGPACK_CMSGPACK_PROJECT_GUID}</ProjectGuid>
    <RootNamespace>msgpack_cmsgpack</RootNamespace>
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
    <TargetName>msgpack._cmsgpack</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>..\\Lib\\msgpack;..\\Lib;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>Py_NO_ENABLE_SHARED;_CRT_SECURE_NO_WARNINGS;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <AdditionalOptions>/bigobj %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
    <ClCompile Include="..\\Lib\\msgpack\\_cmsgpack.c" />
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def prepare_msgpack_cmsgpack_project(context) -> None:
    source = source_path(context, "Lib/msgpack/_cmsgpack.c")
    if not source.exists():
        raise RuntimeError(f"msgpack _cmsgpack source file is missing: {source}")
    write_source_text(context, "PCbuild/msgpack._cmsgpack.vcxproj", _render_msgpack_cmsgpack_project())


LIBRARY_INTEGRATION = pypi_library(
    name="msgpack",
    source_mapping={
        "msgpack": "Lib/msgpack",
    },
    python_packages=["msgpack"],
    static_library_projects_release_x64=["msgpack._cmsgpack.vcxproj"],
    native_static_projects=[
        {
            "project": "msgpack._cmsgpack.vcxproj",
            "guid": MSGPACK_CMSGPACK_PROJECT_GUID,
        }
    ],
    builtin_module_registrations=[
        {
            "name": "msgpack._cmsgpack",
            "pyinit": "PyInit__cmsgpack",
        }
    ],
    python_link_dependencies_release_x64=["msgpack._cmsgpack.lib"],
    prepare_source_hooks=[prepare_msgpack_cmsgpack_project],
)
