from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from libs import (
    pypi_library,
    replace_regex_once,
    replace_text_once,
    source_path,
    transform_source_text,
    write_source_text,
)
from tools import ensure_tool, get_pcbuild_output_dir, run


NUMPY_CORE_PROJECT_GUID = "{42D8BBE4-8B54-4B7D-8E6A-0A3ED6150A7C}"
NUMPY_CORE_PROJECT_NAME = "numpy._core._multiarray_umath"
NUMPY_MARKER_TARGET_NAME = "numpy._core._multiarray_umath_marker"
NUMPY_LINALG_PROJECT_GUID = "{6F8B2CB1-B1F6-4A0E-89F7-5C0DDBA924F1}"
NUMPY_LINALG_PROJECT_NAME = "numpy.linalg._umath_linalg"
NUMPY_LINALG_MARKER_TARGET_NAME = "numpy.linalg._umath_linalg_marker"
NUMPY_POCKETFFT_PROJECT_NAME = "numpy.fft._pocketfft_umath"
NUMPY_RANDOM_BOUNDED_INTEGERS_PROJECT_NAME = "numpy.random._bounded_integers"
NUMPY_RANDOM_COMMON_PROJECT_NAME = "numpy.random._common"
NUMPY_RANDOM_MT19937_PROJECT_NAME = "numpy.random._mt19937"
NUMPY_RANDOM_PHILOX_PROJECT_NAME = "numpy.random._philox"
NUMPY_RANDOM_PCG64_PROJECT_NAME = "numpy.random._pcg64"
NUMPY_RANDOM_SFC64_PROJECT_NAME = "numpy.random._sfc64"
NUMPY_RANDOM_BIT_GENERATOR_PROJECT_NAME = "numpy.random.bit_generator"
NUMPY_RANDOM_GENERATOR_PROJECT_NAME = "numpy.random._generator"
NUMPY_RANDOM_MTRAND_PROJECT_NAME = "numpy.random.mtrand"
NUMPY_RANDOM_BUILTIN_LIBRARY_NAME = "numpy.random._builtin"
NUMPY_CYTHON_REQUIREMENT = "Cython>=3.0.6,<4.0.0"
NUMPY_RANDOM_SUPPORT_OBJECT_NAMES = {
    "src_distributions_distributions.c.obj",
    "src_distributions_logfactorial.c.obj",
    "src_distributions_random_mvhg_count.c.obj",
    "src_distributions_random_mvhg_marginals.c.obj",
    "src_distributions_random_hypergeometric.c.obj",
}
NUMPY_RANDOM_PROJECT_NAMES = [
    NUMPY_RANDOM_BOUNDED_INTEGERS_PROJECT_NAME,
    NUMPY_RANDOM_COMMON_PROJECT_NAME,
    NUMPY_RANDOM_MT19937_PROJECT_NAME,
    NUMPY_RANDOM_PHILOX_PROJECT_NAME,
    NUMPY_RANDOM_PCG64_PROJECT_NAME,
    NUMPY_RANDOM_SFC64_PROJECT_NAME,
    NUMPY_RANDOM_BIT_GENERATOR_PROJECT_NAME,
    NUMPY_RANDOM_GENERATOR_PROJECT_NAME,
    NUMPY_RANDOM_MTRAND_PROJECT_NAME,
]
NUMPY_EXTRA_BUILTIN_PROJECT_NAMES = [
    NUMPY_POCKETFFT_PROJECT_NAME,
    *NUMPY_RANDOM_PROJECT_NAMES,
]


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


