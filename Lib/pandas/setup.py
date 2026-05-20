from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from libs import (
    LibraryIntegration,
    _candidate_pypi_archives,
    _copy_entry,
    _download_file,
    _extract_archive,
    _normalized_project_name,
    _resolve_source_entry,
    replace_regex_once,
    replace_text_once,
    source_path,
    transform_first_existing_source_text,
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
PANDAS_PROJECT_NAME = "pandas"


def pandas_release_version(context) -> str | None:
    return LIBRARY_INTEGRATION.release_version


def pandas_uses_meson_layout(context) -> bool:
    return (pandas_source_root(context) / "meson.build").exists()


def _candidate_archives(
    context,
    project_name: str,
    release_version: str | None,
) -> list[tuple[str, object, str | None, bool]]:
    from packaging.version import Version

    target_version = Version(".".join(str(part) for part in context.version_info))
    return _candidate_pypi_archives(
        context.download_cache_root,
        project_name,
        target_version,
        release_version,
    )


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
    version_tag = f"py{sys.version_info.major}{sys.version_info.minor}"
    return context.download_cache_root / "build-tools" / "pandas-cython" / version_tag


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


def _copy_optional_source_entry(extracted_root: Path, selector: str, destination: Path) -> bool:
    try:
        src = _resolve_source_entry(extracted_root, selector)
    except RuntimeError:
        return False
    _copy_entry(src, destination)
    return True


def prepare_pandas_source(context) -> None:
    project_name = PANDAS_PROJECT_NAME
    normalized = _normalized_project_name(project_name)
    release_version = pandas_release_version(context)
    candidate_archives = _candidate_archives(context, project_name, release_version)

    failures: list[str] = []
    for resolved_release_version, archive_path, url, cached in candidate_archives:
        extract_root = (
            context.work_cache_root
            / "pypi"
            / normalized
            / resolved_release_version
            / "extracted"
            / archive_path.name
        )
        if not archive_path.exists():
            context.log(f"downloading {project_name} {resolved_release_version} from PyPI")
            assert url is not None
            _download_file(url, archive_path)
        elif cached:
            context.log(f"reusing cached {project_name} {resolved_release_version} archive without refreshing PyPI metadata")
        else:
            context.log(f"reusing cached {project_name} {resolved_release_version} archive")

        try:
            extracted_root = _extract_archive(archive_path, extract_root, context.log)
            context.log(f"using {project_name} {resolved_release_version} source from {extracted_root}")

            _copy_entry(_resolve_source_entry(extracted_root, "pandas"), context.source_root / "Lib" / "pandas")

            has_meson = _copy_optional_source_entry(
                extracted_root,
                "meson.build",
                pandas_source_root(context) / "meson.build",
            )
            _copy_optional_source_entry(
                extracted_root,
                "pyproject.toml",
                pandas_source_root(context) / "pyproject.toml",
            )
            if has_meson:
                _copy_entry(
                    _resolve_source_entry(extracted_root, "generate_version.py"),
                    pandas_source_root(context) / "generate_version.py",
                )
                _copy_entry(
                    _resolve_source_entry(extracted_root, "generate_pxi.py"),
                    pandas_source_root(context) / "generate_pxi.py",
                )
                _copy_optional_source_entry(
                    extracted_root,
                    "_version_meson.py",
                    pandas_source_root(context) / "_version_meson.py",
                )
            return
        except RuntimeError as exc:
            failures.append(f"{archive_path.name}: {exc}")
            context.log(f"distribution candidate failed for {project_name} {resolved_release_version}: {archive_path.name}: {exc}")

    target_description = f" release {release_version!r}" if release_version is not None else ""
    raise RuntimeError(
        f"all compatible PyPI distribution artifacts failed for {project_name!r}{target_description}: "
        + "; ".join(failures)
    )


def _render_meson_wrapper(context) -> str:
    include_dir = (context.source_root / "Include").as_posix()
    platinclude_dir = get_pcbuild_output_dir(context.source_root, context.platform).as_posix()
    purelib_dir = (context.source_root / "Lib").as_posix()
    host_python = Path(sys.executable).as_posix()
    cython_target_dir = pandas_cython_target_dir(context).as_posix()
    cython_overlay_dir = pandas_cython_overlay_dir(context).as_posix()
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
import os
import subprocess
import sys
from pathlib import Path


HOST_PYTHON = r"{host_python}"
BOOTSTRAP_PATHS = [
    r"{cython_target_dir}",
    r"{cython_overlay_dir}",
]
INFO = {info!r}


def _build_env() -> dict[str, str]:
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    bootstrap = os.pathsep.join(path for path in BOOTSTRAP_PATHS if path)
    existing = env.get("PYTHONPATH", "")
    if bootstrap and existing:
        env["PYTHONPATH"] = bootstrap + os.pathsep + existing
    elif bootstrap:
        env["PYTHONPATH"] = bootstrap
    return env


def main() -> int:
    args = sys.argv[1:]
    if args and Path(args[0]).name == "python_info.py":
        print(json.dumps(INFO))
        return 0
    if args == ["--version"]:
        print("Python {version_full}")
        return 0
    completed = subprocess.run([HOST_PYTHON, *args], check=False, env=_build_env())
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
    if not pandas_uses_meson_layout(context):
        return
    path = pandas_source_root(context) / "meson.build"
    launcher = pandas_meson_launcher_path(context).as_posix()
    text = path.read_text(encoding="utf-8")
    if launcher in text and "find_installation" in text:
        return
    updated = replace_regex_once(
        text,
        r"(?m)^py = import\('python'\)\.find_installation\((?:pure:\s*false)?\)\s*$",
        f"py = import('python').find_installation('{launcher}', pure: false)",
        label="pandas python installation probe",
    )
    path.write_text(updated, encoding="utf-8", newline="\n")


def _patch_pandas_numpy_include(context) -> None:
    if not pandas_uses_meson_layout(context):
        return
    numpy_include = pandas_numpy_include_dir(context).as_posix()
    numpy_generated_include = pandas_numpy_generated_include_dir(context).as_posix()

    def patch(text: str) -> str:
        if (
            "incdir_numpy_generated =" in text
            and "inc_np = include_directories(incdir_numpy, incdir_numpy_generated)" in text
        ):
            return text
        updated, count = re.subn(
            r"(?ms)^incdir_numpy = .*?^\s*inc_np = include_directories\(incdir_numpy\)\s*$",
            (
                f"incdir_numpy = '{numpy_include}'\n"
                f"incdir_numpy_generated = '{numpy_generated_include}'\n"
                "inc_np = include_directories(incdir_numpy, incdir_numpy_generated)"
            ),
            text,
            count=1,
        )
        if count != 1:
            raise RuntimeError("pandas numpy include probe anchor not found")
        return updated

    transform_first_existing_source_text(
        context,
        [
            "pandas_builtin/source/pandas/meson.build",
            "pandas_builtin/source/meson.build",
        ],
        patch,
        allow_all_missing=True,
    )


def _patch_generate_version(context) -> None:
    if not pandas_uses_meson_layout(context):
        return
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
        allow_missing=True,
    )
    transform_source_text(
        context,
        "pandas_builtin/source/pandas/_libs/src/vendored/numpy/datetime/np_datetime.c",
        replace_symbols,
        allow_missing=True,
    )
    transform_source_text(
        context,
        "pandas_builtin/source/pandas/_libs/src/vendored/numpy/datetime/np_datetime_strings.c",
        replace_symbols,
        allow_missing=True,
    )
    transform_source_text(
        context,
        "pandas_builtin/source/pandas/_libs/tslibs/np_datetime.pyx",
        replace_symbols,
        allow_missing=True,
    )

    def patch_pd_datetime(text: str) -> str:
        if "add_minutes_to_datetimestruct(out, -minutes_offset);" in text:
            text = replace_text_once(
                text,
                "add_minutes_to_datetimestruct(out, -minutes_offset);",
                "pandas_add_minutes_to_datetimestruct(out, -minutes_offset);",
                label="pandas_datetime use renamed minute adjustment helper",
            )
        if "  capi->get_datetime_metadata_from_dtype = get_datetime_metadata_from_dtype;\n" in text:
            text = replace_text_once(
                text,
                "  capi->get_datetime_metadata_from_dtype = get_datetime_metadata_from_dtype;\n",
                "  capi->get_datetime_metadata_from_dtype = pandas_get_datetime_metadata_from_dtype;\n",
                label="pandas_datetime export renamed datetime metadata helper",
            )
        return text

    transform_source_text(
        context,
        "pandas_builtin/source/pandas/_libs/src/datetime/pd_datetime.c",
        patch_pd_datetime,
        allow_missing=True,
    )


