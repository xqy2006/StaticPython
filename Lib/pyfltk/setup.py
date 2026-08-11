from __future__ import annotations

import shutil
import subprocess
import tokenize
from pathlib import Path
from xml.sax.saxutils import escape

from libs import pypi_library, source_path, write_source_text
from tools import download_first_available, ensure_tool, extract_source_archive, get_pcbuild_output_dir, run


PYFLTK_PROJECT_GUID = "{4B6B52A6-20E4-4910-A4F0-87902076E828}"
FLTK_VERSION = "1.4.5"
SWIGWIN_VERSION = "4.3.1"
SWIGWIN_SHA256 = "7ea5197c557af20b2f7780ffcfe803bbe0e2009f5846874112aea37e5f693417"

FLTK_LIBRARY_NAMES = [
    "fltk.lib",
    "fltk_images.lib",
    "fltk_jpeg.lib",
    "fltk_png.lib",
    "fltk_z.lib",
    "fltk_forms.lib",
    "fltk_gl.lib",
]

PYFLTK_SYSTEM_LIBRARIES = [
    "kernel32.lib",
    "user32.lib",
    "gdi32.lib",
    "winspool.lib",
    "comdlg32.lib",
    "comctl32.lib",
    "advapi32.lib",
    "shell32.lib",
    "ole32.lib",
    "oleaut32.lib",
    "uuid.lib",
    "odbc32.lib",
    "odbccp32.lib",
    "wsock32.lib",
    "gdiplus.lib",
    "glu32.lib",
    "opengl32.lib",
]


def _msbuild_path(path: str) -> str:
    return "..\\" + path.replace("/", "\\")


def _object_name(source: str) -> str:
    return "$(IntDir)" + source.replace("/", "_").replace("\\", "_") + ".obj"


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _compile_items(sources: list[str]) -> str:
    blocks = []
    for source in sources:
        blocks.append(
            "\n".join(
                [
                    f'    <ClCompile Include="{escape(_msbuild_path(source))}">',
                    f"      <ObjectFileName>{escape(_object_name(source))}</ObjectFileName>",
                    "    </ClCompile>",
                ]
            )
        )
    return "\n".join(blocks)


def fltk_source_dir(context) -> Path:
    return source_path(context, f"pyfltk_builtin/fltk-{FLTK_VERSION}")


def fltk_build_dir(context) -> Path:
    return (
        context.work_cache_root
        / "pyfltk"
        / context.version_full
        / context.source_root.name
        / f"fltk-{FLTK_VERSION}-{context.platform}-{context.configuration}"
    )


def swigwin_dir(context) -> Path:
    return context.work_cache_root / "tools" / f"swigwin-{SWIGWIN_VERSION}"


def _render_pyfltk_project(context) -> str:
    sources = [
        "Lib/fltk/fltk_wrap.cpp",
        "pyfltk_builtin/contrib/ListSelect.cpp",
    ]
    include_dirs = [
        _msbuild_path("pyfltk_builtin/src"),
        _msbuild_path("pyfltk_builtin/contrib"),
        _msbuild_path(f"pyfltk_builtin/fltk-{FLTK_VERSION}"),
        str(fltk_build_dir(context)),
        "%(AdditionalIncludeDirectories)",
    ]
    definitions = [
        "Py_NO_ENABLE_SHARED",
        "WIN32",
        "FL_INTERNALS",
        "PYTHON",
        "PYTHON3",
        "_CRT_SECURE_NO_WARNINGS",
        "%(PreprocessorDefinitions)",
    ]
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{PYFLTK_PROJECT_GUID}</ProjectGuid>
    <RootNamespace>fltk__fltk</RootNamespace>
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
    <TargetName>fltk._fltk</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>{escape(";".join(include_dirs))}</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>{escape(";".join(definitions))}</PreprocessorDefinitions>
      <DisableSpecificWarnings>4100;4101;4127;4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <ExceptionHandling>Sync</ExceptionHandling>
      <LanguageStandard>stdcpp17</LanguageStandard>
      <AdditionalOptions>/bigobj /EHsc /GR %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{_compile_items(sources)}
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def ensure_fltk_source(context) -> Path:
    source_dir = fltk_source_dir(context)
    if (source_dir / "FL" / "Fl.H").exists():
        return source_dir

    archive_path = context.download_cache_root / "fltk" / FLTK_VERSION / f"fltk-{FLTK_VERSION}.zip"
    used_source = download_first_available(
        context.log,
        [
            f"https://github.com/fltk/fltk/archive/refs/tags/release-{FLTK_VERSION}.zip",
        ],
        archive_path,
    )
    extract_source_archive(context.log, archive_path, source_dir.parent, final_name=source_dir.name)
    if not (source_dir / "FL" / "Fl.H").exists():
        raise RuntimeError(f"downloaded FLTK source is missing FL/Fl.H: {source_dir}")
    context.log(f"materialized FLTK {FLTK_VERSION} from {used_source}")
    return source_dir


