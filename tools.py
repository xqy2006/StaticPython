from __future__ import annotations

import os
import shutil
import struct
import subprocess
import tarfile
import tempfile
import xml.etree.ElementTree as ET
from collections.abc import Callable
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import urlopen
from zipfile import ZipFile


WINDOWS_RESERVED_BASENAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    "CONIN$",
    "CONOUT$",
    *{f"COM{index}" for index in range(1, 10)},
    *{f"LPT{index}" for index in range(1, 10)},
}
MSBUILD_NS = "http://schemas.microsoft.com/developer/msbuild/2003"
MSBUILD_RELEASE_X64_CONDITION = "'$(Configuration)|$(Platform)'=='Release|x64'"
MSBUILD_TOOL_NAMES = {"msbuild", "msbuild.exe"}
MSVC_TOOL_NAMES = {"cl", "cl.exe", "lib", "lib.exe", "link", "link.exe"}
_RESOLVED_TOOLS: dict[str, str] = {}
_MSVC_ENV_READY = False
_MSVC_ENV_NAMES = {
    "DevEnvDir",
    "ExtensionSdkDir",
    "Framework40Version",
    "FrameworkDir",
    "FrameworkDir64",
    "FrameworkVersion",
    "FrameworkVersion64",
    "INCLUDE",
    "LIB",
    "LIBPATH",
    "NETFXSDKDir",
    "PATH",
    "Path",
    "PROCESSOR_ARCHITECTURE",
    "PROCESSOR_ARCHITEW6432",
    "UniversalCRTSdkDir",
    "UCRTVersion",
    "VCIDEInstallDir",
    "VCINSTALLDIR",
    "VCToolsInstallDir",
    "VCToolsRedistDir",
    "VCToolsVersion",
    "VSINSTALLDIR",
    "VSCMD_ARG_HOST_ARCH",
    "VSCMD_ARG_TGT_ARCH",
    "VSCMD_VER",
    "VisualStudioVersion",
    "WindowsLibPath",
    "WindowsSdkBinPath",
    "WindowsSdkDir",
    "WindowsSDKLibVersion",
    "WindowsSDKVersion",
    "WindowsSdkVerBinPath",
}

ET.register_namespace("", MSBUILD_NS)


def _existing_file(path: Path) -> str | None:
    if path.is_file():
        return str(path)
    return None


def _tool_cache_key(name: str) -> str:
    return Path(name).name.casefold()


def _tool_file_name(name: str) -> str:
    tool_name = Path(name).name
    if tool_name.casefold().endswith(".exe"):
        return tool_name
    return f"{tool_name}.exe"


def _path_contains(parent: Path) -> bool:
    target = str(parent).casefold()
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if entry and entry.casefold() == target:
            return True
    return False


def _prepend_path(parent: Path) -> None:
    if _path_contains(parent):
        return
    os.environ["PATH"] = str(parent) + os.pathsep + os.environ.get("PATH", "")