def _patch_pandas_ujson_symbols(context) -> None:
    rename_header = """#pragma once

/*
Keep pandas' vendored UltraJSON objects in a private symbol namespace so
they can coexist with the standalone ujson builtin in the final static link.
*/
#define JSON_EncodeObject pandas_ujson_JSON_EncodeObject
#define JSON_DecodeObject pandas_ujson_JSON_DecodeObject
#define encode pandas_ujson_encode
#define createDouble pandas_ujson_createDouble
#define SkipWhitespace pandas_ujson_SkipWhitespace
#define Buffer_Realloc pandas_ujson_Buffer_Realloc
#define objToJSON pandas_ujson_objToJSON
#define JSONToObj pandas_ujson_JSONToObj
#define get_nat pandas_ujson_get_nat
#define object_is_decimal_type pandas_ujson_object_is_decimal_type
#define object_is_dataframe_type pandas_ujson_object_is_dataframe_type
#define object_is_series_type pandas_ujson_object_is_series_type
#define object_is_index_type pandas_ujson_object_is_index_type
#define object_is_nat_type pandas_ujson_object_is_nat_type
#define object_is_na_type pandas_ujson_object_is_na_type
"""
    write_source_text(
        context,
        "pandas_builtin/source/pandas/_libs/include/pandas/vendored/ujson/lib/staticpython_rename.h",
        rename_header,
    )

    def patch_ultrajson_header(text: str) -> str:
        if '#include "pandas/vendored/ujson/lib/staticpython_rename.h"\n' in text:
            return text
        if '#include "pandas/portable.h"\n' in text:
            return replace_text_once(
                text,
                '#include "pandas/portable.h"\n',
                '#include "pandas/portable.h"\n#include "pandas/vendored/ujson/lib/staticpython_rename.h"\n',
                label="pandas vendored ujson rename header include",
            )
        if "JSON_EncodeObject" in text or "JSON_DecodeObject" in text:
            raise RuntimeError("pandas vendored ujson rename header include anchor not found")
        return text

    transform_source_text(
        context,
        "pandas_builtin/source/pandas/_libs/include/pandas/vendored/ujson/lib/ultrajson.h",
        patch_ultrajson_header,
        allow_missing=True,
    )

    def patch_ujson_module(text: str) -> str:
        if '#include "pandas/vendored/ujson/lib/staticpython_rename.h"\n' in text:
            return text
        if '#include "numpy/arrayobject.h"\n' in text:
            return replace_text_once(
                text,
                '#include "numpy/arrayobject.h"\n',
                '#include "numpy/arrayobject.h"\n#include "pandas/vendored/ujson/lib/staticpython_rename.h"\n',
                label="pandas vendored ujson module rename header include",
            )
        if "ultrajson.h" in text:
            raise RuntimeError("pandas vendored ujson module rename header include anchor not found")
        return text

    transform_source_text(
        context,
        "pandas_builtin/source/pandas/_libs/src/vendored/ujson/python/ujson.c",
        patch_ujson_module,
        allow_missing=True,
    )