def _render_numpy_marker_project(project_guid: str, root_namespace: str, target_name: str, dummy_source: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{project_guid}</ProjectGuid>
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
      <PreprocessorDefinitions>Py_NO_ENABLE_SHARED;_CRT_SECURE_NO_WARNINGS;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
      <AdditionalOptions>/utf-8 %(AdditionalOptions)</AdditionalOptions>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
    <ClCompile Include="{_msbuild_path(dummy_source)}" />
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def numpy_source_root(context) -> Path:
    return source_path(context, "numpy_builtin/source")


def numpy_build_dir(context) -> Path:
    return numpy_source_root(context) / ".build-staticpython-x64"


def numpy_runtime_dir(context) -> Path:
    return source_path(context, "Lib/numpy")


def numpy_build_package_dir(context) -> Path:
    return numpy_source_root(context) / "numpy"


def numpy_build_config_path(context) -> Path:
    return numpy_build_dir(context) / "numpy" / "__config__.py"


def numpy_generated_config_header(context) -> Path:
    return numpy_build_dir(context) / "numpy" / "_core" / "config.h"


def numpy_generated_numpyconfig_header(context) -> Path:
    return numpy_build_dir(context) / "numpy" / "_core" / "_numpyconfig.h"


def numpy_generated_dispatch_header(context) -> Path:
    return numpy_build_dir(context) / "meson_cpu" / "npy_cpu_dispatch_config.h"


def numpy_python_tag(context) -> str:
    major, minor, _patch = context.version_info
    return f"cp{major}{minor}"


def numpy_project_target_name(context, project_name: str) -> str:
    return f"{project_name.replace('.', '/')}.{numpy_python_tag(context)}-win_amd64.pyd"


def numpy_project_object_dir(context, project_name: str) -> Path:
    return numpy_build_dir(context) / f"{numpy_project_target_name(context, project_name)}.p"


def numpy_project_output_lib(context, project_name: str) -> Path:
    return get_pcbuild_output_dir(context.source_root, context.platform) / f"{project_name}.lib"


def numpy_module_target_name(context) -> str:
    return numpy_project_target_name(context, NUMPY_CORE_PROJECT_NAME)


def numpy_module_object_dir(context) -> Path:
    return numpy_project_object_dir(context, NUMPY_CORE_PROJECT_NAME)


def numpy_linalg_target_name(context) -> str:
    return numpy_project_target_name(context, NUMPY_LINALG_PROJECT_NAME)


def numpy_linalg_object_dir(context) -> Path:
    return numpy_project_object_dir(context, NUMPY_LINALG_PROJECT_NAME)


def numpy_npymath_lib(context) -> Path:
    return numpy_build_dir(context) / "numpy" / "_core" / "npymath.lib"


def numpy_npyrandom_lib(context) -> Path:
    return numpy_build_dir(context) / "numpy" / "random" / "npyrandom.lib"


def numpy_unique_hash_lib(context) -> Path:
    return numpy_build_dir(context) / "numpy" / "_core" / "libunique_hash.a"


def numpy_mtargets_lib(context) -> Path:
    return numpy_build_dir(context) / "numpy" / "_core" / "lib_multiarray_umath_mtargets.a"


def numpy_output_lib(context) -> Path:
    return numpy_project_output_lib(context, NUMPY_CORE_PROJECT_NAME)


def numpy_linalg_output_lib(context) -> Path:
    return numpy_project_output_lib(context, NUMPY_LINALG_PROJECT_NAME)


def numpy_dummy_source_path(context) -> Path:
    return source_path(context, "numpy_builtin/_multiarray_umath_marker.c")


def numpy_project_path(context) -> Path:
    return source_path(context, f"PCbuild/{NUMPY_CORE_PROJECT_NAME}.vcxproj")


def numpy_meson_wrapper_path(context) -> Path:
    return source_path(context, "numpy_builtin/meson_target_python.py")


def numpy_meson_launcher_path(context) -> Path:
    return source_path(context, "numpy_builtin/meson_target_python.cmd")


def numpy_meson_native_file_path(context) -> Path:
    return source_path(context, "numpy_builtin/meson-python.ini")


def numpy_cython_cache_dir(context) -> Path:
    version_tag = f"py{sys.version_info.major}{sys.version_info.minor}"
    return context.download_cache_root / "build-tools" / "numpy-cython" / version_tag


def numpy_cython_target_dir(context) -> Path:
    return numpy_cython_cache_dir(context) / "site"


def numpy_cython_wrapper_path(context) -> Path:
    return source_path(context, "numpy_builtin/tools/cython.cmd")


def _replace_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _render_numpy_meson_wrapper(context) -> str:
    include_dir = (context.source_root / "Include").as_posix()
    platinclude_dir = get_pcbuild_output_dir(context.source_root, context.platform).as_posix()
    purelib_dir = (context.source_root / "Lib").as_posix()
    host_python = Path(sys.executable).as_posix()
    major, minor, patch = context.version_info
    version_short = f"{major}.{minor}"
    version_full = f"{major}.{minor}.{patch}"
    extension_suffix = f".cp{major}{minor}-win_amd64.pyd"
    info = {
        "variables": {
            "ABIFLAGS": "",
            "INCLUDEPY": include_dir,
            "Py_GIL_DISABLED": 0,
            "base_prefix": context.source_root.as_posix(),
            "implementation_lower": "python",
            "py_version_nodot": f"{major}{minor}",
            "py_version_short": version_short,
        },
        "paths": {
            "data": context.source_root.as_posix(),
            "include": include_dir,
            "platinclude": platinclude_dir,
            "platlib": purelib_dir,
            "purelib": purelib_dir,
            "scripts": (context.source_root / "PCbuild" / "amd64").as_posix(),
        },
        "sysconfig_paths": {
            "data": context.source_root.as_posix(),
            "include": include_dir,
            "platinclude": platinclude_dir,
            "platlib": purelib_dir,
            "purelib": purelib_dir,
            "scripts": (context.source_root / "PCbuild" / "amd64").as_posix(),
        },
        "install_paths": {
            "data": "",
            "include": "Include",
            "platinclude": "PC",
            "platlib": "Lib",
            "purelib": "Lib",
            "scripts": "PCbuild/amd64",
        },
        "version": version_short,
        "platform": "win-amd64",
        "is_pypy": False,
        "is_venv": False,
        "link_libpython": False,
        "suffix": extension_suffix,
        "limited_api_suffix": ".abi3.pyd",
        "is_freethreaded": False,
    }
    return f"""from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


HOST_PYTHON = r"{host_python}"
INFO = {info!r}


def main() -> int:
    args = sys.argv[1:]
    if args and Path(args[0]).name == "python_info.py":
        print(json.dumps(INFO))
        return 0
    if args == ["--version"]:
        print("Python {version_full}")
        return 0
    completed = subprocess.run([HOST_PYTHON, *args], check=False)
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
"""


def _render_numpy_meson_native_file(context) -> str:
    launcher = numpy_meson_launcher_path(context).as_posix()
    cython = numpy_cython_wrapper_path(context).as_posix()
    return f"""[binaries]
python = '{launcher}'
python3 = '{launcher}'
cython = '{cython}'
cython3 = '{cython}'
"""


def _render_numpy_meson_launcher(context) -> str:
    host_python = Path(sys.executable)
    wrapper = numpy_meson_wrapper_path(context)
    return (
        "@echo off\n"
        f"\"{host_python}\" \"{wrapper}\" %*\n"
    )


def _render_numpy_cython_wrapper(context, target_dir: Path) -> str:
    host_python = Path(sys.executable)
    return (
        "@echo off\n"
        "setlocal\n"
        "set \"PYTHONNOUSERSITE=1\"\n"
        f"set \"PYTHONPATH={target_dir}\"\n"
        f"\"{host_python}\" -S -m cython %*\n"
    )


def _ensure_numpy_cython(context) -> Path:
    target_dir = numpy_cython_target_dir(context)
    package_dir = target_dir / "Cython"
    if not package_dir.exists():
        cache_dir = numpy_cython_cache_dir(context)
        cache_dir.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        context.log(f"installing local numpy build dependency {NUMPY_CYTHON_REQUIREMENT}")
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-compile",
                "--target",
                str(target_dir),
                NUMPY_CYTHON_REQUIREMENT,
            ],
            check=True,
            timeout=60 * 10,
        )
    wrapper_path = numpy_cython_wrapper_path(context)
    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper_path.write_text(
        _render_numpy_cython_wrapper(context, target_dir),
        encoding="utf-8",
        newline="\n",
    )
    return wrapper_path


