from __future__ import annotations

import shutil
from pathlib import Path

from libs import github_library, source_path, transform_source_text, write_source_text
from tools import download_first_available, ensure_tool, extract_source_archive, get_pcbuild_output_dir, run


DEARPYGUI_VERSION = "2.3.1"
DEARPYGUI_STATIC_LIBRARIES = [
    "dearpygui._dearpygui.lib",
    "freetype.lib",
]
DEARPYGUI_SYSTEM_LIBRARIES = [
    "d3d11.lib",
    "dxgi.lib",
    "dwmapi.lib",
]

DEARPYGUI_SUBMODULES = [
    {
        "name": "imgui",
        "commit": "3912b3d9a9c1b3f17431aebafd86d2f40ee6e59c",
        "urls": [
            "https://github.com/ocornut/imgui/archive/3912b3d9a9c1b3f17431aebafd86d2f40ee6e59c.zip",
        ],
        "probe": "imgui.cpp",
    },
    {
        "name": "implot",
        "commit": "4707b245fbcd69075b1a8a74fa8d2435561b3134",
        "urls": [
            "https://github.com/epezent/implot/archive/4707b245fbcd69075b1a8a74fa8d2435561b3134.zip",
        ],
        "probe": "implot.cpp",
    },
    {
        "name": "freetype",
        "commit": "8cf046c38d4c6ada76ba070562beff0d5041f795",
        "urls": [
            "https://github.com/freetype/freetype/archive/8cf046c38d4c6ada76ba070562beff0d5041f795.zip",
            "https://gitlab.freedesktop.org/freetype/freetype/-/archive/8cf046c38d4c6ada76ba070562beff0d5041f795/freetype-8cf046c38d4c6ada76ba070562beff0d5041f795.zip",
        ],
        "probe": "CMakeLists.txt",
    },
]


def _dearpygui_root(context) -> Path:
    return source_path(context, "dearpygui_builtin")


def _dearpygui_build_dir(context) -> Path:
    return (
        context.work_cache_root
        / "dearpygui"
        / context.version_full
        / context.source_root.name
        / f"{DEARPYGUI_VERSION}-{context.platform}-{context.configuration}"
    )


def _patch_dearpygui_package(context) -> None:
    write_source_text(context, "Lib/dearpygui/__init__.py", f"__version__ = {DEARPYGUI_VERSION!r}\n")


def _patch_dearpygui_cpython_api(context) -> None:
    transform_source_text(
        context,
        "dearpygui_builtin/src/mvPyUtils.cpp",
        lambda text: text.replace("_PyUnicode_AsString(", "PyUnicode_AsUTF8("),
    )


def _download_submodule(context, entry: dict) -> None:
    destination = source_path(context, f"dearpygui_builtin/thirdparty/{entry['name']}")
    if (destination / entry["probe"]).exists():
        return

    archive_path = (
        context.download_cache_root
        / "dearpygui"
        / DEARPYGUI_VERSION
        / f"{entry['name']}-{entry['commit']}.zip"
    )
    used_source = download_first_available(context.log, entry["urls"], archive_path)
    extract_source_archive(context.log, archive_path, destination.parent, final_name=destination.name)
    if not (destination / entry["probe"]).exists():
        raise RuntimeError(f"DearPyGui submodule {entry['name']} is missing {entry['probe']}: {destination}")
    context.log(f"materialized DearPyGui submodule {entry['name']} from {used_source}")


def _materialize_dearpygui_submodules(context) -> None:
    for entry in DEARPYGUI_SUBMODULES:
        _download_submodule(context, entry)


def _patch_dearpygui_distribution_cmake(context) -> None:
    source_root = context.source_root.as_posix()
    distribution_cmake = f"""cmake_minimum_required (VERSION 3.16)

add_library(_dearpygui STATIC)

set_target_properties(_dearpygui
  PROPERTIES
  CXX_STANDARD 17
  ARCHIVE_OUTPUT_DIRECTORY "${{CMAKE_BINARY_DIR}}/DearPyGui/"
  LIBRARY_OUTPUT_DIRECTORY "${{CMAKE_BINARY_DIR}}/DearPyGui/"
  RUNTIME_OUTPUT_DIRECTORY "${{CMAKE_BINARY_DIR}}/DearPyGui/"
  OUTPUT_NAME "dearpygui._dearpygui"
  )

target_sources(_dearpygui PRIVATE ${{MARVEL_SOURCES}})

target_include_directories(_dearpygui
        PRIVATE
            "{source_root}/Include"
            "{source_root}/Include/internal"
            "{source_root}/PC"
            ${{MARVEL_INCLUDE_DIR}}
    )

target_compile_definitions(_dearpygui
    PRIVATE
        Py_NO_ENABLE_SHARED
        $<$<CONFIG:Release>:MV_RELEASE>
)

if(WIN32)
    target_precompile_headers(_dearpygui
        PRIVATE mvPyUtils.h
    )
    target_link_libraries(_dearpygui PUBLIC d3d11 dxgi dwmapi freetype)
endif()
"""
    write_source_text(context, "dearpygui_builtin/src/distribution.cmake", distribution_cmake)