def prepare_pandas_project(context) -> None:
    if context.platform != "x64":
        raise RuntimeError(f"pandas builtin integration currently supports only x64, not {context.platform}")

    if not pandas_runtime_dir(context).exists():
        raise RuntimeError(f"expected pandas runtime package at {pandas_runtime_dir(context)}")

    _replace_tree(pandas_runtime_dir(context), pandas_build_package_dir(context))


def prepare_pandas_build_files(context) -> None:
    if not pandas_uses_meson_layout(context):
        return
    if not pandas_numpy_include_dir(context).exists():
        raise RuntimeError(
            "pandas requires the NumPy integration to be materialized first; "
            f"missing include dir: {pandas_numpy_include_dir(context)}"
        )

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
        missing.extend(_missing_pandas_outputs_for_module(context, module_name))
    return missing


def _missing_pandas_outputs_for_module(context, module_name: str) -> list[str]:
    object_dir = pandas_module_object_dir(context, module_name)
    object_files = list(object_dir.rglob("*.obj"))
    if not object_files:
        return [f"{object_dir.relative_to(pandas_build_dir(context))}/*.obj"]

    missing = []
    required_suffixes = PANDAS_REQUIRED_OBJECT_SUFFIXES.get(module_name, ())
    for suffix in required_suffixes:
        if not any(path.name.endswith(suffix) for path in object_files):
            missing.append(f"{object_dir.relative_to(pandas_build_dir(context))}/*{suffix}")
    return missing


