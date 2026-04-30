from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from libs import inline_verification_step, pypi_library, source_path, write_source_text
from tools import (
    download_first_available,
    ensure_tool,
    extract_source_archive,
    get_pcbuild_output_dir,
    platform_output_dir_name,
    run,
)


PYZMQ_PROJECT_GUID = "{A2E3F81C-84B6-4A6D-905D-4D70D728A0A1}"
PYZMQ_PROJECT_NAME = "zmq.backend.cython._zmq"
PYZMQ_CYTHON_REQUIREMENT = "Cython>=3.0.0,<4.0.0"

LIBSODIUM_ARCHIVE_URL_TEMPLATE = (
    "https://github.com/jedisct1/libsodium/releases/download/{version}-RELEASE/libsodium-{version}.tar.gz"
)
LIBZMQ_ARCHIVE_URL_TEMPLATE = (
    "https://github.com/zeromq/libzmq/releases/download/v{version}/zeromq-{version}.tar.gz"
)


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


def _render_pyzmq_project(generated_source: str, bundle_include_dir: str) -> str:
    return f"""<?xml version="1.0" encoding="utf-8"?>
<Project DefaultTargets="Build" ToolsVersion="4.0" xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
{_project_configurations()}  <PropertyGroup Label="Globals">
    <ProjectGuid>{PYZMQ_PROJECT_GUID}</ProjectGuid>
    <RootNamespace>zmq_backend_cython__zmq</RootNamespace>
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
    <TargetName>{PYZMQ_PROJECT_NAME}</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>..\\Lib\\zmq\\utils;{bundle_include_dir};%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>Py_NO_ENABLE_SHARED;ZMQ_STATIC;SODIUM_STATIC;_CRT_SECURE_NO_WARNINGS;CYTHON_CLINE_IN_TRACEBACK=0;%(PreprocessorDefinitions)</PreprocessorDefinitions>
      <DisableSpecificWarnings>4100;4127;4244;4267;4996;%(DisableSpecificWarnings)</DisableSpecificWarnings>
      <AdditionalOptions>/bigobj %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
    <ClCompile Include="{_msbuild_path(generated_source)}" />
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def _version_from_pyzmq_cmake(context, variable_name: str) -> str:
    text = source_path(context, "pyzmq_builtin/CMakeLists.txt").read_text(encoding="utf-8")
    match = re.search(rf'set\({re.escape(variable_name)}\s+"([^"]+)"', text)
    if match is None:
        raise RuntimeError(f"could not detect {variable_name} from pyzmq_builtin/CMakeLists.txt")
    return match.group(1)


def libsodium_version(context) -> str:
    return _version_from_pyzmq_cmake(context, "PYZMQ_LIBSODIUM_VERSION")


def libzmq_version(context) -> str:
    return _version_from_pyzmq_cmake(context, "PYZMQ_LIBZMQ_VERSION")


def libsodium_source_dir(context) -> Path:
    return context.source_root / "pyzmq_builtin" / f"libsodium-{libsodium_version(context)}"


def libzmq_source_dir(context) -> Path:
    return context.source_root / "pyzmq_builtin" / f"zeromq-{libzmq_version(context)}"


def pyzmq_generated_c_path(context) -> Path:
    return context.source_root / "pyzmq_builtin" / "generated" / "_zmq.c"


def pyzmq_bundle_root(context) -> Path:
    return (
        context.source_root
        / "pyzmq_builtin"
        / f"bundle-{libzmq_version(context)}-{libsodium_version(context)}"
        / platform_output_dir_name(context.platform)
    )


def pyzmq_bundle_include_dir(context) -> Path:
    return pyzmq_bundle_root(context) / "include"


def pyzmq_bundle_library_dir(context) -> Path:
    return pyzmq_bundle_root(context) / "lib"


def pyzmq_cython_cache_dir(context) -> Path:
    return context.download_cache_root / "build-tools" / "pyzmq-cython"


def pyzmq_cython_target_dir(context) -> Path:
    return pyzmq_cython_cache_dir(context) / "site"


def libzmq_build_dir(context) -> Path:
    return (
        context.source_root
        / "pyzmq_builtin"
        / f"zeromq-build-{libzmq_version(context)}-{platform_output_dir_name(context.platform)}"
    )


def libzmq_build_stamp_path(context) -> Path:
    return pyzmq_bundle_root(context) / "libzmq-build-stamp.txt"


def libsodium_archive_path(context) -> Path:
    version = libsodium_version(context)
    return context.download_cache_root / "libsodium" / version / f"libsodium-{version}.tar.gz"


def libzmq_archive_path(context) -> Path:
    version = libzmq_version(context)
    return context.download_cache_root / "libzmq" / version / f"zeromq-{version}.tar.gz"


def _ensure_pyzmq_cython(context) -> Path:
    target_dir = pyzmq_cython_target_dir(context)
    package_dir = target_dir / "Cython"
    if not package_dir.exists():
        cache_dir = pyzmq_cython_cache_dir(context)
        cache_dir.mkdir(parents=True, exist_ok=True)
        if target_dir.exists():
            shutil.rmtree(target_dir)
        context.log(f"installing local pyzmq build dependency {PYZMQ_CYTHON_REQUIREMENT}")
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
                PYZMQ_CYTHON_REQUIREMENT,
            ],
            check=True,
            timeout=60 * 10,
        )
    return target_dir


def ensure_libsodium_source(context) -> Path:
    source_dir = libsodium_source_dir(context)
    if (source_dir / "builds" / "msvc" / "vs2022" / "libsodium.sln").exists():
        context.log(f"using existing libsodium source at {source_dir.relative_to(context.source_root)}")
        return source_dir

    version = libsodium_version(context)
    archive_path = libsodium_archive_path(context)
    used_source = download_first_available(
        context.log,
        [LIBSODIUM_ARCHIVE_URL_TEMPLATE.format(version=version)],
        archive_path,
    )
    source_dir.parent.mkdir(parents=True, exist_ok=True)
    extract_source_archive(context.log, archive_path, source_dir.parent, final_name=source_dir.name)
    if not (source_dir / "builds" / "msvc" / "vs2022" / "libsodium.sln").exists():
        raise RuntimeError(f"downloaded libsodium source is missing VS2022 solution: {source_dir}")
    context.log(
        f"materialized libsodium {version} from {used_source} to {source_dir.relative_to(context.source_root)}"
    )
    return source_dir


def ensure_libzmq_source(context) -> Path:
    source_dir = libzmq_source_dir(context)
    if (source_dir / "CMakeLists.txt").exists() and (source_dir / "builds" / "cmake" / "Modules").exists():
        context.log(f"using existing libzmq source at {source_dir.relative_to(context.source_root)}")
        return source_dir

    version = libzmq_version(context)
    archive_path = libzmq_archive_path(context)
    used_source = download_first_available(
        context.log,
        [LIBZMQ_ARCHIVE_URL_TEMPLATE.format(version=version)],
        archive_path,
    )
    source_dir.parent.mkdir(parents=True, exist_ok=True)
    extract_source_archive(context.log, archive_path, source_dir.parent, final_name=source_dir.name)
    if not (source_dir / "CMakeLists.txt").exists():
        raise RuntimeError(f"downloaded libzmq source is missing CMakeLists.txt: {source_dir}")
    context.log(f"materialized libzmq {version} from {used_source} to {source_dir.relative_to(context.source_root)}")
    return source_dir


def _clear_directory(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _copy_directory_contents(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        target = destination / child.name
        if target.exists():
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def patch_generated_libzmq_project(build_dir: Path) -> None:
    project_path = build_dir / "libzmq-static.vcxproj"
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(project_path, parser=parser)
    root = tree.getroot()
    namespace = "{http://schemas.microsoft.com/developer/msbuild/2003}"

    def iter_release_nodes(tag_name: str):
        tag = namespace + tag_name
        for element in root.iter(tag):
            condition = element.get("Condition")
            if condition is None or condition == "'$(Configuration)|$(Platform)'=='Release|x64'":
                yield element

    for element in iter_release_nodes("MultiProcessorCompilation"):
        element.text = "false"
    for element in iter_release_nodes("DebugInformationFormat"):
        element.text = ""
    for element in iter_release_nodes("PrecompiledHeader"):
        element.text = "NotUsing"

    for parent in root.iter():
        children = list(parent)
        for child in children:
            if child.tag != namespace + "PrecompiledHeaderFile":
                continue
            condition = child.get("Condition")
            if condition is None or condition == "'$(Configuration)|$(Platform)'=='Release|x64'":
                parent.remove(child)

    tree.write(project_path, encoding="utf-8", xml_declaration=True)


def ensure_static_libsodium(context) -> Path:
    if context.platform != "x64":
        raise RuntimeError(f"pyzmq static libsodium build currently supports only x64, not {context.platform}")

    source_dir = ensure_libsodium_source(context)
    bundle_root = pyzmq_bundle_root(context)
    bundle_include = pyzmq_bundle_include_dir(context)
    bundle_lib_dir = pyzmq_bundle_library_dir(context)
    bundled_library = bundle_lib_dir / "libsodium.lib"
    bundled_header = bundle_include / "sodium.h"
    if bundled_library.exists() and bundled_header.exists():
        context.log(f"using existing bundled libsodium at {bundle_root.relative_to(context.source_root)}")
        return bundled_library

    ensure_tool("msbuild")
    solution = source_dir / "builds" / "msvc" / "vs2022" / "libsodium.sln"
    run(
        context.log,
        [
            "msbuild",
            str(solution),
            "/m",
            "/nologo",
            "/p:Configuration=StaticRelease",
            "/p:Platform=x64",
            "/p:VcpkgEnabled=false",
        ],
        cwd=solution.parent,
        timeout=60 * 30,
    )

    built_library = source_dir / "bin" / "x64" / "Release" / "v143" / "static" / "libsodium.lib"
    if not built_library.exists():
        raise RuntimeError(f"libsodium build did not produce {built_library}")

    bundle_include.mkdir(parents=True, exist_ok=True)
    bundle_lib_dir.mkdir(parents=True, exist_ok=True)
    _copy_directory_contents(source_dir / "src" / "libsodium" / "include", bundle_include)
    shutil.copy2(built_library, bundled_library)
    context.log(f"prepared bundled libsodium at {bundle_root.relative_to(context.source_root)}")
    return bundled_library


def ensure_static_libzmq(context) -> Path:
    if context.platform != "x64":
        raise RuntimeError(f"pyzmq static libzmq build currently supports only x64, not {context.platform}")

    source_dir = ensure_libzmq_source(context)
    ensure_static_libsodium(context)
    bundle_root = pyzmq_bundle_root(context)
    bundle_include = pyzmq_bundle_include_dir(context)
    bundle_lib_dir = pyzmq_bundle_library_dir(context)
    bundled_library = bundle_lib_dir / "libzmq-static.lib"
    bundled_header = bundle_include / "zmq.h"
    bundled_utils_header = bundle_include / "zmq_utils.h"
    build_stamp_path = libzmq_build_stamp_path(context)
    build_stamp = "\n".join(
        [
            "StaticPython libzmq build stamp v2",
            "cmp0091=NEW",
            "runtime=/MT",
            "poller=select",
            "api_poller=select",
            "curve=on",
            "ipc=off",
        ]
    )
    if (
        bundled_library.exists()
        and bundled_header.exists()
        and bundled_utils_header.exists()
        and build_stamp_path.exists()
        and build_stamp_path.read_text(encoding="utf-8") == build_stamp
    ):
        context.log(f"using existing bundled libzmq at {bundle_root.relative_to(context.source_root)}")
        return bundled_library

    ensure_tool("cmake")
    build_dir = libzmq_build_dir(context)
    _clear_directory(build_dir)
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
            "-DBUILD_SHARED=OFF",
            "-DBUILD_STATIC=ON",
            "-DBUILD_TESTS=OFF",
            "-DENABLE_DRAFTS=OFF",
            "-DENABLE_CURVE=ON",
            "-DWITH_LIBSODIUM=ON",
            "-DWITH_LIBSODIUM_STATIC=ON",
            "-DPOLLER=select",
            "-DAPI_POLLER=select",
            "-DZMQ_HAVE_IPC=OFF",
            f"-DSODIUM_INCLUDE_DIRS:PATH={bundle_include}",
            f"-DSODIUM_LIBRARIES:FILEPATH={bundle_lib_dir / 'libsodium.lib'}",
            f"-DCMAKE_PREFIX_PATH:PATH={bundle_root}",
            "-DCMAKE_MSVC_RUNTIME_LIBRARY=MultiThreaded",
            "-DCMAKE_C_FLAGS_RELEASE:STRING=/MT /O2 /Ob2 /DNDEBUG",
            "-DCMAKE_CXX_FLAGS_RELEASE:STRING=/MT /O2 /Ob2 /DNDEBUG",
        ],
        cwd=source_dir,
        timeout=60 * 20,
    )
    cache_path = build_dir / "CMakeCache.txt"
    cache_text = cache_path.read_text(encoding="utf-8", errors="replace")
    if "/MT" not in cache_text:
        raise RuntimeError(f"libzmq CMake cache did not capture /MT runtime flags: {cache_path}")
    patch_generated_libzmq_project(build_dir)
    run(
        context.log,
        [
            "cmake",
            "--build",
            str(build_dir),
            "--config",
            "Release",
            "--target",
            "libzmq-static",
            "--",
            "/m:1",
            "/p:CL_MPCount=1",
            "/p:UseMultiToolTask=false",
        ],
        cwd=build_dir,
        timeout=60 * 40,
    )

    candidates = sorted((build_dir / "lib" / "Release").glob("libzmq*.lib"))
    built_library = next((candidate for candidate in candidates if candidate.name.startswith("libzmq")), None)
    if built_library is None:
        raise RuntimeError(f"libzmq build did not produce a static library under {build_dir / 'lib' / 'Release'}")

    bundle_include.mkdir(parents=True, exist_ok=True)
    bundle_lib_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_dir / "include" / "zmq.h", bundled_header)
    shutil.copy2(source_dir / "include" / "zmq_utils.h", bundled_utils_header)
    shutil.copy2(built_library, bundled_library)
    build_stamp_path.write_text(build_stamp, encoding="utf-8", newline="\n")
    context.log(f"prepared bundled libzmq at {bundle_root.relative_to(context.source_root)}")
    return bundled_library


def generate_pyzmq_c_source(context) -> str:
    generated_path = pyzmq_generated_c_path(context)
    generated_path.parent.mkdir(parents=True, exist_ok=True)
    cython_target = _ensure_pyzmq_cython(context)
    env = os.environ.copy()
    env["PYTHONNOUSERSITE"] = "1"
    env["PYTHONPATH"] = str(cython_target)
    command = [
        sys.executable,
        "-S",
        "-m",
        "cython",
        "--output-file",
        str(generated_path),
        "--module-name",
        "zmq.backend.cython._zmq",
        str(source_path(context, "Lib/zmq/backend/cython/_zmq.py")),
    ]
    display = subprocess.list2cmdline([str(part) for part in command])
    context.log(f"RUN {display}")
    subprocess.run(
        command,
        cwd=str(context.source_root),
        check=True,
        timeout=60 * 10,
        env=env,
    )
    return generated_path.relative_to(context.source_root).as_posix()


def prepare_pyzmq_project(context) -> None:
    ensure_libsodium_source(context)
    ensure_libzmq_source(context)
    generated_source = generate_pyzmq_c_source(context)
    bundle_include_dir = _msbuild_path(
        pyzmq_bundle_include_dir(context).relative_to(context.source_root).as_posix()
    )
    write_source_text(
        context,
        f"PCbuild/{PYZMQ_PROJECT_NAME}.vcxproj",
        _render_pyzmq_project(generated_source, bundle_include_dir),
    )


def stage_pyzmq_libraries(context) -> None:
    output_dir = get_pcbuild_output_dir(context.source_root, context.platform)
    output_dir.mkdir(parents=True, exist_ok=True)
    for source in (ensure_static_libsodium(context), ensure_static_libzmq(context)):
        if source.name == "libsodium.lib":
            destination = output_dir / "libsodium.lib"
        else:
            destination = output_dir / "libzmq-static.lib"
        shutil.copy2(source, destination)
        context.log(f"staged {destination.relative_to(context.source_root)} from {source.relative_to(context.source_root)}")


LIBRARY_INTEGRATION = pypi_library(
    name="pyzmq",
    project_name="pyzmq",
    source_mapping={
        "zmq": "Lib/zmq",
        "CMakeLists.txt": "pyzmq_builtin/CMakeLists.txt",
    },
    python_packages=["zmq"],
    verification_imports=[
        "zmq",
        "zmq.backend.cython._zmq",
    ],
    static_library_projects_release_x64=[
        f"{PYZMQ_PROJECT_NAME}.vcxproj",
    ],
    native_static_projects=[
        {
            "project": f"{PYZMQ_PROJECT_NAME}.vcxproj",
            "guid": PYZMQ_PROJECT_GUID,
        }
    ],
    builtin_module_registrations=[
        {
            "name": "zmq.backend.cython._zmq",
            "pyinit": "PyInit__zmq",
        }
    ],
    python_link_dependencies_release_x64=[
        f"{PYZMQ_PROJECT_NAME}.lib",
        "libzmq-static.lib",
        "libsodium.lib",
        "Advapi32.lib",
        "ws2_32.lib",
        "Iphlpapi.lib",
        "Rpcrt4.lib",
    ],
    prepare_source_hooks=[prepare_pyzmq_project],
    pre_build_hooks=[stage_pyzmq_libraries],
    verification_steps=[
        inline_verification_step(
            "pyzmq-smoke",
            r"""
