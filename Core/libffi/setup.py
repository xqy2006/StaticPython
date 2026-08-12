from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from libs import LibraryIntegration
from tools import (
    download_first_available,
    ensure_direct_child,
    ensure_tool,
    extract_source_archive,
    find_direct_child,
    get_pcbuild_output_dir,
    iter_item_definition_link_nodes,
    load_msbuild_project,
    merge_msbuild_semicolon_list,
    platform_output_dir_name,
    remove_msbuild_items,
    remove_msbuild_targets,
    run,
    save_msbuild_project,
    set_or_create_property,
)


ARCHIVE_URL_TEMPLATES = [
    "https://github.com/libffi/libffi/releases/download/v{version}/libffi-{version}.tar.gz",
    "https://codeload.github.com/libffi/libffi/tar.gz/refs/tags/v{version}",
    "https://github.com/libffi/libffi/archive/refs/tags/v{version}.tar.gz",
]
COMMON_SOURCES = [
    "src/prep_cif.c",
    "src/types.c",
    "src/raw_api.c",
    "src/java_raw_api.c",
    "src/closures.c",
    "src/tramp.c",
]
X64_SOURCES = [
    "src/x86/ffiw64.c",
]
X64_ASM_SOURCE = "src/x86/win64_intel.S"


def detect_cpython_libffi_version(context) -> str:
    files = [
        context.source_root / "PCbuild" / "python.props",
        context.source_root / "PCbuild" / "get_externals.bat",
        context.source_root / "PCbuild" / "libffi.props",
    ]
    pattern = re.compile(r"libffi-([0-9]+(?:\.[0-9]+)+)", flags=re.IGNORECASE)
    matches: list[str] = []
    for path in files:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for match in pattern.finditer(text):
            version = match.group(1).rstrip("\\/\"'<>")
            if version not in matches:
                matches.append(version)

    if not matches:
        raise RuntimeError(
            "could not detect the libffi version required by this CPython tree. "
            "Expected to find a token like libffi-3.4.4 in PCbuild/python.props or get_externals.bat."
        )
    if len(matches) > 1:
        context.log(f"multiple libffi versions were mentioned; using {matches[0]} from CPython metadata")
    return matches[0]


def libffi_source_dir(context, version: str) -> Path:
    return context.source_root / "externals" / f"libffi-{version}"


def libffi_archive_path(context, version: str) -> Path:
    return context.download_cache_root / "libffi" / f"libffi-{version}.tar.gz"


def libffi_archive_urls(version: str) -> list[str]:
    return [template.format(version=version) for template in ARCHIVE_URL_TEMPLATES]


def ensure_libffi_source(context, version: str) -> Path:
    source_dir = libffi_source_dir(context, version)
    if (source_dir / "include" / "ffi.h.in").exists() and (source_dir / "src" / "x86" / "ffiw64.c").exists():
        context.log(f"using existing libffi source at {source_dir.relative_to(context.source_root)}")
        return source_dir

    archive_path = libffi_archive_path(context, version)
    used_source = download_first_available(context.log, libffi_archive_urls(version), archive_path)
    source_dir.parent.mkdir(parents=True, exist_ok=True)
    extract_source_archive(context.log, archive_path, source_dir.parent, final_name=source_dir.name)
    if not (source_dir / "include" / "ffi.h.in").exists():
        raise RuntimeError(f"downloaded libffi source is missing include/ffi.h.in: {source_dir}")
    context.log(f"materialized libffi {version} from {used_source} to {source_dir.relative_to(context.source_root)}")
    return source_dir


def libffi_output_dir(context, version: str) -> Path:
    return libffi_source_dir(context, version) / platform_output_dir_name(context.platform)