def _numpy_build_env(context) -> dict[str, str]:
    wrapper_dir = str(_ensure_numpy_cython(context).parent)
    env = os.environ.copy()
    env["PATH"] = wrapper_dir + os.pathsep + env.get("PATH", "")
    env["CYTHON"] = "cython.cmd"
    return env


def _run_with_env(context, command: list[str], *, cwd: Path, timeout: float, env: dict[str, str]) -> None:
    display = subprocess.list2cmdline([str(part) for part in command])
    context.log(f"RUN {display}")
    subprocess.run(command, cwd=str(cwd), env=env, check=True, timeout=timeout)


def _patch_numpy_meson_build(context) -> None:
    meson_build_path = numpy_source_root(context) / "meson.build"
    if not meson_build_path.exists():
        return
    launcher = numpy_meson_launcher_path(context).as_posix()
    text = meson_build_path.read_text(encoding="utf-8")
    if launcher in text and "find_installation" in text:
        return
    updated, count = re.subn(
        r"(?m)^py\s*=\s*import\('python'\)\.find_installation\([^)]*\)\s*$",
        f"py = import('python').find_installation('{launcher}', pure: false)",
        text,
        count=1,
    )
    if count != 1:
        raise RuntimeError(f"expected python installation probe not found in {meson_build_path}")
    meson_build_path.write_text(updated, encoding="utf-8", newline="\n")


