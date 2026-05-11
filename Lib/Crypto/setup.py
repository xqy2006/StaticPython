from __future__ import annotations

import ast
from pathlib import Path
import re

from libs import (
    pypi_library,
    replace_function_block_once,
    replace_regex_once,
    replace_text_once,
    source_path,
    transform_source_text,
    write_source_text,
)


PYCRYPTODOME_PROJECT_GUID = "{6C86E524-8C37-4E87-8F0B-8D1748F81234}"
POLY1305_EMBEDDED_PREFIX = "pycryptodome_poly1305"
BLAKE2B_EMBEDDED_PREFIX = "pycryptodome_blake2b"
BLAKE2S_EMBEDDED_PREFIX = "pycryptodome_blake2s"

def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _literal_string_sequence(node: ast.AST) -> list[str] | None:
    if not isinstance(node, (ast.List, ast.Tuple)):
        return None
    values: list[str] = []
    for element in node.elts:
        if not isinstance(element, ast.Constant) or not isinstance(element.value, str):
            return None
        values.append(element.value)
    return values


def _collapse_simple_include_wrapper(context, relative: str) -> str:
    current = relative
    seen: set[str] = set()

    while True:
        if current in seen:
            raise RuntimeError(f"recursive pycryptodome wrapper source detected: {relative}")
        seen.add(current)

        source_file = source_path(context, f"pycryptodome_builtin/src/{current}")
        text = source_file.read_text(encoding="utf-8", errors="ignore")
        stripped = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
        stripped = re.sub(r"//.*", "", stripped)
        stripped = "\n".join(line.strip() for line in stripped.splitlines() if line.strip())
        match = re.fullmatch(r'#include\s+"([^"]+\.c)"', stripped)
        if match is None:
            return current

        current = (Path(current).parent / match.group(1)).as_posix()
        wrapped_source = source_path(context, f"pycryptodome_builtin/src/{current}")
        if not wrapped_source.exists():
            raise RuntimeError(
                f"pycryptodome wrapper source {relative} references missing target {current}"
            )
        context.log(f"collapsed pycryptodome wrapper source {relative} -> {current}")


def _discover_pycryptodome_sources_from_setup(context) -> list[str]:
    candidates = [
        source_path(context, "pycryptodome_builtin/upstream_setup.py"),
        *sorted(context.work_cache_root.glob("pypi/pycryptodome/*/extracted/*/setup.py")),
    ]
    setup_path = next((candidate for candidate in candidates if candidate.exists()), None)
    if setup_path is None:
        raise RuntimeError("could not locate pycryptodome upstream setup.py in the target tree or builder cache")
    tree = ast.parse(setup_path.read_text(encoding="utf-8"), filename=str(setup_path))
    discovered: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or _call_name(node.func) != "Extension":
            continue
        for keyword in node.keywords:
            if keyword.arg != "sources":
                continue
            sources = _literal_string_sequence(keyword.value)
            if not sources:
                continue
            for raw_source in sources:
                normalized = raw_source.replace("\\", "/")
                if not normalized.startswith("src/"):
                    continue
                if Path(normalized).suffix.lower() not in {".c", ".cc", ".cpp"}:
                    continue
                relative = normalized.removeprefix("src/")
                if not source_path(context, f"pycryptodome_builtin/src/{relative}").exists():
                    raise RuntimeError(f"pycryptodome declared native source is missing: {relative}")
                relative = _collapse_simple_include_wrapper(context, relative)
                if relative not in discovered:
                    discovered.append(relative)

    if not discovered:
        raise RuntimeError(f"could not discover pycryptodome native sources from {setup_path}")
    context.log(f"resolved pycryptodome native sources from upstream setup.py: {', '.join(discovered)}")
    return discovered


