from __future__ import annotations

import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from libs import (
    inline_verification_step,
    pypi_library,
    replace_text_once,
    source_path,
    transform_source_text,
    write_source_text,
)
from tools import ensure_tool, get_pcbuild_output_dir, run


PANDAS_EXTENSION_MODULES = [
    "pandas._libs._cyutility",
    "pandas._libs.algos",
    "pandas._libs.arrays",
    "pandas._libs.groupby",
    "pandas._libs.hashing",
    "pandas._libs.hashtable",
    "pandas._libs.index",
    "pandas._libs.indexing",
    "pandas._libs.internals",
    "pandas._libs.interval",
    "pandas._libs.join",
    "pandas._libs.lib",
    "pandas._libs.missing",
    "pandas._libs.pandas_datetime",
    "pandas._libs.pandas_parser",
    "pandas._libs.parsers",
    "pandas._libs.json",
    "pandas._libs.ops",
    "pandas._libs.ops_dispatch",
    "pandas._libs.properties",
    "pandas._libs.reshape",
    "pandas._libs.sas",
    "pandas._libs.byteswap",
    "pandas._libs.sparse",
    "pandas._libs.tslib",
    "pandas._libs.testing",
    "pandas._libs.writers",
    "pandas._libs.tslibs.base",
    "pandas._libs.tslibs.ccalendar",
    "pandas._libs.tslibs.dtypes",
    "pandas._libs.tslibs.conversion",
    "pandas._libs.tslibs.fields",
    "pandas._libs.tslibs.nattype",
    "pandas._libs.tslibs.np_datetime",
    "pandas._libs.tslibs.offsets",
    "pandas._libs.tslibs.parsing",
    "pandas._libs.tslibs.period",
    "pandas._libs.tslibs.strptime",
    "pandas._libs.tslibs.timedeltas",
    "pandas._libs.tslibs.timestamps",
    "pandas._libs.tslibs.timezones",
    "pandas._libs.tslibs.tzconversion",
    "pandas._libs.tslibs.vectorized",
    "pandas._libs.window.aggregations",
    "pandas._libs.window.indexers",
]
PANDAS_CYTHON_REQUIREMENT = "Cython>3.1.0,<4.0.0a0"
PANDAS_DUPLICATE_OBJECT_SUFFIXES = {
    "pandas._libs.lib": ("src_parser_tokenizer.c.obj",),
    "pandas._libs.parsers": ("src_parser_tokenizer.c.obj", "src_parser_io.c.obj"),
    "pandas._libs.tslibs.parsing": ("src_parser_tokenizer.c.obj",),
}
PANDAS_REQUIRED_OBJECT_SUFFIXES = {
    "pandas._libs.pandas_datetime": ("src_datetime_pd_datetime.c.obj",),
}


def pandas_source_root(context) -> Path:
    return source_path(context, "pandas_builtin/source")


def pandas_runtime_dir(context) -> Path:
    return source_path(context, "Lib/pandas")


def pandas_build_dir(context) -> Path:
    return pandas_source_root(context) / ".build-staticpython-x64"


def pandas_build_package_dir(context) -> Path:
    return pandas_source_root(context) / "pandas"


def pandas_meson_wrapper_path(context) -> Path:
    return source_path(context, "pandas_builtin/meson_target_python.py")


def pandas_meson_launcher_path(context) -> Path:
    return source_path(context, "pandas_builtin/meson_target_python.cmd")


def pandas_meson_native_file_path(context) -> Path:
    return source_path(context, "pandas_builtin/meson-python.ini")


def pandas_cython_cache_dir(context) -> Path:
    return context.download_cache_root / "build-tools" / "pandas-cython"


def pandas_cython_target_dir(context) -> Path:
    return pandas_cython_cache_dir(context) / "site"


def pandas_cython_overlay_dir(context) -> Path:
    return pandas_cython_cache_dir(context) / "overlay"


def pandas_cython_wrapper_path(context) -> Path:
    return source_path(context, "pandas_builtin/tools/cython.cmd")


