from __future__ import annotations

import re
from pathlib import Path

from libs import pypi_library, source_path, transform_source_text, write_source_text


IMGUI_CPP_PROJECT_GUID = "{8E9B677E-21D6-4E6C-B44C-F6C1AB9AE017}"
IMGUI_CORE_PROJECT_GUID = "{9F9DEBD8-11F6-4D3E-9C49-9E71F7647DD7}"
IMGUI_INTERNAL_PROJECT_GUID = "{A75B159A-18F1-4F71-993B-78618872E88A}"

IMGUI_CPP_CANDIDATE_SOURCES = [
    "config-cpp/py_imconfig.cpp",
    "imgui-cpp/imgui.cpp",
    "imgui-cpp/imgui_draw.cpp",
    "imgui-cpp/imgui_demo.cpp",
    "imgui-cpp/imgui_widgets.cpp",
    "imgui-cpp/imgui_tables.cpp",
]

IMGUI_CYTHON_COMPAT_DEFINES = [
    "CYTHON_USE_PYLONG_INTERNALS=0",
    "CYTHON_USE_DICT_VERSIONS=0",
    "CYTHON_FAST_THREAD_STATE=0",
    "CYTHON_USE_EXC_INFO_STACK=0",
    "CYTHON_USE_UNICODE_INTERNALS=0",
    "HAVE_STDARG_PROTOTYPES=1",
]

IMGUI_PRIVATE_SYMBOL_MARKER = "STATICPYTHON_IMGUI_PRIVATE_SYMBOLS"
IMGUI_PRIVATE_SYMBOL_SKIP = {
    # py_imconfig.h intentionally exposes this as a configurable typedef-like macro.
    "ImDrawIdx",
}


def _project_configurations() -> str:
    return """  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
"""


def _imgui_include_dirs() -> str:
    return (
        "..\\Lib\\imgui;"
        "..\\config-cpp;"
        "..\\imgui-cpp;"
        "..\\Lib\\ansifeed-cpp;"
        "%(AdditionalIncludeDirectories)"
    )


def _imgui_preprocessor_definitions(*extra_defines: str) -> str:
    defines = [
        "Py_NO_ENABLE_SHARED",
        "PYIMGUI_CUSTOM_EXCEPTION",
        "_CRT_SECURE_NO_WARNINGS",
        *IMGUI_CYTHON_COMPAT_DEFINES,
        *extra_defines,
        "%(PreprocessorDefinitions)",
    ]
    return ";".join(defines)


def _compile_items(sources: list[str]) -> str:
    items = []
    for source in sources:
        windows_source = source.replace("/", "\\")
        items.append(f'    <ClCompile Include="..\\{windows_source}" />')
    return "\n".join(items)


