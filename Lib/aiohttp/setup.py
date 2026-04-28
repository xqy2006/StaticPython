from __future__ import annotations

from libs import inline_verification_step, pypi_library, source_path, write_source_text


PROJECTS = {
    "aiohttp._http_parser": {
        "guid": "{C73B7812-A40A-49A7-86E9-59313F01955C}",
        "pyinit": "PyInit__http_parser",
        "sources": [
            "Lib/aiohttp/_http_parser.c",
            "Lib/aiohttp/_find_header.c",
            "aiohttp_builtin/vendor/llhttp/build/c/llhttp.c",
            "aiohttp_builtin/vendor/llhttp/src/native/api.c",
            "aiohttp_builtin/vendor/llhttp/src/native/http.c",
        ],
        "include_dirs": [
            "Lib/aiohttp",
            "aiohttp_builtin/vendor/llhttp/build",
            "aiohttp_builtin/vendor/llhttp/src/native",
        ],
        "defines": ["LLHTTP_STRICT_MODE=0"],
    },
    "aiohttp._http_writer": {
        "guid": "{5C2F4920-87A3-4013-9D6D-E4D8B9F7B4DD}",
        "pyinit": "PyInit__http_writer",
        "sources": ["Lib/aiohttp/_http_writer.c"],
        "include_dirs": ["Lib/aiohttp"],
        "defines": [],
    },
    "aiohttp._websocket.mask": {
        "guid": "{2E8B4905-88F2-47D4-9FA7-C87FC034EED0}",
        "pyinit": "PyInit_mask",
        "sources": ["Lib/aiohttp/_websocket/mask.c"],
        "include_dirs": ["Lib/aiohttp", "Lib/aiohttp/_websocket"],
        "defines": [],
    },
    "aiohttp._websocket.reader_c": {
        "guid": "{BD1B8D1F-1798-4EE3-A8D8-56697419B0C2}",
        "pyinit": "PyInit_reader_c",
        "sources": ["Lib/aiohttp/_websocket/reader_c.c"],
        "include_dirs": ["Lib/aiohttp", "Lib/aiohttp/_websocket"],
        "defines": [],
    },
}


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _msbuild_path(path: str) -> str:
    return "..\\" + path.replace("/", "\\")


def _object_name(source: str) -> str:
    return "$(IntDir)" + source.replace("/", "_").replace("\\", "_") + ".obj"


def _render_compile_items(sources: list[str]) -> str:
    blocks = []
    for source in sources:
        blocks.append(
            "\n".join(
                [
                    f'    <ClCompile Include="{_msbuild_path(source)}">',
                    f"      <ObjectFileName>{_object_name(source)}</ObjectFileName>",
                    "    </ClCompile>",
                ]
            )
        )
    return "\n".join(blocks)


def _render_project(name: str, info: dict) -> str:
    include_dirs = ";".join(_msbuild_path(path) for path in info["include_dirs"])
    defines = ";".join(["Py_NO_ENABLE_SHARED", "_CRT_SECURE_NO_WARNINGS", "NDEBUG", *info["defines"]])
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{info["guid"]}</ProjectGuid>
    <RootNamespace>{name.replace(".", "_")}</RootNamespace>
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
    <TargetName>{name}</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>{include_dirs};%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>{defines};%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <AdditionalOptions>/bigobj %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{_render_compile_items(info["sources"])}
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def prepare_aiohttp_projects(context) -> None:
    missing = [
        relative
        for info in PROJECTS.values()
        for relative in info["sources"]
        if not source_path(context, relative).exists()
    ]
    if missing:
        raise RuntimeError("aiohttp source files are missing: " + ", ".join(missing))

    for name, info in PROJECTS.items():
        write_source_text(context, f"PCbuild/{name}.vcxproj", _render_project(name, info))


LIBRARY_INTEGRATION = pypi_library(
    name="aiohttp",
    source_mapping={
        "aiohttp": "Lib/aiohttp",
        "vendor/llhttp": "aiohttp_builtin/vendor/llhttp",
    },
    python_packages=["aiohttp"],
    verification_imports=[
        "aiohttp",
        "aiohttp._http_parser",
        "aiohttp._http_writer",
        "aiohttp._websocket.mask",
        "aiohttp._websocket.reader_c",
    ],
    static_library_projects_release_x64=[f"{name}.vcxproj" for name in PROJECTS],
    native_static_projects=[
        {
            "project": f"{name}.vcxproj",
            "guid": info["guid"],
        }
        for name, info in PROJECTS.items()
    ],
    builtin_module_registrations=[
        {
            "name": name,
            "pyinit": info["pyinit"],
        }
        for name, info in PROJECTS.items()
    ],
    python_link_dependencies_release_x64=[f"{name}.lib" for name in PROJECTS],
    prepare_source_hooks=[prepare_aiohttp_projects],
    verification_steps=[
        inline_verification_step(
            "aiohttp-smoke",
            """
import importlib.util

import aiohttp
import aiohttp._http_parser as http_parser_ext
import aiohttp._http_writer as http_writer_ext
import aiohttp._websocket.mask as mask_ext
import aiohttp._websocket.reader_c as reader_ext
from multidict import CIMultiDict

for name in (
    "aiohttp._http_parser",
    "aiohttp._http_writer",
    "aiohttp._websocket.mask",
    "aiohttp._websocket.reader_c",
):
    assert importlib.util.find_spec(name).origin == "built-in", name

headers = CIMultiDict([("Host", "example.com"), ("X-Test", "ok")])
serialized = http_writer_ext._serialize_headers("GET / HTTP/1.1", headers)
assert serialized == b"GET / HTTP/1.1\\r\\nHost: example.com\\r\\nX-Test: ok\\r\\n\\r\\n", serialized

data = bytearray(b"abcd")
mask_ext._websocket_mask_cython(b"\\x01\\x02\\x03\\x04", data)
assert data == bytearray([0x60, 0x60, 0x60, 0x60]), data

request = http_parser_ext.RawRequestMessage(
    "GET",
    "/",
    aiohttp.HttpVersion11,
    headers,
    tuple(headers.items()),
    False,
    None,
    False,
    False,
    None,
)
assert request.method == "GET" and request.path == "/", request
assert hasattr(reader_ext, "WebSocketReader")
""",
        )
    ],
)
