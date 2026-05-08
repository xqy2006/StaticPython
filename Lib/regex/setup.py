from __future__ import annotations

from libs import pypi_library, source_path, write_source_text


REGEX_PROJECT_GUID = "{5C650E6E-5A5E-4EE9-9B96-4D0FE1F44A12}"


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _render_regex_project() -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{REGEX_PROJECT_GUID}</ProjectGuid>
    <RootNamespace>regex_regex</RootNamespace>
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
    <TargetName>regex._regex</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>..\\regex_builtin\\src;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>Py_NO_ENABLE_SHARED;_CRT_SECURE_NO_WARNINGS;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <AdditionalOptions>/bigobj %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
    <ClCompile Include="..\\regex_builtin\\src\\_regex.c" />
    <ClCompile Include="..\\regex_builtin\\src\\_regex_unicode.c" />
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def prepare_regex_project(context) -> None:
    missing = [
        path
        for path in (
            source_path(context, "regex_builtin/src/_regex.c"),
            source_path(context, "regex_builtin/src/_regex_unicode.c"),
        )
        if not path.exists()
    ]
    if missing:
        raise RuntimeError("regex source files are missing: " + ", ".join(str(path) for path in missing))
    write_source_text(context, "PCbuild/regex._regex.vcxproj", _render_regex_project())
LIBRARY_INTEGRATION = pypi_library(
    name="regex",
    source_mapping={
        "regex||regex_3": "Lib/regex",
        "src||regex_3": "regex_builtin/src",
    },
    python_packages=["regex"],
    static_library_projects_release_x64=["regex._regex.vcxproj"],
    native_static_projects=[
        {
            "project": "regex._regex.vcxproj",
            "guid": REGEX_PROJECT_GUID,
        }
    ],
    builtin_module_registrations=[
        {
            "name": "regex._regex",
            "pyinit": "PyInit__regex",
        }
    ],
    python_link_dependencies_release_x64=["regex._regex.lib"],
    prepare_source_hooks=[prepare_regex_project],
)
