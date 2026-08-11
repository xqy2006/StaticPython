from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packaging.version import InvalidVersion, Version

from libs import (
    _extract_archive,
    _find_cached_pypi_archive,
    _normalized_project_name,
    _resolve_extracted_root,
    _resolve_source_entry,
    _select_pypi_file,
    load_integrations,
)


RUNTIME_RESOURCE_SUFFIXES = {
    ".babel",
    ".bin",
    ".bnf",
    ".cfg",
    ".conf",
    ".crt",
    ".css",
    ".csv",
    ".dat",
    ".db",
    ".dtd",
    ".gif",
    ".gz",
    ".htm",
    ".html",
    ".ico",
    ".ini",
    ".ipynb",
    ".j2",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".key",
    ".lark",
    ".map",
    ".mjs",
    ".mo",
    ".otf",
    ".pem",
    ".png",
    ".schema",
    ".svg",
    ".template",
    ".tex",
    ".tpl",
    ".ttf",
    ".txt",
    ".woff",
    ".woff2",
    ".xhtml",
    ".xml",
    ".xsl",
    ".yaml",
    ".yml",
}

NATIVE_OR_BUILD_SUFFIXES = {
    ".a",
    ".asm",
    ".bat",
    ".c",
    ".cc",
    ".cmd",
    ".cmake",
    ".cpp",
    ".cxx",
    ".def",
    ".dll",
    ".dylib",
    ".exp",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".in",
    ".lib",
    ".o",
    ".obj",
    ".pc",
    ".pxd",
    ".pxi",
    ".pyx",
    ".rc",
    ".sln",
    ".so",
    ".targets",
    ".vcxproj",
}

PACKAGING_OR_DOC_SUFFIXES = {
    ".authors",
    ".cfg",
    ".coveragerc",
    ".gitattributes",
    ".gitignore",
    ".license",
    ".lock",
    ".md",
    ".po",
    ".pot",
    ".rst",
    ".toml",
    ".tox",
    ".typed",
    ".whl",
    ".yaml",
    ".yml",
}

TYPE_OR_MARKER_FILES = {
    "py.typed",
}

PACKAGING_OR_DOC_NAMES = {
    "authors",
    "authors.rst",
    "changelog",
    "changelog.md",
    "changelog.rst",
    "changes",
    "changes.md",
    "changes.rst",
    "cmakelists.txt",
    "code_of_conduct.md",
    "contributing",
    "contributing.md",
    "contributing.rst",
    "copying",
    "copying.rst",
    "license",
    "license.md",
    "license.rst",
    "license.txt",
    "manifest.in",
    "notice",
    "notice.txt",
    "pkg-info",
    "pyproject.toml",
    "readme",
    "readme.md",
    "readme.rst",
    "readme.txt",
    ".readthedocs.yaml",
    "security.md",
    "setup.cfg",
    "setup.py",
    "tox.ini",
}

IGNORED_PARTS = {
    "__pycache__",
    ".git",
    ".github",
    ".hg",
    ".mypy_cache",
    ".pytest_cache",
    ".tox",
    ".agents",
    ".bcr",
    "benchmarks",
    "ci",
    "code_generators",
    "docs",
    "doc",
    "examples",
    "g3doc",
    "licenses",
    "misc",
    "scripts",
    "test",
    "test-examples",
    "test_data",
    "tests",
    "testing",
}

RESOURCE_PARENT_HINTS = {
    "data",
    "dataset",
    "datasets",
    "event_schemas",
    "grammar",
    "grammars",
    "kernelspec",
    "labextension",
    "locale-data",
    "models",
    "package_data",
    "resources",
    "schema",
    "schemas",
    "share",
    "specs",
    "static",
    "staging",
    "templates",
    "themes",
    "zoneinfo",
}


@dataclass(frozen=True)
class PyPISourceInfo:
    project_name: str
    normalized_name: str
    source_mapping: dict[str, str]


def normalized_relpath(path: str | Path) -> str:
    return str(path).replace("\\", "/").strip("/")


def log(message: str) -> None:
    print(f"[resource-scan] {message}", flush=True)


def parse_version(value: str) -> Version | None:
    try:
        return Version(value)
    except InvalidVersion:
        return None


