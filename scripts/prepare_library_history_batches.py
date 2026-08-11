from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
from collections import defaultdict
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build
import libs


SCHEMA_VERSION = 1
DEFAULT_PURE_BATCH_SIZE = 16
DEFAULT_NATIVE_BATCH_SIZE = 1
DEFAULT_MAX_JOBS_PER_RUN = 256
DEFAULT_MAX_RUN_SHARDS = 256


def _canonical_sha256(payload: object) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    return slug or "batch"


def integration_build_kinds(config: dict) -> dict[str, str]:
    _profile_name, profile = build.resolve_profile(config, "full")
    selected = profile.get("third_party_libraries")
    if not isinstance(selected, list):
        raise RuntimeError("full profile third_party_libraries must be a list")
    catalog = build.profile_library_catalog(config, profile, "third_party_library_catalog")
    integrations = libs.load_integration_definitions(
        build.LIB_PATCH_ROOT,
        library_catalog=catalog,
    )
    by_name = {integration.name.casefold(): integration for integration in integrations}
    kinds: dict[str, str] = {}
    for name in selected:
        integration = by_name.get(str(name).casefold())
        if integration is None:
            raise RuntimeError(f"full-profile integration is missing: {name}")
        native = bool(
            integration.static_library_projects_release_x64
            or integration.native_static_projects
            or integration.builtin_module_registrations
            or integration.staged_static_libraries_release_x64
            or integration.python_link_wholearchive_release_x64
            or any(
                str(library).lower().endswith(".lib")
                and not build.is_windows_system_library(str(library))
                and not build.is_windows_sdk_library(str(library))
                for library in integration.python_link_dependencies_release_x64
            )
        )
        kinds[integration.name] = "native" if native else "pure-python"
    return kinds


def candidate_combinations(
    contract: dict,
    *,
    selected_libraries: list[str] | tuple[str, ...] | None = None,
    smoke_library: str | None = None,
    smoke_python_series: str | None = None,
) -> list[dict]:
    if (smoke_library is None) != (smoke_python_series is None):
        raise RuntimeError("smoke library and Python series must be provided together")
    if selected_libraries is not None and smoke_library is not None:
        raise RuntimeError(
            "targeted libraries and smoke selection are mutually exclusive"
        )
    if smoke_python_series is not None and not re.fullmatch(
        r"3\.(11|12|13|14|15)", smoke_python_series
    ):
        raise RuntimeError(f"invalid smoke-test Python series: {smoke_python_series!r}")
    combinations: list[dict] = []
    libraries = contract.get("libraries")
    if not isinstance(libraries, dict):
        raise RuntimeError("contract libraries must be an object")
    selected_names: set[str] | None = None
    if selected_libraries is not None:
        if not isinstance(selected_libraries, (list, tuple)) or not selected_libraries:
            raise RuntimeError("targeted library selection must not be empty")
        requested: dict[str, str] = {}
        for raw_name in selected_libraries:
            if not isinstance(raw_name, str) or not raw_name.strip():
                raise RuntimeError("targeted library names must be non-empty strings")
            name = raw_name.strip()
            folded = name.casefold()
            if folded in requested:
                raise RuntimeError(f"targeted library is repeated: {name}")
            requested[folded] = name
        available = {name.casefold(): name for name in libraries}
        missing = [requested[key] for key in requested if key not in available]
        if missing:
            raise RuntimeError(
                "targeted libraries are missing from contract: " + ", ".join(missing)
            )
        selected_names = set(requested)
    for library_name, library in libraries.items():
        if not isinstance(library, dict) or library.get("source_provider") != "pypi":
            continue
        if selected_names is not None and library_name.casefold() not in selected_names:
            continue
        project_name = library.get("project_name")
        versions = library.get("versions")
        if not isinstance(project_name, str) or not isinstance(versions, dict):
            raise RuntimeError(f"contract library has invalid metadata: {library_name}")
        for raw_version, version_record in versions.items():
            targets = version_record.get("targets") if isinstance(version_record, dict) else None
            if not isinstance(targets, dict):
                raise RuntimeError(f"contract version has no targets: {library_name} {raw_version}")
            for python_version, target in targets.items():
                if not isinstance(target, dict) or target.get("status") != "candidate":
                    continue
                source = target.get("source")
                if not isinstance(source, dict):
                    raise RuntimeError(
                        f"candidate has no source: {library_name} {raw_version} {python_version}"
                    )
                combinations.append(
                    {
                        "library": library_name,
                        "project_name": project_name,
                        "version": raw_version,
                        "python_version": python_version,
                        "source": source,
                    }
                )
    combinations = sorted(
        combinations,
        key=lambda item: (
            item["library"].casefold(),
            libs.Version(item["python_version"]),
            libs.Version(item["version"]),
        ),
    )
    if selected_names is not None:
        covered = {record["library"].casefold() for record in combinations}
        empty = [
            name
            for name in selected_libraries or ()
            if name.strip().casefold() not in covered
        ]
        if empty:
            raise RuntimeError(
                "targeted libraries have no candidate combinations: " + ", ".join(empty)
            )
    if smoke_library is None:
        return combinations
    matching = [
        combination
        for combination in combinations
        if combination["library"].casefold() == smoke_library.casefold()
        and combination["python_version"].startswith(f"{smoke_python_series}.")
    ]
    if not matching:
        raise RuntimeError(
            f"smoke-test library {smoke_library} has no candidate for CPython "
            f"{smoke_python_series}"
        )
    return [
        max(
            matching,
            key=lambda item: (
                libs.Version(item["version"]),
                libs.Version(item["python_version"]),
            ),
        )
    ]


