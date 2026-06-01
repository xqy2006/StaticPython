from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from xml.sax.saxutils import escape

from libs import pypi_library, source_path, write_source_text
from tools import ensure_tool, get_pcbuild_output_dir, run


WXPYTHON_VERSION = "4.2.5"
WXPYTHON_GUID_NAMESPACE = uuid.UUID("63b70660-0ed9-4b6a-97c9-91f857ed5d65")

WXPYTHON_ETG_MODULES = [
    "_core",
    "_adv",
    "_aui",
    "_dataview",
    "_glcanvas",
    "_grid",
    "_html",
    "_html2",
    "_media",
    "_msw",
    "_propgrid",
    "_ribbon",
    "_richtext",
    "_stc",
    "_xml",
    "_xrc",
]

WXPYTHON_SIPLIB_SOURCES = [
    "wxpython_builtin/sip/siplib/apiversions.c",
    "wxpython_builtin/sip/siplib/descriptors.c",
    "wxpython_builtin/sip/siplib/int_convertors.c",
    "wxpython_builtin/sip/siplib/objmap.c",
    "wxpython_builtin/sip/siplib/qtlib.c",
    "wxpython_builtin/sip/siplib/sip_array.c",
    "wxpython_builtin/sip/siplib/siplib.c",
    "wxpython_builtin/sip/siplib/threads.c",
    "wxpython_builtin/sip/siplib/voidptr.c",
]

WXPYTHON_STATIC_PROJECTS = [
    "wx.siplib.vcxproj",
    *(f"wx.{module}.vcxproj" for module in WXPYTHON_ETG_MODULES),
]

WXPYTHON_MODULE_LIBRARIES = [
    "wx.siplib.lib",
    *(f"wx.{module}.lib" for module in WXPYTHON_ETG_MODULES),
]

WXWIDGETS_STATIC_LIBRARIES = [
    "wxbase32u.lib",
    "wxbase32u_net.lib",
    "wxbase32u_xml.lib",
    "wxexpat.lib",
    "wxjpeg.lib",
    "wxmsw32u_adv.lib",
    "wxmsw32u_aui.lib",
    "wxmsw32u_core.lib",
    "wxmsw32u_gl.lib",
    "wxmsw32u_html.lib",
    "wxmsw32u_media.lib",
    "wxmsw32u_propgrid.lib",
    "wxmsw32u_qa.lib",
    "wxmsw32u_ribbon.lib",
    "wxmsw32u_richtext.lib",
    "wxmsw32u_stc.lib",
    "wxmsw32u_webview.lib",
    "wxmsw32u_xrc.lib",
    "wxpng.lib",
    "wxregexu.lib",
    "wxscintilla.lib",
    "wxtiff.lib",
    "wxzlib.lib",
]

WXPYTHON_SYSTEM_LIBRARIES = [
    "kernel32.lib",
    "user32.lib",
    "gdi32.lib",
    "winspool.lib",
    "comdlg32.lib",
    "comctl32.lib",
    "advapi32.lib",
    "shell32.lib",
    "shlwapi.lib",
    "ole32.lib",
    "oleaut32.lib",
    "uuid.lib",
    "version.lib",
    "rpcrt4.lib",
    "ws2_32.lib",
    "wininet.lib",
    "winmm.lib",
    "uxtheme.lib",
    "oleacc.lib",
    "msimg32.lib",
    "imm32.lib",
    "setupapi.lib",
    "propsys.lib",
    "gdiplus.lib",
    "windowscodecs.lib",
    "opengl32.lib",
    "glu32.lib",
]


def _project_guid(name: str) -> str:
    return "{" + str(uuid.uuid5(WXPYTHON_GUID_NAMESPACE, name)).upper() + "}"


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


def _compile_items(sources: list[str]) -> str:
    items = []
    for source in sources:
        items.append(
            "\n".join(
                [
                    f'    <ClCompile Include="{escape(_msbuild_path(source))}">',
                    f"      <ObjectFileName>{escape(_object_name(source))}</ObjectFileName>",
                    "    </ClCompile>",
                ]
            )
        )
    return "\n".join(items)