def generate_libffi_ffi_h(source_dir: Path, include_dir: Path, version: str) -> None:
    text = (source_dir / "include" / "ffi.h.in").read_text(encoding="utf-8")
    replacements = {
        "@VERSION@": version,
        "@TARGET@": "X86_WIN64",
        "@HAVE_LONG_DOUBLE@": "0",
        "@FFI_EXEC_TRAMPOLINE_TABLE@": "0",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    include_dir.mkdir(parents=True, exist_ok=True)
    (include_dir / "ffi.h").write_text(text, encoding="utf-8", newline="\n")


def generate_libffi_fficonfig_h(source_dir: Path, include_dir: Path, version: str) -> None:
    text = (source_dir / "fficonfig.h.in").read_text(encoding="utf-8")
    replacements = {
        "HAVE_ALLOCA": "1",
        "HAVE_AS_X86_PCREL": "1",
        "HAVE_INTTYPES_H": "1",
        "HAVE_STDINT_H": "1",
        "HAVE_STDIO_H": "1",
        "HAVE_STDLIB_H": "1",
        "HAVE_STRING_H": "1",
        "HAVE_SYS_STAT_H": "1",
        "HAVE_SYS_TYPES_H": "1",
        "LT_OBJDIR": "\".libs/\"",
        "PACKAGE": "\"libffi\"",
        "PACKAGE_BUGREPORT": "\"http://github.com/libffi/libffi/issues\"",
        "PACKAGE_NAME": "\"libffi\"",
        "PACKAGE_STRING": f"\"libffi {version}\"",
        "PACKAGE_TARNAME": "\"libffi\"",
        "PACKAGE_URL": "\"\"",
        "PACKAGE_VERSION": f"\"{version}\"",
        "SIZEOF_DOUBLE": "8",
        "SIZEOF_LONG_DOUBLE": "8",
        "SIZEOF_SIZE_T": "8",
        "STDC_HEADERS": "1",
        "VERSION": f"\"{version}\"",
    }
    for name, value in replacements.items():
        text = re.sub(rf"^#undef {re.escape(name)}$", f"#define {name} {value}", text, flags=re.MULTILINE)
    text = re.sub(r"^#undef ([A-Za-z_][A-Za-z0-9_]*)$", r"/* #undef \1 */", text, flags=re.MULTILINE)
    include_dir.mkdir(parents=True, exist_ok=True)
    (include_dir / "fficonfig.h").write_text(text, encoding="utf-8", newline="\n")


def prepare_libffi_headers(source_dir: Path, output_dir: Path, version: str) -> None:
    include_dir = output_dir / "include"
    include_dir.mkdir(parents=True, exist_ok=True)
    generate_libffi_ffi_h(source_dir, include_dir, version)
    generate_libffi_fficonfig_h(source_dir, include_dir, version)
    shutil.copy2(source_dir / "src" / "x86" / "ffitarget.h", include_dir / "ffitarget.h")


def libffi_compile_definitions(context) -> list[str]:
    if context.platform != "x64":
        raise RuntimeError(f"unsupported libffi static build platform: {context.platform}")
    return [
        "FFI_BUILDING",
        "X86_WIN64",
        "_CRT_SECURE_NO_WARNINGS",
        "_CRT_NONSTDC_NO_DEPRECATE",
        "_WIN64",
    ]


def libffi_include_args(source_dir: Path, output_dir: Path) -> list[str]:
    return [
        f"/I{output_dir / 'include'}",
        f"/I{source_dir / 'include'}",
        f"/I{source_dir / 'src'}",
        f"/I{source_dir / 'src' / 'x86'}",
    ]


def compile_libffi_c_source(context, source_dir: Path, output_dir: Path, source_rel: str, definitions: list[str]) -> Path:
    obj_dir = output_dir / "obj"
    obj_dir.mkdir(parents=True, exist_ok=True)
    source = source_dir / source_rel
    object_name = source_rel.replace("/", "_").replace("\\", "_")
    obj = obj_dir / f"{Path(object_name).stem}.obj"
    cmd = [
        "cl",
        "/nologo",
        "/c",
        "/O2",
        "/MT",
        "/GS-",
        "/wd4244",
        "/wd4267",
        "/wd4996",
        *[f"/D{name}" for name in definitions],
        *libffi_include_args(source_dir, output_dir),
        f"/Fo{obj}",
        str(source),
    ]
    run(context.log, cmd, cwd=source_dir)
    return obj


def preprocess_libffi_asm(context, source_dir: Path, output_dir: Path, definitions: list[str]) -> Path:
    asm_source = source_dir / X64_ASM_SOURCE
    preprocessed = output_dir / "obj" / "win64_intel.asm"
    preprocessed.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "cl",
        "/nologo",
        "/EP",
        "/TC",
        *[f"/D{name}" for name in definitions],
        *libffi_include_args(source_dir, output_dir),
        str(asm_source),
    ]
    display = subprocess.list2cmdline(cmd)
    context.log(f"RUN {display} > {preprocessed}")
    with preprocessed.open("w", encoding="utf-8", newline="\n") as out_file:
        subprocess.run(cmd, cwd=str(source_dir), stdout=out_file, check=True)
    return preprocessed