def _patch_numpy_top_level_imports(context) -> None:
    def patch(text: str) -> str:
        if "try:\n        from . import matrixlib as _mat\n    except ImportError:\n        _mat = None\n" not in text:
            if "    from . import lib, matrixlib as _mat\n" in text:
                text = replace_text_once(
                    text,
                    "    from . import lib, matrixlib as _mat\n",
                    "    from . import lib\n"
                    "    try:\n"
                    "        from . import matrixlib as _mat\n"
                    "    except ImportError:\n"
                    "        _mat = None\n",
                    label="numpy optional matrixlib combined import",
                )
            elif "    from . import matrixlib as _mat\n" in text:
                text = replace_regex_once(
                    text,
                    r"(?ms)^    from \. import matrixlib as _mat\s*\n",
                    (
                        "    try:\n"
                        "        from . import matrixlib as _mat\n"
                        "    except ImportError:\n"
                        "        _mat = None\n"
                    ),
                    label="numpy optional matrixlib import",
                )
            else:
                return text

        if "    from .matrixlib import *\n" in text and "asmatrix = bmat = mat = matrix = None\n" not in text:
            text = replace_text_once(
                text,
                "    from .matrixlib import *\n",
                "    if _mat is not None:\n"
                "        from .matrixlib import *\n"
                "    else:\n"
                "        asmatrix = bmat = mat = matrix = None\n",
                label="numpy optional matrixlib star import",
            )
        elif "from .matrixlib import (\n        asmatrix, bmat, matrix\n    )\n" in text:
            text = replace_text_once(
                text,
                "    from .matrixlib import (\n        asmatrix, bmat, matrix\n    )\n",
                "    if _mat is not None:\n"
                "        from .matrixlib import (\n"
                "            asmatrix, bmat, matrix\n"
                "        )\n"
                "    else:\n"
                "        asmatrix = bmat = matrix = None\n",
                label="numpy optional matrixlib symbol imports",
            )
        elif re.search(r"(?m)^    from \.matrixlib import asmatrix,\s*bmat,\s*matrix\s*$", text) and "asmatrix = bmat = matrix = None\n" not in text:
            text = replace_regex_once(
                text,
                r"(?m)^    from \.matrixlib import asmatrix,\s*bmat,\s*matrix\s*$",
                "    if _mat is not None:\n"
                "        from .matrixlib import asmatrix, bmat, matrix\n"
                "    else:\n"
                "        asmatrix = bmat = matrix = None\n",
                label="numpy optional matrixlib single-line symbol imports",
            )
        elif "from .matrixlib import" in text and "asmatrix = bmat = matrix = None" not in text:
            updated, count = re.subn(
                r"(?ms)^    from \.matrixlib import \(\n(?P<body>(?:        .+\n)+)    \)\n",
                (
                    "    if _mat is not None:\n"
                    "        from .matrixlib import (\n"
                    "\\g<body>"
                    "        )\n"
                    "    else:\n"
                    "        asmatrix = bmat = matrix = None\n"
                ),
                text,
                count=1,
            )
            if count == 1:
                text = updated
        if "set(_mat.__all__) if _mat is not None else set()" in text:
            return text
        if "        set(_mat.__all__) |\n" in text:
            return replace_text_once(
                text,
                "        set(_mat.__all__) |\n",
                "        (set(_mat.__all__) if _mat is not None else set()) |\n",
                label="numpy optional matrixlib __all__ set-union",
            )
        if "    __all__.extend(_mat.__all__)\n" in text:
            return replace_text_once(
                text,
                "    __all__.extend(_mat.__all__)\n",
                "    if _mat is not None:\n        __all__.extend(_mat.__all__)\n",
                label="numpy optional matrixlib __all__ extend",
            )
        return text

    transform_source_text(context, "Lib/numpy/__init__.py", patch)


def _ensure_generated_pyconfig_header(context) -> None:
    generated = get_pcbuild_output_dir(context.source_root, context.platform) / "pyconfig.h"
    include_target = context.source_root / "Include" / "pyconfig.h"
    generated.parent.mkdir(parents=True, exist_ok=True)
    include_target.parent.mkdir(parents=True, exist_ok=True)
    candidates = [
        generated,
        include_target,
        context.source_root / "PC" / "pyconfig.h",
        context.source_root / "PC" / "pyconfig.h.in",
        context.source_root / "pyconfig.h.in",
    ]
    source = next(
        (
            candidate
            for candidate in candidates
            if candidate.exists() and candidate.stat().st_size > 0
        ),
        None,
    )
    if source is None:
        checked = ", ".join(path.relative_to(context.source_root).as_posix() for path in candidates)
        raise RuntimeError(
            "could not bootstrap pyconfig.h; checked "
            f"{checked}"
        )

    for target in (generated, include_target):
        if source.resolve() == target.resolve():
            continue
        shutil.copy2(source, target)

    if source.resolve() == generated.resolve():
        context.log(
            "refreshed pyconfig.h from "
            f"{generated.relative_to(context.source_root).as_posix()}"
        )
    else:
        context.log(
            "bootstrapped pyconfig.h from "
            f"{source.relative_to(context.source_root).as_posix()}"
        )

    if not generated.exists() or not include_target.exists():
        checked = ", ".join(path.relative_to(context.source_root).as_posix() for path in candidates)
        raise RuntimeError(
            "pyconfig.h bootstrap did not populate both targets; checked "
            f"{checked}"
        )