def prepare_history_batches(
    contract: dict,
    build_kinds: dict[str, str],
    *,
    pure_batch_size: int = DEFAULT_PURE_BATCH_SIZE,
    native_batch_size: int = DEFAULT_NATIVE_BATCH_SIZE,
    max_jobs_per_run: int = DEFAULT_MAX_JOBS_PER_RUN,
    max_run_shards: int = DEFAULT_MAX_RUN_SHARDS,
    selected_libraries: list[str] | tuple[str, ...] | None = None,
    smoke_library: str | None = None,
    smoke_python_series: str | None = None,
) -> dict:
    if pure_batch_size < 1 or native_batch_size < 1:
        raise ValueError("batch sizes must be positive")
    if not 1 <= max_jobs_per_run <= 256:
        raise ValueError("max_jobs_per_run must be between 1 and 256")
    if not 1 <= max_run_shards <= 256:
        raise ValueError("max_run_shards must be between 1 and 256")
    contract_sha = contract.get("contract_sha256")
    if not isinstance(contract_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", contract_sha):
        raise RuntimeError("contract has no valid contract_sha256")

    combinations = candidate_combinations(
        contract,
        selected_libraries=selected_libraries,
        smoke_library=smoke_library,
        smoke_python_series=smoke_python_series,
    )
    recorded_candidate_count = contract.get("status_counts", {}).get("candidate")
    if (
        smoke_library is None
        and selected_libraries is None
        and isinstance(recorded_candidate_count, int)
        and recorded_candidate_count != len(combinations)
    ):
        raise RuntimeError(
            "contract candidate count does not match candidate records: "
            f"{recorded_candidate_count} != {len(combinations)}"
        )
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for combination in combinations:
        grouped[(combination["library"], combination["python_version"])].append(combination)

    batches: list[dict] = []
    for (library_name, python_version), records in sorted(
        grouped.items(),
        key=lambda item: (item[0][0].casefold(), libs.Version(item[0][1])),
    ):
        build_kind = build_kinds.get(library_name)
        if build_kind not in {"pure-python", "native"}:
            raise RuntimeError(f"library has no valid build-kind classification: {library_name}")
        batch_size = native_batch_size if build_kind == "native" else pure_batch_size
        for offset in range(0, len(records), batch_size):
            chunk = records[offset : offset + batch_size]
            identity = {
                "contract_sha256": contract_sha.lower(),
                "library": library_name,
                "python_version": python_version,
                "build_kind": build_kind,
                "combinations": [
                    {
                        "version": record["version"],
                        "source": record["source"],
                    }
                    for record in chunk
                ],
            }
            digest = _canonical_sha256(identity)
            batches.append(
                {
                    "batch_id": (
                        f"{_safe_slug(library_name)}-py{_safe_slug(python_version)}-"
                        f"{offset // batch_size:04d}-{digest[:12]}"
                    ),
                    "batch_sha256": digest,
                    "library": library_name,
                    "project_name": chunk[0]["project_name"],
                    "python_version": python_version,
                    "build_kind": build_kind,
                    "versions": [record["version"] for record in chunk],
                    "combination_count": len(chunk),
                }
            )

    run_count = math.ceil(len(batches) / max_jobs_per_run) if batches else 0
    if run_count > max_run_shards:
        raise RuntimeError(
            f"history planner needs {run_count} run shards, exceeding the GitHub Actions "
            f"matrix limit of {max_run_shards}; increase explicit batch sizes without "
            "dropping combinations"
        )
    for index, batch in enumerate(batches):
        batch["batch_index"] = index
        # Adjacent batches normally belong to the same library. Spread them
        # across workflow runs so one native-heavy integration cannot dominate
        # a single six-hour run shard.
        batch["run_shard_index"] = index % run_count
        batch["job_index_in_run"] = index // run_count
    if run_count:
        largest_shard = max(
            sum(1 for batch in batches if batch["run_shard_index"] == shard_index)
            for shard_index in range(run_count)
        )
        if largest_shard > max_jobs_per_run:
            raise RuntimeError(
                f"history planner produced {largest_shard} jobs in one run shard"
            )
    run_shards: list[dict] = []
    for shard_index in range(run_count):
        shard_batches = [
            batch for batch in batches if batch["run_shard_index"] == shard_index
        ]
        shard_identity = {
            "contract_sha256": contract_sha.lower(),
            "shard_index": shard_index,
            "batch_sha256s": [batch["batch_sha256"] for batch in shard_batches],
        }
        run_shards.append(
            {
                "shard_index": shard_index,
                "batch_count": len(shard_batches),
                "combination_count": sum(
                    batch["combination_count"] for batch in shard_batches
                ),
                "batch_sha256s": shard_identity["batch_sha256s"],
                "shard_sha256": _canonical_sha256(shard_identity),
            }
        )
    if smoke_library is not None:
        selection_mode = "smoke"
    elif selected_libraries is not None:
        selection_mode = "targeted"
    else:
        selection_mode = "full-history"
    canonical_selected_libraries = (
        sorted({record["library"] for record in combinations}, key=str.casefold)
        if selected_libraries is not None
        else None
    )
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": "staticpython-library-history-batches",
        "contract_sha256": contract_sha.lower(),
        "batch_policy": {
            "pure_python_versions_per_job": pure_batch_size,
            "native_versions_per_job": native_batch_size,
            "max_jobs_per_run": max_jobs_per_run,
            "max_run_shards": max_run_shards,
        },
        "selection": {
            "mode": selection_mode,
            "libraries": canonical_selected_libraries,
            "smoke_library": smoke_library,
            "smoke_python_series": smoke_python_series,
        },
        "combination_count": len(combinations),
        "batch_count": len(batches),
        "run_shard_count": run_count,
        "build_kind_counts": {
            kind: sum(batch["combination_count"] for batch in batches if batch["build_kind"] == kind)
            for kind in ("pure-python", "native")
        },
        "run_shards": run_shards,
        "batches": batches,
    }
    payload["manifest_sha256"] = _canonical_sha256(payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create deterministic cross-run batches for the StaticPython history contract."
    )
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config.json")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--pure-batch-size", type=int, default=DEFAULT_PURE_BATCH_SIZE)
    parser.add_argument("--native-batch-size", type=int, default=DEFAULT_NATIVE_BATCH_SIZE)
    parser.add_argument("--max-jobs-per-run", type=int, default=DEFAULT_MAX_JOBS_PER_RUN)
    parser.add_argument("--max-run-shards", type=int, default=DEFAULT_MAX_RUN_SHARDS)
    parser.add_argument(
        "--library",
        action="append",
        dest="selected_libraries",
        help="Validate all candidate combinations for this exact integration name; repeatable.",
    )
    parser.add_argument("--smoke-library")
    parser.add_argument("--smoke-python-series")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    contract = json.loads(args.contract.read_text(encoding="utf-8"))
    canonical_contract = {
        key: value for key, value in contract.items() if key != "contract_sha256"
    }
    if contract.get("contract_sha256", "").lower() != _canonical_sha256(canonical_contract):
        raise RuntimeError("library history input contract failed canonical SHA-256 validation")
    payload = prepare_history_batches(
        contract,
        integration_build_kinds(config),
        pure_batch_size=args.pure_batch_size,
        native_batch_size=args.native_batch_size,
        max_jobs_per_run=args.max_jobs_per_run,
        max_run_shards=args.max_run_shards,
        selected_libraries=args.selected_libraries,
        smoke_library=args.smoke_library,
        smoke_python_series=args.smoke_python_series,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"[library-history] {payload['combination_count']} combinations -> "
        f"{payload['batch_count']} jobs across {payload['run_shard_count']} workflow runs"
    )
    print(f"[library-history] manifest sha256={payload['manifest_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
