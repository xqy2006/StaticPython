from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

from packaging.version import Version

from libs import pypi_library, source_path, write_source_text
from tools import (
    download_first_available,
    ensure_tool,
    extract_source_archive,
    get_pcbuild_output_dir,
    platform_output_dir_name,
    run,
)


PYZMQ_MODERN_PROJECT_GUID = "{A2E3F81C-84B6-4A6D-905D-4D70D728A0A1}"
PYZMQ_MODERN_PROJECT_NAME = "zmq.backend.cython._zmq"
PYZMQ_LEGACY_LIBZMQ_PROJECT_NAME = "pyzmq.libzmq-static"
PYZMQ_CYTHON_REQUIREMENT = "Cython>=3.0.0,<4.0.0"

PYZMQ_SYSTEM_LIBRARIES = [
    "Advapi32.lib",
    "ws2_32.lib",
    "Iphlpapi.lib",
    "Rpcrt4.lib",
]

PYZMQ_LEGACY_EXTENSION_SOURCES = [
    ("zmq.backend.cython.constants", "Lib/zmq/backend/cython/constants.c"),
    ("zmq.backend.cython.error", "Lib/zmq/backend/cython/error.c"),
    ("zmq.backend.cython._poll", "Lib/zmq/backend/cython/_poll.c"),
    ("zmq.backend.cython.utils", "Lib/zmq/backend/cython/utils.c"),
    ("zmq.backend.cython.context", "Lib/zmq/backend/cython/context.c"),
    ("zmq.backend.cython.message", "Lib/zmq/backend/cython/message.c"),
    ("zmq.backend.cython.socket", "Lib/zmq/backend/cython/socket.c"),
    ("zmq.backend.cython._device", "Lib/zmq/backend/cython/_device.c"),
    ("zmq.backend.cython._proxy_steerable", "Lib/zmq/backend/cython/_proxy_steerable.c"),
    ("zmq.backend.cython._version", "Lib/zmq/backend/cython/_version.c"),
    ("zmq.devices.monitoredqueue", "Lib/zmq/devices/monitoredqueue.c"),
]

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


def _object_name(source: str) -> str:
    return "$(IntDir)" + source.replace("/", "_").replace("\\", "_") + ".obj"


def _project_guid_for_name(name: str) -> str:
    project_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"https://staticpython.dev/pyzmq/{name}")
    return "{" + str(project_uuid).upper() + "}"


def _compile_items(sources: list[str]) -> str:
    blocks = []
    for source in sources:
        blocks.append(
            "\n".join(
                [
                    f'    <ClCompile Include="{_msbuild_path(source)}">',
                    f"      <ObjectFileName>{_object_name(source)}</ObjectFileName>",
                    "    </ClCompile>",
                ]
            )
        )
    return "\n".join(blocks)


def _render_static_library_project(
    name: str,
    guid: str,
    sources: list[str],
    include_dirs: list[str],
    defines: list[str],
    *,
    disable_warnings: str = "4100;4127;4244;4267;4996",
    additional_options: str = "/bigobj",
    exception_handling: bool = False,
) -> str:
    include_text = ";".join(_msbuild_path(path) for path in include_dirs)
    define_text = ";".join([*defines, "%(PreprocessorDefinitions)"])
    exception_block = "      <ExceptionHandling>Sync</ExceptionHandling>\n" if exception_handling else ""
    root_namespace = re.sub(r"[^A-Za-z0-9_]", "_", name)
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
    <TargetName>{name}</TargetName>
    <TargetExt>.lib</TargetExt>
  </PropertyGroup>
  <ItemDefinitionGroup>
    <ClCompile>
      <AdditionalIncludeDirectories>{include_text};%(AdditionalIncludeDirectories)</AdditionalIncludeDirectories>
      <PreprocessorDefinitions>{define_text}</PreprocessorDefinitions>
      <DisableSpecificWarnings>{disable_warnings};%(DisableSpecificWarnings)</DisableSpecificWarnings>
{exception_block}      <AdditionalOptions>{additional_options} %(AdditionalOptions)</AdditionalOptions>
      <RuntimeLibrary Condition="'$(Configuration)|$(Platform)'=='Release|x64'">MultiThreaded</RuntimeLibrary>
    </ClCompile>
  </ItemDefinitionGroup>
  <ItemGroup>
{_compile_items(sources)}
  </ItemGroup>
  <Import Project="$(VCTargetsPath)\\Microsoft.Cpp.targets" />
