from __future__ import annotations

import ast
from pathlib import Path

from libs import pypi_library, source_path, transform_source_text, write_source_text


PSUTIL_WINDOWS_PROJECT_GUID = "{3B30BB3F-D913-48A8-AB4D-88CB41369C1D}"


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _object_file_name(source_file: str) -> str:
    stem = source_file.replace("/", "_").replace("\\", "_")
    return f"$(IntDir){stem}.obj"


def _render_psutil_windows_project(source_files: list[str], psutil_version: int) -> str:
    compile_items = "\n".join(
        "\n".join(
            [
                f'    <ClCompile Include="..\\Lib\\psutil\\{name}">',
                f"      <ObjectFileName>{_object_file_name(name)}</ObjectFileName>",
                "    </ClCompile>",
            ]
        )
        for name in source_files
    )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{PSUTIL_WINDOWS_PROJECT_GUID}</ProjectGuid>
    <RootNamespace>psutil_psutil_windows</RootNamespace>
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
    <TargetName>psutil._psutil_windows</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>..\\Lib\\psutil;..\\Lib\\psutil\\arch\\all;..\\Lib\\psutil\\arch\\windows;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>Py_NO_ENABLE_SHARED;PSUTIL_WINDOWS=1;PSUTIL_SIZEOF_PID_T=4;PSUTIL_VERSION={psutil_version};_WIN32_WINNT=0x0A00;_AVAIL_WINVER_=0x0A00;_CRT_SECURE_NO_WARNINGS;PSAPI_VERSION=1;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <AdditionalOptions>/bigobj %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{compile_items}
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def _parse_psutil_version(context) -> int:
    candidates = [
        source_path(context, "Lib/psutil/__init__.py"),
        source_path(context, "Lib/psutil/psutil.py"),
    ]
    for candidate in candidates:
        if not candidate.exists():
            continue
        for line in candidate.read_text(encoding="utf-8").splitlines():
            if line.startswith("__version__"):
                version = ast.literal_eval(line.split("=", 1)[1].strip())
                return int(version.replace(".", ""))
    if source_path(context, "Lib/psutil/_psutil_mswindows.c").exists():
        return 11
    searched = ", ".join(str(path) for path in candidates)
    raise RuntimeError(f"could not find psutil __version__ in {searched}")


def _discover_psutil_windows_sources(context) -> list[str]:
    root = source_path(context, "Lib/psutil")
    source_files = [path.relative_to(root).as_posix() for path in sorted((root / "arch" / "all").glob("*.c"))]
    if (root / "_psutil_windows.c").exists():
        source_files.append("_psutil_windows.c")
        source_files.extend(path.relative_to(root).as_posix() for path in sorted((root / "arch" / "windows").glob("*.c")))
    elif (root / "_psutil_mswindows.c").exists():
        legacy_support_sources = []
        if (root / "_psutil_common.c").exists():
            legacy_support_sources.append("_psutil_common.c")
        source_files.extend(
            [
                "_psutil_mswindows.c",
                *legacy_support_sources,
                *[
                    path.relative_to(root).as_posix()
                    for path in sorted((root / "arch" / "mswindows").glob("*.c"))
                ],
            ]
        )
    else:
        raise RuntimeError("psutil source files are missing: _psutil_windows.c or _psutil_mswindows.c")
    missing = [name for name in source_files if not (root / name).exists()]
    if missing:
        raise RuntimeError("psutil source files are missing: " + ", ".join(missing))
    return source_files


def _patch_legacy_psutil_windows_names(context) -> None:
    root = source_path(context, "Lib/psutil")
    if not (root / "_psutil_mswindows.c").exists():
        return

    def patch_c(text: str) -> str:
        updated = text.replace("_psutil_mswindows", "_psutil_windows").replace(
            "psutil_mswindows",
            "psutil_windows",
        )
        if "mswindows" in updated:
            raise RuntimeError("psutil legacy Windows C module rename anchor not patched")
        return updated

    def patch_py(text: str) -> str:
        updated = text.replace("import _psutil_mswindows", "from psutil import _psutil_windows").replace(
            "from _psutil_mswindows import",
            "from psutil._psutil_windows import",
        ).replace("_psutil_mswindows", "_psutil_windows")
        if "_psutil_mswindows" in updated:
            raise RuntimeError("psutil legacy Windows Python module rename anchor not patched")
        return updated

    transform_source_text(context, "Lib/psutil/_psutil_mswindows.c", patch_c)
    transform_source_text(context, "Lib/psutil/_psmswindows.py", patch_py)


def prepare_psutil_windows_project(context) -> None:
    _patch_legacy_psutil_windows_names(context)
    write_source_text(
        context,
        "PCbuild/psutil._psutil_windows.vcxproj",
        _render_psutil_windows_project(_discover_psutil_windows_sources(context), _parse_psutil_version(context)),
    )


LIBRARY_INTEGRATION = pypi_library(
    name="psutil",
    source_mapping={
        "psutil": "Lib/psutil",
    },
    python_packages=["psutil"],
    static_library_projects_release_x64=["psutil._psutil_windows.vcxproj"],
    native_static_projects=[
        {
            "project": "psutil._psutil_windows.vcxproj",
            "guid": PSUTIL_WINDOWS_PROJECT_GUID,
        }
    ],
    builtin_module_registrations=[
        {
            "name": "psutil._psutil_windows",
            "pyinit": "PyInit__psutil_windows",
        }
    ],
    python_link_dependencies_release_x64=[
        "advapi32.lib",
        "kernel32.lib",
        "netapi32.lib",
        "pdh.lib",
        "PowrProf.lib",
        "psapi.lib",
        "shell32.lib",
        "ws2_32.lib",
        "psutil._psutil_windows.lib",
    ],
    prepare_source_hooks=[prepare_psutil_windows_project],
)