def sort_version_dirs(paths: list[Path]) -> list[Path]:
    def key(path: Path) -> tuple[int, Version | str]:
        parsed = parse_version(path.name)
        if parsed is not None:
            return (0, parsed)
        return (1, path.name)

    return sorted(paths, key=key, reverse=True)


def read_config(path: Path, profile_name: str | None) -> tuple[str, dict[str, Any], dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    selected = profile_name or data.get("default_profile") or "full"
    profiles = data.get("profiles") or {}
    profile = profiles.get(selected)
    if not isinstance(profile, dict):
        raise RuntimeError(f"profile {selected!r} was not found in {path}")
    return selected, data, profile


def hook_closure_value(hook: object, name: str) -> Any:
    code = getattr(hook, "__code__", None)
    closure = getattr(hook, "__closure__", None)
    if code is None or closure is None:
        return None
    for freevar, cell in zip(code.co_freevars, closure):
        if freevar == name:
            return cell.cell_contents
    return None


def pypi_source_info(integration: object) -> PyPISourceInfo | None:
    hooks = getattr(integration, "prepare_source_hooks", [])
    if not hooks:
        return None
    hook = hooks[0]
    project_name = hook_closure_value(hook, "project_name")
    normalized_name = hook_closure_value(hook, "normalized")
    source_mapping = hook_closure_value(hook, "source_mapping")
    if not isinstance(project_name, str) or not isinstance(normalized_name, str) or not isinstance(source_mapping, dict):
        return None
    return PyPISourceInfo(
        project_name=project_name,
        normalized_name=normalized_name,
        source_mapping={str(key): str(value) for key, value in source_mapping.items()},
    )


def selected_cached_version(download_root: Path, normalized_name: str, release_version: str | None) -> str | None:
    project_root = download_root / "pypi" / normalized_name
    if not project_root.exists():
        return None
    if release_version and (project_root / release_version).exists():
        return release_version
    versions = [path for path in project_root.iterdir() if path.is_dir()]
    if not versions:
        return None
    return sort_version_dirs(versions)[0].name


def extracted_source_root(
    repo_root: Path,
    work_root: Path,
    info: PyPISourceInfo,
    release_version: str | None,
    target_version: Version,
    *,
    download_missing: bool,
) -> tuple[Path | None, str | None, str]:
    download_root = repo_root / "downloads"
    vendor_project_root = repo_root / ".vendor-stage" / "pypi" / info.normalized_name

    version = release_version
    if version is None:
        version = selected_cached_version(download_root, info.normalized_name, None)
    if version is None and vendor_project_root.exists():
        versions = [path for path in vendor_project_root.iterdir() if path.is_dir()]
        if versions:
            version = sort_version_dirs(versions)[0].name

    if version is not None:
        vendor_extracted = vendor_project_root / version / "extracted"
        if vendor_extracted.exists():
            return _resolve_extracted_root(vendor_extracted), version, "vendor-stage"

    archive_path: Path | None = None
    if version is not None:
        archive_path = _find_cached_pypi_archive(
            download_root,
            info.normalized_name,
            version,
            target_version,
        )

    if archive_path is None and download_missing:
        version, file_info = _select_pypi_file(info.project_name, target_version, release_version)
        filename = file_info["filename"]
        archive_path = download_root / "pypi" / info.normalized_name / version / filename
        if not archive_path.exists():
            from urllib.request import urlretrieve

            archive_path.parent.mkdir(parents=True, exist_ok=True)
            log(f"downloading {info.project_name} {version} for resource scan")
            urlretrieve(file_info["url"], archive_path)

    if archive_path is None:
        return None, version, "missing-cache"

    version = archive_path.parent.name
    extract_root = work_root / "pypi" / info.normalized_name / version / "extracted"
    return _extract_archive(archive_path, extract_root), version, "downloads"


def file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


def should_ignore_by_parts(parts: tuple[str, ...]) -> bool:
    lowered = {part.lower() for part in parts}
    return bool(lowered & IGNORED_PARTS) or any(part.endswith((".egg-info", ".dist-info")) for part in lowered)


def is_packaging_or_doc(path: Path, destination: str) -> bool:
    name = path.name.lower()
    suffix = path.suffix.lower()
    if name in TYPE_OR_MARKER_FILES or suffix == ".pyi":
        return True
    if name in PACKAGING_OR_DOC_NAMES:
        return True
    if suffix in PACKAGING_OR_DOC_SUFFIXES and (not destination.startswith("Lib/") or suffix in {".po", ".pot"}):
        return True
    return False


def is_runtime_resource(path: Path, destination: str) -> bool:
    suffix = path.suffix.lower()
    if destination.startswith("Lib/"):
        if suffix in RUNTIME_RESOURCE_SUFFIXES:
            return True
        if suffix == "" and "zoneinfo" in {part.lower() for part in Path(destination).parts}:
            return True
    if destination.startswith(("share/", "etc/")) and suffix in RUNTIME_RESOURCE_SUFFIXES:
        return True
    return False


def static_setup_markers(setup_text: str) -> bool:
    lowered = setup_text.lower()
    return any(marker in lowered for marker in ("_staticpython", "_static_", "embedded", "embed_"))


def handled_reason(destination: str, source_rel: str, setup_text: str, integration: object) -> str | None:
    if not static_setup_markers(setup_text):
        return None

    normalized_destination = destination.replace("\\", "/")
    normalized_source = source_rel.replace("\\", "/")
    name = Path(normalized_destination).name
    parent_names = [part for part in Path(normalized_destination).parts[:-1]]
    destination_parts = Path(normalized_destination).parts

    probes = {
        normalized_destination,
        normalized_source,
        normalized_destination.removeprefix("Lib/"),
        normalized_source.removeprefix("Lib/"),
        name,
    }
    for probe in sorted(probes, key=len, reverse=True):
        if probe and probe in setup_text:
            return f"setup references {probe!r}"

    lowered = setup_text.lower()
    for parent in parent_names:
        parent_lower = parent.lower()
        if parent_lower in RESOURCE_PARENT_HINTS and parent_lower in lowered:
            return f"setup references resource directory {parent!r}"

    if "rglob" in lowered or "glob" in lowered:
        suffix = Path(normalized_destination).suffix.lower()
        if suffix and (f"*{suffix}" in lowered or repr(suffix) in lowered or f'"{suffix}"' in lowered):
            return f"setup scans resources with suffix {suffix!r}"
        for index, part in enumerate(destination_parts):
            part_lower = part.lower()
            if part_lower not in RESOURCE_PARENT_HINTS:
                continue
            suffix = "/" + "/".join(destination_parts[index:])
            if suffix in normalized_destination and part_lower in lowered:
                return f"setup scans resource directory {part!r}"

    materialized = [
        normalized_relpath(path)
        for path in getattr(integration, "materialized_paths", [])
        if Path(path).name.lower().startswith(("_staticpython", "_static_"))
    ]
    if materialized:
        for parent in parent_names:
            parent_lower = parent.lower()
            if parent_lower in RESOURCE_PARENT_HINTS and parent_lower in lowered:
                return "integration declares generated static resource module"
    return None


def classify_resource(path: Path, destination: str, source_rel: str, setup_text: str, integration: object) -> tuple[str, str]:
    parts = tuple(part.lower() for part in Path(destination).parts)
    suffix = path.suffix.lower()
    if should_ignore_by_parts(parts):
        return "ignored", "test/doc/cache/metadata tree"
    if is_packaging_or_doc(path, destination):
        return "ignored", "packaging, docs, or typing marker"
    if suffix in NATIVE_OR_BUILD_SUFFIXES or not destination.startswith(("Lib/", "share/", "etc/")):
        return "build_only", "native or build-time source"
    if not is_runtime_resource(path, destination):
        return "ignored", "not a known runtime resource type"

    reason = handled_reason(destination, source_rel, setup_text, integration)
    if reason is not None:
        return "handled", reason
    return "needs_handling", "runtime resource has no detected inline/access-point handler"


def iter_mapped_files(extracted_root: Path, source_mapping: dict[str, str]) -> list[tuple[Path, str, str]]:
    files: list[tuple[Path, str, str]] = []
    for selector, target_rel in sorted(source_mapping.items()):
        try:
            source_path = _resolve_source_entry(extracted_root, selector)
        except Exception as exc:
            files.append((Path(f"<missing:{selector}:{exc}>"), selector, normalized_relpath(target_rel)))
            continue
        target = normalized_relpath(target_rel)
        if source_path.is_file():
            files.append((source_path, source_path.relative_to(extracted_root).as_posix(), target))
            continue
        for path in sorted(source_path.rglob("*")):
            if not path.is_file():
                continue
            rel_inside = path.relative_to(source_path).as_posix()
            destination = normalized_relpath(Path(target) / rel_inside)
            source_rel = path.relative_to(extracted_root).as_posix()
            files.append((path, source_rel, destination))
    return files


def scan_integration(
    integration: object,
    repo_root: Path,
    work_root: Path,
    target_version: Version,
    *,
    download_missing: bool,
    max_examples: int,
) -> dict[str, Any]:
    name = getattr(integration, "name", "<unknown>")
    setup_path = repo_root / "Lib" / str(name) / "setup.py"
    setup_text = setup_path.read_text(encoding="utf-8") if setup_path.exists() else ""
    info = pypi_source_info(integration)
    if info is None:
        return {
            "name": name,
            "status": "scan_failed",
            "error": "could not introspect pypi source mapping from prepare hook",
            "counts": {},
            "resources": [],
        }

    extracted_root, resolved_version, cache_source = extracted_source_root(
        repo_root,
        work_root,
        info,
        getattr(integration, "release_version", None),
        target_version,
        download_missing=download_missing,
    )
    if extracted_root is None:
        return {
            "name": name,
            "project_name": info.project_name,
            "normalized_project_name": info.normalized_name,
            "version": resolved_version,
            "cache_source": cache_source,
            "status": "missing_cache",
            "error": "source cache not found; rerun build or pass --download-missing",
            "counts": {},
            "resources": [],
        }

    records: list[dict[str, Any]] = []
    counts: Counter[str] = Counter()
    total_non_python = 0
    total_size = 0
    missing_sources: list[str] = []
    for path, source_rel, destination in iter_mapped_files(extracted_root, info.source_mapping):
        if str(path).startswith("<missing:"):
            missing_sources.append(str(path))
            continue
        if path.suffix.lower() == ".py":
            continue
        total_non_python += 1
        total_size += file_size(path)
        status, reason = classify_resource(path, destination, source_rel, setup_text, integration)
        counts[status] += 1
        records.append(
            {
                "status": status,
                "reason": reason,
                "source": source_rel,
                "destination": destination,
                "suffix": path.suffix.lower(),
                "size": file_size(path),
            }
        )

    order = {"needs_handling": 0, "handled": 1, "build_only": 2, "ignored": 3}
    records.sort(key=lambda item: (order.get(item["status"], 9), item["destination"]))
    return {
        "name": name,
        "project_name": info.project_name,
        "normalized_project_name": info.normalized_name,
        "version": resolved_version,
        "cache_source": cache_source,
        "extracted_root": str(extracted_root),
        "status": "ok" if not missing_sources else "partial",
        "missing_sources": missing_sources,
        "counts": dict(sorted(counts.items())),
        "total_non_python_files": total_non_python,
        "total_non_python_size": total_size,
        "resources": records,
        "examples": {
            key: [item for item in records if item["status"] == key][:max_examples]
            for key in ("needs_handling", "handled", "build_only", "ignored")
        },
    }


def summarize_markdown(report: dict[str, Any], *, max_examples: int) -> str:
    lines: list[str] = []
    summary = report["summary"]
    lines.append("# StaticPython Library Resource Scan")
    lines.append("")
    lines.append(f"- Profile: `{report['profile']}`")
    lines.append(f"- Python target: `{report['target_version']}`")
    lines.append(f"- Libraries scanned: `{summary['libraries_scanned']}`")
    lines.append(f"- Runtime resources handled: `{summary['handled']}`")
    lines.append(f"- Runtime resources needing handling: `{summary['needs_handling']}`")
    lines.append(f"- Build/native non-Python files: `{summary['build_only']}`")
    lines.append(f"- Ignored non-runtime files: `{summary['ignored']}`")
    lines.append("")
    lines.append("## Libraries With Pending Runtime Resources")
    lines.append("")
    pending = [item for item in report["integrations"] if item.get("counts", {}).get("needs_handling")]
    if not pending:
        lines.append("No pending runtime resources were detected.")
    for item in pending:
        counts = item["counts"]
        lines.append(
            f"### {item['name']} {item.get('version') or ''} "
            f"(needs {counts.get('needs_handling', 0)}, handled {counts.get('handled', 0)})"
        )
        for resource in item["examples"]["needs_handling"][:max_examples]:
            lines.append(
                f"- `{resource['destination']}` from `{resource['source']}` "
                f"({resource['size']} bytes): {resource['reason']}"
            )
        lines.append("")
    lines.append("## Per-Library Counts")
    lines.append("")
    lines.append("| library | version | handled | needs | build-only | ignored | non-py total |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for item in report["integrations"]:
        counts = item.get("counts", {})
        lines.append(
            f"| `{item['name']}` | `{item.get('version') or ''}` | "
            f"{counts.get('handled', 0)} | {counts.get('needs_handling', 0)} | "
            f"{counts.get('build_only', 0)} | {counts.get('ignored', 0)} | "
            f"{item.get('total_non_python_files', 0)} |"
        )
    lines.append("")
    return "\n".join(lines)


def parse_libraries(values: list[str] | None) -> str | list[str]:
    if not values:
        return "all"
    names: list[str] = []
    for value in values:
        names.extend(part for part in re.split(r"[,\s]+", value.strip()) if part)
    return names or "all"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan downloaded library source caches for non-Python runtime resources."
    )
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config.json")
    parser.add_argument("--profile")
    parser.add_argument("--python-version", default="3.13.2")
    parser.add_argument("--libraries", nargs="*", help="Optional library names; defaults to the selected profile.")
    parser.add_argument("--work-root", type=Path, default=REPO_ROOT / ".tmp" / "library-resource-scan-work")
    parser.add_argument("--json", type=Path, default=REPO_ROOT / ".tmp" / "library-resource-scan.json")
    parser.add_argument("--markdown", type=Path, default=REPO_ROOT / ".tmp" / "library-resource-scan.md")
    parser.add_argument("--download-missing", action="store_true")
    parser.add_argument("--max-examples", type=int, default=25)
    parser.add_argument("--fail-on-needs", action="store_true")
    args = parser.parse_args(argv)

    repo_root = args.repo_root.resolve()
    config_path = args.config if args.config.is_absolute() else repo_root / args.config
    profile_name, config, profile = read_config(config_path, args.profile)
    target_version = Version(args.python_version)
    selected_libraries = parse_libraries(args.libraries)
    if selected_libraries == "all":
        selected_libraries = profile.get("third_party_libraries", "all")
    version_overrides = profile.get("third_party_library_version_overrides")

    integrations = load_integrations(
        repo_root / "Lib",
        selected_libraries,
        target_version=target_version,
        version_overrides=version_overrides,
        library_catalog=profile.get(
            "third_party_library_catalog",
            config.get("third_party_library_catalog"),
        ),
    )
    args.work_root.mkdir(parents=True, exist_ok=True)
    results = []
    totals: Counter[str] = Counter()
    for index, integration in enumerate(integrations, start=1):
        log(f"[{index}/{len(integrations)}] scanning {integration.name}")
        result = scan_integration(
            integration,
            repo_root,
            args.work_root,
            target_version,
            download_missing=args.download_missing,
            max_examples=args.max_examples,
        )
        results.append(result)
        totals.update(result.get("counts", {}))

    report = {
        "profile": profile_name,
        "target_version": str(target_version),
        "summary": {
            "libraries_scanned": len(results),
            "handled": totals.get("handled", 0),
            "needs_handling": totals.get("needs_handling", 0),
            "build_only": totals.get("build_only", 0),
            "ignored": totals.get("ignored", 0),
            "missing_cache": sum(1 for item in results if item.get("status") == "missing_cache"),
            "scan_failed": sum(1 for item in results if item.get("status") == "scan_failed"),
        },
        "integrations": results,
    }

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    args.markdown.parent.mkdir(parents=True, exist_ok=True)
    args.markdown.write_text(
        summarize_markdown(report, max_examples=args.max_examples),
        encoding="utf-8",
        newline="\n",
    )
    log(f"wrote {args.json}")
    log(f"wrote {args.markdown}")
    log(
        "summary: "
        f"handled={report['summary']['handled']}, "
        f"needs={report['summary']['needs_handling']}, "
        f"build_only={report['summary']['build_only']}, "
        f"ignored={report['summary']['ignored']}"
    )
    if args.fail_on_needs and report["summary"]["needs_handling"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
