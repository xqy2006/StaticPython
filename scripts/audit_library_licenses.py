from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

import build
import libs
from packaging.licenses import canonicalize_license_expression
from packaging.version import Version

from build_pack_shard_config import PACK_FAMILIES, build_shard_config
from resolve_pack_versions import load_pack_version_lock


def _safe_name(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z_.-]+", "-", value).strip("-")


def _cpython_archive_urls(version: str) -> list[str]:
    return [
        f"https://github.com/python/cpython/archive/refs/tags/v{version}.zip",
        f"https://codeload.github.com/python/cpython/zip/refs/tags/v{version}",
    ]


def _download_cpython_source(version: str, root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    archive_path = root / f"cpython-v{version}.zip"
    attempts = 5
    for attempt in range(1, attempts + 1):
        try:
            used_url = build.download_first_available(
                _cpython_archive_urls(version),
                archive_path,
            )
            source_root = build.extract_zip_archive(
                archive_path,
                root,
                reuse_existing=True,
            )
            print(f"[library-license-audit] downloaded CPython {version} from {used_url}")
            return source_root
        except Exception as exc:
            if attempt == attempts:
                raise
            wait_seconds = min(60, attempt * 10)
            print(
                f"[library-license-audit] CPython {version} download failed on "
                f"attempt {attempt}/{attempts}: {type(exc).__name__}: {exc}; "
                f"retrying in {wait_seconds}s"
            )
            time.sleep(wait_seconds)
    raise RuntimeError(f"failed to download CPython {version}")


def audit_integration_licenses(
    source_root: Path,
    integrations: list[libs.LibraryIntegration],
) -> dict:
    source_root = source_root.resolve()
    records: list[dict] = []
    failures: list[dict] = []
    for integration in integrations:
        integration_failures: list[str] = []
        expression = (integration.license_expression or "").strip()
        if not expression:
            integration_failures.append("license expression is missing")
        else:
            try:
                canonicalize_license_expression(expression)
            except Exception as exc:
                integration_failures.append(
                    f"license expression is not valid SPDX: {type(exc).__name__}: {exc}"
                )

        license_records: list[dict] = []
        if not integration.license_files:
            integration_failures.append("license/notice files are missing")
        for relative in integration.license_files:
            candidate = (source_root / relative).resolve()
            try:
                candidate.relative_to(source_root)
            except ValueError:
                integration_failures.append(
                    f"license path escapes the source root: {relative}"
                )
                continue
            if not candidate.is_file():
                integration_failures.append(f"license file does not exist: {relative}")
                continue
            payload = candidate.read_bytes()
            if not payload:
                integration_failures.append(f"license file is empty: {relative}")
                continue
            license_records.append(
                {
                    "path": relative,
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size": len(payload),
                }
            )

        record = {
            "name": integration.name,
            "project_name": integration.project_name,
            "version": integration.release_version,
            "source_provider": integration.source_provider,
            "expression": expression or None,
            "files": license_records,
            "status": "failed" if integration_failures else "passed",
        }
        records.append(record)
        if integration_failures:
            failures.append(
                {
                    "name": integration.name,
                    "version": integration.release_version,
                    "errors": integration_failures,
                }
            )

    return {
        "schema_version": 1,
        "status": "failed" if failures else "passed",
        "integration_count": len(records),
        "failure_count": len(failures),
        "integrations": records,
        "failures": failures,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Prepare the current StaticPython library shard and audit license metadata."
    )
    parser.add_argument("--cpython-version", required=True)
    parser.add_argument(
        "--family",
        required=True,
        choices=[family for family in PACK_FAMILIES if family != "other"],
    )
    parser.add_argument("--work-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--version-lock", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    work_root = args.work_root.resolve()
    if work_root.exists():
        libs._remove_tree(work_root)
    work_root.mkdir(parents=True)

    build.DOWNLOAD_ROOT = work_root / "downloads"
    build.WORK_CACHE_ROOT = work_root / "vendor-stage"
    libs.DOWNLOAD_CACHE_ROOT = work_root / "metadata"
    build.DOWNLOAD_ROOT.mkdir(parents=True)
    build.WORK_CACHE_ROOT.mkdir(parents=True)
    libs.DOWNLOAD_CACHE_ROOT.mkdir(parents=True)

    config = build.load_config()
    _shard_config, selected_libraries = build_shard_config(config, args.family)
    _profile_name, profile = build.resolve_profile(config, "full")
    catalog = build.profile_library_catalog(
        config,
        profile,
        "third_party_library_catalog",
    )

    source_root = _download_cpython_source(
        args.cpython_version,
        work_root / "cpython",
    )
    version_info, version_mm, version_full = build.parse_cpython_version(source_root)
    version_lock = load_pack_version_lock(
        args.version_lock,
        target_python_version=version_full,
    )
    integrations = libs.load_integrations(
        build.LIB_PATCH_ROOT,
        selected_libraries,
        target_version=Version(version_full),
        version_overrides=version_lock["versions"],
        library_catalog=catalog,
    )
    context = build.make_library_hook_context(
        source_root,
        version_info,
        version_mm,
        version_full,
        "Release",
        "x64",
    )
    libs.run_prepare_source_hooks(integrations, context)

    summary = audit_integration_licenses(source_root, integrations)
    summary.update(
        {
            "cpython_version": version_full,
            "family": args.family,
            "selected_libraries": selected_libraries,
            "version_lock_sha256": hashlib.sha256(
                args.version_lock.read_bytes()
            ).hexdigest(),
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )

    print(
        f"[library-license-audit] CPython {version_full} / {args.family}: "
        f"{summary['integration_count'] - summary['failure_count']} passed, "
        f"{summary['failure_count']} failed"
    )
    for failure in summary["failures"]:
        print(
            json.dumps(
                failure,
                ensure_ascii=False,
                sort_keys=True,
            )
        )
    if summary["failure_count"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
