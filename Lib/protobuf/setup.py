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
    transform_source_text,
    write_source_text,
)


PROTOBUF_UPB_PROJECT_GUID = "{49F92857-8E8C-42B7-B81A-1DB737C9570A}"
PROTOBUF_UPB_PROJECT = "google._upb._message"


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


def _render_protobuf_upb_project(sources: list[str]) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{PROTOBUF_UPB_PROJECT_GUID}</ProjectGuid>
    <RootNamespace>google_upb_message</RootNamespace>
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
    <TargetName>{PROTOBUF_UPB_PROJECT}</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>..\\protobuf_builtin;..\\protobuf_builtin\\utf8_range;..\\Lib;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>Py_NO_ENABLE_SHARED;_CRT_SECURE_NO_WARNINGS;NDEBUG;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <AdditionalOptions>/bigobj %(AdditionalOptions)</AdditionalOptions>
      <CompileAs>CompileAsC</CompileAs>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{_render_compile_items(sources)}
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def _prepare_protobuf_source(context) -> None:
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

    _copy_entry(_resolve_source_entry(extracted_root, "google/protobuf"), context.source_root / "Lib" / "google" / "protobuf")

    for selector, target in (
        ("python", context.source_root / "protobuf_builtin" / "python"),
        ("upb", context.source_root / "protobuf_builtin" / "upb"),
        ("utf8_range", context.source_root / "protobuf_builtin" / "utf8_range"),
    ):
        try:
            src = _resolve_source_entry(extracted_root, selector)
        except RuntimeError:
            continue
        _copy_entry(src, target)


def _discover_upb_sources(context) -> list[str]:
    groups = [
        ("Lib/google/protobuf", "*.c", False),
        ("protobuf_builtin/python", "*.c", False),
        ("protobuf_builtin/upb", "*.c", True),
        ("protobuf_builtin/utf8_range", "*.c", False),
    ]
    sources: list[str] = []
    for relative, pattern, recursive in groups:
        root = source_path(context, relative)
        if not root.exists():
            continue
        paths = root.rglob(pattern) if recursive else root.glob(pattern)
        for path in sorted(paths):
            source = path.relative_to(context.source_root).as_posix()
            if "decode_fast" not in source:
                sources.append(source)

    required = [
        "protobuf_builtin/python/protobuf.c",
        "Lib/google/protobuf/descriptor.upb.c",
        "Lib/google/protobuf/descriptor.upbdefs.c",
    ]
    if not all(source_path(context, rel).exists() for rel in required):
        return []
    if not any(source.startswith("protobuf_builtin/upb/") for source in sources):
        return []
    return sources


def patch_protobuf_namespace(context) -> None:
    google_init = source_path(context, "Lib/google/__init__.py")
    if not google_init.exists():
        write_source_text(
            context,
            "Lib/google/__init__.py",
            "# Namespace package marker generated by StaticPython.\n",
        )
    upb_init = source_path(context, "Lib/google/_upb/__init__.py")
    if not upb_init.exists():
        write_source_text(
            context,
            "Lib/google/_upb/__init__.py",
            "# Package marker generated by StaticPython for the builtin google._upb._message module.\n",
        )


def _patch_protobuf_c_text(text: str) -> str:
    old_mutex_type = (
        "typedef struct {\n"
        "#ifdef ENABLE_MUTEX\n"
        "  pthread_mutex_t mutex;\n"
        "#endif\n"
        "} FreeThreadingMutex;\n"
    )
    new_mutex_type = (
        "typedef struct {\n"
        "#ifdef ENABLE_MUTEX\n"
        "  pthread_mutex_t mutex;\n"
        "#else\n"
        "  char unused;\n"
        "#endif\n"
        "} FreeThreadingMutex;\n"
    )
    old_cache_initializer = (
        "#ifdef ENABLE_MUTEX\n"
        "static FreeThreadingMutex obj_cache_mutex = {PTHREAD_MUTEX_INITIALIZER};\n"
        "#else\n"
        "static FreeThreadingMutex obj_cache_mutex = {};\n"
        "#endif\n"
    )
    new_cache_initializer = (
        "#ifdef ENABLE_MUTEX\n"
        "static FreeThreadingMutex obj_cache_mutex = {PTHREAD_MUTEX_INITIALIZER};\n"
        "#else\n"
        "static FreeThreadingMutex obj_cache_mutex = {0};\n"
        "#endif\n"
    )

    old_type_count = text.count(old_mutex_type)
    if old_type_count:
        if old_type_count != 1:
            raise RuntimeError("protobuf free-threading mutex type anchor matched more than once")
        text = text.replace(old_mutex_type, new_mutex_type, 1)
    elif new_mutex_type not in text:
        if "FreeThreadingMutex" in text:
            raise RuntimeError("protobuf free-threading mutex type anchor not found")
        return text

    old_initializer_count = text.count(old_cache_initializer)
    if old_initializer_count:
        if old_initializer_count != 1:
            raise RuntimeError("protobuf free-threading mutex initializer anchor matched more than once")
        text = text.replace(old_cache_initializer, new_cache_initializer, 1)
    elif (
        "static FreeThreadingMutex obj_cache_mutex" in text
        and new_cache_initializer not in text
    ):
        raise RuntimeError("protobuf free-threading mutex initializer anchor not found")
    return text


def patch_protobuf_sources(context) -> None:
    def patch_message_c(text: str) -> str:
        updated = text.replace(
            "__attribute__((flatten)) static PyObject* PyUpb_Message_GetAttr(",
            "static PyObject* PyUpb_Message_GetAttr(",
        )
        if "__attribute__((flatten))" in updated:
            raise RuntimeError("protobuf message flatten attribute anchor not patched")
        return updated

    transform_source_text(
        context,
        "protobuf_builtin/python/protobuf.c",
        _patch_protobuf_c_text,
        allow_missing=True,
    )
    transform_source_text(
        context,
        "protobuf_builtin/python/message.c",
        patch_message_c,
        allow_missing=True,
    )


def prepare_protobuf_project(context) -> None:
    patch_protobuf_sources(context)
    sources = _discover_upb_sources(context)
    if not sources:
        context.log("protobuf upb source tree is absent in this release; keeping pure Python build")
        return
    write_source_text(
        context,
        f"PCbuild/{PROTOBUF_UPB_PROJECT}.vcxproj",
        _render_protobuf_upb_project(sources),
    )


LIBRARY_INTEGRATION = LibraryIntegration(
    name="protobuf",
    source_provider="pypi",
    project_name="protobuf",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/google/protobuf",
    ],
    cleanup_paths=[],
    python_packages=["google.protobuf", "google._upb"],
    static_library_projects_release_x64=[f"{PROTOBUF_UPB_PROJECT}.vcxproj"],
    native_static_projects=[
        {
            "project": f"{PROTOBUF_UPB_PROJECT}.vcxproj",
            "guid": PROTOBUF_UPB_PROJECT_GUID,
        }
    ],
    builtin_module_registrations=[
        {
            "name": "google._upb._message",
            "pyinit": "PyInit__message",
        }
    ],
    staged_static_libraries_release_x64=[],
    python_link_dependencies_release_x64=[f"{PROTOBUF_UPB_PROJECT}.lib"],
    python_link_wholearchive_release_x64=[],
    prepare_source_hooks=[_prepare_protobuf_source, prepare_protobuf_project],
    pre_patch_hooks=[],
    post_patch_hooks=[patch_protobuf_namespace],
    pre_build_hooks=[],
)
