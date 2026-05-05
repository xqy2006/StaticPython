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
    "https://github.com/openssl/openssl/archive/refs/tags/openssl-{version}.tar.gz",
    "https://www.openssl.org/source/openssl-{version}.tar.gz",
]
STATIC_DIR_NAME = "openssl-static"


def detect_cpython_openssl_version(context) -> str:
    files = [
        context.source_root / "PCbuild" / "python.props",
        context.source_root / "PCbuild" / "get_externals.bat",
        context.source_root / "PCbuild" / "openssl.props",
    ]
    pattern = re.compile(r"openssl-(?!bin-)([0-9][0-9A-Za-z._-]*)", flags=re.IGNORECASE)
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
            "could not detect the OpenSSL version required by this CPython tree. "
            "Expected to find a token like openssl-3.0.19 in PCbuild/python.props or get_externals.bat."
        )
    if len(matches) > 1:
        context.log(f"multiple OpenSSL source versions were mentioned; using {matches[0]} from CPython metadata")
    return matches[0]


def openssl_source_dir(context, version: str) -> Path:
    return context.source_root / "externals" / f"openssl-{version}"


def openssl_archive_path(context, version: str) -> Path:
    return context.download_cache_root / "openssl" / f"openssl-{version}.tar.gz"


def openssl_archive_urls(version: str) -> list[str]:
    return [template.format(version=version) for template in ARCHIVE_URL_TEMPLATES]


def ensure_openssl_source(context, version: str) -> Path:
    source_dir = openssl_source_dir(context, version)
    if (source_dir / "Configure").exists():
        context.log(f"using existing OpenSSL source at {source_dir.relative_to(context.source_root)}")
        return source_dir

    archive_path = openssl_archive_path(context, version)
    used_source = download_first_available(context.log, openssl_archive_urls(version), archive_path)
    source_dir.parent.mkdir(parents=True, exist_ok=True)
    extract_source_archive(context.log, archive_path, source_dir.parent, final_name=source_dir.name)
    if not (source_dir / "Configure").exists():
        raise RuntimeError(f"downloaded OpenSSL source is missing Configure: {source_dir}")
    context.log(f"materialized OpenSSL {version} from {used_source} to {source_dir.relative_to(context.source_root)}")
    return source_dir


def openssl_platform(platform: str) -> str:
    mapping = {
        "x64": "VC-WIN64A",
        "Win32": "VC-WIN32",
        "ARM64": "VC-WIN64-ARM",
    }
    if platform not in mapping:
        raise RuntimeError(f"unsupported OpenSSL static build platform: {platform}")
    return mapping[platform]


def openssl_static_output_dir(context) -> Path:
    return context.source_root / "externals" / STATIC_DIR_NAME / platform_output_dir_name(context.platform)


def openssl_static_library_path(output_dir: Path, library_name: str) -> Path | None:
    candidates = [
        output_dir / library_name,
        output_dir / "lib" / library_name,
    ]
    return next((candidate for candidate in candidates if candidate.exists()), None)


def normalize_static_openssl_layout(output_dir: Path) -> None:
    for library_name in ("libcrypto.lib", "libssl.lib"):
        source = openssl_static_library_path(output_dir, library_name)
        target = output_dir / library_name
        if source is not None and source != target:
            shutil.copy2(source, target)


def validate_windows_perl(perl: str) -> None:
    probe = (
        "use Config; "
        "die qq(non-windows path perl\\n) unless $Config::Config{path_sep} eq q(;); "
        "use Win32; use IPC::Cmd; print qq(ok\\n);"
    )
    completed = subprocess.run(
        [perl, "-e", probe],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "OpenSSL static build requires a Windows-native Perl on PATH "
            "(for example Strawberry Perl or ActivePerl). "
            f"The detected perl failed validation:\n{completed.stderr or completed.stdout}"
        )


def require_windows_perl_for_static_openssl() -> str:
    perl = shutil.which("perl")
    if perl is None:
        raise RuntimeError(
            "OpenSSL static build requires perl on PATH. Install Strawberry Perl or ActivePerl "
            "and rerun from VS Developer PowerShell."
        )
    validate_windows_perl(perl)
    return perl