def _vswhere_installation_path() -> Path | None:
    for root_variable in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(root_variable)
        if not root:
            continue
        vswhere = Path(root) / "Microsoft Visual Studio" / "Installer" / "vswhere.exe"
        if not vswhere.is_file():
            continue
        try:
            result = subprocess.run(
                [
                    str(vswhere),
                    "-latest",
                    "-products",
                    "*",
                    "-requires",
                    "Microsoft.Component.MSBuild",
                    "-property",
                    "installationPath",
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=15,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if result.returncode != 0:
            continue
        for line in result.stdout.splitlines():
            stripped = line.strip()
            if stripped:
                return Path(stripped)
    return None


def _visual_studio_installation_candidates() -> list[Path]:
    candidates: list[Path] = []
    latest = _vswhere_installation_path()
    if latest is not None:
        candidates.append(latest)
    for root_variable in ("ProgramFiles(x86)", "ProgramFiles"):
        root = os.environ.get(root_variable)
        if not root:
            continue
        visual_studio_root = Path(root) / "Microsoft Visual Studio"
        for version in ("2022", "2019"):
            for edition in ("Enterprise", "Professional", "Community", "BuildTools"):
                candidates.append(visual_studio_root / version / edition)
    unique: list[Path] = []
    seen: set[str] = set()
    for path in candidates:
        key = str(path).casefold()
        if key in seen:
            continue
        seen.add(key)
        unique.append(path)
    return unique


def _version_key(path: Path) -> tuple[int, ...]:
    parts: list[int] = []
    for part in path.name.split("."):
        try:
            parts.append(int(part))
        except ValueError:
            parts.append(-1)
    return tuple(parts)


def _resolve_msbuild_exe() -> str | None:
    configured = os.environ.get("STATICPYTHON_MSBUILD")
    if configured:
        return _existing_file(Path(configured))

    for installation_path in _visual_studio_installation_candidates():
        for relative_path in (
            Path("MSBuild") / "Current" / "Bin" / "amd64" / "MSBuild.exe",
            Path("MSBuild") / "Current" / "Bin" / "MSBuild.exe",
        ):
            resolved = _existing_file(installation_path / relative_path)
            if resolved is not None:
                return resolved
    return shutil.which("msbuild") or shutil.which("MSBuild.exe")


def _resolve_msvc_tool_exe(name: str) -> str | None:
    file_name = _tool_file_name(name)
    for installation_path in _visual_studio_installation_candidates():
        msvc_root = installation_path / "VC" / "Tools" / "MSVC"
        if not msvc_root.is_dir():
            continue
        versions = sorted(
            (path for path in msvc_root.iterdir() if path.is_dir()),
            key=_version_key,
            reverse=True,
        )
        for version_root in versions:
            for relative_path in (
                Path("bin") / "HostX64" / "x64" / file_name,
                Path("bin") / "Hostx64" / "x64" / file_name,
                Path("bin") / "HostX86" / "x64" / file_name,
                Path("bin") / "Hostx86" / "x64" / file_name,
            ):
                resolved = _existing_file(version_root / relative_path)
                if resolved is not None:
                    return resolved
    return shutil.which(name)


def _vcvars64_bat() -> Path | None:
    for installation_path in _visual_studio_installation_candidates():
        candidate = installation_path / "VC" / "Auxiliary" / "Build" / "vcvars64.bat"
        if candidate.is_file():
            return candidate
    return None


def _is_msvc_env_name(name: str) -> bool:
    if name in _MSVC_ENV_NAMES:
        return True
    upper = name.upper()
    return upper.startswith("__VSCMD") or upper.startswith("VSCMD_")


def _set_environ(name: str, value: str) -> None:
    for existing in os.environ:
        if existing.casefold() == name.casefold():
            os.environ[existing] = value
            return
    os.environ[name] = value


def _ensure_windows_processor_architecture() -> None:
    if os.name != "nt":
        return
    architecture = os.environ.get("PROCESSOR_ARCHITECTURE")
    if architecture:
        return
    if struct.calcsize("P") * 8 == 64:
        _set_environ("PROCESSOR_ARCHITECTURE", "AMD64")


def _ensure_msvc_environment() -> None:
    global _MSVC_ENV_READY
    if _MSVC_ENV_READY:
        return

    _ensure_windows_processor_architecture()

    vcvars = _vcvars64_bat()
    if vcvars is None:
        _MSVC_ENV_READY = True
        return

    script_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile("w", suffix=".cmd", delete=False, encoding="utf-8", newline="\r\n") as script:
            script.write("@echo off\n")
            script.write(f'call "{vcvars}" >nul\n')
            script.write("if errorlevel 1 exit /b %errorlevel%\n")
            script.write("set\n")
            script_path = Path(script.name)
        result = subprocess.run(
            [
                "cmd.exe",
                "/d",
                "/c",
                str(script_path),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="mbcs",
            errors="replace",
            timeout=60,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise RuntimeError(f"failed to initialize VS x64 build environment from {vcvars}: {exc}") from exc
    finally:
        if script_path is not None:
            try:
                script_path.unlink()
            except OSError:
                pass

    if result.returncode != 0:
        raise RuntimeError(
            "failed to initialize VS x64 build environment from "
            f"{vcvars}\nstdout:\n{result.stdout[-4000:]}\nstderr:\n{result.stderr[-4000:]}"
        )

    for line in result.stdout.splitlines():
        if "=" not in line:
            continue
        name, value = line.split("=", 1)
        if _is_msvc_env_name(name):
            _set_environ(name, value)
    _MSVC_ENV_READY = True


def resolve_tool_exe(name: str) -> str:
    key = _tool_cache_key(name)
    cached = _RESOLVED_TOOLS.get(key)
    if cached is not None:
        return cached

    if Path(name).parent != Path("."):
        resolved = _existing_file(Path(name))
    elif key in MSBUILD_TOOL_NAMES:
        resolved = _resolve_msbuild_exe()
    elif key in MSVC_TOOL_NAMES:
        resolved = _resolve_msvc_tool_exe(name)
    else:
        resolved = shutil.which(name)

    if resolved is None:
        raise RuntimeError(
            f"required tool not found: {name}. Run this inside the VS2022 Developer PowerShell / DevShell."
        )
    _RESOLVED_TOOLS[key] = resolved
    if key in MSBUILD_TOOL_NAMES or key in MSVC_TOOL_NAMES:
        _ensure_msvc_environment()
    _prepend_path(Path(resolved).parent)
    return resolved


def _resolve_command(cmd: list[str]) -> list[str]:
    if not cmd:
        return cmd
    first = str(cmd[0])
    key = _tool_cache_key(first)
    if key not in MSBUILD_TOOL_NAMES and key not in MSVC_TOOL_NAMES:
        return cmd
    return [resolve_tool_exe(first), *cmd[1:]]


def run(log: Callable[[str], None], cmd: list[str], cwd: Path, *, timeout: float | None = None) -> None:
    resolved_cmd = _resolve_command(cmd)
    display = subprocess.list2cmdline([str(part) for part in resolved_cmd])
    log(f"RUN {display}")
    subprocess.run(resolved_cmd, cwd=str(cwd), check=True, timeout=timeout)


def ensure_tool(name: str) -> None:
    resolve_tool_exe(name)


def download_file(log: Callable[[str], None], url: str, destination: Path, *, force: bool = False) -> None:
    if destination.exists() and not force:
        log(f"using cached download {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    log(f"downloading {url}")
    temporary = Path(str(destination) + ".tmp")
    with urlopen(url) as response, temporary.open("wb") as out_file:
        shutil.copyfileobj(response, out_file)
    temporary.replace(destination)


def download_first_available(log: Callable[[str], None], urls: list[str], destination: Path) -> str:
    if destination.exists():
        log(f"using cached download {destination}")
        return str(destination)

    errors: list[str] = []
    for url in urls:
        try:
            download_file(log, url, destination, force=True)
            return url
        except (HTTPError, URLError, OSError) as exc:
            errors.append(f"{url}: {exc}")
            if destination.exists():
                destination.unlink()
            temporary = Path(str(destination) + ".tmp")
            if temporary.exists():
                temporary.unlink()
            log(f"download failed from {url}: {exc}")
    raise RuntimeError("all download sources failed:\n" + "\n".join(errors))


def archive_top_level_from_zip(archive: ZipFile) -> str:
    top_level = {name.split("/", 1)[0] for name in archive.namelist() if name and "/" in name}
    if len(top_level) != 1:
        raise RuntimeError("unexpected zip archive layout")
    return next(iter(top_level))


def archive_top_level_from_tar(archive: tarfile.TarFile) -> str:
    top_level = {name.split("/", 1)[0] for name in archive.getnames() if name and "/" in name}
    if len(top_level) != 1:
        raise RuntimeError("unexpected tar archive layout")
    return next(iter(top_level))


def is_windows_reserved_path(path: str) -> bool:
    normalized = path.replace("\\", "/")
    for part in normalized.split("/"):
        if not part or part in {".", ".."}:
            continue
        basename = part.split(".", 1)[0].rstrip(" ").upper()
        if basename in WINDOWS_RESERVED_BASENAMES:
            return True
    return False


def ensure_safe_archive_member(log: Callable[[str], None], destination_root: Path, member_name: str) -> bool:
    if is_windows_reserved_path(member_name):
        log(f"skip archive member with Windows reserved name: {member_name}")
        return False
    target = (destination_root / member_name).resolve()
    root = destination_root.resolve()
    if target != root and root not in target.parents:
        raise RuntimeError(f"archive member escapes destination: {member_name}")
    return True


def safe_extract_zip(log: Callable[[str], None], archive: ZipFile, destination_root: Path) -> None:
    for info in archive.infolist():
        if ensure_safe_archive_member(log, destination_root, info.filename):
            archive.extract(info, destination_root)


def safe_extract_tar(log: Callable[[str], None], archive: tarfile.TarFile, destination_root: Path) -> None:
    for member in archive.getmembers():
        if ensure_safe_archive_member(log, destination_root, member.name):
            archive.extract(member, destination_root)


def extract_source_archive(
    log: Callable[[str], None],
    archive_path: Path,
    destination_root: Path,
    *,
    final_name: str | None = None,
) -> Path:
    destination_root.mkdir(parents=True, exist_ok=True)
    suffixes = "".join(archive_path.suffixes).lower()
    if suffixes.endswith(".zip"):
        with ZipFile(archive_path) as archive:
            extracted_name = archive_top_level_from_zip(archive)
            extracted_root = destination_root / extracted_name
            if extracted_root.exists():
                shutil.rmtree(extracted_root)
            safe_extract_zip(log, archive, destination_root)
    elif suffixes.endswith((".tar.gz", ".tgz", ".tar")):
        mode = "r:gz" if suffixes.endswith((".tar.gz", ".tgz")) else "r:"
        with tarfile.open(archive_path, mode) as archive:
            extracted_name = archive_top_level_from_tar(archive)
            extracted_root = destination_root / extracted_name
            if extracted_root.exists():
                shutil.rmtree(extracted_root)
            safe_extract_tar(log, archive, destination_root)
    else:
        raise RuntimeError(f"unsupported source archive format: {archive_path}")

    if final_name is None or extracted_root.name == final_name:
        return extracted_root

    final_root = destination_root / final_name
    if final_root.exists():
        shutil.rmtree(final_root)
    extracted_root.rename(final_root)
    return final_root


def platform_output_dir_name(platform: str) -> str:
    return {
        "x64": "amd64",
        "Win32": "win32",
        "ARM64": "arm64",
        "ARM": "arm",
    }.get(platform, platform)


def get_pcbuild_output_dir(source_root: Path, platform: str) -> Path:
    return source_root / "PCbuild" / platform_output_dir_name(platform)


def msbuild_tag(name: str) -> str:
    return f"{{{MSBUILD_NS}}}{name}"


def load_msbuild_project(path: Path) -> tuple[ET.ElementTree, ET.Element]:
    parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
    tree = ET.parse(path, parser=parser)
    root = tree.getroot()
    if root.tag != msbuild_tag("Project"):
        raise RuntimeError(f"{path} is not an MSBuild project")
    return tree, root


def save_msbuild_project(path: Path, tree: ET.ElementTree) -> None:
    ET.indent(tree, space="  ")
    tree.write(path, encoding="utf-8", xml_declaration=True)


def _matches_condition(element: ET.Element, condition: str | None) -> bool:
    actual = element.get("Condition")
    if condition is None:
        return actual is None
    return actual == condition


def find_direct_child(parent: ET.Element, tag: str, *, condition: str | None = None) -> ET.Element | None:
    qname = msbuild_tag(tag)
    for child in parent:
        if child.tag != qname:
            continue
        if _matches_condition(child, condition):
            return child
    return None


def find_direct_children(parent: ET.Element, tag: str, *, condition: str | None = None) -> list[ET.Element]:
    qname = msbuild_tag(tag)
    return [child for child in parent if child.tag == qname and _matches_condition(child, condition)]


def ensure_direct_child(parent: ET.Element, tag: str, *, condition: str | None = None) -> ET.Element:
    child = find_direct_child(parent, tag, condition=condition)
    if child is not None:
        return child
    child = ET.Element(msbuild_tag(tag))
    if condition is not None:
        child.set("Condition", condition)
    parent.append(child)
    return child


def ensure_property_group(root: ET.Element, *, label: str | None = None) -> ET.Element:
    for child in root:
        if child.tag != msbuild_tag("PropertyGroup"):
            continue
        if label is None:
            if child.get("Label") is None and child.get("Condition") is None:
                return child
            continue
        if child.get("Label") == label:
            return child
    group = ET.Element(msbuild_tag("PropertyGroup"))
    if label is not None:
        group.set("Label", label)
    root.append(group)
    return group


def set_or_create_property(root: ET.Element, name: str, value: str) -> None:
    existing = next(root.iter(msbuild_tag(name)), None)
    if existing is not None:
        existing.text = value
        return
    child = ensure_direct_child(ensure_property_group(root), name)
    child.text = value


def iter_item_definition_link_nodes(root: ET.Element) -> list[ET.Element]:
    links: list[ET.Element] = []
    for group in root.iter(msbuild_tag("ItemDefinitionGroup")):
        link = find_direct_child(group, "Link")
        if link is not None:
            links.append(link)
    return links


def merge_msbuild_semicolon_list(current: str | None, additions: list[str], placeholder: str) -> str:
    values = [item for item in (current or "").split(";") if item]
    values = [item for item in values if item != placeholder]
    for addition in additions:
        if addition not in values:
            values.append(addition)
    values.append(placeholder)
    return ";".join(values)


def remove_msbuild_items(root: ET.Element, tag: str) -> None:
    qname = msbuild_tag(tag)
    for item_group in find_direct_children(root, "ItemGroup"):
        for child in list(item_group):
            if child.tag == qname:
                item_group.remove(child)


def remove_msbuild_targets(root: ET.Element, names: set[str]) -> None:
    for target in list(root.iter(msbuild_tag("Target"))):
        if target.get("Name") not in names:
            continue
        parent = next((candidate for candidate in root.iter() if target in list(candidate)), None)
        if parent is not None:
            parent.remove(target)