def pandas_python_tag(context) -> str:
    major, minor, _patch = context.version_info
    return f"cp{major}{minor}"


def pandas_numpy_include_dir(context) -> Path:
    return pandas_runtime_dir(context).parents[0] / "numpy" / "_core" / "include"


def pandas_numpy_generated_include_dir(context) -> Path:
    return source_path(context, "numpy_builtin/source/.build-staticpython-x64/numpy/_core")


def pandas_module_target_name(context, module_name: str) -> str:
    return f"{module_name.rsplit('.', 1)[-1]}.{pandas_python_tag(context)}-win_amd64.pyd"


def pandas_module_object_dir(context, module_name: str) -> Path:
    if module_name == "pandas._libs._cyutility":
        return pandas_build_dir(context) / f"_cyutility.{pandas_python_tag(context)}-win_amd64.pyd.p"
    parts = module_name.split(".")
    return pandas_build_dir(context).joinpath(*parts[:-1], f"{parts[-1]}.{pandas_python_tag(context)}-win_amd64.pyd.p")


def pandas_output_lib(context, module_name: str) -> Path:
    return get_pcbuild_output_dir(context.source_root, context.platform) / f"{module_name}.lib"


def _replace_tree(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)


def _render_meson_wrapper(context) -> str:
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


def _render_meson_native_file(context) -> str:
    launcher = pandas_meson_launcher_path(context).as_posix()
    return f"""[binaries]
python = '{launcher}'
python3 = '{launcher}'
"""


def _render_meson_launcher(context) -> str:
    host_python = Path(sys.executable)
    wrapper = pandas_meson_wrapper_path(context)
    return (
        "@echo off\n"
        f"\"{host_python}\" \"{wrapper}\" %*\n"
    )


def _render_pandas_cython_wrapper(context, target_dir: Path, overlay_dir: Path) -> str:
    host_python = Path(sys.executable)
    return (
        "@echo off\n"
        "setlocal\n"
        "set \"PYTHONNOUSERSITE=1\"\n"
        f"set \"PYTHONPATH={target_dir};{overlay_dir}\"\n"
        f"\"{host_python}\" -S -m cython %*\n"
    )


def _prepare_pandas_cython_overlay(context) -> Path:
    overlay_dir = pandas_cython_overlay_dir(context)
    source_numpy_dir = context.source_root / "Lib" / "numpy"
    if not source_numpy_dir.exists():
        raise RuntimeError(f"expected NumPy runtime package at {source_numpy_dir}")
    overlay_dir.mkdir(parents=True, exist_ok=True)
    _replace_tree(source_numpy_dir, overlay_dir / "numpy")
    return overlay_dir


def _ensure_pandas_cython(context) -> Path:
    target_dir = pandas_cython_target_dir(context)
    package_dir = target_dir / "Cython"
    if not package_dir.exists():
        cache_dir = pandas_cython_cache_dir(context)
        cache_dir.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        context.log(f"installing local pandas build dependency {PANDAS_CYTHON_REQUIREMENT}")
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
                PANDAS_CYTHON_REQUIREMENT,
            ],
            check=True,
            timeout=60 * 10,
        )
    overlay_dir = _prepare_pandas_cython_overlay(context)
    wrapper_path = pandas_cython_wrapper_path(context)
    wrapper_path.parent.mkdir(parents=True, exist_ok=True)
    wrapper_path.write_text(
        _render_pandas_cython_wrapper(context, target_dir, overlay_dir),
        encoding="utf-8",
        newline="\n",
    )
    return wrapper_path


def _pandas_build_env(context) -> dict[str, str]:
    _ensure_pandas_cython(context)
    wrapper_dir = str(pandas_cython_wrapper_path(context).parent)
    env = os.environ.copy()
    env["PATH"] = wrapper_dir + os.pathsep + env.get("PATH", "")
    env["CYTHON"] = "cython.cmd"
    return env


def _run_with_env(context, command: list[str], *, cwd: Path, timeout: float, env: dict[str, str]) -> None:
    display = subprocess.list2cmdline([str(part) for part in command])
    context.log(f"RUN {display}")
    subprocess.run(command, cwd=str(cwd), env=env, check=True, timeout=timeout)