def ensure_swigwin(context) -> Path:
    tool_dir = swigwin_dir(context)
    swig_exe = tool_dir / "swig.exe"
    if swig_exe.exists():
        return swig_exe

    archive_path = context.download_cache_root / "swigwin" / SWIGWIN_VERSION / f"swigwin-{SWIGWIN_VERSION}.zip"
    used_source = download_first_available(
        context.log,
        [
            f"https://prdownloads.sourceforge.net/swig/swigwin-{SWIGWIN_VERSION}.zip",
            f"https://downloads.sourceforge.net/project/swig/swigwin/swigwin-{SWIGWIN_VERSION}/swigwin-{SWIGWIN_VERSION}.zip",
        ],
        archive_path,
        expected_sha256=SWIGWIN_SHA256,
    )
    extract_source_archive(context.log, archive_path, tool_dir.parent, final_name=tool_dir.name)
    if not swig_exe.exists():
        raise RuntimeError(f"downloaded swigwin archive is missing swig.exe: {tool_dir}")
    context.log(f"materialized swigwin {SWIGWIN_VERSION} from {used_source}")
    return swig_exe


def _wrap_pyfltk_shadow_module(path: Path) -> None:
    try:
        with tokenize.open(path) as handle:
            text = handle.read()
    except UnicodeDecodeError:
        raw = path.read_bytes()
        try:
            text = raw.decode("cp1252")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")
    if "_STATICPYTHON_PYFLTK_SHADOW_SOURCE" in text:
        return
    wrapped = (
        "# Generated by StaticPython; keep pyfltk's generated SWIG shadow module\n"
        "# importable while avoiding _freeze_module crashes on the very large file.\n"
        f"_STATICPYTHON_PYFLTK_SHADOW_SOURCE = {text!r}\n"
        "_STATICPYTHON_PYFLTK_SHADOW_FILENAME = globals().get('__file__', 'fltk/fltk.py')\n"
        "exec(compile(_STATICPYTHON_PYFLTK_SHADOW_SOURCE, _STATICPYTHON_PYFLTK_SHADOW_FILENAME, 'exec'), globals(), globals())\n"
        "\n"
        "_STATICPYTHON_PYFLTK_ALIASES = {\n"
        "    'Window': 'Fl_Window',\n"
        "    'DoubleWindow': 'Fl_Double_Window',\n"
        "    'SingleWindow': 'Fl_Single_Window',\n"
        "    'Button': 'Fl_Button',\n"
        "    'CheckButton': 'Fl_Check_Button',\n"
        "    'RadioButton': 'Fl_Radio_Button',\n"
        "    'LightButton': 'Fl_Light_Button',\n"
        "    'Input': 'Fl_Input',\n"
        "    'Output': 'Fl_Output',\n"
        "    'Box': 'Fl_Box',\n"
        "    'Group': 'Fl_Group',\n"
        "    'Browser': 'Fl_Browser',\n"
        "    'Choice': 'Fl_Choice',\n"
        "    'MenuBar': 'Fl_Menu_Bar',\n"
        "    'Slider': 'Fl_Slider',\n"
        "    'ValueSlider': 'Fl_Value_Slider',\n"
        "    'HorValueSlider': 'Fl_Hor_Value_Slider',\n"
        "    'Progress': 'Fl_Progress',\n"
        "    'Pack': 'Fl_Pack',\n"
        "    'Scroll': 'Fl_Scroll',\n"
        "    'Tabs': 'Fl_Tabs',\n"
        "    'TextBuffer': 'Fl_Text_Buffer',\n"
        "    'TextDisplay': 'Fl_Text_Display',\n"
        "    'TextEditor': 'Fl_Text_Editor',\n"
        "    'MultilineInput': 'Fl_Multiline_Input',\n"
        "    'MultilineOutput': 'Fl_Multiline_Output',\n"
        "}\n"
        "for _alias, _target in _STATICPYTHON_PYFLTK_ALIASES.items():\n"
        "    if _alias not in globals() and _target in globals():\n"
        "        globals()[_alias] = globals()[_target]\n"
        "\n"
        "def _STATICPYTHON_PYFLTK_FL_CALL(name, *args, **kwargs):\n"
        "    return getattr(Fl, name)(*args, **kwargs)\n"
        "\n"
        "def run(*args, **kwargs):\n"
        "    return _STATICPYTHON_PYFLTK_FL_CALL('run', *args, **kwargs)\n"
        "\n"
        "def check(*args, **kwargs):\n"
        "    return _STATICPYTHON_PYFLTK_FL_CALL('check', *args, **kwargs)\n"
        "\n"
        "def wait(*args, **kwargs):\n"
        "    return _STATICPYTHON_PYFLTK_FL_CALL('wait', *args, **kwargs)\n"
        "\n"
        "def add_timeout(*args, **kwargs):\n"
        "    return _STATICPYTHON_PYFLTK_FL_CALL('add_timeout', *args, **kwargs)\n"
        "\n"
        "def repeat_timeout(*args, **kwargs):\n"
        "    return _STATICPYTHON_PYFLTK_FL_CALL('repeat_timeout', *args, **kwargs)\n"
        "\n"
        "def remove_timeout(*args, **kwargs):\n"
        "    return _STATICPYTHON_PYFLTK_FL_CALL('remove_timeout', *args, **kwargs)\n"
    )
    path.write_text(wrapped, encoding="utf-8", newline="\n")