def _missing_pandas_modules(context) -> list[str]:
    return [
        module_name
        for module_name in PANDAS_EXTENSION_MODULES
        if _missing_pandas_outputs_for_module(context, module_name)
    ]


def _wait_for_expected_pandas_outputs(context, timeout_seconds: float = 5.0) -> list[str]:
    deadline = time.time() + timeout_seconds
    missing = _missing_pandas_outputs(context)
    while missing and time.time() < deadline:
        time.sleep(0.25)
        missing = _missing_pandas_outputs(context)
    return missing


def _ninja_target_listing(context) -> list[tuple[str, str]]:
    command = [
        "ninja",
        "-C",
        str(pandas_build_dir(context)),
        "-t",
        "targets",
        "all",
    ]
    display = subprocess.list2cmdline(command)
    context.log(f"RUN {display}")
    completed = subprocess.run(
        command,
        cwd=str(pandas_source_root(context)),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "failed to enumerate pandas Meson targets.\n"
            f"stdout:\n{completed.stdout[-12000:]}\n"
            f"stderr:\n{completed.stderr[-12000:]}"
        )
    entries: list[tuple[str, str]] = []
    for raw_line in completed.stdout.splitlines():
        line = raw_line.strip()
        if not line or ": " not in line:
            continue
        target, rule = line.split(": ", 1)
        entries.append((target.strip(), rule.strip()))
    return entries


def _pandas_object_targets_by_module(context) -> dict[str, list[str]]:
    build_dir = pandas_build_dir(context)
    prefixes = {
        module_name: pandas_module_object_dir(context, module_name).relative_to(build_dir).as_posix() + "/"
        for module_name in PANDAS_EXTENSION_MODULES
    }
    per_module_targets: dict[str, list[str]] = {module_name: [] for module_name in PANDAS_EXTENSION_MODULES}
    for target, rule in _ninja_target_listing(context):
        if not target.endswith(".obj"):
            continue
        if rule not in {"c_COMPILER", "cpp_COMPILER"}:
            continue
        for module_name, prefix in prefixes.items():
            if target.startswith(prefix):
                per_module_targets[module_name].append(target)
                break

    missing_modules = [module_name for module_name, targets in per_module_targets.items() if not targets]
    if missing_modules:
        raise RuntimeError(
            "failed to map pandas Meson object targets for: "
            + ", ".join(missing_modules)
        )

    return {
        module_name: sorted(per_module_targets[module_name])
        for module_name in PANDAS_EXTENSION_MODULES
    }


def _pandas_object_targets(context) -> list[str]:
    per_module_targets = _pandas_object_targets_by_module(context)
    targets: list[str] = []
    for module_name in PANDAS_EXTENSION_MODULES:
        targets.extend(per_module_targets[module_name])
    return targets