def _patch_pandas_python_probe(context) -> None:
    path = pandas_source_root(context) / "meson.build"
    launcher = pandas_meson_launcher_path(context).as_posix()
    original = "py = import('python').find_installation(pure: false)\n"
    replacement = f"py = import('python').find_installation('{launcher}', pure: false)\n"
    text = path.read_text(encoding="utf-8")
    if replacement in text:
        return
    if original not in text:
        raise RuntimeError(f"expected python installation probe not found in {path}")
    path.write_text(text.replace(original, replacement, 1), encoding="utf-8", newline="\n")


def _patch_pandas_numpy_include(context) -> None:
    numpy_include = pandas_numpy_include_dir(context).as_posix()
    numpy_generated_include = pandas_numpy_generated_include_dir(context).as_posix()

    def patch(text: str) -> str:
        original = """incdir_numpy = run_command(
    py,
    [
        '-c',
        '''
import os
import numpy as np
try:
    # Check if include directory is inside the pandas dir
    # e.g. a venv created inside the pandas dir
    # If so, convert it to a relative path
    incdir = os.path.relpath(np.get_include())
except Exception:
    incdir = np.get_include()
print(incdir)
     ''',
    ],
    check: true,
).stdout().strip()
"""
        replacement = (
            f"incdir_numpy = '{numpy_include}'\n"
            f"incdir_numpy_generated = '{numpy_generated_include}'\n"
        )
        text = replace_text_once(
            text,
            original,
            replacement,
            label="pandas numpy include probe",
        )
        return replace_text_once(
            text,
            "inc_np = include_directories(incdir_numpy)\n",
            "inc_np = include_directories(incdir_numpy, incdir_numpy_generated)\n",
            label="pandas numpy generated include dir",
        )

    transform_source_text(context, "pandas_builtin/source/pandas/meson.build", patch)


def _patch_generate_version(context) -> None:
    def patch(text: str) -> str:
        text = replace_text_once(
            text,
            "import versioneer\n",
            "try:\n    import versioneer\nexcept ImportError:\n    versioneer = None\n",
            label="pandas generate_version lazy versioneer import",
        )
        text = replace_text_once(
            text,
            "        version = versioneer.get_version()\n        git_version = versioneer.get_versions()[\"full-revisionid\"]\n",
            "        if versioneer is None:\n            raise RuntimeError(\"versioneer is unavailable and _version_meson.py was not found\")\n        version = versioneer.get_version()\n        git_version = versioneer.get_versions()[\"full-revisionid\"]\n",
            label="pandas generate_version fallback writer",
        )
        return replace_text_once(
            text,
            "            version = versioneer.get_version()\n",
            "            if versioneer is None:\n                raise RuntimeError(\"versioneer is unavailable and _version_meson.py was not found\")\n            version = versioneer.get_version()\n",
            label="pandas generate_version fallback printer",
        )

    transform_source_text(context, "pandas_builtin/source/generate_version.py", patch)


def _patch_pandas_datetime_symbols(context) -> None:
    symbol_map = {
        "days_per_month_table": "pandas_days_per_month_table",
        "is_leapyear": "pandas_is_leapyear",
        "add_minutes_to_datetimestruct": "pandas_add_minutes_to_datetimestruct",
        "get_datetimestruct_days": "pandas_get_datetimestruct_days",
        "get_datetime_metadata_from_dtype": "pandas_get_datetime_metadata_from_dtype",
    }

    def replace_symbols(text: str) -> str:
        for original, renamed in symbol_map.items():
            text = text.replace(original, renamed)
        return text

    transform_source_text(
        context,
        "pandas_builtin/source/pandas/_libs/include/pandas/vendored/numpy/datetime/np_datetime.h",
        replace_symbols,
    )
    transform_source_text(
        context,
        "pandas_builtin/source/pandas/_libs/src/vendored/numpy/datetime/np_datetime.c",
        replace_symbols,
    )
    transform_source_text(
        context,
        "pandas_builtin/source/pandas/_libs/src/vendored/numpy/datetime/np_datetime_strings.c",
        replace_symbols,
    )
    transform_source_text(
        context,
        "pandas_builtin/source/pandas/_libs/tslibs/np_datetime.pyx",
        replace_symbols,
    )

    def patch_pd_datetime(text: str) -> str:
        text = replace_text_once(
            text,
            "add_minutes_to_datetimestruct(out, -minutes_offset);",
            "pandas_add_minutes_to_datetimestruct(out, -minutes_offset);",
            label="pandas_datetime use renamed minute adjustment helper",
        )
        return replace_text_once(
            text,
            "  capi->get_datetime_metadata_from_dtype = get_datetime_metadata_from_dtype;\n",
            "  capi->get_datetime_metadata_from_dtype = pandas_get_datetime_metadata_from_dtype;\n",
            label="pandas_datetime export renamed datetime metadata helper",
        )

    transform_source_text(
        context,
        "pandas_builtin/source/pandas/_libs/src/datetime/pd_datetime.c",
        patch_pd_datetime,
    )