import asyncio
import importlib.util

import zmq
import zmq.asyncio
from zmq.utils import z85

assert importlib.util.find_spec("zmq.backend.cython._zmq").origin == "built-in"
assert zmq.has("curve"), "CURVE support should be enabled"
assert not zmq.has("ipc"), "Windows pyzmq static build should disable IPC with select poller"

payload = b"0123456789abcdef"
encoded = z85.encode(payload)
assert z85.decode(encoded) == payload

context = zmq.Context()
left = context.socket(zmq.PAIR)
right = context.socket(zmq.PAIR)
endpoint = "inproc://staticpython-pyzmq-sync"
left.bind(endpoint)
right.connect(endpoint)
poller = zmq.Poller()
poller.register(right, zmq.POLLIN)
left.send_multipart([b"alpha", b"beta"])
events = dict(poller.poll(1000))
assert events.get(right) == zmq.POLLIN
assert right.recv_multipart() == [b"alpha", b"beta"]
frame = zmq.Frame(b"frame-data")
assert bytes(frame) == b"frame-data"
assert right.getsockopt(zmq.TYPE) == zmq.PAIR
left.close(0)
right.close(0)
context.term()

async def _probe_asyncio():
    actx = zmq.asyncio.Context()
    async_left = actx.socket(zmq.PAIR)
    async_right = actx.socket(zmq.PAIR)
    async_endpoint = "inproc://staticpython-pyzmq-async"
    async_left.bind(async_endpoint)
    async_right.connect(async_endpoint)
    await async_left.send_json({"answer": 42})
    data = await async_right.recv_json()
    assert data == {"answer": 42}
    async_left.close(0)
    async_right.close(0)
    actx.term()

asyncio.run(_probe_asyncio())
""",
            timeout=600,
        )
    ],
)
