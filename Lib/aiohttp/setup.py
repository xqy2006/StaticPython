from __future__ import annotations

from packaging.version import Version

from libs import (
    LibraryIntegration,
    _copy_entry,
    _download_file,
    _extract_archive,
    _find_cached_pypi_archive,
    _normalized_project_name,
    _resolve_source_entry,
    _select_pypi_file,
    source_path,
    write_source_text,
)


POTENTIAL_PROJECTS = {
    "aiohttp._http_parser": {
        "guid": "{C73B7812-A40A-49A7-86E9-59313F01955C}",
        "pyinit": "PyInit__http_parser",
    },
    "aiohttp._http_writer": {
        "guid": "{5C2F4920-87A3-4013-9D6D-E4D8B9F7B4DD}",
        "pyinit": "PyInit__http_writer",
    },
    "aiohttp._helpers": {
        "guid": "{FAAD4B16-D0DA-4B47-9D0F-262247355BA2}",
        "pyinit": "PyInit__helpers",
    },
    "aiohttp._websocket": {
        "guid": "{E2B3E298-9B75-44A0-9A5B-6B77B65D0D0A}",
        "pyinit": "PyInit__websocket",
    },
    "aiohttp._websocket.mask": {
        "guid": "{2E8B4905-88F2-47D4-9FA7-C87FC034EED0}",
        "pyinit": "PyInit_mask",
    },
    "aiohttp._websocket.reader_c": {
        "guid": "{BD1B8D1F-1798-4EE3-A8D8-56697419B0C2}",
        "pyinit": "PyInit_reader_c",
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


def _prepare_aiohttp_source(context) -> None:
    integration = LIBRARY_INTEGRATION
    project_name = integration.project_name or integration.name
    normalized = _normalized_project_name(project_name)
    release_version = integration.release_version
    target_version = Version(".".join(str(part) for part in context.version_info))
    cached_archive_path = None

    if release_version is not None:
        cached_archive_path = _find_cached_pypi_archive(
            context.download_cache_root,
            normalized,
            release_version,
            target_version,
        )
        if cached_archive_path is not None:
            context.log(f"reusing cached {project_name} {release_version} archive without refreshing PyPI metadata")
            resolved_release_version = release_version
            archive_path = cached_archive_path
        else:
            resolved_release_version, file_info = _select_pypi_file(project_name, target_version, release_version)
            archive_path = (
                context.download_cache_root
                / "pypi"
                / normalized
                / resolved_release_version
                / file_info["filename"]
            )
            url = file_info["url"]
    else:
        resolved_release_version, file_info = _select_pypi_file(project_name, target_version, release_version)
        archive_path = (
            context.download_cache_root
            / "pypi"
            / normalized
            / resolved_release_version
            / file_info["filename"]
        )
        url = file_info["url"]

    extract_root = context.work_cache_root / "pypi" / normalized / resolved_release_version / "extracted"

    if not archive_path.exists():
        context.log(f"downloading {project_name} {resolved_release_version} from PyPI")
        _download_file(url, archive_path)
    elif cached_archive_path is None:
        context.log(f"reusing cached {project_name} {resolved_release_version} archive")

    extracted_root = _extract_archive(archive_path, extract_root, context.log)
    context.log(f"using {project_name} {resolved_release_version} source from {extracted_root}")

    _copy_entry(_resolve_source_entry(extracted_root, "aiohttp"), context.source_root / "Lib" / "aiohttp")

    try:
        llhttp_src = _resolve_source_entry(extracted_root, "vendor/llhttp")
    except RuntimeError:
        llhttp_src = None
    if llhttp_src is not None:
        _copy_entry(llhttp_src, context.source_root / "aiohttp_builtin" / "vendor" / "llhttp")

    try:
        http_parser_src = _resolve_source_entry(extracted_root, "vendor/http-parser")
    except RuntimeError:
        http_parser_src = None
    if http_parser_src is not None:
        _copy_entry(http_parser_src, context.source_root / "aiohttp_builtin" / "vendor" / "http-parser")


def _available_projects(context) -> dict[str, dict]:
    available: dict[str, dict] = {}

    if source_path(context, "Lib/aiohttp/_helpers.c").exists():
        available["aiohttp._helpers"] = {
            **POTENTIAL_PROJECTS["aiohttp._helpers"],
            "sources": ["Lib/aiohttp/_helpers.c"],
            "include_dirs": ["Lib/aiohttp"],
            "defines": [],
        }

    if source_path(context, "Lib/aiohttp/_http_writer.c").exists():
        available["aiohttp._http_writer"] = {
            **POTENTIAL_PROJECTS["aiohttp._http_writer"],
            "sources": ["Lib/aiohttp/_http_writer.c"],
            "include_dirs": ["Lib/aiohttp"],
            "defines": [],
        }

    if source_path(context, "Lib/aiohttp/_http_parser.c").exists():
        if source_path(context, "aiohttp_builtin/vendor/llhttp/build/c/llhttp.c").exists():
            available["aiohttp._http_parser"] = {
                **POTENTIAL_PROJECTS["aiohttp._http_parser"],
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
            }
        elif source_path(context, "aiohttp_builtin/vendor/http-parser/http_parser.c").exists():
            available["aiohttp._http_parser"] = {
                **POTENTIAL_PROJECTS["aiohttp._http_parser"],
                "sources": [
                    "Lib/aiohttp/_http_parser.c",
                    "Lib/aiohttp/_find_header.c",
                    "aiohttp_builtin/vendor/http-parser/http_parser.c",
                ],
                "include_dirs": [
                    "Lib/aiohttp",
                    "aiohttp_builtin/vendor/http-parser",
                ],
                "defines": [],
            }

    websocket_split = (
        source_path(context, "Lib/aiohttp/_websocket/mask.c").exists()
        and source_path(context, "Lib/aiohttp/_websocket/reader_c.c").exists()
    )
    if websocket_split:
        available["aiohttp._websocket.mask"] = {
            **POTENTIAL_PROJECTS["aiohttp._websocket.mask"],
            "sources": ["Lib/aiohttp/_websocket/mask.c"],
            "include_dirs": ["Lib/aiohttp", "Lib/aiohttp/_websocket"],
            "defines": [],
        }
        available["aiohttp._websocket.reader_c"] = {
            **POTENTIAL_PROJECTS["aiohttp._websocket.reader_c"],
            "sources": ["Lib/aiohttp/_websocket/reader_c.c"],
            "include_dirs": ["Lib/aiohttp", "Lib/aiohttp/_websocket"],
            "defines": [],
        }
    elif source_path(context, "Lib/aiohttp/_websocket.c").exists():
        available["aiohttp._websocket"] = {
            **POTENTIAL_PROJECTS["aiohttp._websocket"],
            "sources": ["Lib/aiohttp/_websocket.c"],
            "include_dirs": ["Lib/aiohttp"],
            "defines": [],
        }

    return available


def prepare_aiohttp_projects(context) -> None:
    for name, info in _available_projects(context).items():
        write_source_text(context, f"PCbuild/{name}.vcxproj", _render_project(name, info))


LIBRARY_INTEGRATION = LibraryIntegration(
    name="aiohttp",
    source_provider="pypi",
    project_name="aiohttp",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/aiohttp",
    ],
    cleanup_paths=[],
    python_packages=[
        "aiohttp",
    ],
    static_library_projects_release_x64=[f"{name}.vcxproj" for name in POTENTIAL_PROJECTS],
    native_static_projects=[
        {
            "project": f"{name}.vcxproj",
            "guid": info["guid"],
        }
        for name, info in POTENTIAL_PROJECTS.items()
    ],
    builtin_module_registrations=[
        {
            "name": name,
            "pyinit": info["pyinit"],
        }
        for name, info in POTENTIAL_PROJECTS.items()
    ],
    staged_static_libraries_release_x64=[],
    python_link_dependencies_release_x64=[f"{name}.lib" for name in POTENTIAL_PROJECTS],
    python_link_wholearchive_release_x64=[],
    prepare_source_hooks=[_prepare_aiohttp_source, prepare_aiohttp_projects],
    pre_patch_hooks=[],
    post_patch_hooks=[],
    pre_build_hooks=[],
)