def _normalize_numpy_runtime_config_module(context) -> None:
    config_path = numpy_runtime_dir(context) / "__config__.py"
    if not config_path.exists():
        write_source_text(
            context,
            "Lib/numpy/__config__.py",
            "# Auto-generated by StaticPython to keep NumPy importable before native build artifacts exist.\n"
            "__all__ = [\"show_config\"]\n\n"
            "def show(*args, **kwargs):\n"
            "    return None\n\n"
            "def show_config(*args, **kwargs):\n"
            "    return show(*args, **kwargs)\n",
        )
        return

    text = config_path.read_text(encoding="utf-8")
    updated = text
    if '__all__ = ["show"]\n' in updated and "show_config" not in updated:
        updated = updated.replace('__all__ = ["show"]\n', '__all__ = ["show_config"]\n', 1)
    if "def show_config(" not in updated:
        if "def show(" in updated:
            if not updated.endswith("\n"):
                updated += "\n"
            updated += (
                "\n"
                "def show_config(*args, **kwargs):\n"
                "    return show(*args, **kwargs)\n"
            )
        else:
            updated = (
                "# Auto-generated by StaticPython to keep NumPy importable before native build artifacts exist.\n"
                "__all__ = [\"show_config\"]\n\n"
                "def show(*args, **kwargs):\n"
                "    return None\n\n"
                "def show_config(*args, **kwargs):\n"
                "    return show(*args, **kwargs)\n"
            )
    if updated != text:
        write_source_text(context, "Lib/numpy/__config__.py", updated)


def prepare_numpy_project(context) -> None:
    if context.platform != "x64":
        raise RuntimeError(f"numpy builtin integration currently supports only x64, not {context.platform}")

    build_source_dir = numpy_build_package_dir(context)
    runtime_dir = numpy_runtime_dir(context)
    if not runtime_dir.exists():
        raise RuntimeError(f"expected NumPy runtime package at {runtime_dir}")
    _replace_tree(runtime_dir, build_source_dir)
    _normalize_numpy_runtime_config_module(context)

    write_source_text(
        context,
        "numpy_builtin/_multiarray_umath_marker.c",
        "void staticpython_numpy_core_marker(void) {}\n",
    )
    write_source_text(
        context,
        f"PCbuild/{NUMPY_CORE_PROJECT_NAME}.vcxproj",
        _render_numpy_marker_project(
            NUMPY_CORE_PROJECT_GUID,
            "numpy_core_multiarray_umath_marker",
            NUMPY_MARKER_TARGET_NAME,
            numpy_dummy_source_path(context).relative_to(context.source_root).as_posix()
        ),
    )
    write_source_text(
        context,
        f"PCbuild/{NUMPY_LINALG_PROJECT_NAME}.vcxproj",
        _render_numpy_marker_project(
            NUMPY_LINALG_PROJECT_GUID,
            "numpy_linalg_umath_linalg_marker",
            NUMPY_LINALG_MARKER_TARGET_NAME,
            numpy_dummy_source_path(context).relative_to(context.source_root).as_posix()
        ),
    )
    write_source_text(context, "numpy_builtin/meson_target_python.py", _render_numpy_meson_wrapper(context))
    write_source_text(context, "numpy_builtin/meson_target_python.cmd", _render_numpy_meson_launcher(context))
    write_source_text(context, "numpy_builtin/meson-python.ini", _render_numpy_meson_native_file(context))
    _patch_numpy_meson_build(context)
    _patch_numpy_top_level_imports(context)
    _ensure_generated_pyconfig_header(context)