def patch_openssl_props(context) -> None:
    path = context.source_root / "PCbuild" / "openssl.props"
    if not path.exists():
        context.log("skip openssl.props patch because the file does not exist")
        return

    tree, root = load_msbuild_project(path)
    for link in iter_item_definition_link_nodes(root):
        dependencies = find_direct_child(link, "AdditionalDependencies")
        if dependencies is None:
            dependencies = ensure_direct_child(link, "AdditionalDependencies")
        dependencies.text = merge_msbuild_semicolon_list(
            dependencies.text,
            ["ws2_32.lib", "libcrypto.lib", "libssl.lib"],
            "%(AdditionalDependencies)",
        )

    remove_msbuild_targets(root, {"_CopySSLDLL", "_CleanSSLDLL"})
    remove_msbuild_items(root, "_SSLDLL")
    save_msbuild_project(path, tree)


def patch_python_props_for_static_openssl(context) -> None:
    path = context.source_root / "PCbuild" / "python.props"
    tree, root = load_msbuild_project(path)
    out_dir = f"$(ExternalsDir){STATIC_DIR_NAME}\\{platform_output_dir_name(context.platform)}\\"
    set_or_create_property(root, "opensslOutDir", out_dir)
    set_or_create_property(root, "opensslIncludeDir", r"$(opensslOutDir)include")
    save_msbuild_project(path, tree)


def patch_openssl_build_files(context) -> None:
    patch_openssl_props(context)
    patch_python_props_for_static_openssl(context)


def ensure_static_openssl(context) -> None:
    has_ssl_project = (context.source_root / "PCbuild" / "_ssl.vcxproj").exists()
    has_hashlib_project = (context.source_root / "PCbuild" / "_hashlib.vcxproj").exists()
    if not has_ssl_project and not has_hashlib_project:
        return

    openssl_version = detect_cpython_openssl_version(context)
    output_dir = openssl_static_output_dir(context)
    required = [
        output_dir / "libcrypto.lib",
        output_dir / "libssl.lib",
        output_dir / "include" / "openssl" / "ssl.h",
        output_dir / "include" / "applink.c",
    ]
    normalize_static_openssl_layout(output_dir)
    if all(path.exists() for path in required):
        context.log(f"using existing static OpenSSL {openssl_version} at {output_dir.relative_to(context.source_root)}")
        return

    perl = require_windows_perl_for_static_openssl()
    validate_windows_perl(perl)
    ensure_tool("nmake")

    source_dir = ensure_openssl_source(context, openssl_version)
    output_dir.mkdir(parents=True, exist_ok=True)
    if (source_dir / "makefile").exists():
        run(context.log, ["nmake", "clean"], cwd=source_dir)

    configure_cmd = [
        perl,
        "Configure",
        openssl_platform(context.platform),
        "no-shared",
        "no-tests",
        "no-makedepend",
        "no-asm",
        "no-uplink",
        f"--prefix={output_dir}",
        f"--openssldir={output_dir / 'ssl'}",
    ]
    context.log(f"building static OpenSSL {openssl_version} for {context.platform}")
    run(context.log, configure_cmd, cwd=source_dir, timeout=60 * 10)
    run(context.log, ["nmake", "build_libs"], cwd=source_dir, timeout=60 * 45)
    run(context.log, ["nmake", "install_sw"], cwd=source_dir, timeout=60 * 20)
    normalize_static_openssl_layout(output_dir)

    applink_source = source_dir / "ms" / "applink.c"
    applink_target = output_dir / "include" / "applink.c"
    if applink_source.exists() and not applink_target.exists():
        applink_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(applink_source, applink_target)

    missing = [str(path) for path in required if not path.exists()]
    if missing:
        raise RuntimeError("OpenSSL static build did not produce expected files:\n" + "\n".join(missing))


def stage_static_openssl_libraries(context) -> None:
    output_dir = get_pcbuild_output_dir(context.source_root, context.platform)
    output_dir.mkdir(parents=True, exist_ok=True)
    openssl_dir = openssl_static_output_dir(context)
    normalize_static_openssl_layout(openssl_dir)
    for name in ("libcrypto.lib", "libssl.lib"):
        source = openssl_static_library_path(openssl_dir, name)
        if source is None:
            raise RuntimeError(f"static OpenSSL library is missing from {openssl_dir}: {name}")
        destination = output_dir / name
        shutil.copy2(source, destination)
        context.log(f"staged {destination.relative_to(context.source_root)} from {source.relative_to(context.source_root)}")


def prepare_static_openssl(context) -> None:
    ensure_static_openssl(context)
    stage_static_openssl_libraries(context)


LIBRARY_INTEGRATION = LibraryIntegration(
    name="openssl",
    pre_patch_hooks=[patch_openssl_build_files],
    pre_build_hooks=[prepare_static_openssl],
)
