from __future__ import annotations

from pathlib import Path

from libs import pypi_library, source_path, write_source_text


UJSON_PROJECT_GUID = "{E87E7715-3227-4F4D-A7F7-02F02E3E9B4D}"


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _render_ujson_project(source_files: list[str], include_dirs: list[str]) -> str:
    compile_items = "\n".join(f'    <ClCompile Include="..\\ujson_builtin\\{name}" />' for name in source_files)
    include_directories = ";".join(f"..\\ujson_builtin\\{name}" for name in include_dirs)
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{UJSON_PROJECT_GUID}</ProjectGuid>
    <RootNamespace>ujson</RootNamespace>
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
    <TargetName>ujson</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>{include_directories};%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>Py_NO_ENABLE_SHARED;_GNU_SOURCE;_CRT_SECURE_NO_WARNINGS;%(PreprocessorDefinitions)</PreprocessorDefinitions>
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


def _discover_ujson_build_layout(context) -> tuple[list[str], list[str]]:
    root = source_path(context, "ujson_builtin")
    source_files = [
        "python/ujson.c",
        "python/objToJSON.c",
        "python/JSONtoObj.c",
        "lib/ultrajsonenc.c",
        "lib/ultrajsondec.c",
    ]
    include_dirs = [
        "python",
        "lib",
    ]
    double_conversion_dir = root / "deps" / "double-conversion" / "double-conversion"
    dconv_wrapper = root / "lib" / "dconv_wrapper.cc"
    if dconv_wrapper.exists() and double_conversion_dir.exists():
        include_dirs.append("deps/double-conversion/double-conversion")
        source_files.append("lib/dconv_wrapper.cc")
        source_files.extend(path.relative_to(root).as_posix() for path in sorted(double_conversion_dir.glob("*.cc")))
    missing = [name for name in source_files if not (root / name).exists()]
    if missing:
        raise RuntimeError("ujson source files are missing: " + ", ".join(missing))
    return source_files, include_dirs


def _ensure_version_header(context) -> None:
    version_header = source_path(context, "ujson_builtin/python/version.h")
    if version_header.exists():
        return
    template = source_path(context, "ujson_builtin/python/version_template.h")
    if not template.exists():
        raise RuntimeError("ujson version.h and version_template.h are both missing")
    text = template.read_text(encoding="utf-8").replace("{version}", "0+staticpython")
    version_header.write_text(text, encoding="utf-8", newline="\n")
    context.log(f"generated {version_header.relative_to(context.source_root)}")


def prepare_ujson_project(context) -> None:
    _ensure_version_header(context)
    source_files, include_dirs = _discover_ujson_build_layout(context)
    write_source_text(context, "PCbuild/ujson.vcxproj", _render_ujson_project(source_files, include_dirs))


LIBRARY_INTEGRATION = pypi_library(
    name="ujson",
    source_mapping={
        "src/ujson||.": "ujson_builtin",
    },
    python_packages=["ujson"],
    static_library_projects_release_x64=["ujson.vcxproj"],
    native_static_projects=[
        {
            "project": "ujson.vcxproj",
            "guid": UJSON_PROJECT_GUID,
        }
    ],
    builtin_module_registrations=[
        {
            "name": "ujson",
            "pyinit": "PyInit_ujson",
        }
    ],
    python_link_dependencies_release_x64=["ujson.lib"],
    prepare_source_hooks=[prepare_ujson_project],
)