</Project>
"""


def pyzmq_build_metadata_path(context) -> Path:
    return source_path(context, "pyzmq_builtin/build-metadata.txt")


def _read_pyzmq_build_metadata(context) -> str:
    return pyzmq_build_metadata_path(context).read_text(encoding="utf-8")


def _pyzmq_native_build_mode(context) -> str | None:
    if source_path(context, "Lib/zmq/backend/cython/_zmq.py").exists():
        return "modern"
    if any(source_path(context, relative).exists() for _, relative in PYZMQ_LEGACY_EXTENSION_SOURCES):
        return "legacy"
    return None


def _version_from_pyzmq_metadata(
    context,
    variable_name: str,
    *,
    allow_missing: bool = False,
) -> str | None:
    text = _read_pyzmq_build_metadata(context)
    match = re.search(rf'set\({re.escape(variable_name)}\s+"([^"]+)"', text)
    legacy_names = {
        "PYZMQ_LIBSODIUM_VERSION": "LIBSODIUM_BUNDLED_VERSION",
        "PYZMQ_LIBZMQ_VERSION": "LIBZMQ_BUNDLED_VERSION",
    }
    if match is None and variable_name in legacy_names:
        match = re.search(rf'set\({re.escape(legacy_names[variable_name])}\s+"([^"]+)"', text)
    if match is not None:
        return match.group(1)

    if variable_name == "PYZMQ_LIBZMQ_VERSION":
        tuple_match = re.search(r"bundled_version\s*=\s*\(([^)]*)\)", text)
        if tuple_match is not None:
            parts = [part.strip() for part in tuple_match.group(1).split(",") if part.strip()]
            numeric = [str(int(part)) for part in parts[:3]]
            if numeric:
                return ".".join(numeric)
        string_match = re.search(r'bundled_version\s*=\s*["\']([^"\']+)["\']', text)
        if string_match is not None:
            return string_match.group(1)

    if variable_name == "PYZMQ_LIBSODIUM_VERSION":
        string_match = re.search(r'bundled_libsodium_version\s*=\s*["\']([^"\']+)["\']', text)
        if string_match is not None:
            return string_match.group(1)

    if allow_missing:
        return None
    raise RuntimeError(f"could not detect {variable_name} from {pyzmq_build_metadata_path(context)}")


def libsodium_version(context) -> str:
    version = _version_from_pyzmq_metadata(context, "PYZMQ_LIBSODIUM_VERSION")
    assert version is not None
    return version


def libzmq_version(context) -> str:
    version = _version_from_pyzmq_metadata(context, "PYZMQ_LIBZMQ_VERSION")
    assert version is not None
    return version


def pyzmq_version(context) -> str:
    version_path = source_path(context, "Lib/zmq/sugar/version.py")
    text = version_path.read_text(encoding="utf-8")
    direct_match = re.search(r'__version__(?::\s*str)?\s*=\s*["\']([^"\']+)["\']', text)
    if direct_match is not None:
        raw_version = direct_match.group(1)
        raw_version = re.sub(r"\.(a|b|rc)(?=\d)", r"\1", raw_version)
        return str(Version(raw_version))

    def _require_int(name: str) -> str:
        match = re.search(rf"^{re.escape(name)}\s*=\s*(\d+)\s*$", text, flags=re.MULTILINE)
        if match is None:
            raise RuntimeError(f"could not detect {name} from {version_path}")
        return match.group(1)

    major = _require_int("VERSION_MAJOR")
    minor = _require_int("VERSION_MINOR")
    patch = _require_int("VERSION_PATCH")
    extra_match = re.search(r'^VERSION_EXTRA\s*=\s*["\']([^"\']*)["\']\s*$', text, flags=re.MULTILINE)
    extra = extra_match.group(1).lstrip(".") if extra_match is not None else ""
    raw_version = f"{major}.{minor}.{patch}{extra}"
    return str(Version(raw_version))


def pyzmq_archive_path(context) -> Path:
    version = pyzmq_version(context)
    archive_root = context.download_cache_root / "pypi" / "pyzmq" / version
    candidates: list[Path] = []
    for pattern in ("*.tar.gz", "*.tgz", "*.zip", "*.tar"):
        candidates.extend(sorted(archive_root.glob(pattern)))
    if candidates:
        return candidates[0]
    raise RuntimeError(f"could not find cached pyzmq source archive under {archive_root}")


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
    version_tag = f"py{sys.version_info.major}{sys.version_info.minor}"
    return context.download_cache_root / "build-tools" / "pyzmq-cython" / version_tag


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


def legacy_pyzmq_buildutils_dir(context) -> Path:
    return source_path(context, "pyzmq_builtin/buildutils")


def legacy_pyzmq_bundled_dir(context) -> Path:
    return source_path(context, "pyzmq_builtin/bundled")


def legacy_libzmq_root(context) -> Path:
    return legacy_pyzmq_bundled_dir(context) / "zeromq"


def _ensure_legacy_platform_hpp(context) -> None:
    platform_hpp = legacy_libzmq_root(context) / "src" / "platform.hpp"
    if platform_hpp.exists():
        return

    candidate_sources = [
        legacy_pyzmq_buildutils_dir(context) / "include_win32" / "platform.hpp",
        legacy_libzmq_root(context) / "builds" / "msvc" / "platform.hpp",
    ]
    for candidate in candidate_sources:
        if not candidate.exists():
            continue
        platform_hpp.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(candidate, platform_hpp)
        context.log(
            f"staged {platform_hpp.relative_to(context.source_root)} from {candidate.relative_to(context.source_root)}"
        )
        return

    searched = ", ".join(str(path) for path in candidate_sources)
    raise RuntimeError(f"could not find a legacy pyzmq platform.hpp source; checked {searched}")


def ensure_legacy_pyzmq_support_files(context) -> None:
    buildutils_dir = legacy_pyzmq_buildutils_dir(context)
    bundled_dir = legacy_pyzmq_bundled_dir(context)
    if buildutils_dir.exists() and bundled_dir.exists():
        _ensure_legacy_platform_hpp(context)
        return

    archive_path = pyzmq_archive_path(context)
    extract_root = context.work_cache_root / "pypi" / "pyzmq" / pyzmq_version(context) / "legacy-support"
    extracted_root = extract_source_archive(
        context.log,
        archive_path,
        extract_root.parent,
        final_name=extract_root.name,
    )
    extracted_buildutils = extracted_root / "buildutils"
    extracted_bundled = extracted_root / "bundled"
    if not extracted_buildutils.exists():
        raise RuntimeError(f"legacy pyzmq archive is missing buildutils/: {archive_path}")
    if not extracted_bundled.exists():
        raise RuntimeError(f"legacy pyzmq archive is missing bundled/: {archive_path}")

    _copy_directory_contents(extracted_buildutils, buildutils_dir)
    _copy_directory_contents(extracted_bundled, bundled_dir)
    context.log(
        f"restored legacy pyzmq support files from {archive_path.name} into "
        f"{buildutils_dir.relative_to(context.source_root).parent}"
    )
    _ensure_legacy_platform_hpp(context)


def _discover_legacy_pyzmq_extensions(context) -> list[dict[str, str]]:
    extensions: list[dict[str, str]] = []
    for module_name, source_relative in PYZMQ_LEGACY_EXTENSION_SOURCES:
        if not source_path(context, source_relative).exists():
            continue
        extensions.append(
            {
                "name": module_name,
                "source": source_relative,
                "project": f"{module_name}.vcxproj",
                "guid": _project_guid_for_name(module_name),
                "pyinit": f"PyInit_{module_name.rsplit('.', 1)[1]}",
            }
        )
    return extensions


def _legacy_extension_include_dirs(context) -> list[str]:
    bundle_include = legacy_libzmq_root(context) / "include"
    return [
        "Lib/zmq/utils",
        bundle_include.relative_to(context.source_root).as_posix(),
    ]


def _legacy_extension_defines() -> list[str]:
    return [
        "Py_NO_ENABLE_SHARED",
        "ZMQ_STATIC",
        "_CRT_SECURE_NO_WARNINGS",
    ]


def _discover_legacy_libzmq_project_inputs(context) -> tuple[list[str], list[str], list[str]]:
    ensure_legacy_pyzmq_support_files(context)
    root = legacy_libzmq_root(context)
    source_root = context.source_root

    sources = [
        path.relative_to(source_root).as_posix()
        for path in sorted((root / "src").glob("*.cpp"))
        if not path.name.startswith(("ws_", "wss_"))
    ]
    if not sources:
        raise RuntimeError(f"legacy pyzmq bundled libzmq sources are missing under {root / 'src'}")

    include_dirs = [
        (root / "include").relative_to(source_root).as_posix(),
        (root / "src").relative_to(source_root).as_posix(),
    ]

    wepoll_source = root / "external" / "wepoll" / "wepoll.c"
    if wepoll_source.exists():
        sources.append(wepoll_source.relative_to(source_root).as_posix())

    tweetnacl_source_root = root / "tweetnacl" / "src"
    if tweetnacl_source_root.exists():
        include_dirs.extend(
            [
                tweetnacl_source_root.relative_to(source_root).as_posix(),
                (root / "tweetnacl" / "contrib" / "randombytes").relative_to(source_root).as_posix(),
            ]
        )
        sources.extend(
            path.relative_to(source_root).as_posix()
            for path in sorted(tweetnacl_source_root.glob("*.c"))
        )
        winrandom_source = root / "tweetnacl" / "contrib" / "randombytes" / "winrandom.c"
        if winrandom_source.exists():
            sources.append(winrandom_source.relative_to(source_root).as_posix())
    else:
        bundled_tweetnacl = root / "src" / "tweetnacl.c"
        if bundled_tweetnacl.exists():
            sources.append(bundled_tweetnacl.relative_to(source_root).as_posix())

    defines = [
        "Py_NO_ENABLE_SHARED",
        "_CRT_SECURE_NO_WARNINGS",
        "FD_SETSIZE=16384",
        "DLL_EXPORT=1",
        "ZMQ_HAVE_CURVE=1",
        "ZMQ_USE_TWEETNACL=1",
        "ZMQ_USE_SELECT=1",
    ]
    if Version(libzmq_version(context)) >= Version("4.3"):
        defines.extend(
            [
                "ZMQ_IOTHREADS_USE_SELECT=1",
                "ZMQ_POLL_BASED_ON_SELECT=1",
            ]
        )

    return sources, include_dirs, defines


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
        PYZMQ_MODERN_PROJECT_NAME,
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


def _pyzmq_generated_source_relative_path(context) -> str:
    return pyzmq_generated_c_path(context).relative_to(context.source_root).as_posix()


def _render_modern_pyzmq_project(generated_source: str, bundle_include_dir: str) -> str:
    return _render_static_library_project(
        PYZMQ_MODERN_PROJECT_NAME,
        PYZMQ_MODERN_PROJECT_GUID,
        [generated_source],
        [
            "Lib/zmq/utils",
            bundle_include_dir,
        ],
        [
            "Py_NO_ENABLE_SHARED",
            "ZMQ_STATIC",
            "SODIUM_STATIC",
            "_CRT_SECURE_NO_WARNINGS",
            "CYTHON_CLINE_IN_TRACEBACK=0",
        ],
    )


def _write_legacy_pyzmq_projects(context, legacy_extensions: list[dict[str, str]]) -> None:
    libzmq_sources, libzmq_include_dirs, libzmq_defines = _discover_legacy_libzmq_project_inputs(context)
    write_source_text(
        context,
        f"PCbuild/{PYZMQ_LEGACY_LIBZMQ_PROJECT_NAME}.vcxproj",
        _render_static_library_project(
            PYZMQ_LEGACY_LIBZMQ_PROJECT_NAME,
            _project_guid_for_name(PYZMQ_LEGACY_LIBZMQ_PROJECT_NAME),
            libzmq_sources,
            libzmq_include_dirs,
            libzmq_defines,
            exception_handling=True,
            additional_options="/bigobj /EHsc",
        ),
    )

    include_dirs = _legacy_extension_include_dirs(context)
    defines = _legacy_extension_defines()
    for extension in legacy_extensions:
        write_source_text(
            context,
            f"PCbuild/{extension['project']}",
            _render_static_library_project(
                extension["name"],
                extension["guid"],
                [extension["source"]],
                include_dirs,
                defines,
            ),
        )


def prepare_pyzmq_project(context) -> None:
    mode = _pyzmq_native_build_mode(context)
    if mode == "modern":
        _set_pyzmq_native_build_configuration("modern")
        generated_source = _pyzmq_generated_source_relative_path(context)
        bundle_include_dir = pyzmq_bundle_include_dir(context).relative_to(context.source_root).as_posix()
        write_source_text(
            context,
            f"PCbuild/{PYZMQ_MODERN_PROJECT_NAME}.vcxproj",
            _render_modern_pyzmq_project(generated_source, bundle_include_dir),
        )
        return

    if mode == "legacy":
        ensure_legacy_pyzmq_support_files(context)
        legacy_extensions = _discover_legacy_pyzmq_extensions(context)
        if not legacy_extensions:
            context.log("legacy pyzmq layout detected but no pre-generated extension sources were found")
            _set_pyzmq_native_build_configuration(None)
            return
        _set_pyzmq_native_build_configuration("legacy", legacy_extensions)
        _write_legacy_pyzmq_projects(context, legacy_extensions)
        return

    context.log("pyzmq native build disabled because no supported source layout was detected")
    _set_pyzmq_native_build_configuration(None)


def prepare_pyzmq_native_build(context) -> None:
    if _pyzmq_native_build_mode(context) != "modern":
        return
    ensure_libsodium_source(context)
    ensure_libzmq_source(context)
    generate_pyzmq_c_source(context)


def stage_pyzmq_libraries(context) -> None:
    if _pyzmq_native_build_mode(context) != "modern":
        return
    output_dir = get_pcbuild_output_dir(context.source_root, context.platform)
    output_dir.mkdir(parents=True, exist_ok=True)
    for source in (ensure_static_libsodium(context), ensure_static_libzmq(context)):
        if source.name == "libsodium.lib":
            destination = output_dir / "libsodium.lib"
        else:
            destination = output_dir / "libzmq-static.lib"
        shutil.copy2(source, destination)
        context.log(f"staged {destination.relative_to(context.source_root)} from {source.relative_to(context.source_root)}")


def _set_pyzmq_native_build_configuration(
    mode: str | None,
    legacy_extensions: list[dict[str, str]] | None = None,
) -> None:
    if mode == "modern":
        LIBRARY_INTEGRATION.static_library_projects_release_x64 = [f"{PYZMQ_MODERN_PROJECT_NAME}.vcxproj"]
        LIBRARY_INTEGRATION.native_static_projects = [
            {
                "project": f"{PYZMQ_MODERN_PROJECT_NAME}.vcxproj",
                "guid": PYZMQ_MODERN_PROJECT_GUID,
            }
        ]
        LIBRARY_INTEGRATION.builtin_module_registrations = [
            {
                "name": PYZMQ_MODERN_PROJECT_NAME,
                "pyinit": "PyInit__zmq",
            }
        ]
        LIBRARY_INTEGRATION.python_link_dependencies_release_x64 = [
            f"{PYZMQ_MODERN_PROJECT_NAME}.lib",
            "libzmq-static.lib",
            "libsodium.lib",
            *PYZMQ_SYSTEM_LIBRARIES,
        ]
        LIBRARY_INTEGRATION.pre_build_hooks = [prepare_pyzmq_native_build, stage_pyzmq_libraries]
        return

    if mode == "legacy":
        legacy_extensions = legacy_extensions or []
        static_projects = [extension["project"] for extension in legacy_extensions]
        static_projects.append(f"{PYZMQ_LEGACY_LIBZMQ_PROJECT_NAME}.vcxproj")
        LIBRARY_INTEGRATION.static_library_projects_release_x64 = static_projects
        LIBRARY_INTEGRATION.native_static_projects = [
            {
                "project": extension["project"],
                "guid": extension["guid"],
            }
            for extension in legacy_extensions
        ]
        LIBRARY_INTEGRATION.builtin_module_registrations = [
            {
                "name": extension["name"],
                "pyinit": extension["pyinit"],
            }
            for extension in legacy_extensions
        ]
        LIBRARY_INTEGRATION.python_link_dependencies_release_x64 = [
            *[f"{extension['name']}.lib" for extension in legacy_extensions],
            f"{PYZMQ_LEGACY_LIBZMQ_PROJECT_NAME}.lib",
            *PYZMQ_SYSTEM_LIBRARIES,
        ]
        LIBRARY_INTEGRATION.pre_build_hooks = []
        return

    LIBRARY_INTEGRATION.static_library_projects_release_x64 = []
    LIBRARY_INTEGRATION.native_static_projects = []
    LIBRARY_INTEGRATION.builtin_module_registrations = []
    LIBRARY_INTEGRATION.python_link_dependencies_release_x64 = []
    LIBRARY_INTEGRATION.pre_build_hooks = []


LIBRARY_INTEGRATION = pypi_library(
    name="pyzmq",
    project_name="pyzmq",
    source_mapping={
        "zmq": "Lib/zmq",
        "CMakeLists.txt || buildutils/bundle.py": "pyzmq_builtin/build-metadata.txt",
    },
    cleanup_paths=[
        "pyzmq_builtin/buildutils",
        "pyzmq_builtin/bundled",
    ],
    python_packages=["zmq"],
    static_library_projects_release_x64=[f"{PYZMQ_MODERN_PROJECT_NAME}.vcxproj"],
    native_static_projects=[
        {
            "project": f"{PYZMQ_MODERN_PROJECT_NAME}.vcxproj",
            "guid": PYZMQ_MODERN_PROJECT_GUID,
        }
    ],
    builtin_module_registrations=[
        {
            "name": PYZMQ_MODERN_PROJECT_NAME,
            "pyinit": "PyInit__zmq",
        }
    ],
    python_link_dependencies_release_x64=[
        f"{PYZMQ_MODERN_PROJECT_NAME}.lib",
        "libzmq-static.lib",
        "libsodium.lib",
        *PYZMQ_SYSTEM_LIBRARIES,
    ],
    prepare_source_hooks=[prepare_pyzmq_project],
    pre_build_hooks=[prepare_pyzmq_native_build, stage_pyzmq_libraries],
)