def _wxpython_include_dirs(module: str) -> list[str]:
    dirs = [
        _msbuild_path("wxpython_builtin/sip/siplib"),
        _msbuild_path("wxpython_builtin/sip/cpp"),
        _msbuild_path("wxpython_builtin/src"),
        _msbuild_path("Lib/wx/include"),
        _msbuild_path("wxpython_builtin/wxWidgets/lib/vc_x64_lib/mswu"),
        _msbuild_path("wxpython_builtin/wxWidgets/include"),
        _msbuild_path("wxpython_builtin/wxWidgets/src/tiff/libtiff"),
        _msbuild_path("wxpython_builtin/wxWidgets/src/jpeg"),
        _msbuild_path("wxpython_builtin/wxWidgets/src/png"),
        _msbuild_path("wxpython_builtin/wxWidgets/src/zlib"),
        _msbuild_path("wxpython_builtin/wxWidgets/3rdparty/pcre/src"),
        _msbuild_path("wxpython_builtin/wxWidgets/src/expat/lib"),
    ]
    if module == "_stc":
        dirs.extend(
            [
                _msbuild_path("wxpython_builtin/wxWidgets/src/stc/scintilla/include"),
                _msbuild_path("wxpython_builtin/wxWidgets/src/stc/scintilla/lexlib"),
                _msbuild_path("wxpython_builtin/wxWidgets/src/stc/scintilla/src"),
            ]
        )
    dirs.append("%(AdditionalIncludeDirectories)")
    return dirs


def _wxpython_definitions(module: str) -> list[str]:
    definitions = [
        "Py_NO_ENABLE_SHARED",
        "WIN32",
        "_WINDOWS",
        "__WXMSW__",
        "ISOLATION_AWARE_ENABLED",
        "_CRT_SECURE_NO_WARNINGS",
        "_CRT_SECURE_NO_DEPRECATE=1",
        "_SCL_SECURE_NO_WARNINGS=1",
        "NDEBUG",
        "_UNICODE",
        "UNICODE",
    ]
    if module == "_stc":
        definitions.extend(["SCI_LEXER", "LINK_LEXERS"])
    definitions.append("%(PreprocessorDefinitions)")
    return definitions


def _render_static_project(
    *,
    project_name: str,
    module_name: str,
    root_namespace: str,
    sources: list[str],
) -> str:
    include_dirs = ";".join(_wxpython_include_dirs(module_name))
    definitions = ";".join(_wxpython_definitions(module_name))
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{_project_guid(project_name)}</ProjectGuid>
    <RootNamespace>{root_namespace}</RootNamespace>
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
    <TargetName>{project_name.removesuffix(".vcxproj")}</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>{escape(include_dirs)}</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>{escape(definitions)}</PreprocessorDefinitions>
      <DisableSpecificWarnings>4100;4127;4244;4267;4355;4512;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <ExceptionHandling>Sync</ExceptionHandling>
      <RuntimeTypeInfo>true</RuntimeTypeInfo>
      <LanguageStandard>stdcpp17</LanguageStandard>
      <AdditionalOptions>/bigobj /EHsc /GR /utf-8 %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{_compile_items(sources)}
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def _read_sbf_sources(context, module: str) -> list[str]:
    sbf_path = source_path(context, f"wxpython_builtin/sip/cpp/{module}.sbf")
    if not sbf_path.exists():
        raise RuntimeError(f"wxPython generated source manifest is missing: {sbf_path}")
    for line in sbf_path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if separator and key.strip() == "sources":
            sources = [f"wxpython_builtin/sip/cpp/{entry}" for entry in value.split()]
            missing = [source for source in sources if not source_path(context, source).exists()]
            if missing:
                raise RuntimeError(f"wxPython generated sources are missing for {module}: {', '.join(missing[:5])}")
            return sorted(sources)
    raise RuntimeError(f"wxPython generated source manifest has no sources entry: {sbf_path}")