def generate_pyfltk_sources(context) -> None:
    fltk_dir = ensure_fltk_source(context)
    swig_exe = ensure_swigwin(context)
    swig_dir = source_path(context, "pyfltk_builtin/swig")
    package_dir = source_path(context, "Lib/fltk")
    wrapper_path = package_dir / "fltk_wrap.cpp"
    shadow_path = package_dir / "fltk.py"
    command = [
        str(swig_exe),
        "-DWIN32",
        "-DFL_INTERNALS",
        "-w302",
        "-w312",
        "-w325",
        "-w362",
        "-w389",
        "-w401",
        "-w473",
        "-w509",
        f"-I{swig_dir}",
        f"-I{fltk_dir}",
        f"-I{fltk_dir / 'FL'}",
        f"-I{source_path(context, 'pyfltk_builtin/src')}",
        f"-I{source_path(context, 'pyfltk_builtin/contrib')}",
        "-DPYTHON",
        "-DPYTHON3",
        "-c++",
        "-python",
        "-shadow",
        "-fastdispatch",
        "-outdir",
        str(package_dir),
        "-o",
        str(wrapper_path),
        str(swig_dir / "fltk.i"),
    ]
    context.log("RUN " + subprocess.list2cmdline(command))
    subprocess.run(command, cwd=str(context.source_root), check=True, timeout=60 * 5)
    if not wrapper_path.exists() or not shadow_path.exists():
        raise RuntimeError("SWIG did not generate pyfltk wrapper sources")
    _wrap_pyfltk_shadow_module(shadow_path)


def prepare_pyfltk_project(context) -> None:
    generate_pyfltk_sources(context)
    write_source_text(context, "PCbuild/fltk._fltk.vcxproj", _render_pyfltk_project(context))


def _copy_built_fltk_libraries(context, build_dir: Path) -> None:
    output_dir = get_pcbuild_output_dir(context.source_root, context.platform)
    output_dir.mkdir(parents=True, exist_ok=True)
    missing: list[str] = []
    for name in FLTK_LIBRARY_NAMES:
        candidates = sorted(build_dir.rglob(name), key=lambda path: (0 if "Release" in path.parts else 1, len(path.parts), str(path)))
        if not candidates:
            missing.append(name)
            continue
        shutil.copy2(candidates[0], output_dir / name)
    if missing:
        raise RuntimeError(f"FLTK build did not produce required static libraries: {', '.join(missing)}")


def _force_fltk_static_runtime(context, build_dir: Path) -> None:
    changed = 0
    for project in build_dir.rglob("*.vcxproj"):
        text = project.read_text(encoding="utf-8")
        updated = text
        updated = updated.replace("MultiThreadedDebugDLL", "MultiThreadedDebug")
        updated = updated.replace("MultiThreadedDLL", "MultiThreaded")
        updated = updated.replace("/MDd", "/MTd")
        updated = updated.replace("/MD", "/MT")
        updated = updated.replace("FL_DLL;", "")
        updated = updated.replace(";FL_DLL", "")
        updated = updated.replace("_DLL;", "")
        updated = updated.replace(";_DLL", "")
        if updated != text:
            project.write_text(updated, encoding="utf-8")
            changed += 1
    if changed:
        context.log(f"forced FLTK static runtime in {changed} generated project(s)")