def _render_pycryptodome_project(source_files: list[str]) -> str:
    compile_items = "\n".join(
        f'    <ClCompile Include="..\\pycryptodome_builtin\\src\\{name}" />'
        for name in source_files
    )
    arm_remove_items = "\n".join(
        f'    <ClCompile Remove="..\\pycryptodome_builtin\\src\\{name}" />'
        for name in ("AESNI.c", "ghash_clmul.c")
        if name in source_files
    )
    if arm_remove_items:
        arm_remove_items = (
            "  <ItemGroup Condition=\"'$(Platform)'=='ARM' or '$(Platform)'=='ARM64'\">\n"
            f"{arm_remove_items}\n"
            "  </ItemGroup>\n"
        )
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <ItemGroup Label="ProjectConfigurations">
    <ProjectConfiguration Include="Debug|ARM">
      <Configuration>Debug</Configuration>
      <Platform>ARM</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="Debug|ARM64">
      <Configuration>Debug</Configuration>
      <Platform>ARM64</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="Debug|Win32">
      <Configuration>Debug</Configuration>
      <Platform>Win32</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="Debug|x64">
      <Configuration>Debug</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="PGInstrument|ARM">
      <Configuration>PGInstrument</Configuration>
      <Platform>ARM</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="PGInstrument|ARM64">
      <Configuration>PGInstrument</Configuration>
      <Platform>ARM64</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="PGInstrument|Win32">
      <Configuration>PGInstrument</Configuration>
      <Platform>Win32</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="PGInstrument|x64">
      <Configuration>PGInstrument</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="PGUpdate|ARM">
      <Configuration>PGUpdate</Configuration>
      <Platform>ARM</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="PGUpdate|ARM64">
      <Configuration>PGUpdate</Configuration>
      <Platform>ARM64</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="PGUpdate|Win32">
      <Configuration>PGUpdate</Configuration>
      <Platform>Win32</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="PGUpdate|x64">
      <Configuration>PGUpdate</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="Release|ARM">
      <Configuration>Release</Configuration>
      <Platform>ARM</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="Release|ARM64">
      <Configuration>Release</Configuration>
      <Platform>ARM64</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="Release|Win32">
      <Configuration>Release</Configuration>
      <Platform>Win32</Platform>
    </ProjectConfiguration>
    <ProjectConfiguration Include="Release|x64">
      <Configuration>Release</Configuration>
      <Platform>x64</Platform>
    </ProjectConfiguration>
  </ItemGroup>
  <PropertyGroup Label="Globals">
    <ProjectGuid>{PYCRYPTODOME_PROJECT_GUID}</ProjectGuid>
    <RootNamespace>_pycryptodome_raw</RootNamespace>
    <Keyword>Win32Proj</Keyword>
    <SupportPGO>false</SupportPGO>
    <WindowsTargetPlatformVersion>$(DefaultWindowsSDKVersion)</WindowsTargetPlatformVersion>
  </PropertyGroup>
  <Import Project="python.props" />
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.Default.props" />
  <PropertyGroup Label="Configuration">
    <ConfigurationType>StaticLibrary</ConfigurationType>
    <CharacterSet>Unicode</CharacterSet>
  </PropertyGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.props" />
  <PropertyGroup>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ImportGroup Label="ExtensionSettings">
  </ImportGroup>
  <ImportGroup Label="PropertySheets">
    <Import Project="$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props" Condition="exists('$(UserRootDir)\\Microsoft.Cpp.$(Platform).user.props')" Label="LocalAppDataPlatform" />
    <Import Project="pyproject.props" />
  </ImportGroup>
  <PropertyGroup Label="UserMacros" />
  <PropertyGroup>
    <_ProjectFileVersion>10.0.30319.1</_ProjectFileVersion>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>..\\pycryptodome_builtin\\src;..\\pycryptodome_builtin\\src\\libtom;%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>NO_CPYTHON_MODULE;HAVE_STDINT_H;PYCRYPTO_LITTLE_ENDIAN;LTC_NO_ASM;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <DisableSpecificWarnings>4100;4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <AdditionalOptions>/bigobj %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemDefinitionGroup Condition="'$(Platform)'=='Win32'">
    <ClCompile>
      <PreprocessorDefinitions>SYS_BITS=32;HAVE_INTRIN_H;USE_SSE2;HAVE_WMMINTRIN_H;HAVE_TMMINTRIN_H;%(PreprocessorDefinitions)</PreprocessorDefinitions>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemDefinitionGroup Condition="'$(Platform)'=='x64'">
    <ClCompile>
      <PreprocessorDefinitions>SYS_BITS=64;HAVE_INTRIN_H;USE_SSE2;HAVE_WMMINTRIN_H;HAVE_TMMINTRIN_H;%(PreprocessorDefinitions)</PreprocessorDefinitions>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemDefinitionGroup Condition="'$(Platform)'=='ARM'">
    <ClCompile>
      <PreprocessorDefinitions>SYS_BITS=32;%(PreprocessorDefinitions)</PreprocessorDefinitions>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemDefinitionGroup Condition="'$(Platform)'=='ARM64'">
    <ClCompile>
      <PreprocessorDefinitions>SYS_BITS=64;%(PreprocessorDefinitions)</PreprocessorDefinitions>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
    <ClCompile Include="..\\pycryptodome_builtin\\embedded_marker.c" />
{compile_items}
  </ItemGroup>
{arm_remove_items}  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
  <ImportGroup Label="ExtensionTargets">
  </ImportGroup>