def prepare_dearpygui_project(context) -> None:
    _patch_dearpygui_package(context)
    _patch_dearpygui_cpython_api(context)
    _materialize_dearpygui_submodules(context)
    _patch_dearpygui_distribution_cmake(context)


def _copy_first_built_library(context, build_dir: Path, output_name: str) -> None:
    candidates = sorted(
        build_dir.rglob(output_name),
        key=lambda path: (0 if "Release" in path.parts else 1, len(path.parts), str(path)),
    )
    if not candidates:
        raise RuntimeError(f"DearPyGui build did not produce {output_name}")
    output_dir = get_pcbuild_output_dir(context.source_root, context.platform)
    output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidates[0], output_dir / output_name)


def prepare_dearpygui_artifacts(context) -> None:
    output_dir = get_pcbuild_output_dir(context.source_root, context.platform)
    if all((output_dir / name).exists() for name in DEARPYGUI_STATIC_LIBRARIES):
        context.log(f"using existing DearPyGui static libraries at {output_dir.relative_to(context.source_root)}")
        return

    ensure_tool("cmake")
    source_dir = _dearpygui_root(context)
    build_dir = _dearpygui_build_dir(context)
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
            "-DCMAKE_C_FLAGS_RELEASE:STRING=/MT /O2 /Ob2 /DNDEBUG",
            "-DCMAKE_CXX_FLAGS_RELEASE:STRING=/MT /O2 /Ob2 /DNDEBUG",
            "-DCMAKE_DISABLE_FIND_PACKAGE_ZLIB=TRUE",
            "-DCMAKE_DISABLE_FIND_PACKAGE_BZip2=TRUE",
            "-DCMAKE_DISABLE_FIND_PACKAGE_PNG=TRUE",
            "-DCMAKE_DISABLE_FIND_PACKAGE_HarfBuzz=TRUE",
            "-DBUILD_SHARED_LIBS=OFF",
            "-DMVDIST_ONLY=True",
            f"-DMVDPG_VERSION={DEARPYGUI_VERSION}",
            f"-DMV_PY_VERSION={context.version_mm}",
        ],
        cwd=source_dir,
        timeout=60 * 15,
    )
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
        timeout=60 * 50,
    )
    _copy_first_built_library(context, build_dir, "dearpygui._dearpygui.lib")
    _copy_first_built_library(context, build_dir, "freetype.lib")


LIBRARY_INTEGRATION = github_library(
    name="dearpygui",
    repo="hoffstadt/DearPyGui",
    ref=f"v{DEARPYGUI_VERSION}",
    source_mapping={
        "dearpygui": "Lib/dearpygui",
        "src": "dearpygui_builtin/src",
        "thirdparty": "dearpygui_builtin/thirdparty",
        "CMakeLists.txt": "dearpygui_builtin/CMakeLists.txt",
    },
    source_ignore_patterns=[
        ".git",
        ".github",
        "docs",
        "sandbox",
        "testing",
    ],
    materialized_paths=[
        "Lib/dearpygui/__init__.py",
        "dearpygui_builtin/src/distribution.cmake",
        "dearpygui_builtin/thirdparty/imgui/imgui.cpp",
        "dearpygui_builtin/thirdparty/implot/implot.cpp",
        "dearpygui_builtin/thirdparty/freetype/CMakeLists.txt",
    ],
    cleanup_paths=[
        "dearpygui_builtin",
    ],
    python_packages=["dearpygui"],
    builtin_module_registrations=[
        {
            "name": "dearpygui._dearpygui",
            "pyinit": "PyInit__dearpygui",
        }
    ],
    python_link_dependencies_release_x64=[
        *DEARPYGUI_STATIC_LIBRARIES,
        *DEARPYGUI_SYSTEM_LIBRARIES,
    ],
    overlay_entries=[
        "dearpygui_runtime_test.py",
    ],
    prepare_source_hooks=[prepare_dearpygui_project],
    pre_build_hooks=[prepare_dearpygui_artifacts],
)