def prepare_pandas_project(context) -> None:
    if context.platform != "x64":
        raise RuntimeError(f"pandas builtin integration currently supports only x64, not {context.platform}")

    if not pandas_runtime_dir(context).exists():
        raise RuntimeError(f"expected pandas runtime package at {pandas_runtime_dir(context)}")

    if not pandas_numpy_include_dir(context).exists():
        raise RuntimeError(
            "pandas requires the NumPy integration to be materialized first; "
            f"missing include dir: {pandas_numpy_include_dir(context)}"
        )

    _replace_tree(pandas_runtime_dir(context), pandas_build_package_dir(context))
    write_source_text(context, "pandas_builtin/meson_target_python.py", _render_meson_wrapper(context))
    write_source_text(context, "pandas_builtin/meson_target_python.cmd", _render_meson_launcher(context))
    write_source_text(context, "pandas_builtin/meson-python.ini", _render_meson_native_file(context))


def _pandas_meson_script(context) -> Path:
    candidate = source_path(context, "numpy_builtin/source/vendored-meson/meson.py")
    if not candidate.exists():
        raise RuntimeError(
            "pandas integration expects NumPy's vendored Meson launcher to exist first; "
            f"missing {candidate}"
        )
    return candidate


def _meson_setup_command(context) -> list[str]:
    command = [
        sys.executable,
        str(_pandas_meson_script(context)),
        "setup",
        str(pandas_build_dir(context)),
        "--native-file",
        str(pandas_meson_native_file_path(context)),
        "--backend=ninja",
        "--buildtype=release",
        "-Db_vscrt=mt",
        "-Dc_args=/DPy_NO_ENABLE_SHARED",
        "-Dcpp_args=/DPy_NO_ENABLE_SHARED",
    ]
    if (pandas_build_dir(context) / "build.ninja").exists():
        command.insert(3, "--reconfigure")
    return command


def _missing_pandas_outputs(context) -> list[str]:
    missing = []
    for module_name in PANDAS_EXTENSION_MODULES:
        object_dir = pandas_module_object_dir(context, module_name)
        object_files = list(object_dir.rglob("*.obj"))
        if not object_files:
            missing.append(f"{object_dir.relative_to(pandas_build_dir(context))}/*.obj")
            continue
        required_suffixes = PANDAS_REQUIRED_OBJECT_SUFFIXES.get(module_name, ())
        for suffix in required_suffixes:
            if not any(path.name.endswith(suffix) for path in object_files):
                missing.append(f"{object_dir.relative_to(pandas_build_dir(context))}/*{suffix}")
    return missing


def _wait_for_expected_pandas_outputs(context, timeout_seconds: float = 5.0) -> list[str]:
    deadline = time.time() + timeout_seconds
    missing = _missing_pandas_outputs(context)
    while missing and time.time() < deadline:
        time.sleep(0.25)
        missing = _missing_pandas_outputs(context)
    return missing