def _render_static_project(
    *,
    guid: str,
    root_namespace: str,
    target_name: str,
    sources: list[str],
    extra_defines: list[str] | None = None,
) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{guid}</ProjectGuid>
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
    <TargetName>{target_name}</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>{_imgui_include_dirs()}</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>{_imgui_preprocessor_definitions(*(extra_defines or []))}</PreprocessorDefinitions>
      <DisableSpecificWarnings>4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <ExceptionHandling>Sync</ExceptionHandling>
      <AdditionalOptions>/bigobj /EHsc /FIpy_imconfig.h %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{_compile_items(sources)}
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def _patch_generated_cython_cpp(text: str) -> str:
    replacements = {
        "#if CYTHON_USE_DICT_VERSIONS && CYTHON_USE_TYPE_SLOTS": (
            "#if CYTHON_USE_DICT_VERSIONS && CYTHON_USE_TYPE_SLOTS && PY_VERSION_HEX < 0x030E0000"
        ),
        "static CYTHON_INLINE int __Pyx_PyList_Extend(PyObject* L, PyObject* v) {\n"
        "#if CYTHON_COMPILING_IN_CPYTHON\n"
        "    PyObject* none = _PyList_Extend((PyListObject*)L, v);\n"
        "    if (unlikely(!none))\n"
        "        return -1;\n"
        "    Py_DECREF(none);\n"
        "    return 0;\n"
        "#else\n"
        "    return PyList_SetSlice(L, PY_SSIZE_T_MAX, PY_SSIZE_T_MAX, v);\n"
        "#endif\n"
        "}": (
            "static CYTHON_INLINE int __Pyx_PyList_Extend(PyObject* L, PyObject* v) {\n"
            "#if CYTHON_COMPILING_IN_CPYTHON && PY_VERSION_HEX >= 0x030D0000\n"
            "    return PyList_Extend(L, v);\n"
            "#elif CYTHON_COMPILING_IN_CPYTHON\n"
            "    PyObject* none = _PyList_Extend((PyListObject*)L, v);\n"
            "    if (unlikely(!none))\n"
            "        return -1;\n"
            "    Py_DECREF(none);\n"
            "    return 0;\n"
            "#else\n"
            "    return PyList_SetSlice(L, PY_SSIZE_T_MAX, PY_SSIZE_T_MAX, v);\n"
            "#endif\n"
            "}"
        ),
        "#define __Pyx_PyFrame_SetLineNumber(frame, lineno)  (frame)->f_lineno = (lineno)": (
            "#if PY_VERSION_HEX >= 0x030B0000\n"
            "  #define __Pyx_PyFrame_SetLineNumber(frame, lineno)  ((void)0)\n"
            "#else\n"
            "  #define __Pyx_PyFrame_SetLineNumber(frame, lineno)  (frame)->f_lineno = (lineno)\n"
            "#endif"
        ),
        "#define __Pyx_PyUnicode_READY(op)       (likely(PyUnicode_IS_READY(op)) ?\\\n"
        "                                              0 : _PyUnicode_Ready((PyObject *)(op)))": (
            "#if PY_VERSION_HEX >= 0x030C0000\n"
            "  #define __Pyx_PyUnicode_READY(op)       (0)\n"
            "  #else\n"
            "  #define __Pyx_PyUnicode_READY(op)       (likely(PyUnicode_IS_READY(op)) ?\\\n"
            "                                              0 : _PyUnicode_Ready((PyObject *)(op)))\n"
            "  #endif"
        ),
        "        PyThreadState *tstate = __Pyx_PyThreadState_Current;\n"
        "        PyObject* tmp_tb = tstate->curexc_traceback;\n"
        "        if (tb != tmp_tb) {\n"
        "            Py_INCREF(tb);\n"
        "            tstate->curexc_traceback = tb;\n"
        "            Py_XDECREF(tmp_tb);\n"
        "        }": (
            "        #if PY_VERSION_HEX >= 0x030C0000\n"
            "        PyObject *tmp_type, *tmp_value, *tmp_tb;\n"
            "        PyErr_Fetch(&tmp_type, &tmp_value, &tmp_tb);\n"
            "        Py_INCREF(tb);\n"
            "        PyErr_Restore(tmp_type, tmp_value, tb);\n"
            "        Py_XDECREF(tmp_tb);\n"
            "        #else\n"
            "        PyThreadState *tstate = __Pyx_PyThreadState_Current;\n"
            "        PyObject* tmp_tb = tstate->curexc_traceback;\n"
            "        if (tb != tmp_tb) {\n"
            "            Py_INCREF(tb);\n"
            "            tstate->curexc_traceback = tb;\n"
            "            Py_XDECREF(tmp_tb);\n"
            "        }\n"
            "        #endif"
        ),
        "        PyTracebackObject *tb = (PyTracebackObject *) exc_tb;\n"
        "        PyFrameObject *f = tb->tb_frame;\n"
        "        Py_CLEAR(f->f_back);": (
            "        #if PY_VERSION_HEX < 0x030B0000\n"
            "        PyTracebackObject *tb = (PyTracebackObject *) exc_tb;\n"
            "        PyFrameObject *f = tb->tb_frame;\n"
            "        Py_CLEAR(f->f_back);\n"
            "        #endif"
        ),
        "        if (exc_state->exc_traceback) {\n"
        "            PyTracebackObject *tb = (PyTracebackObject *) exc_state->exc_traceback;\n"
        "            PyFrameObject *f = tb->tb_frame;\n"
        "            assert(f->f_back == NULL);\n"
        "            #if PY_VERSION_HEX >= 0x030B00A1\n"
        "            f->f_back = PyThreadState_GetFrame(tstate);\n"
        "            #else\n"
        "            Py_XINCREF(tstate->frame);\n"
        "            f->f_back = tstate->frame;\n"
        "            #endif\n"
        "        }": (
            "        #if PY_VERSION_HEX < 0x030B0000\n"
            "        if (exc_state->exc_traceback) {\n"
            "            PyTracebackObject *tb = (PyTracebackObject *) exc_state->exc_traceback;\n"
            "            PyFrameObject *f = tb->tb_frame;\n"
            "            assert(f->f_back == NULL);\n"
            "            Py_XINCREF(tstate->frame);\n"
            "            f->f_back = tstate->frame;\n"
            "        }\n"
            "        #endif"
        ),
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = text.replace("_PyGC_FINALIZED(o)", "PyObject_GC_IsFinalized(o)")
    text = text.replace(
        "                int ret = _PyLong_AsByteArray((PyLongObject *)v,\n"
        "                                              bytes, sizeof(val),\n"
        "                                              is_little, !is_unsigned);",
        "                int ret = _PyLong_AsByteArray((PyLongObject *)v,\n"
        "                                              bytes, sizeof(val),\n"
        "                                              is_little, !is_unsigned\n"
        "#if PY_VERSION_HEX >= 0x030D0000\n"
        "                                              , 1\n"
        "#endif\n"
        "                );",
    )
    text = text.replace(
        "            _PyGen_SetStopIterationValue(result);",
        "            #if PY_VERSION_HEX >= 0x030D0000\n"
        "            {\n"
        "                PyObject *exc = PyObject_CallOneArg(PyExc_StopIteration, result);\n"
        "                if (unlikely(!exc)) {\n"
        "                    Py_CLEAR(result);\n"
        "                    return NULL;\n"
        "                }\n"
        "                PyErr_SetRaisedException(exc);\n"
        "            }\n"
        "            #else\n"
        "            _PyGen_SetStopIterationValue(result);\n"
        "            #endif",
    )
    text = re.sub(
        r"__Pyx_GetModuleGlobalName\((?P<var>__pyx_t_\d+), __pyx_n_s_namedtuple\); "
        r"if \(unlikely\(!(?P=var)\)\) (?P<err>__PYX_ERR\([^)]+\))",
        lambda match: (
            f"{match.group('var')} = PyDict_GetItemWithError(__pyx_d, __pyx_n_s_namedtuple); "
            f"if (unlikely(!{match.group('var')})) {{ "
            "if (!PyErr_Occurred()) PyErr_SetString(PyExc_NameError, \"name 'namedtuple' is not defined\"); "
            f"{match.group('err')}; "
            f"}} __Pyx_INCREF({match.group('var')});"
        ),
        text,
    )
    return text


def _patch_imgui_python_sources(context) -> None:
    def patch_pyglet(text: str) -> str:
        old = "from distutils.version import LooseVersion\n"
        if old not in text:
            return text
        new = """try:
    from distutils.version import LooseVersion
except ModuleNotFoundError:
    class LooseVersion:
        def __init__(self, value):
            parts = []
            for part in str(value).replace("-", ".").split("."):
                digits = ""
                for char in part:
                    if char.isdigit():
                        digits += char
                    else:
                        break
                if digits:
                    parts.append(int(digits))
                else:
                    break
            self.parts = tuple(parts)

        def __lt__(self, other):
            return self.parts < other.parts

"""
        return text.replace(old, new, 1)

    transform_source_text(context, "Lib/imgui/integrations/pyglet.py", patch_pyglet, allow_missing=True)


def _patch_imgui_generated_sources(context) -> None:
    transform_source_text(context, "Lib/imgui/core.cpp", _patch_generated_cython_cpp)

    def patch_internal(text: str) -> str:
        text = _patch_generated_cython_cpp(text)
        # core.cpp and internal.cpp both publish a Cython-level ImGuiError
        # variable. They are separate extension modules, but static linking
        # merges them into one executable, so keep the internal module's C
        # symbol private while preserving the Python attribute name.
        return re.sub(
            r'(?<![A-Za-z0-9_"\'_])ImGuiError(?![A-Za-z0-9_"\'_])',
            "StaticPythonImguiInternal_ImGuiError",
            text,
        )

    transform_source_text(context, "Lib/imgui/internal.cpp", patch_internal, allow_missing=True)
    transform_source_text(
        context,
        "Lib/imgui/internal.h",
        lambda text: re.sub(
            r'(?<![A-Za-z0-9_"\'_])ImGuiError(?![A-Za-z0-9_"\'_])',
            "StaticPythonImguiInternal_ImGuiError",
            text,
        ),
        allow_missing=True,
    )


def _patch_imgui_private_symbols(context) -> None:
    tokens: set[str] = {"GImGui", "ImGui"}
    guarded_config_tokens: set[str] = set()
    for root_name in ("imgui-cpp", "config-cpp"):
        root = source_path(context, root_name)
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix.lower() not in {".h", ".hpp", ".cpp", ".cxx", ".cc"}:
                continue
            source = path.read_text(encoding="utf-8", errors="ignore")
            tokens.update(re.findall(r"\bIm[A-Z][A-Za-z0-9_]*\b", source))
            guarded_config_tokens.update(re.findall(r"^\s*#\s*ifndef\s+(Im[A-Z][A-Za-z0-9_]*)\b", source, re.MULTILINE))
    tokens.difference_update(IMGUI_PRIVATE_SYMBOL_SKIP | (guarded_config_tokens - {"GImGui"}))

    lines = [
        "",
        f"#ifndef {IMGUI_PRIVATE_SYMBOL_MARKER}",
        f"#define {IMGUI_PRIVATE_SYMBOL_MARKER}",
        "/* Keep pyimgui's bundled Dear ImGui private when DearPyGui is linked too. */",
    ]
    for token in sorted(tokens):
        lines.extend(
            [
                f"#ifndef {token}",
                f"#define {token} StaticPythonImgui_{token}",
                "#endif",
            ]
        )
    if "GImGui" in tokens:
        lines.extend(
            [
                "struct ImGuiContext;",
                "extern ImGuiContext* GImGui;",
            ]
        )
    lines.append("#endif")
    block = "\n".join(lines) + "\n"

    def patch(text: str) -> str:
        if IMGUI_PRIVATE_SYMBOL_MARKER in text:
            return text
        return text.rstrip() + "\n" + block

    transform_source_text(context, "config-cpp/py_imconfig.h", patch)

    if "GImGui" in tokens:
        def patch_storage(text: str) -> str:
            marker = "STATICPYTHON_IMGUI_PRIVATE_GIMGUI_STORAGE"
            if marker in text:
                return text
            return (
                text.rstrip()
                + "\n\n"
                + f"#ifndef {marker}\n"
                + f"#define {marker}\n"
                + "ImGuiContext* GImGui = NULL;\n"
                + "#endif\n"
            )

        transform_source_text(context, "config-cpp/py_imconfig.cpp", patch_storage)


def _existing_sources(context, candidates: list[str]) -> list[str]:
    return [candidate for candidate in candidates if source_path(context, candidate).exists()]


def _render_imgui_projects(context) -> None:
    common_sources = _existing_sources(context, IMGUI_CPP_CANDIDATE_SOURCES)
    if "config-cpp/py_imconfig.cpp" not in common_sources or "imgui-cpp/imgui.cpp" not in common_sources:
        raise RuntimeError("imgui native sources are missing required Dear ImGui files")
    has_internal = source_path(context, "Lib/imgui/internal.cpp").exists()
    write_source_text(
        context,
        "PCbuild/imgui_cpp.vcxproj",
        _render_static_project(
            guid=IMGUI_CPP_PROJECT_GUID,
            root_namespace="imgui_cpp",
            target_name="imgui_cpp",
            sources=common_sources,
        ),
    )
    write_source_text(
        context,
        "PCbuild/imgui.core.vcxproj",
        _render_static_project(
            guid=IMGUI_CORE_PROJECT_GUID,
            root_namespace="imgui_core",
            target_name="imgui.core",
            sources=["Lib/imgui/core.cpp"],
        ),
    )
    if has_internal:
        write_source_text(
            context,
            "PCbuild/imgui.internal.vcxproj",
            _render_static_project(
                guid=IMGUI_INTERNAL_PROJECT_GUID,
                root_namespace="imgui_internal",
                target_name="imgui.internal",
                sources=["Lib/imgui/internal.cpp"],
            ),
        )
    _configure_imgui_integration(has_internal)


def _configure_imgui_integration(has_internal: bool) -> None:
    projects = ["imgui_cpp.vcxproj", "imgui.core.vcxproj"]
    native_projects = [
        {"project": "imgui_cpp.vcxproj", "guid": IMGUI_CPP_PROJECT_GUID},
        {"project": "imgui.core.vcxproj", "guid": IMGUI_CORE_PROJECT_GUID},
    ]
    registrations = [
        {
            "name": "imgui.core",
            "pyinit": "PyInit_core",
        }
    ]
    link_dependencies = ["imgui.core.lib", "imgui_cpp.lib"]
    if has_internal:
        projects.append("imgui.internal.vcxproj")
        native_projects.append({"project": "imgui.internal.vcxproj", "guid": IMGUI_INTERNAL_PROJECT_GUID})
        registrations.append(
            {
                "name": "imgui.internal",
                "pyinit": "PyInit_internal",
            }
        )
        link_dependencies.insert(1, "imgui.internal.lib")
    LIBRARY_INTEGRATION.static_library_projects_release_x64 = projects
    LIBRARY_INTEGRATION.native_static_projects = native_projects
    LIBRARY_INTEGRATION.builtin_module_registrations = registrations
    LIBRARY_INTEGRATION.python_link_dependencies_release_x64 = link_dependencies


def prepare_imgui_project(context) -> None:
    _patch_imgui_python_sources(context)
    _patch_imgui_generated_sources(context)
    _patch_imgui_private_symbols(context)
    _render_imgui_projects(context)


LIBRARY_INTEGRATION = pypi_library(
    name="imgui",
    minimum_release_version="1.0.0a2",
    dependencies=[
        "OpenGL",
        "glfw",
        "pyglet",
    ],
    source_mapping={
        "imgui": "Lib/imgui",
        "config-cpp": "config-cpp",
        "imgui-cpp": "imgui-cpp",
        "?ansifeed-cpp": "Lib/ansifeed-cpp",
    },
    materialized_paths=[
        "Lib/imgui",
        "config-cpp",
        "imgui-cpp",
    ],
    python_packages=["imgui"],
    static_library_projects_release_x64=[
        "imgui_cpp.vcxproj",
        "imgui.core.vcxproj",
    ],
    native_static_projects=[
        {"project": "imgui_cpp.vcxproj", "guid": IMGUI_CPP_PROJECT_GUID},
        {"project": "imgui.core.vcxproj", "guid": IMGUI_CORE_PROJECT_GUID},
    ],
    builtin_module_registrations=[
        {
            "name": "imgui.core",
            "pyinit": "PyInit_core",
        },
    ],
    python_link_dependencies_release_x64=[
        "imgui.core.lib",
        "imgui_cpp.lib",
    ],
    overlay_entries=[
        "imgui_runtime_test.py",
        "imgui_glfw_runtime_test.py",
        "imgui_pyglet_runtime_test.py",
    ],
    prepare_source_hooks=[prepare_imgui_project],
)
