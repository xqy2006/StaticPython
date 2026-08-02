from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Callable


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build
import libs


SCHEMA_VERSION = 1
TARGET_SERIES = {"3.11", "3.12", "3.13", "3.14", "3.15"}
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
PayloadLoader = Callable[[str], dict]


def _target_version(raw_version: str) -> libs.Version:
    version = libs.Version(raw_version)
    release = version.release
    if len(release) < 2 or f"{release[0]}.{release[1]}" not in TARGET_SERIES:
        raise ValueError(f"target Python must be in 3.11 through 3.15: {raw_version}")
    return version


def _minimum_version(integration: libs.LibraryIntegration) -> libs.Version | None:
    raw_version = integration.minimum_release_version
    if not raw_version:
        return None
    try:
        return libs.Version(raw_version)
    except libs.InvalidVersion as exc:
        raise RuntimeError(
            f"integration {integration.name} has invalid minimum_release_version {raw_version!r}"
        ) from exc


def _source_record(file_info: dict) -> dict:
    digests = file_info.get("digests")
    sha256 = digests.get("sha256") if isinstance(digests, dict) else None
    record = {
        "filename": file_info.get("filename"),
        "packagetype": file_info.get("packagetype"),
        "requires_python": file_info.get("requires_python"),
        "url": file_info.get("url"),
    }
    if isinstance(sha256, str) and sha256:
        record["sha256"] = sha256
    return record


def _applicable_files(files: list[dict], target_version: libs.Version) -> list[dict]:
    return [
        file_info
        for file_info in files
        if not file_info.get("yanked")
        and file_info.get("url")
        and libs._supports_target_python(file_info.get("requires_python"), target_version)
    ]


def pypi_library_contract(
    integration: libs.LibraryIntegration,
    payload: dict,
    target_versions: list[libs.Version],
) -> dict:
    releases = payload.get("releases")
    if not isinstance(releases, dict):
        raise RuntimeError(f"PyPI metadata for {integration.name} has no releases object")

    minimum_version = _minimum_version(integration)
    version_records: dict[str, dict] = {}
    for raw_version in reversed(libs._sorted_release_versions(releases)):
        parsed_version = libs.Version(raw_version)
        if minimum_version is not None and parsed_version < minimum_version:
            continue

        files = [
            file_info
            for file_info in releases.get(raw_version, [])
            if isinstance(file_info, dict) and not file_info.get("yanked") and file_info.get("url")
        ]
        # Yanked-only releases are outside the version contract.
        if not files:
            continue

        targets: dict[str, dict] = {}
        for target_version in target_versions:
            target_key = str(target_version)
            applicable = _applicable_files(files, target_version)
            if not applicable:
                targets[target_key] = {
                    "status": "not-applicable",
                    "reason": "all non-yanked artifacts exclude this Python version via Requires-Python",
                }
                continue

            # Historical files with no Requires-Python metadata must be tried on
            # every target. Do not inherit the latest project's requirement.
            compatible_sources = libs._compatible_pypi_files(
                applicable,
                project_requires_python=None,
                target_version=target_version,
            )
            verified_sources = [
                file_info
                for file_info in compatible_sources
                if SHA256_PATTERN.fullmatch(
                    str((file_info.get("digests") or {}).get("sha256", ""))
                )
            ]
            if verified_sources:
                targets[target_key] = {
                    "status": "candidate",
                    "source": _source_record(verified_sources[0]),
                }
            else:
                if compatible_sources:
                    reason = "compatible source artifacts have no verifiable SHA-256"
                else:
                    reason = (
                        "no non-yanked sdist or pure universal wheel; "
                        "native wheels are not static inputs"
                    )
                targets[target_key] = {
                    "status": "unbuildable",
                    "reason": reason,
                    "artifacts": sorted(
                        str(file_info.get("filename"))
                        for file_info in applicable
                        if file_info.get("filename")
                    ),
                }

        version_records[raw_version] = {"targets": targets}

    return {
        "project_name": integration.project_name or integration.name,
        "source_provider": integration.source_provider,
        "minimum_release_version": integration.minimum_release_version,
        "versions": version_records,
    }