def _enable_wxwidgets_feature(context, relative_path: str, name: str) -> bool:
    path = source_path(context, relative_path)
    if not path.exists():
        return False

    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        stripped = line.lstrip()
        if not stripped.startswith("#define"):
            continue
        parts = stripped.split()
        if len(parts) < 3 or parts[1] != name:
            continue
        if parts[2] == "1":
            return True
        if parts[2] != "0":
            raise RuntimeError(f"wxWidgets setup option {name} has unexpected value in {relative_path}: {parts[2]}")

        newline = "\r\n" if line.endswith("\r\n") else "\n" if line.endswith("\n") else ""
        indent = line[: len(line) - len(stripped)]
        lines[index] = f"{indent}#define {name}           1{newline}"
        path.write_text("".join(lines), encoding="utf-8")
        context.log(f"enabled wxWidgets setup option {name} in {relative_path}")
        return True

    raise RuntimeError(f"wxWidgets setup option {name} was not found in {relative_path}")


def _patch_wxwidgets_setup(context) -> None:
    patched = False
    for relative_path in (
        "wxpython_builtin/wxWidgets/include/wx/msw/setup.h",
        "wxpython_builtin/wxWidgets/include/wx/setup_inc.h",
    ):
        patched = _enable_wxwidgets_feature(context, relative_path, "wxUSE_IFF") or patched
    if not patched:
        raise RuntimeError("wxPython integration could not locate a wxWidgets setup header to enable wxUSE_IFF")


def _write_wxpython_projects(context) -> None:
    write_source_text(
        context,
        "PCbuild/wx.siplib.vcxproj",
        _render_static_project(
            project_name="wx.siplib.vcxproj",
            module_name="siplib",
            root_namespace="wx_siplib",
            sources=WXPYTHON_SIPLIB_SOURCES,
        ),
    )
    for module in WXPYTHON_ETG_MODULES:
        write_source_text(
            context,
            f"PCbuild/wx.{module}.vcxproj",
            _render_static_project(
                project_name=f"wx.{module}.vcxproj",
                module_name=module,
                root_namespace=f"wx_{module.removeprefix('_')}",
                sources=_read_sbf_sources(context, module),
            ),
        )


def prepare_wxpython_project(context) -> None:
    if context.platform != "x64":
        raise RuntimeError(f"wxPython builtin integration currently supports only x64, not {context.platform}")
    _patch_wxwidgets_setup(context)
    _write_wxpython_projects(context)


def _wxwidgets_source_dir(context) -> Path:
    return source_path(context, "wxpython_builtin/wxWidgets")


def _wxwidgets_library_dir(context) -> Path:
    return _wxwidgets_source_dir(context) / "lib" / "vc_x64_lib"


def _force_wxwidgets_static_runtime(context) -> None:
    changed = 0
    for project in (_wxwidgets_source_dir(context) / "build" / "msw").glob("*.vcxproj"):
        text = project.read_text(encoding="utf-8")
        updated = text
        updated = updated.replace("MultiThreadedDebugDLL", "MultiThreadedDebug")
        updated = updated.replace("MultiThreadedDLL", "MultiThreaded")
        updated = updated.replace("/MDd", "/MTd")
        updated = updated.replace("/MD", "/MT")
        if updated != text:
            project.write_text(updated, encoding="utf-8")
            changed += 1
    if changed:
        context.log(f"forced wxWidgets static runtime in {changed} project(s)")


def _copy_wxwidgets_libraries(context) -> None:
    library_dir = _wxwidgets_library_dir(context)
    output_dir = get_pcbuild_output_dir(context.source_root, context.platform)
    output_dir.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    for library in WXWIDGETS_STATIC_LIBRARIES:
        source = library_dir / library
        if not source.exists():
            missing.append(library)
            continue
        shutil.copy2(source, output_dir / library)
    if missing:
        raise RuntimeError(f"wxWidgets build did not produce required static libraries: {', '.join(missing)}")