def _meson_setup_command(context) -> list[str]:
    meson_script = numpy_source_root(context) / "vendored-meson" / "meson.py"
    command = [
        sys.executable,
        str(meson_script),
        "setup",
        str(numpy_build_dir(context)),
        "--native-file",
        str(numpy_meson_native_file_path(context)),
        "--backend=ninja",
        "--buildtype=release",
        "-Db_vscrt=mt",
        "-Dc_args=/DPy_NO_ENABLE_SHARED",
        "-Dcpp_args=/DPy_NO_ENABLE_SHARED",
        "-Dblas=none",
        "-Dlapack=none",
        "-Dallow-noblas=true",
        "-Ddisable-optimization=true",
        "-Ddisable-highway=true",
        "-Ddisable-intel-sort=true",
        "-Ddisable-threading=true",
        "-Denable-openmp=false",
        "-Dcpu-baseline=none",
        "-Dcpu-dispatch=none",
    ]
    if (numpy_build_dir(context) / "build.ninja").exists():
        command.insert(3, "--reconfigure")
    return command


def _ensure_generated_headers(context) -> None:
    include_dir = numpy_runtime_dir(context) / "_core" / "include" / "numpy"
    include_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(numpy_generated_config_header(context), include_dir / "config.h")
    shutil.copy2(numpy_generated_numpyconfig_header(context), include_dir / "_numpyconfig.h")
    shutil.copy2(numpy_generated_dispatch_header(context), include_dir / "npy_cpu_dispatch_config.h")


def _expected_numpy_outputs_exist(context) -> bool:
    return not _missing_numpy_outputs(context)


def _missing_numpy_outputs(context) -> list[str]:
    required_paths = [
        ("numpy/__config__.py", numpy_build_config_path(context)),
        ("numpy/_core/config.h", numpy_generated_config_header(context)),
        ("numpy/_core/_numpyconfig.h", numpy_generated_numpyconfig_header(context)),
        ("meson_cpu/npy_cpu_dispatch_config.h", numpy_generated_dispatch_header(context)),
        ("numpy/_core/npymath.lib", numpy_npymath_lib(context)),
        ("numpy/random/npyrandom.lib", numpy_npyrandom_lib(context)),
        ("numpy/_core/libunique_hash.a", numpy_unique_hash_lib(context)),
        ("numpy/_core/lib_multiarray_umath_mtargets.a", numpy_mtargets_lib(context)),
    ]
    missing = [label for label, path in required_paths if not path.exists()]
    if not any(numpy_module_object_dir(context).glob("*.obj")):
        missing.append(f"{numpy_module_object_dir(context).name}/*.obj")
    if not any(numpy_linalg_object_dir(context).glob("*.obj")):
        missing.append(f"{numpy_linalg_object_dir(context).name}/*.obj")
    for project_name in NUMPY_EXTRA_BUILTIN_PROJECT_NAMES:
        object_dir = numpy_project_object_dir(context, project_name)
        if not any(object_dir.glob("*.obj")):
            missing.append(f"{object_dir.name}/*.obj")
    return missing


def _wait_for_expected_numpy_outputs(context, timeout_seconds: float = 5.0) -> list[str]:
    deadline = time.time() + timeout_seconds
    missing = _missing_numpy_outputs(context)
    while missing and time.time() < deadline:
        time.sleep(0.25)
        missing = _missing_numpy_outputs(context)
    return missing