def configured_library_contract(
    integration: libs.LibraryIntegration,
    target_versions: list[libs.Version],
) -> dict:
    raw_version = integration.release_version or integration.source_provider
    return {
        "project_name": integration.project_name or integration.name,
        "source_provider": integration.source_provider,
        "minimum_release_version": integration.minimum_release_version,
        "versions": {
            raw_version: {
                "targets": {
                    str(target_version): {
                        "status": "configured",
                        "reason": "non-PyPI source is pinned and is outside stable PyPI version discovery",
                        "source": {
                            "resolver": integration.source_resolver or integration.source_provider,
                        },
                    }
                    for target_version in target_versions
                }
            }
        },
    }


def _status_counts(libraries: dict[str, dict]) -> dict[str, int]:
    counts = {"candidate": 0, "configured": 0, "not-applicable": 0, "unbuildable": 0}
    for library in libraries.values():
        for version in library["versions"].values():
            for target in version["targets"].values():
                status = target["status"]
                counts[status] = counts.get(status, 0) + 1
    return counts


def _contract_sha256(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def validate_contract_integrity(payload: dict) -> None:
    if payload.get("schema_version") != SCHEMA_VERSION:
        raise RuntimeError(
            f"unsupported library contract schema: {payload.get('schema_version')!r}"
        )
    recorded = payload.get("contract_sha256")
    if not isinstance(recorded, str) or not SHA256_PATTERN.fullmatch(recorded):
        raise RuntimeError("library contract has no valid contract_sha256")
    canonical_payload = {
        key: value for key, value in payload.items() if key != "contract_sha256"
    }
    calculated = _contract_sha256(canonical_payload)
    if recorded.lower() != calculated:
        raise RuntimeError(
            f"library contract SHA-256 mismatch: expected {recorded.lower()}, got {calculated}"
        )


def _target_records(payload: dict) -> dict[tuple[str, str, str], dict]:
    records: dict[tuple[str, str, str], dict] = {}
    for library_name, library in payload.get("libraries", {}).items():
        for version, version_record in library.get("versions", {}).items():
            for python_version, target in version_record.get("targets", {}).items():
                records[(library_name, version, python_version)] = target
    return records


def _combination_record(key: tuple[str, str, str], target: dict) -> dict:
    library, version, python_version = key
    record = {
        "library": library,
        "version": version,
        "python_version": python_version,
        "status": target.get("status"),
    }
    if isinstance(target.get("source"), dict):
        record["source"] = target["source"]
    if isinstance(target.get("reason"), str):
        record["reason"] = target["reason"]
    if isinstance(target.get("artifacts"), list):
        record["artifacts"] = target["artifacts"]
    return record


def contract_delta(current: dict, previous: dict | None) -> dict:
    if previous is None:
        return {
            "schema_version": SCHEMA_VERSION,
            "baseline": True,
            "previous_contract_sha256": None,
            "current_contract_sha256": current.get("contract_sha256"),
            "new_candidates": [],
            "new_unbuildable": [],
            "drifted_candidates": [],
            "regressions": [],
        }

    current_records = _target_records(current)
    previous_records = _target_records(previous)
    current_targets = set(current.get("target_python_versions", []))
    new_candidates: list[dict] = []
    new_unbuildable: list[dict] = []
    drifted_candidates: list[dict] = []
    regressions: list[dict] = []

    for key in sorted(current_records, key=lambda item: tuple(part.casefold() for part in item)):
        target = current_records[key]
        previous_target = previous_records.get(key)
        status = target.get("status")
        if previous_target is None:
            if status == "candidate":
                new_candidates.append(_combination_record(key, target))
            elif status == "unbuildable":
                new_unbuildable.append(_combination_record(key, target))
            continue
        if status == "candidate" and previous_target.get("status") == "candidate":
            if target.get("source") != previous_target.get("source"):
                drifted_candidates.append(
                    {
                        **_combination_record(key, target),
                        "previous_source": previous_target.get("source"),
                    }
                )
        elif status == "candidate":
            new_candidates.append(_combination_record(key, target))
        elif previous_target.get("status") == "candidate" and status != "candidate":
            regressions.append(
                {
                    **_combination_record(key, target),
                    "previous_status": "candidate",
                }
            )
        elif status == "unbuildable" and previous_target.get("status") != "unbuildable":
            new_unbuildable.append(_combination_record(key, target))

    for key, previous_target in sorted(
        previous_records.items(),
        key=lambda item: tuple(part.casefold() for part in item[0]),
    ):
        if key[2] not in current_targets or key in current_records:
            continue
        if previous_target.get("status") == "candidate":
            regressions.append(
                {
                    "library": key[0],
                    "version": key[1],
                    "python_version": key[2],
                    "status": "missing",
                    "previous_status": "candidate",
                }
            )

    return {
        "schema_version": SCHEMA_VERSION,
        "baseline": False,
        "previous_contract_sha256": previous.get("contract_sha256"),
        "current_contract_sha256": current.get("contract_sha256"),
        "new_candidates": new_candidates,
        "new_unbuildable": new_unbuildable,
        "drifted_candidates": drifted_candidates,
        "regressions": regressions,
    }


def discover_contract(
    config: dict,
    target_python_versions: list[str],
    *,
    selected_libraries: list[str] | None = None,
    payload_loader: PayloadLoader | None = None,
) -> dict:
    targets = sorted({_target_version(value) for value in target_python_versions})
    if not targets:
        raise ValueError("at least one target Python version is required")

    _profile_name, profile = build.resolve_profile(config, "full")
    full_libraries = list(profile.get("third_party_libraries", []))
    requested = selected_libraries or full_libraries
    unknown = sorted(set(requested) - set(full_libraries), key=str.casefold)
    if unknown:
        raise RuntimeError("libraries are not in the full profile: " + ", ".join(unknown))

    catalog = build.profile_library_catalog(config, profile, "third_party_library_catalog")
    definitions = libs.load_integration_definitions(build.LIB_PATCH_ROOT, library_catalog=catalog)
    by_name = {integration.name.casefold(): integration for integration in definitions}
    ordered_integrations: list[libs.LibraryIntegration] = []
    for requested_name in requested:
        integration = by_name.get(requested_name.casefold())
        if integration is None:
            raise RuntimeError(f"full-profile integration is missing: {requested_name}")
        ordered_integrations.append(integration)

    loader = payload_loader or (lambda project_name: libs._load_pypi_release_payload(project_name, None))
    library_records: dict[str, dict] = {}
    for integration in sorted(ordered_integrations, key=lambda item: item.name.casefold()):
        if integration.source_provider == "pypi":
            payload = loader(integration.project_name or integration.name)
            record = pypi_library_contract(integration, payload, targets)
        else:
            record = configured_library_contract(integration, targets)
        library_records[integration.name] = record

    payload = {
        "schema_version": SCHEMA_VERSION,
        "target_python_versions": [str(version) for version in targets],
        "libraries": library_records,
    }
    payload["status_counts"] = _status_counts(library_records)
    payload["contract_sha256"] = _contract_sha256(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover the stable, non-yanked StaticPython library version contract."
    )
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config.json")
    parser.add_argument("--python-version", action="append", required=True)
    parser.add_argument("--library", action="append")
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--delta-output", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    payload = discover_contract(
        config,
        args.python_version,
        selected_libraries=args.library,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if args.delta_output is not None:
        previous = None
        if args.previous is not None and args.previous.is_file():
            previous = json.loads(args.previous.read_text(encoding="utf-8"))
            validate_contract_integrity(previous)
        delta = contract_delta(payload, previous)
        args.delta_output.parent.mkdir(parents=True, exist_ok=True)
        args.delta_output.write_text(
            json.dumps(delta, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(
        "[library-version-contract] "
        f"{len(payload['libraries'])} libraries / "
        f"{len(payload['target_python_versions'])} Python targets / "
        f"{payload['status_counts']['candidate']} candidate combinations / "
        f"{payload['status_counts']['unbuildable']} unbuildable combinations"
    )
    print(f"[library-version-contract] sha256={payload['contract_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