def prepare_wxpython_artifacts(context) -> None:
    _patch_wxwidgets_setup(context)
    output_dir = get_pcbuild_output_dir(context.source_root, context.platform)
    if all((output_dir / library).exists() for library in WXWIDGETS_STATIC_LIBRARIES):
        context.log(f"using existing wxWidgets static libraries at {output_dir.relative_to(context.source_root)}")
        return

    ensure_tool("msbuild")
    wxwidgets_root = _wxwidgets_source_dir(context)
    solution = _find_wxwidgets_solution(wxwidgets_root)
    _force_wxwidgets_static_runtime(context)
    run(
        context.log,
        [
            "msbuild",
            str(solution),
            "/m:1",
            "/nologo",
            "/p:Configuration=Release",
            "/p:Platform=x64",
            "/p:PreferredToolArchitecture=x64",
            "/p:CL_MPCount=1",
            "/p:MultiProcMaxCount=1",
            "/p:EnforceProcessCountAcrossBuilds=true",
            "/p:VcpkgEnabled=false",
        ],
        cwd=solution.parent,
        timeout=60 * 60,
    )
    _copy_wxwidgets_libraries(context)


def _find_wxwidgets_solution(wxwidgets_root: Path) -> Path:
    build_dir = wxwidgets_root / "build" / "msw"
    preferred = build_dir / "wx_vc17.sln"
    if preferred.exists():
        return preferred
    candidates = sorted(build_dir.glob("wx_vc*.sln"), reverse=True)
    if candidates:
        return candidates[0]
    raise RuntimeError(f"wxWidgets MSBuild solution is missing under {build_dir}")


LIBRARY_INTEGRATION = pypi_library(
    name="wxpython",
    project_name="wxPython",
    release_version=WXPYTHON_VERSION,
    source_mapping={
        "wx": "Lib/wx",
        "sip": "wxpython_builtin/sip",
        "src": "wxpython_builtin/src",
        "ext/wxWidgets/build/msw": "wxpython_builtin/wxWidgets/build/msw",
        "ext/wxWidgets/art": "wxpython_builtin/wxWidgets/art",
        "ext/wxWidgets/include": "wxpython_builtin/wxWidgets/include",
        "ext/wxWidgets/src": "wxpython_builtin/wxWidgets/src",
        "?ext/wxWidgets/3rdparty": "wxpython_builtin/wxWidgets/3rdparty",
    },
    source_ignore_patterns=[
        ".git",
        ".github",
        "docs",
        "demos",
        "demo",
        "samples",
        "tests",
        "unittests",
        "buildbot",
        "docker",
    ],
    materialized_paths=[
        "Lib/wx/__init__.py",
        "Lib/wx/core.py",
        "wxpython_builtin/sip/cpp/_core.sbf",
        "wxpython_builtin/sip/siplib/siplib.c",
        "wxpython_builtin/wxWidgets/build/msw",
        "wxpython_builtin/wxWidgets/art",
        "wxpython_builtin/wxWidgets/include/wx/wx.h",
        *[f"PCbuild/{project}" for project in WXPYTHON_STATIC_PROJECTS],
    ],
    cleanup_paths=[
        "wxpython_builtin",
    ],
    python_packages=["wx"],
    static_library_projects_release_x64=WXPYTHON_STATIC_PROJECTS,
    native_static_projects=[
        {
            "project": project,
            "guid": _project_guid(project),
        }
        for project in WXPYTHON_STATIC_PROJECTS
    ],
    builtin_module_registrations=[
        {
            "name": "wx.siplib",
            "pyinit": "PyInit_siplib",
        },
        *[
            {
                "name": f"wx.{module}",
                "pyinit": f"PyInit_{module}",
            }
            for module in WXPYTHON_ETG_MODULES
        ],
    ],
    python_link_dependencies_release_x64=[
        *WXPYTHON_MODULE_LIBRARIES,
        *WXWIDGETS_STATIC_LIBRARIES,
        *WXPYTHON_SYSTEM_LIBRARIES,
    ],
    overlay_entries=[
        "wxpython_runtime_test.py",
    ],
    prepare_source_hooks=[prepare_wxpython_project],
    pre_build_hooks=[prepare_wxpython_artifacts],
)
