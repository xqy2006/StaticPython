from __future__ import annotations

from packaging.version import Version

from libs import (
    LibraryIntegration,
    _candidate_pypi_archives,
    _copy_entry,
    _download_file,
    _extract_archive,
    _normalized_project_name,
    _resolve_source_entry,
    source_path,
    write_source_text,
)


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


def prepare_regex_source(context) -> None:
    integration = LIBRARY_INTEGRATION
    project_name = integration.project_name or integration.name
    normalized = _normalized_project_name(project_name)
    release_version = integration.release_version
    target_version = Version(".".join(str(part) for part in context.version_info))

    candidates = list(
        _candidate_pypi_archives(
            context.download_cache_root,
            project_name,
            target_version,
            release_version,
        )
    )

    # Newer regex releases may publish wheels only on PyPI. In that case we still
    # need the real C sources for our static build, so fall back to the matching
    # upstream tag archive.
    if release_version is not None:
        github_archive_path = (
            context.download_cache_root
            / "github"
            / "mrabarnett-mrab-regex"
            / "tags"
            / release_version
            / f"{release_version}.zip"
        )
        github_url = f"https://github.com/mrabarnett/mrab-regex/archive/refs/tags/{release_version}.zip"
        candidates.append((release_version, github_archive_path, github_url, github_archive_path.exists()))

    failures: list[str] = []
    for resolved_release_version, archive_path, url, cached in candidates:
        source_kind = "github" if "github" in archive_path.parts else "pypi"
        extract_root = (
            context.work_cache_root
            / source_kind
            / normalized
            / resolved_release_version
            / "extracted"
            / archive_path.name
        )

        if not archive_path.exists():
            assert url is not None
            context.log(f"downloading {project_name} {resolved_release_version} from {source_kind}")
            _download_file(url, archive_path)
        elif cached:
            context.log(
                f"reusing cached {project_name} {resolved_release_version} {source_kind} archive without refreshing metadata"
            )
        else:
            context.log(f"reusing cached {project_name} {resolved_release_version} {source_kind} archive")

        try:
            extracted_root = _extract_archive(archive_path, extract_root, context.log)
            context.log(f"using {project_name} {resolved_release_version} source from {extracted_root}")

            _copy_entry(
                _resolve_source_entry(extracted_root, "regex||Python3||regex_3"),
                context.source_root / "Lib" / "regex",
            )
            _copy_entry(
                _resolve_source_entry(extracted_root, "src||Python3||regex_3"),
                context.source_root / "regex_builtin" / "src",
            )
            return
        except RuntimeError as exc:
            failure = f"{archive_path.name}: {exc}"
            failures.append(failure)
            context.log(
                f"distribution candidate failed for {project_name} {resolved_release_version}: {failure}"
            )

    target_description = f" release {release_version!r}" if release_version is not None else ""
    raise RuntimeError(
        f"all compatible source artifacts failed for {project_name!r}{target_description}: "
        + "; ".join(failures)
    )


LIBRARY_INTEGRATION = LibraryIntegration(
    name="regex",
    source_provider="pypi",
    project_name="regex",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/regex",
        "regex_builtin/src",
    ],
    cleanup_paths=[],
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
    prepare_source_hooks=[prepare_regex_source, prepare_regex_project],
    pre_patch_hooks=[],
    post_patch_hooks=[],
    pre_build_hooks=[],
)