def _compile_numpy_core(context) -> None:
    env = _numpy_build_env(context)
    command = [
        "ninja",
        "-C",
        str(numpy_build_dir(context)),
        "-k",
        "0",
        "numpy/_core/npymath.lib",
        numpy_module_target_name(context),
        numpy_linalg_target_name(context),
        *[numpy_project_target_name(context, project_name) for project_name in NUMPY_EXTRA_BUILTIN_PROJECT_NAMES],
    ]
    display = subprocess.list2cmdline(command)
    context.log(f"RUN {display}")
    completed = subprocess.run(
        command,
        cwd=str(numpy_source_root(context)),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode == 0:
        return
    missing_outputs = _wait_for_expected_numpy_outputs(context)
    if not missing_outputs:
        context.log(
            "NumPy Meson compile ended with the expected shared-module link failure; "
            "reusing the successfully compiled objects and static archives."
        )
        return
    raise RuntimeError(
        "NumPy Meson compile failed before the required artifacts were generated.\n"
        f"missing outputs: {', '.join(missing_outputs)}\n"
        f"stdout:\n{completed.stdout[-12000:]}\n"
        f"stderr:\n{completed.stderr[-12000:]}"
    )


def _archive_numpy_core_builtin(context) -> None:
    _archive_numpy_builtin(
        context,
        NUMPY_CORE_PROJECT_NAME,
        [
            numpy_npymath_lib(context),
            numpy_unique_hash_lib(context),
            numpy_mtargets_lib(context),
        ],
    )


def _archive_numpy_linalg_builtin(context) -> None:
    _archive_numpy_builtin(context, NUMPY_LINALG_PROJECT_NAME, [])


def _archive_numpy_builtin(context, project_name: str, extra_items: list[Path]) -> None:
    output_lib = numpy_project_output_lib(context, project_name)
    output_lib.parent.mkdir(parents=True, exist_ok=True)
    response_path = source_path(
        context,
        f"numpy_builtin/{project_name.replace('.', '_')}_objects.rsp",
    )
    response_items = [
        *sorted(numpy_project_object_dir(context, project_name).glob("*.obj")),
        *extra_items,
    ]
    response_path.write_text(
        "\n".join(f'"{path}"' for path in response_items),
        encoding="utf-8",
        newline="\n",
    )
    run(
        context.log,
        [
            "lib.exe",
            "/nologo",
            f"/OUT:{output_lib}",
            f"@{response_path}",
        ],
        cwd=context.source_root,
        timeout=60 * 10,
    )
    context.log(f"prepared {output_lib.relative_to(context.source_root)}")


def _archive_numpy_fft_builtin(context) -> None:
    _archive_numpy_builtin(context, NUMPY_POCKETFFT_PROJECT_NAME, [])


def _archive_numpy_random_builtins(context) -> None:
    output_lib = get_pcbuild_output_dir(context.source_root, context.platform) / f"{NUMPY_RANDOM_BUILTIN_LIBRARY_NAME}.lib"
    output_lib.parent.mkdir(parents=True, exist_ok=True)
    response_path = source_path(context, "numpy_builtin/numpy_random_builtin_objects.rsp")
    unique_objects: dict[str, Path] = {}
    duplicate_objects: dict[str, list[str]] = {}
    for project_name in NUMPY_RANDOM_PROJECT_NAMES:
        for path in sorted(numpy_project_object_dir(context, project_name).glob("*.obj")):
            if path.name in NUMPY_RANDOM_SUPPORT_OBJECT_NAMES:
                context.log(f"excluding random support object {path} because npyrandom.lib already provides it")
                continue
            key = path.name.casefold()
            if key in unique_objects:
                duplicate_objects.setdefault(path.name, [str(unique_objects[key])]).append(str(path))
                continue
            unique_objects[key] = path
    for object_name, sources in sorted(duplicate_objects.items()):
        context.log(f"deduplicated random support object {object_name}: {sources}")
    response_items = [*unique_objects.values(), numpy_npyrandom_lib(context)]
    response_path.write_text(
        "\n".join(f'"{path}"' for path in response_items),
        encoding="utf-8",
        newline="\n",
    )
    run(
        context.log,
        [
            "lib.exe",
            "/nologo",
            f"/OUT:{output_lib}",
            f"@{response_path}",
        ],
        cwd=context.source_root,
        timeout=60 * 10,
    )
    context.log(f"prepared {output_lib.relative_to(context.source_root)}")


def prepare_numpy_artifacts(context) -> None:
    if context.platform != "x64":
        raise RuntimeError(f"numpy builtin integration currently supports only x64, not {context.platform}")

    ensure_tool("ninja")
    ensure_tool("lib")
    env = _numpy_build_env(context)

    _replace_tree(numpy_runtime_dir(context), numpy_build_package_dir(context))
    _run_with_env(
        context,
        _meson_setup_command(context),
        cwd=numpy_source_root(context),
        timeout=60 * 20,
        env=env,
    )

    if not _expected_numpy_outputs_exist(context):
        _compile_numpy_core(context)
    if not _expected_numpy_outputs_exist(context):
        raise RuntimeError("NumPy build did not produce the expected core artifacts")

    shutil.copy2(numpy_build_config_path(context), numpy_runtime_dir(context) / "__config__.py")
    _normalize_numpy_runtime_config_module(context)
    _ensure_generated_headers(context)
    _archive_numpy_core_builtin(context)
    _archive_numpy_linalg_builtin(context)
    _archive_numpy_fft_builtin(context)
    _archive_numpy_random_builtins(context)


LIBRARY_INTEGRATION = pypi_library(
    name="numpy",
    release_version="2.4.4",
    source_mapping={
        "numpy": "Lib/numpy",
        "?LICENSE.txt": "numpy_builtin/source/LICENSE.txt",
        "?README.md || ?README.txt || ?README.rst": "numpy_builtin/source/README.md",
        "?meson.build": "numpy_builtin/source/meson.build",
        "?meson.options || ?meson_options.txt": "numpy_builtin/source/meson.options",
        "?meson_cpu": "numpy_builtin/source/meson_cpu",
        "?pyproject.toml": "numpy_builtin/source/pyproject.toml",
        "?tools": "numpy_builtin/source/tools",
        "?vendored-meson/meson/meson.py": "numpy_builtin/source/vendored-meson/meson.py",
        "?vendored-meson/meson/mesonbuild": "numpy_builtin/source/vendored-meson/mesonbuild",
    },
    materialized_paths=[
        "numpy_builtin/_multiarray_umath_marker.c",
        f"PCbuild/{NUMPY_CORE_PROJECT_NAME}.vcxproj",
        f"PCbuild/{NUMPY_LINALG_PROJECT_NAME}.vcxproj",
        "numpy_builtin/meson_target_python.py",
        "numpy_builtin/meson_target_python.cmd",
        "numpy_builtin/meson-python.ini",
    ],
    cleanup_paths=[
        "numpy_builtin/source",
    ],
    python_packages=["numpy"],
    static_library_projects_release_x64=[
        f"{NUMPY_CORE_PROJECT_NAME}.vcxproj",
        f"{NUMPY_LINALG_PROJECT_NAME}.vcxproj",
    ],
    native_static_projects=[
        {
            "project": f"{NUMPY_CORE_PROJECT_NAME}.vcxproj",
            "guid": NUMPY_CORE_PROJECT_GUID,
        },
        {
            "project": f"{NUMPY_LINALG_PROJECT_NAME}.vcxproj",
            "guid": NUMPY_LINALG_PROJECT_GUID,
        },
    ],
    builtin_module_registrations=[
        {
            "name": "numpy._core._multiarray_umath",
            "pyinit": "PyInit__multiarray_umath",
        },
        {
            "name": "numpy.linalg._umath_linalg",
            "pyinit": "PyInit__umath_linalg",
        },
        {
            "name": "numpy.fft._pocketfft_umath",
            "pyinit": "PyInit__pocketfft_umath",
        },
        {
            "name": "numpy.random._bounded_integers",
            "pyinit": "PyInit__bounded_integers",
            "library": f"{NUMPY_RANDOM_BUILTIN_LIBRARY_NAME}.lib",
        },
        {
            "name": "numpy.random._common",
            "pyinit": "PyInit__common",
            "library": f"{NUMPY_RANDOM_BUILTIN_LIBRARY_NAME}.lib",
        },
        {
            "name": "numpy.random._philox",
            "pyinit": "PyInit__philox",
            "library": f"{NUMPY_RANDOM_BUILTIN_LIBRARY_NAME}.lib",
        },
        {
            "name": "numpy.random._sfc64",
            "pyinit": "PyInit__sfc64",
            "library": f"{NUMPY_RANDOM_BUILTIN_LIBRARY_NAME}.lib",
        },
        {
            "name": "numpy.random.bit_generator",
            "pyinit": "PyInit_bit_generator",
            "library": f"{NUMPY_RANDOM_BUILTIN_LIBRARY_NAME}.lib",
        },
        {
            "name": "numpy.random._generator",
            "pyinit": "PyInit__generator",
            "library": f"{NUMPY_RANDOM_BUILTIN_LIBRARY_NAME}.lib",
        },
        {
            "name": "numpy.random._mt19937",
            "pyinit": "PyInit__mt19937",
            "library": f"{NUMPY_RANDOM_BUILTIN_LIBRARY_NAME}.lib",
        },
        {
            "name": "numpy.random._pcg64",
            "pyinit": "PyInit__pcg64",
            "library": f"{NUMPY_RANDOM_BUILTIN_LIBRARY_NAME}.lib",
        },
        {
            "name": "numpy.random.mtrand",
            "pyinit": "PyInit_mtrand",
            "library": f"{NUMPY_RANDOM_BUILTIN_LIBRARY_NAME}.lib",
        },
    ],
    python_link_dependencies_release_x64=[
        f"{NUMPY_CORE_PROJECT_NAME}.lib",
        f"{NUMPY_LINALG_PROJECT_NAME}.lib",
        f"{NUMPY_POCKETFFT_PROJECT_NAME}.lib",
        f"{NUMPY_RANDOM_BUILTIN_LIBRARY_NAME}.lib",
    ],
    python_link_wholearchive_release_x64=[
        f"{NUMPY_CORE_PROJECT_NAME}.lib",
        f"{NUMPY_LINALG_PROJECT_NAME}.lib",
        f"{NUMPY_POCKETFFT_PROJECT_NAME}.lib",
        f"{NUMPY_RANDOM_BUILTIN_LIBRARY_NAME}.lib",
    ],
    prepare_source_hooks=[prepare_numpy_project],
    pre_build_hooks=[prepare_numpy_artifacts],
)