</Project>
"""


def prepare_pycryptodome_project(context) -> None:
    write_source_text(
        context,
        "PCbuild/_pycryptodome_raw.vcxproj",
        _render_pycryptodome_project(_discover_pycryptodome_sources_from_setup(context)),
    )


def _patch_raw_api(text: str) -> str:
    if not text:
        return text
    if "_PyObject_GetBuffer = None" not in text and "_PyObject_GetBuffer = ctypes.pythonapi.PyObject_GetBuffer" in text:
        text = replace_regex_once(
            text,
            r"(?m)^    _PyBUF_SIMPLE = 0\n    _PyObject_GetBuffer = ctypes\.pythonapi\.PyObject_GetBuffer\n    _PyBuffer_Release = ctypes\.pythonapi\.PyBuffer_Release\n",
            "    _PyBUF_SIMPLE = 0\n"
            "    try:\n"
            "        _PyObject_GetBuffer = ctypes.pythonapi.PyObject_GetBuffer\n"
            "        _PyBuffer_Release = ctypes.pythonapi.PyBuffer_Release\n"
            "    except AttributeError:\n"
            "        _PyObject_GetBuffer = None\n"
            "        _PyBuffer_Release = None\n",
            label="Crypto.Util._raw_api.buffer-api",
        )
    if "_buffer_as_ubyte_array" not in text and "except ImportError:\n" in text and "class _Py_buffer" in text:
        head, tail = text.split("except ImportError:\n", 1)
        tail = replace_function_block_once(
            tail,
            "c_uint8_ptr",
            "def _buffer_as_ubyte_array(data):\n"
            "    view = memoryview(data)\n"
            "    if view.format not in (\"B\", \"b\", \"c\") or view.itemsize != 1:\n"
            "        view = view.cast(\"B\")\n"
            "\n"
            "    if view.readonly:\n"
            "        return (ctypes.c_ubyte * view.nbytes).from_buffer_copy(view.tobytes())\n"
            "\n"
            "    try:\n"
            "        return (ctypes.c_ubyte * view.nbytes).from_buffer(data)\n"
            "    except TypeError:\n"
            "        return (ctypes.c_ubyte * view.nbytes).from_buffer(view)\n"
            "\n"
            "def c_uint8_ptr(data):\n"
            "    if byte_string(data) or isinstance(data, _Array):\n"
            "        return data\n"
            "    elif isinstance(data, _buffer_type):\n"
            "        if _PyObject_GetBuffer is None:\n"
            "            return _buffer_as_ubyte_array(data)\n"
            "        obj = _py_object(data)\n"
            "        buf = _Py_buffer()\n"
            "        _PyObject_GetBuffer(obj, byref(buf), _PyBUF_SIMPLE)\n"
            "        try:\n"
            "            buffer_type = ctypes.c_ubyte * buf.len\n"
            "            return buffer_type.from_address(buf.buf)\n"
            "        finally:\n"
            "            _PyBuffer_Release(byref(buf))\n"
            "    else:\n"
            "        raise TypeError(\"Object type %s cannot be passed to C code\" % type(data))\n",
            label="Crypto.Util._raw_api.c_uint8_ptr",
        )
        text = head + "except ImportError:\n" + tail
    if "_load_embedded_process_lib" not in text:
        if "\n\ndef load_pycryptodome_raw_lib(name, cdecl):\n" in text:
            text = replace_text_once(
                text,
                "\n\ndef load_pycryptodome_raw_lib(name, cdecl):\n",
                "\n\n_EMBEDDED_PROCESS_LIB = None\n\n\n"
                "def _load_embedded_process_lib():\n"
                "    global _EMBEDDED_PROCESS_LIB\n\n"
                "    if _EMBEDDED_PROCESS_LIB is False:\n"
                "        return None\n"
                "    if _EMBEDDED_PROCESS_LIB is not None:\n"
                "        return _EMBEDDED_PROCESS_LIB\n\n"
                "    if backend != \"ctypes\" or os.name != \"nt\":\n"
                "        _EMBEDDED_PROCESS_LIB = False\n"
                "        return None\n\n"
                "    executable = getattr(sys, \"executable\", None)\n"
                "    if not executable:\n"
                "        _EMBEDDED_PROCESS_LIB = False\n"
                "        return None\n\n"
                "    try:\n"
                "        lib = load_lib(executable, \"\")\n"
                "        getattr(lib, \"pycryptodome_embedded\")\n"
                "    except (AttributeError, OSError):\n"
                "        _EMBEDDED_PROCESS_LIB = False\n"
                "        return None\n\n"
                "    _EMBEDDED_PROCESS_LIB = lib\n"
                "    return lib\n\n\n"
                "def load_pycryptodome_raw_lib(name, cdecl):\n",
                label="Crypto.Util._raw_api.embedded-loader",
            )
        elif "def load_pycryptodome_raw_lib(name, cdecl):\n" in text:
            insert_anchor = "def load_pycryptodome_raw_lib(name, cdecl):\n"
            text = text.replace(
                insert_anchor,
                "_EMBEDDED_PROCESS_LIB = None\n\n\n"
                "def _load_embedded_process_lib():\n"
                "    global _EMBEDDED_PROCESS_LIB\n\n"
                "    if _EMBEDDED_PROCESS_LIB is False:\n"
                "        return None\n"
                "    if _EMBEDDED_PROCESS_LIB is not None:\n"
                "        return _EMBEDDED_PROCESS_LIB\n\n"
                "    if backend != \"ctypes\" or os.name != \"nt\":\n"
                "        _EMBEDDED_PROCESS_LIB = False\n"
                "        return None\n\n"
                "    executable = getattr(sys, \"executable\", None)\n"
                "    if not executable:\n"
                "        _EMBEDDED_PROCESS_LIB = False\n"
                "        return None\n\n"
                "    try:\n"
                "        lib = load_lib(executable, \"\")\n"
                "        getattr(lib, \"pycryptodome_embedded\")\n"
                "    except (AttributeError, OSError):\n"
                "        _EMBEDDED_PROCESS_LIB = False\n"
                "        return None\n\n"
                "    _EMBEDDED_PROCESS_LIB = lib\n"
                "    return lib\n\n\n"
                + insert_anchor,
                1,
            )
        else:
            return text
    next_name = None
    for candidate in ("is_buffer", "expect_byte_string", "make_byte_string"):
        if f"def {candidate}(" in text:
            next_name = candidate
            break
    if next_name is None:
        return text
    text = replace_function_block_once(
        text,
        "load_pycryptodome_raw_lib",
        "def load_pycryptodome_raw_lib(name, cdecl):\n"
        "    \"\"\"Load a shared library and return a handle to it.\n\n"
        "    @name,  the name of the library expressed as a PyCryptodome module,\n"
        "            for instance Crypto.Cipher._raw_cbc.\n\n"
        "    @cdecl, the C function declarations.\n"
        "    \"\"\"\n\n"
        "    embedded_process_lib = _load_embedded_process_lib()\n"
        "    if embedded_process_lib is not None:\n"
        "        return embedded_process_lib\n\n"
        "    split = name.split(\".\")\n"
        "    dir_comps, basename = split[:-1], split[-1]\n"
        "    attempts = []\n"
        "    suffixes = globals().get('extension_suffixes')\n"
        "    if suffixes is None:\n"
        "        suffixes = [ext for ext, mod, typ in imp.get_suffixes() if typ == imp.C_EXTENSION]\n"
        "    for ext in suffixes:\n"
        "        filename = basename + ext\n"
        "        try:\n"
        "            if \"pycryptodome_filename\" in globals():\n"
        "                full_name = pycryptodome_filename(dir_comps, filename)\n"
        "                if not os.path.isfile(full_name):\n"
        "                    attempts.append(\"Not found '%s'\" % filename)\n"
        "                    continue\n"
        "            else:\n"
        "                full_name = _get_mod_name(name, ext)\n"
        "            return load_lib(full_name, cdecl)\n"
        "        except (NameError, OSError, TypeError, ValueError) as exp:\n"
        "            attempts.append(\"Cannot load '%s': %s\" % (filename, str(exp)))\n"
        "    raise OSError(\"Cannot load native module '%s': %s\" % (name, \", \".join(attempts)))\n\n",
        label="Crypto.Util._raw_api.load-function",
        next_name=next_name,
    )
    return text


def _replace_required_tokens(text: str, replacements: list[tuple[str, str]], *, label: str) -> str:
    updated = text
    for old, new in replacements:
        if old not in updated:
            raise RuntimeError(f"missing expected token {old!r} while patching {label}")
        updated = updated.replace(old, new)
    return updated


def _patch_poly1305_c(text: str) -> str:
    renamed_block = (
        "FAKE_INIT(poly1305)\n\n"
        f"#define poly1305_init {POLY1305_EMBEDDED_PREFIX}_init\n"
        f"#define poly1305_destroy {POLY1305_EMBEDDED_PREFIX}_destroy\n"
        f"#define poly1305_update {POLY1305_EMBEDDED_PREFIX}_update\n"
        f"#define poly1305_digest {POLY1305_EMBEDDED_PREFIX}_digest\n"
    )
    return replace_text_once(
        text,
        "FAKE_INIT(poly1305)\n",
        renamed_block,
        label="pycryptodome poly1305 symbol prefix",
    )


def _patch_poly1305_py(text: str) -> str:
    return _replace_required_tokens(
        text,
        [
            ("poly1305_init", f"{POLY1305_EMBEDDED_PREFIX}_init"),
            ("poly1305_destroy", f"{POLY1305_EMBEDDED_PREFIX}_destroy"),
            ("poly1305_update", f"{POLY1305_EMBEDDED_PREFIX}_update"),
            ("poly1305_digest", f"{POLY1305_EMBEDDED_PREFIX}_digest"),
        ],
        label="Crypto.Hash.Poly1305",
    )


def _patch_blake2b_c(text: str) -> str:
    return _replace_required_tokens(
        text,
        [
            ("#define blake2_init blake2b_init", f"#define blake2_init {BLAKE2B_EMBEDDED_PREFIX}_init"),
            ("#define blake2_copy blake2b_copy", f"#define blake2_copy {BLAKE2B_EMBEDDED_PREFIX}_copy"),
            ("#define blake2_destroy blake2b_destroy", f"#define blake2_destroy {BLAKE2B_EMBEDDED_PREFIX}_destroy"),
            ("#define blake2_digest blake2b_digest", f"#define blake2_digest {BLAKE2B_EMBEDDED_PREFIX}_digest"),
            ("#define blake2_update blake2b_update", f"#define blake2_update {BLAKE2B_EMBEDDED_PREFIX}_update"),
        ],
        label="pycryptodome blake2b symbol prefix",
    )


def _patch_blake2b_py(text: str) -> str:
    return _replace_required_tokens(
        text,
        [
            ("blake2b_init", f"{BLAKE2B_EMBEDDED_PREFIX}_init"),
            ("blake2b_destroy", f"{BLAKE2B_EMBEDDED_PREFIX}_destroy"),
            ("blake2b_update", f"{BLAKE2B_EMBEDDED_PREFIX}_update"),
            ("blake2b_digest", f"{BLAKE2B_EMBEDDED_PREFIX}_digest"),
            ("blake2b_copy", f"{BLAKE2B_EMBEDDED_PREFIX}_copy"),
        ],
        label="Crypto.Hash.BLAKE2b",
    )


def _patch_blake2s_c(text: str) -> str:
    return _replace_required_tokens(
        text,
        [
            ("#define blake2_init blake2s_init", f"#define blake2_init {BLAKE2S_EMBEDDED_PREFIX}_init"),
            ("#define blake2_copy blake2s_copy", f"#define blake2_copy {BLAKE2S_EMBEDDED_PREFIX}_copy"),
            ("#define blake2_destroy blake2s_destroy", f"#define blake2_destroy {BLAKE2S_EMBEDDED_PREFIX}_destroy"),
            ("#define blake2_digest blake2s_digest", f"#define blake2_digest {BLAKE2S_EMBEDDED_PREFIX}_digest"),
            ("#define blake2_update blake2s_update", f"#define blake2_update {BLAKE2S_EMBEDDED_PREFIX}_update"),
        ],
        label="pycryptodome blake2s symbol prefix",
    )


def _patch_blake2s_py(text: str) -> str:
    return _replace_required_tokens(
        text,
        [
            ("blake2s_init", f"{BLAKE2S_EMBEDDED_PREFIX}_init"),
            ("blake2s_destroy", f"{BLAKE2S_EMBEDDED_PREFIX}_destroy"),
            ("blake2s_update", f"{BLAKE2S_EMBEDDED_PREFIX}_update"),
            ("blake2s_digest", f"{BLAKE2S_EMBEDDED_PREFIX}_digest"),
            ("blake2s_copy", f"{BLAKE2S_EMBEDDED_PREFIX}_copy"),
        ],
        label="Crypto.Hash.BLAKE2s",
    )


def _patch_bignum_c(text: str) -> str:
    return replace_text_once(
        text,
        "int sub_mod(uint64_t *out, const uint64_t *a, const uint64_t *b, const uint64_t *modulus, uint64_t *tmp1, uint64_t *tmp2, size_t nw)\n",
        "STATIC int sub_mod(uint64_t *out, const uint64_t *a, const uint64_t *b, const uint64_t *modulus, uint64_t *tmp1, uint64_t *tmp2, size_t nw)\n",
        label="pycryptodome bignum sub_mod internal linkage",
    )


def patch_crypto_sources(context) -> None:
    transform_source_text(context, "Lib/Crypto/Util/_raw_api.py", _patch_raw_api, allow_missing=True)
    if source_path(context, "pycryptodome_builtin/src/bignum.c").exists():
        transform_source_text(context, "pycryptodome_builtin/src/bignum.c", _patch_bignum_c)
    if source_path(context, "pycryptodome_builtin/src/blake2b.c").exists():
        transform_source_text(context, "pycryptodome_builtin/src/blake2b.c", _patch_blake2b_c)
    if source_path(context, "Lib/Crypto/Hash/BLAKE2b.py").exists():
        transform_source_text(context, "Lib/Crypto/Hash/BLAKE2b.py", _patch_blake2b_py)
    if source_path(context, "pycryptodome_builtin/src/blake2s.c").exists():
        transform_source_text(context, "pycryptodome_builtin/src/blake2s.c", _patch_blake2s_c)
    if source_path(context, "Lib/Crypto/Hash/BLAKE2s.py").exists():
        transform_source_text(context, "Lib/Crypto/Hash/BLAKE2s.py", _patch_blake2s_py)
    if source_path(context, "pycryptodome_builtin/src/poly1305.c").exists():
        transform_source_text(context, "pycryptodome_builtin/src/poly1305.c", _patch_poly1305_c)
    if source_path(context, "Lib/Crypto/Hash/Poly1305.py").exists():
        transform_source_text(context, "Lib/Crypto/Hash/Poly1305.py", _patch_poly1305_py)


LIBRARY_INTEGRATION = pypi_library(
    name="Crypto",
    project_name="pycryptodome",
    release_version="3.20.0",
    source_mapping={
        "Crypto": "Lib/Crypto",
        "src": "pycryptodome_builtin/src",
        "setup.py": "pycryptodome_builtin/upstream_setup.py",
    },
    overlay_entries=[
        "pycryptodome_builtin/embedded_marker.c",
    ],
    python_packages=["Crypto"],
    static_library_projects_release_x64=[
        "_pycryptodome_raw.vcxproj",
    ],
    native_static_projects=[
        {
            "project": "_pycryptodome_raw.vcxproj",
            "guid": PYCRYPTODOME_PROJECT_GUID,
        }
    ],
    python_link_dependencies_release_x64=[
        "_pycryptodome_raw.lib",
    ],
    python_link_wholearchive_release_x64=[
        "_pycryptodome_raw.lib",
    ],
    prepare_source_hooks=[prepare_pycryptodome_project],
    post_patch_hooks=[patch_crypto_sources],
)