def _compile_pandas_extensions(context) -> None:
    env = _pandas_build_env(context)
    command = [
        "ninja",
        "-C",
        str(pandas_build_dir(context)),
        "-k",
        "0",
    ]
    display = subprocess.list2cmdline(command)
    context.log(f"RUN {display}")
    completed = subprocess.run(
        command,
        cwd=str(pandas_source_root(context)),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode == 0:
        return
    missing_outputs = _wait_for_expected_pandas_outputs(context)
    if not missing_outputs:
        context.log(
            "pandas Meson compile ended with the expected shared-module link failure; "
            "reusing the successfully compiled objects for builtin static archives."
        )
        return
    raise RuntimeError(
        "pandas Meson compile failed before the required artifacts were generated.\n"
        f"missing outputs: {', '.join(missing_outputs)}\n"
        f"stdout:\n{completed.stdout[-12000:]}\n"
        f"stderr:\n{completed.stderr[-12000:]}"
    )


def _archive_pandas_builtin(context, module_name: str) -> None:
    output_lib = pandas_output_lib(context, module_name)
    output_lib.parent.mkdir(parents=True, exist_ok=True)
    response_path = source_path(
        context,
        f"pandas_builtin/{module_name.replace('.', '_')}_objects.rsp",
    )
    object_files = sorted(pandas_module_object_dir(context, module_name).rglob("*.obj"))
    duplicate_suffixes = PANDAS_DUPLICATE_OBJECT_SUFFIXES.get(module_name, ())
    if duplicate_suffixes:
        filtered_objects = []
        for path in object_files:
            if any(path.name.endswith(suffix) for suffix in duplicate_suffixes):
                context.log(
                    "excluding duplicate pandas support object "
                    f"{path.relative_to(pandas_build_dir(context))} from {module_name}"
                )
                continue
            filtered_objects.append(path)
        object_files = filtered_objects
    if not object_files:
        raise RuntimeError(f"no object files were produced for {module_name}")
    response_path.write_text(
        "\n".join(f'"{path}"' for path in object_files),
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


def _copy_runtime_support_files(context) -> None:
    version_path = pandas_source_root(context) / "_version_meson.py"
    if version_path.exists():
        shutil.copy2(version_path, pandas_runtime_dir(context) / "_version_meson.py")
    shutil.copy2(pandas_source_root(context) / "pyproject.toml", pandas_runtime_dir(context) / "pyproject.toml")


def prepare_pandas_artifacts(context) -> None:
    if context.platform != "x64":
        raise RuntimeError(f"pandas builtin integration currently supports only x64, not {context.platform}")

    ensure_tool("ninja")
    ensure_tool("lib")
    if pandas_build_dir(context).exists():
        shutil.rmtree(pandas_build_dir(context))
    _run_with_env(
        context,
        _meson_setup_command(context),
        cwd=pandas_source_root(context),
        timeout=60 * 20,
        env=_pandas_build_env(context),
    )

    if _missing_pandas_outputs(context):
        _compile_pandas_extensions(context)
    if _missing_pandas_outputs(context):
        raise RuntimeError("pandas build did not produce the expected builtin-extension objects")

    _copy_runtime_support_files(context)
    for module_name in PANDAS_EXTENSION_MODULES:
        _archive_pandas_builtin(context, module_name)


LIBRARY_INTEGRATION = pypi_library(
    name="pandas",
    release_version="3.0.2",
    source_mapping={
        "pandas": "Lib/pandas",
        "_version_meson.py": "pandas_builtin/source/_version_meson.py",
        "generate_pxi.py": "pandas_builtin/source/generate_pxi.py",
        "generate_version.py": "pandas_builtin/source/generate_version.py",
        "meson.build": "pandas_builtin/source/meson.build",
        "pyproject.toml": "pandas_builtin/source/pyproject.toml",
    },
    materialized_paths=[
        "Lib/pandas/__init__.py",
        "Lib/pandas/_version.py",
        "Lib/pandas/_version_meson.py",
        "Lib/pandas/pyproject.toml",
        "Lib/pandas/core/frame.py",
        "Lib/pandas/io/parsers/readers.py",
        "Lib/pandas/_libs/lib.pyx",
        "Lib/pandas/_libs/tslibs/timestamps.pyx",
        "Lib/pandas/_libs/window/aggregations.pyx",
        "pandas_builtin/source/meson.build",
        "pandas_builtin/source/generate_pxi.py",
        "pandas_builtin/source/generate_version.py",
    ],
    python_packages=["pandas"],
    verification_imports=PANDAS_EXTENSION_MODULES,
    builtin_module_registrations=[
        {
            "name": module_name,
            "pyinit": f"PyInit_{module_name.rsplit('.', 1)[-1]}",
        }
        for module_name in PANDAS_EXTENSION_MODULES
    ],
    python_link_dependencies_release_x64=[
        f"{module_name}.lib"
        for module_name in PANDAS_EXTENSION_MODULES
    ],
    python_link_wholearchive_release_x64=[
        f"{module_name}.lib"
        for module_name in PANDAS_EXTENSION_MODULES
    ],
    prepare_source_hooks=[prepare_pandas_project],
    post_patch_hooks=[
        _patch_pandas_python_probe,
        _patch_pandas_numpy_include,
        _patch_generate_version,
        _patch_pandas_datetime_symbols,
        prepare_pandas_artifacts,
    ],
    verification_steps=[
        inline_verification_step(
            "pandas-smoke",
            r"""
import importlib.util
import io

import numpy as np
import pandas as pd

assert importlib.util.find_spec("pandas._libs.algos").origin == "built-in"
assert importlib.util.find_spec("pandas._libs._cyutility").origin == "built-in"
assert importlib.util.find_spec("pandas._libs.tslibs.base").origin == "built-in"
assert importlib.util.find_spec("pandas._libs.window.aggregations").origin == "built-in"
assert pd.__version__.startswith("3.0.")

left = pd.DataFrame(
    {
        "id": [1, 2, 3],
        "value": [10, 20, 30],
        "when": pd.to_datetime(
            ["2024-01-01T00:00:00Z", "2024-01-01T01:00:00Z", "2024-01-02T00:00:00Z"],
            utc=True,
        ),
    }
)
right = pd.DataFrame({"id": [1, 2, 4], "name": ["a", "b", "d"]})
merged = left.merge(right, on="id", how="left")
assert merged["name"].iloc[0] == "a"
assert merged["name"].iloc[1] == "b"
assert pd.isna(merged["name"].iloc[2])

grouped = merged.groupby(merged["when"].dt.day)["value"].sum()
assert grouped.to_dict() == {1: 30, 2: 30}

csv_buffer = io.StringIO()
merged.to_csv(csv_buffer, index=False)
csv_buffer.seek(0)
roundtrip = pd.read_csv(csv_buffer)
assert roundtrip.shape == (3, 4)
assert roundtrip["value"].sum() == 60

json_frame = pd.read_json(io.StringIO('[{"id": 1, "value": 2}, {"id": 2, "value": 3}]'))
assert json_frame["value"].sum() == 5

pivot = pd.DataFrame(
    {
        "kind": ["a", "a", "b"],
        "column": ["x", "y", "x"],
        "value": [1, 2, 3],
    }
).pivot_table(index="kind", columns="column", values="value", aggfunc="sum")
assert pivot.loc["a", "x"] == 1
assert pivot.loc["a", "y"] == 2
assert pivot.loc["b", "x"] == 3

rolling = pd.Series([1, 2, 3, 4], dtype="float64").rolling(2).sum()
assert pd.isna(rolling.iloc[0])
assert rolling.iloc[1:].tolist() == [3.0, 5.0, 7.0]

timestamp = pd.Timestamp("2024-01-02T03:04:05", tz="UTC")
assert timestamp.tz is not None
date_range = pd.date_range("2024-01-01", periods=3, tz="UTC")
assert len(date_range) == 3

series = pd.Series([1.0, None, 3.0]).fillna(2.0)
assert series.tolist() == [1.0, 2.0, 3.0]
assert np.array_equal(series.to_numpy(), np.array([1.0, 2.0, 3.0]))
""",
            timeout=600,
        )
    ],
)