def prepare_pyfltk_artifacts(context) -> None:
    output_dir = get_pcbuild_output_dir(context.source_root, context.platform)
    if all((output_dir / name).exists() for name in FLTK_LIBRARY_NAMES):
        context.log(f"using existing FLTK static libraries at {output_dir.relative_to(context.source_root)}")
        return

    ensure_tool("cmake")
    source_dir = ensure_fltk_source(context)
    build_dir = fltk_build_dir(context)
    if build_dir.exists():
        shutil.rmtree(build_dir)
    build_dir.mkdir(parents=True, exist_ok=True)
    run(
        context.log,
        [
            "cmake",
            "-S",
            str(source_dir),
            "-B",
            str(build_dir),
            "-G",
            "Visual Studio 17 2022",
            "-A",
            "x64",
            "-DCMAKE_POLICY_DEFAULT_CMP0091=NEW",
            "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
            "-DCMAKE_C_FLAGS:STRING=/MT",
            "-DCMAKE_CXX_FLAGS:STRING=/MT",
            "-DCMAKE_C_FLAGS_RELEASE:STRING=/MT /O2 /Ob2 /DNDEBUG",
            "-DCMAKE_CXX_FLAGS_RELEASE:STRING=/MT /O2 /Ob2 /DNDEBUG",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DFLTK_BUILD_SHARED_LIBS=OFF",
            "-DFLTK_BUILD_TEST=OFF",
            "-DFLTK_BUILD_EXAMPLES=OFF",
            "-DFLTK_BUILD_FLUID=OFF",
            "-DFLTK_BUILD_FLTK_OPTIONS=OFF",
            "-DFLTK_BUILD_HTML_DOCS=OFF",
            "-DFLTK_BUILD_PDF_DOCS=OFF",
            "-DFLTK_BUILD_FORMS=ON",
            "-DFLTK_BUILD_GL=ON",
            "-DFLTK_USE_SYSTEM_ZLIB=OFF",
            "-DFLTK_USE_SYSTEM_LIBPNG=OFF",
            "-DFLTK_USE_SYSTEM_LIBJPEG=OFF",
        ],
        cwd=source_dir,
        timeout=60 * 15,
    )
    _force_fltk_static_runtime(context, build_dir)
    run(
        context.log,
        [
            "cmake",
            "--build",
            str(build_dir),
            "--config",
            "Release",
            "--",
            "/m:1",
            "/p:CL_MPCount=1",
            "/p:UseMultiToolTask=false",
        ],
        cwd=build_dir,
        timeout=60 * 40,
    )
    _copy_built_fltk_libraries(context, build_dir)


LIBRARY_INTEGRATION = pypi_library(
    name="pyfltk",
    project_name="pyfltk",
    minimum_release_version="1.4.1.0",
    source_mapping={
        "fltk": "Lib/fltk",
        "swig": "pyfltk_builtin/swig",
        "src": "pyfltk_builtin/src",
        "contrib": "pyfltk_builtin/contrib",
    },
    source_ignore_patterns=[
        "test",
    ],
    materialized_paths=[
        "Lib/fltk/__init__.py",
        "Lib/fltk/fltk.py",
        "Lib/fltk/fltk_wrap.cpp",
        f"pyfltk_builtin/fltk-{FLTK_VERSION}/FL/Fl.H",
        "PCbuild/fltk._fltk.vcxproj",
    ],
    cleanup_paths=[
        f"pyfltk_builtin/fltk-{FLTK_VERSION}",
    ],
    python_packages=["fltk"],
    static_library_projects_release_x64=[
        "fltk._fltk.vcxproj",
    ],
    native_static_projects=[
        {
            "project": "fltk._fltk.vcxproj",
            "guid": PYFLTK_PROJECT_GUID,
        }
    ],
    builtin_module_registrations=[
        {
            "name": "fltk._fltk",
            "pyinit": "PyInit__fltk",
        }
    ],
    python_link_dependencies_release_x64=[
        "fltk._fltk.lib",
        *FLTK_LIBRARY_NAMES,
        *PYFLTK_SYSTEM_LIBRARIES,
    ],
    overlay_entries=[
        "pyfltk_runtime_test.py",
    ],
    prepare_source_hooks=[prepare_pyfltk_project],
    pre_build_hooks=[prepare_pyfltk_artifacts],
)