def assemble_libffi_x64(context, output_dir: Path, preprocessed: Path) -> Path:
    obj = output_dir / "obj" / "win64_intel.obj"
    run(context.log, ["ml64", "/nologo", "/c", f"/Fo{obj}", str(preprocessed)], cwd=preprocessed.parent)
    return obj


def patch_libffi_props(context) -> None:
    path = context.source_root / "PCbuild" / "libffi.props"
    if not path.exists():
        context.log("skip libffi.props patch because the file does not exist")
        return

    tree, root = load_msbuild_project(path)
    for link in iter_item_definition_link_nodes(root):
        library_dirs = find_direct_child(link, "AdditionalLibraryDirectories")
        if library_dirs is None:
            library_dirs = ensure_direct_child(link, "AdditionalLibraryDirectories")
        library_dirs.text = merge_msbuild_semicolon_list(
            library_dirs.text,
            ["$(libffiOutDir)"],
            "%(AdditionalLibraryDirectories)",
        )

        dependencies = find_direct_child(link, "AdditionalDependencies")
        if dependencies is None:
            dependencies = ensure_direct_child(link, "AdditionalDependencies")
        current = dependencies.text or ""
        current = current.replace("libffi-8.lib", "ffi.lib")
        dependencies.text = merge_msbuild_semicolon_list(
            current,
            ["ffi.lib"],
            "%(AdditionalDependencies)",
        )

    remove_msbuild_items(root, "_LIBFFIDLL")
    remove_msbuild_targets(root, {"_CopyLIBFFIDLL", "_CleanLIBFFIDLL"})
    save_msbuild_project(path, tree)


def patch_python_props_for_static_libffi(context) -> None:
    path = context.source_root / "PCbuild" / "python.props"
    if not path.exists():
        return

    tree, root = load_msbuild_project(path)
    libffi_version = detect_cpython_libffi_version(context)
    out_dir = f"$(ExternalsDir)libffi-{libffi_version}\\{platform_output_dir_name(context.platform)}\\"
    set_or_create_property(root, "libffiOutDir", out_dir)
    set_or_create_property(root, "libffiIncludeDir", r"$(libffiOutDir)include")
    save_msbuild_project(path, tree)


def patch_libffi_build_files(context) -> None:
    patch_libffi_props(context)
    patch_python_props_for_static_libffi(context)


def ensure_static_libffi(context) -> None:
    if not (context.source_root / "PCbuild" / "_ctypes.vcxproj").exists():
        return

    libffi_version = detect_cpython_libffi_version(context)
    source_dir = ensure_libffi_source(context, libffi_version)
    output_dir = libffi_output_dir(context, libffi_version)
    required = [
        output_dir / "ffi.lib",
        output_dir / "include" / "ffi.h",
        output_dir / "include" / "fficonfig.h",
        output_dir / "include" / "ffitarget.h",
    ]
    if all(path.exists() for path in required):
        context.log(f"using existing static libffi {libffi_version} at {output_dir.relative_to(context.source_root)}")
        return

    ensure_tool("cl")
    ensure_tool("ml64")
    ensure_tool("lib")
    prepare_libffi_headers(source_dir, output_dir, libffi_version)
    definitions = libffi_compile_definitions(context)
    objects = [
        compile_libffi_c_source(context, source_dir, output_dir, source, definitions)
        for source in [*COMMON_SOURCES, *X64_SOURCES]
    ]
    preprocessed = preprocess_libffi_asm(context, source_dir, output_dir, definitions)
    objects.append(assemble_libffi_x64(context, output_dir, preprocessed))

    library_path = output_dir / "ffi.lib"
    run(context.log, ["lib", "/nologo", f"/OUT:{library_path}", *[str(obj) for obj in objects]], cwd=source_dir)

    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("libffi static build did not produce expected files:\n" + "\n".join(missing))


def stage_static_libffi_library(context) -> None:
    libffi_version = detect_cpython_libffi_version(context)
    source = libffi_output_dir(context, libffi_version) / "ffi.lib"
    if not source.exists():
        raise RuntimeError(f"static libffi library is missing: {source}")
    output_dir = get_pcbuild_output_dir(context.source_root, context.platform)
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "ffi.lib"
    shutil.copy2(source, destination)
    context.log(f"staged {destination.relative_to(context.source_root)} from {source.relative_to(context.source_root)}")


def prepare_static_libffi(context) -> None:
    ensure_static_libffi(context)
    stage_static_libffi_library(context)


LIBRARY_INTEGRATION = LibraryIntegration(
    name="libffi",
    pre_patch_hooks=[patch_libffi_build_files],
    pre_build_hooks=[prepare_static_libffi],
)
