from __future__ import annotations

from libs import inline_verification_step, pypi_library, source_path, write_source_text


WEBSOCKETS_SPEEDUPS_GUID = "{E6A16A21-1D95-4866-A375-455DD2E9F2D4}"


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _render_speedups_project() -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{WEBSOCKETS_SPEEDUPS_GUID}</ProjectGuid>
    <RootNamespace>websockets_speedups</RootNamespace>
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
    <TargetName>websockets.speedups</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>..\\Lib\\websockets;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>Py_NO_ENABLE_SHARED;_CRT_SECURE_NO_WARNINGS;NDEBUG;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <AdditionalOptions>/bigobj %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
    <ClCompile Include="..\\Lib\\websockets\\speedups.c" />
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def prepare_speedups_project(context) -> None:
    source = source_path(context, "Lib/websockets/speedups.c")
    if not source.exists():
        raise RuntimeError(f"websockets speedups source file is missing: {source}")
    write_source_text(context, "PCbuild/websockets.speedups.vcxproj", _render_speedups_project())


LIBRARY_INTEGRATION = pypi_library(
    name="websockets",
    source_mapping={
        "src/websockets": "Lib/websockets",
    },
    python_packages=["websockets"],
    verification_imports=["websockets", "websockets.speedups"],
    static_library_projects_release_x64=["websockets.speedups.vcxproj"],
    native_static_projects=[
        {
            "project": "websockets.speedups.vcxproj",
            "guid": WEBSOCKETS_SPEEDUPS_GUID,
        }
    ],
    builtin_module_registrations=[
        {
            "name": "websockets.speedups",
            "pyinit": "PyInit_speedups",
        }
    ],
    python_link_dependencies_release_x64=["websockets.speedups.lib"],
    prepare_source_hooks=[prepare_speedups_project],
    verification_steps=[
        inline_verification_step(
            "websockets-smoke",
            """
import importlib.util

import websockets
import websockets.frames
import websockets.speedups as speedups
from websockets.uri import parse_uri

assert importlib.util.find_spec("websockets.speedups").origin == "built-in"
assert speedups.apply_mask(b"abcd", b"\\x01\\x02\\x03\\x04") == bytes([0x60, 0x60, 0x60, 0x60])
assert websockets.frames.apply_mask is speedups.apply_mask
uri = parse_uri("wss://example.com/chat")
assert uri.secure is True and uri.host == "example.com" and uri.path == "/chat", uri
""",
        )
    ],
)