def _run_pandas_ninja(
    context,
    env: dict[str, str],
    *,
    targets: list[str],
    jobs: int | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [
        "ninja",
        "-C",
        str(pandas_build_dir(context)),
        "-k",
        "0",
    ]
    if jobs is not None:
        command.extend(["-j", str(jobs)])
    command.extend(targets)
    display = subprocess.list2cmdline(command)
    context.log(f"RUN {display}")
    return subprocess.run(
        command,
        cwd=str(pandas_source_root(context)),
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _compile_pandas_extensions(context) -> None:
    env = _pandas_build_env(context)
    object_targets_by_module = _pandas_object_targets_by_module(context)
    completed = _run_pandas_ninja(
        context,
        env,
        targets=[
            target
            for module_name in PANDAS_EXTENSION_MODULES
            for target in object_targets_by_module[module_name]
        ],
    )
    if completed.returncode == 0:
        return
    missing_outputs = _wait_for_expected_pandas_outputs(context)
    if not missing_outputs:
        context.log(
            "pandas Meson object compile returned non-zero after producing the required objects; "
            "reusing the successfully compiled objects for builtin static archives."
        )
        return

    pending_modules = _missing_pandas_modules(context)
    if pending_modules:
        context.log(
            "pandas Meson batch compile left missing objects for: "
            + ", ".join(pending_modules)
            + "; retrying those modules sequentially with -j 1"
        )
        retry_failures: list[tuple[str, subprocess.CompletedProcess[str], list[str]]] = []
        for module_name in pending_modules:
            module_missing = _missing_pandas_outputs_for_module(context, module_name)
            if not module_missing:
                continue
            module_completed = _run_pandas_ninja(
                context,
                env,
                targets=object_targets_by_module[module_name],
                jobs=1,
            )
            module_missing = _missing_pandas_outputs_for_module(context, module_name)
            if module_missing:
                retry_failures.append((module_name, module_completed, module_missing))
                continue
            if module_completed.returncode != 0:
                context.log(
                    "pandas Meson retry for "
                    f"{module_name} returned non-zero after producing the required objects; "
                    "reusing the generated objects."
                )

        missing_outputs = _wait_for_expected_pandas_outputs(context)
        if not missing_outputs:
            context.log(
                "pandas Meson sequential retry produced the remaining required objects; "
                "continuing with builtin static archives."
            )
            return
        if retry_failures:
            module_name, module_completed, module_missing = retry_failures[0]
            raise RuntimeError(
                "pandas Meson compile failed after sequential retry.\n"
                f"failed module: {module_name}\n"
                f"missing outputs: {', '.join(module_missing)}\n"
                f"stdout:\n{module_completed.stdout[-12000:]}\n"
                f"stderr:\n{module_completed.stderr[-12000:]}"
            )

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
    pyproject_path = pandas_source_root(context) / "pyproject.toml"
    if pyproject_path.exists():
        shutil.copy2(pyproject_path, pandas_runtime_dir(context) / "pyproject.toml")


def prepare_pandas_artifacts(context) -> None:
    if context.platform != "x64":
        raise RuntimeError(f"pandas builtin integration currently supports only x64, not {context.platform}")
    if not pandas_uses_meson_layout(context):
        context.log("skip pandas Meson artifact preparation for legacy non-Meson source layout")
        return

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


LIBRARY_INTEGRATION = LibraryIntegration(
    name="pandas",
    source_provider="pypi",
    project_name=PANDAS_PROJECT_NAME,
    release_version="3.0.2",
    dependencies=["numpy"],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/pandas/__init__.py",
        "Lib/pandas/core/frame.py",
        "Lib/pandas/io/__init__.py",
    ],
    cleanup_paths=[
        "pandas_builtin/source",
        "pandas_builtin/meson_target_python.py",
        "pandas_builtin/meson_target_python.cmd",
        "pandas_builtin/meson-python.ini",
        "pandas_builtin/tools",
    ],
    python_packages=["pandas"],
    static_library_projects_release_x64=[],
    native_static_projects=[],
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
    prepare_source_hooks=[prepare_pandas_source, prepare_pandas_project],
    pre_patch_hooks=[],
    post_patch_hooks=[
        prepare_pandas_build_files,
        _patch_pandas_python_probe,
        _patch_pandas_numpy_include,
        _patch_generate_version,
        _patch_pandas_datetime_symbols,
        _patch_pandas_ujson_symbols,
    ],
    pre_build_hooks=[prepare_pandas_artifacts],
)
