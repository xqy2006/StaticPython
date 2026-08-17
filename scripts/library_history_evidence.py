from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


SCRIPT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_ROOT.parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import library_version_contract as version_contract  # noqa: E402
import prepare_library_history_batches as history_batches  # noqa: E402


SCHEMA_VERSION = 1
MANIFEST_KIND = "staticpython-library-history-batches"
SHARD_PLAN_KIND = "staticpython-library-history-shard-plan"
BATCH_EVIDENCE_KIND = "staticpython-library-history-batch-evidence"
COMBINATION_EVIDENCE_KIND = "staticpython-library-history-combination-evidence"
SHARD_EVIDENCE_KIND = "staticpython-library-history-shard-evidence"
SUPPORT_KIND = "staticpython-library-history-support"
SUPPORT_INDEX_KIND = "staticpython-library-history-support-index"
PROMOTION_EVIDENCE_KIND = "staticpython-library-history-promotion-evidence"
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
SAFE_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def canonical_sha256(payload: Any) -> str:
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_object(path: Path, description: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"could not read {description}: {path}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"{description} must be a JSON object: {path}")
    return payload


def write_object(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _recorded_hash(payload: dict, field: str, description: str) -> str:
    recorded = payload.get(field)
    if not isinstance(recorded, str) or not SHA256_PATTERN.fullmatch(recorded):
        raise RuntimeError(f"{description} has no valid {field}")
    calculated = canonical_sha256(
        {key: value for key, value in payload.items() if key != field}
    )
    if calculated != recorded.lower():
        raise RuntimeError(
            f"{description} {field} mismatch: expected {recorded.lower()}, got {calculated}"
        )
    return recorded.lower()


def _safe_relative(root: Path, relative: str, description: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise RuntimeError(f"{description} must be a non-empty relative path")
    path = (root / relative).resolve()
    try:
        path.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"{description} escapes its root: {relative!r}") from exc
    return path


def runtime_artifact_name(
    contract_sha256: str,
    python_version: str,
    artifact_suffix: str | None = None,
) -> str:
    if not SHA256_PATTERN.fullmatch(contract_sha256):
        raise RuntimeError("runtime artifact contract SHA-256 is invalid")
    if not re.fullmatch(
        r"3\.(11|12|13|14|15)\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", python_version
    ):
        raise RuntimeError(
            f"runtime artifact Python version is invalid: {python_version!r}"
        )
    suffix = ""
    if artifact_suffix is not None:
        if not isinstance(artifact_suffix, str) or not SAFE_ID_PATTERN.fullmatch(
            artifact_suffix
        ):
            raise RuntimeError("runtime artifact suffix is invalid")
        suffix = f"-{artifact_suffix}"
    return (
        f"library-history-runtime-{contract_sha256[:16].lower()}-py{python_version}"
        f"{suffix}"
    )


def expected_combinations(contract: dict, batch: dict) -> list[dict]:
    library_name = batch.get("library")
    project_name = batch.get("project_name")
    python_version = batch.get("python_version")
    versions = batch.get("versions")
    if not all(
        isinstance(value, str) and value
        for value in (library_name, project_name, python_version)
    ):
        raise RuntimeError(f"history batch has invalid identity fields: {batch!r}")
    if not isinstance(versions, list) or not versions:
        raise RuntimeError(f"history batch has no versions: {batch.get('batch_id')!r}")
    libraries = contract.get("libraries")
    library = libraries.get(library_name) if isinstance(libraries, dict) else None
    if not isinstance(library, dict) or library.get("project_name") != project_name:
        raise RuntimeError(f"history batch library metadata mismatch: {library_name}")
    version_records = library.get("versions")
    if not isinstance(version_records, dict):
        raise RuntimeError(f"history contract library has no versions: {library_name}")
    records: list[dict] = []
    for release_version in versions:
        if not isinstance(release_version, str) or not release_version:
            raise RuntimeError(
                f"history batch has invalid release version: {release_version!r}"
            )
        version_record = version_records.get(release_version)
        targets = (
            version_record.get("targets") if isinstance(version_record, dict) else None
        )
        target = targets.get(python_version) if isinstance(targets, dict) else None
        source = target.get("source") if isinstance(target, dict) else None
        if not isinstance(target, dict) or target.get("status") != "candidate":
            raise RuntimeError(
                f"history batch target is not a candidate: {library_name} {release_version} "
                f"{python_version}"
            )
        if not isinstance(source, dict):
            raise RuntimeError(
                f"history batch target has no source: {library_name} {release_version}"
            )
        filename = source.get("filename")
        url = source.get("url")
        source_sha256 = source.get("sha256")
        if not all(
            isinstance(value, str) and value for value in (filename, url, source_sha256)
        ):
            raise RuntimeError(
                f"history batch source is incomplete: {library_name} {release_version}"
            )
        if not SHA256_PATTERN.fullmatch(source_sha256):
            raise RuntimeError(
                f"history batch source SHA-256 is invalid: {library_name} {release_version}"
            )
        records.append(
            {
                "library": library_name,
                "project_name": project_name,
                "version": release_version,
                "python_version": python_version,
                "source_filename": filename,
                "source_url": url,
                "source_sha256": source_sha256.lower(),
            }
        )
    return records


def validate_manifest(manifest: dict, contract: dict) -> str:
    version_contract.validate_contract_integrity(contract)
    if (
        manifest.get("schema_version") != SCHEMA_VERSION
        or manifest.get("kind") != MANIFEST_KIND
    ):
        raise RuntimeError("history manifest has an unsupported schema or kind")
    manifest_sha = _recorded_hash(manifest, "manifest_sha256", "history manifest")
    contract_sha = contract["contract_sha256"].lower()
    if manifest.get("contract_sha256") != contract_sha:
        raise RuntimeError("history manifest contract SHA-256 mismatch")

    batches = manifest.get("batches")
    shards = manifest.get("run_shards")
    if not isinstance(batches, list) or not isinstance(shards, list):
        raise RuntimeError("history manifest batches and run_shards must be arrays")
    if manifest.get("batch_count") != len(batches):
        raise RuntimeError("history manifest batch_count mismatch")
    if manifest.get("run_shard_count") != len(shards):
        raise RuntimeError("history manifest run_shard_count mismatch")
    if len(shards) > 256:
        raise RuntimeError("history manifest exceeds the 256 run-shard matrix limit")

    batch_ids: set[str] = set()
    batch_hashes: set[str] = set()
    combination_identities: set[tuple[str, str, str, str]] = set()
    by_shard: dict[int, list[dict]] = {index: [] for index in range(len(shards))}
    for batch in batches:
        if not isinstance(batch, dict):
            raise RuntimeError("history manifest batch records must be objects")
        batch_id = batch.get("batch_id")
        batch_sha = batch.get("batch_sha256")
        shard_index = batch.get("run_shard_index")
        if not isinstance(batch_id, str) or not SAFE_ID_PATTERN.fullmatch(batch_id):
            raise RuntimeError(f"history manifest has unsafe batch ID: {batch_id!r}")
        if batch_id.casefold() in batch_ids:
            raise RuntimeError(f"history manifest has duplicate batch ID: {batch_id}")
        batch_ids.add(batch_id.casefold())
        if not isinstance(batch_sha, str) or not SHA256_PATTERN.fullmatch(batch_sha):
            raise RuntimeError(
                f"history manifest batch has invalid SHA-256: {batch_id}"
            )
        if batch_sha.lower() in batch_hashes:
            raise RuntimeError(
                f"history manifest has duplicate batch SHA-256: {batch_sha}"
            )
        batch_hashes.add(batch_sha.lower())
        if not isinstance(shard_index, int) or shard_index not in by_shard:
            raise RuntimeError(
                f"history manifest batch has invalid shard index: {batch_id}"
            )
        combinations = expected_combinations(contract, batch)
        if batch.get("combination_count") != len(combinations):
            raise RuntimeError(
                f"history manifest combination count mismatch: {batch_id}"
            )
        identity = {
            "contract_sha256": contract_sha,
            "library": batch["library"],
            "python_version": batch["python_version"],
            "build_kind": batch.get("build_kind"),
            "combinations": [
                {
                    "version": combination["version"],
                    "source": contract["libraries"][batch["library"]]["versions"][
                        combination["version"]
                    ]["targets"][batch["python_version"]]["source"],
                }
                for combination in combinations
            ],
        }
        if canonical_sha256(identity) != batch_sha.lower():
            raise RuntimeError(f"history manifest batch SHA-256 mismatch: {batch_id}")
        for combination in combinations:
            combination_identity = (
                combination["library"].casefold(),
                combination["version"],
                combination["python_version"],
                combination["source_sha256"],
            )
            if combination_identity in combination_identities:
                raise RuntimeError(
                    f"history manifest repeats a combination: {combination_identity!r}"
                )
            combination_identities.add(combination_identity)
        by_shard[shard_index].append(batch)

    if manifest.get("combination_count") != len(combination_identities):
        raise RuntimeError("history manifest combination_count mismatch")
    selection = manifest.get("selection")
    if not isinstance(selection, dict):
        raise RuntimeError("history manifest has no selection record")
    selection_mode = selection.get("mode")
    selected_libraries = None
    smoke_library = None
    smoke_python_series = None
    if selection_mode == "full-history":
        if any(
            selection.get(field) is not None
            for field in ("libraries", "smoke_library", "smoke_python_series")
        ):
            raise RuntimeError("full-history selection must not contain filters")
    elif selection_mode == "targeted":
        selected_libraries = selection.get("libraries")
        if any(
            selection.get(field) is not None
            for field in ("smoke_library", "smoke_python_series")
        ):
            raise RuntimeError("targeted selection must not contain smoke filters")
    elif selection_mode == "smoke":
        if selection.get("libraries") is not None:
            raise RuntimeError("smoke selection must not contain targeted libraries")
        smoke_library = selection.get("smoke_library")
        smoke_python_series = selection.get("smoke_python_series")
    else:
        raise RuntimeError(
            f"history manifest has invalid selection mode: {selection_mode!r}"
        )
    selected = history_batches.candidate_combinations(
        contract,
        selected_libraries=selected_libraries,
        smoke_library=smoke_library,
        smoke_python_series=smoke_python_series,
    )
    selected_identities = {
        (
            record["library"].casefold(),
            record["version"],
            record["python_version"],
            str(record["source"]["sha256"]).lower(),
        )
        for record in selected
    }
    if selected_identities != combination_identities:
        raise RuntimeError(
            "history manifest does not cover its selected contract combinations"
        )

    for shard_index, shard in enumerate(shards):
        if not isinstance(shard, dict) or shard.get("shard_index") != shard_index:
            raise RuntimeError(
                f"history manifest shard ordering mismatch at {shard_index}"
            )
        shard_batches = by_shard[shard_index]
        batch_sha256s = [batch["batch_sha256"].lower() for batch in shard_batches]
        shard_identity = {
            "contract_sha256": contract_sha,
            "shard_index": shard_index,
            "batch_sha256s": batch_sha256s,
        }
        if shard.get("batch_sha256s") != batch_sha256s:
            raise RuntimeError(
                f"history manifest shard batch hashes mismatch: {shard_index}"
            )
        if shard.get("shard_sha256") != canonical_sha256(shard_identity):
            raise RuntimeError(
                f"history manifest shard SHA-256 mismatch: {shard_index}"
            )
        if shard.get("batch_count") != len(shard_batches):
            raise RuntimeError(
                f"history manifest shard batch count mismatch: {shard_index}"
            )
        if shard.get("combination_count") != sum(
            batch["combination_count"] for batch in shard_batches
        ):
            raise RuntimeError(
                f"history manifest shard combination count mismatch: {shard_index}"
            )
    return manifest_sha


def prepare_shard_plan(
    contract: dict,
    manifest: dict,
    shard_index: int,
    *,
    plan_artifact: str,
    artifact_suffix: str | None = None,
) -> tuple[dict, dict]:
    manifest_sha = validate_manifest(manifest, contract)
    shards = manifest["run_shards"]
    if shard_index < 0 or shard_index >= len(shards):
        raise RuntimeError(f"history shard index is out of range: {shard_index}")
    shard = shards[shard_index]
    batches = [
        batch
        for batch in manifest["batches"]
        if batch["run_shard_index"] == shard_index
    ]
    include = [
        {
            "batch_id": batch["batch_id"],
            "batch_sha256": batch["batch_sha256"],
            "library": batch["library"],
            "python_version": batch["python_version"],
            "build_kind": batch["build_kind"],
            "runtime_artifact": runtime_artifact_name(
                manifest["contract_sha256"],
                batch["python_version"],
                artifact_suffix,
            ),
        }
        for batch in batches
    ]
    if len(include) > 256:
        raise RuntimeError(
            f"history shard {shard_index} exceeds the 256-job matrix limit"
        )
    matrix = {"include": include}
    plan = {
        "schema_version": SCHEMA_VERSION,
        "kind": SHARD_PLAN_KIND,
        "contract_sha256": manifest["contract_sha256"],
        "manifest_sha256": manifest_sha,
        "plan_artifact": plan_artifact,
        "shard": shard,
        "matrix": matrix,
    }
    plan["shard_plan_sha256"] = canonical_sha256(plan)
    return plan, matrix


def _validate_file_records(
    evidence_root: Path, records: object
) -> dict[str, tuple[Path, str]]:
    if not isinstance(records, list):
        raise RuntimeError("batch evidence files must be an array")
    seen: set[str] = set()
    validated: dict[str, tuple[Path, str]] = {}
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError("batch evidence file record must be an object")
        relative = record.get("path")
        sha256 = record.get("sha256")
        if not isinstance(relative, str) or relative.casefold() in seen:
            raise RuntimeError(
                f"batch evidence file path is invalid or duplicated: {relative!r}"
            )
        seen.add(relative.casefold())
        if not isinstance(sha256, str) or not SHA256_PATTERN.fullmatch(sha256):
            raise RuntimeError(f"batch evidence file SHA-256 is invalid: {relative!r}")
        path = _safe_relative(evidence_root, relative, "batch evidence file")
        if not path.is_file():
            raise RuntimeError(f"batch evidence file is missing: {relative}")
        if file_sha256(path) != sha256.lower():
            raise RuntimeError(f"batch evidence file SHA-256 mismatch: {relative}")
        validated[relative] = (path, sha256.lower())
    return validated


def validate_batch_evidence(
    evidence: dict,
    evidence_root: Path,
    contract: dict,
    manifest: dict,
    batch: dict,
) -> str:
    if (
        evidence.get("schema_version") != SCHEMA_VERSION
        or evidence.get("kind") != BATCH_EVIDENCE_KIND
    ):
        raise RuntimeError("batch evidence has an unsupported schema or kind")
    evidence_sha = _recorded_hash(evidence, "evidence_sha256", "batch evidence")
    expected_identity = {
        "contract_sha256": manifest["contract_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "batch_id": batch["batch_id"],
        "batch_sha256": batch["batch_sha256"],
        "shard_index": batch["run_shard_index"],
    }
    for key, value in expected_identity.items():
        if evidence.get(key) != value:
            raise RuntimeError(f"batch evidence {key} mismatch: {batch['batch_id']}")
    expected = expected_combinations(contract, batch)
    runtime_sdk_sha = evidence.get("runtime_sdk_sha256")
    if not isinstance(runtime_sdk_sha, str) or not SHA256_PATTERN.fullmatch(
        runtime_sdk_sha
    ):
        raise RuntimeError("batch evidence has no valid runtime SDK SHA-256")
    results = evidence.get("results")
    if not isinstance(results, list):
        raise RuntimeError("batch evidence results must be an array")
    expected_keys = {
        (
            record["library"].casefold(),
            record["version"],
            record["python_version"],
            record["source_sha256"],
        )
        for record in expected
    }
    result_keys: set[tuple[str, str, str, str]] = set()
    for result in results:
        if not isinstance(result, dict):
            raise RuntimeError("batch evidence result must be an object")
        key = (
            str(result.get("library", "")).casefold(),
            result.get("version"),
            result.get("python_version"),
            str(result.get("source_sha256", "")).lower(),
        )
        if key in result_keys:
            raise RuntimeError(f"batch evidence repeats a result: {key!r}")
        result_keys.add(key)
        if result.get("status") not in {"passed", "failed"}:
            raise RuntimeError(f"batch evidence result has invalid status: {key!r}")
        if result.get("status") == "passed":
            for field in (
                "pack_sha256",
                "runtime_sdk_sha256",
                "verifier_report_sha256",
                "combination_evidence_sha256",
                "dependency_lock_sha256",
                "dependency_solver_fingerprint",
                "dependency_toolchain_fingerprint",
            ):
                value = result.get(field)
                if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
                    raise RuntimeError(
                        f"passed batch result has no valid {field}: {key!r}"
                    )
            if result["runtime_sdk_sha256"].lower() != runtime_sdk_sha.lower():
                raise RuntimeError(f"passed batch result runtime SDK mismatch: {key!r}")
            runtime_abi = result.get("runtime_abi")
            if not isinstance(runtime_abi, str) or not re.fullmatch(
                r"staticpython-pack-v1-cp3(?:11|12|13|14|15)", runtime_abi
            ):
                raise RuntimeError(f"passed batch result has no valid runtime ABI: {key!r}")
        else:
            failure = result.get("failure")
            if (
                not isinstance(failure, dict)
                or not failure.get("type")
                or not failure.get("message")
            ):
                raise RuntimeError(
                    f"failed batch result has no structured failure: {key!r}"
                )
    if result_keys != expected_keys:
        raise RuntimeError(
            f"batch evidence result coverage mismatch: {batch['batch_id']}"
        )
    validated_files = _validate_file_records(evidence_root, evidence.get("files"))
    passed_results = {
        (
            str(result.get("library", "")).casefold(),
            result.get("version"),
            result.get("python_version"),
            str(result.get("source_sha256", "")).lower(),
        ): result
        for result in results
        if result.get("status") == "passed"
    }
    verifier_records = [
        (path, sha256)
        for relative, (path, sha256) in validated_files.items()
        if Path(relative).name == "staticpython-pack-verify-report.json"
    ]
    verifier_hashes = {sha256 for _path, sha256 in verifier_records}
    for key, result in passed_results.items():
        if result["verifier_report_sha256"].lower() not in verifier_hashes:
            raise RuntimeError(
                f"passed batch result verifier report is not hash-linked: {key!r}"
            )
    if len(verifier_records) != len(passed_results):
        raise RuntimeError("batch evidence verifier report coverage mismatch")

    dependency_locks: dict[str, dict] = {}
    profile_metadata_count = 0
    for relative, (path, sha256) in validated_files.items():
        if Path(relative).name == "dependency-lock.v1.json":
            lock = load_object(path, "historical dependency lock")
            if (
                lock.get("schema_version") != SCHEMA_VERSION
                or lock.get("kind") != "staticpython-history-dependency-lock"
            ):
                raise RuntimeError(
                    f"historical dependency lock has an unsupported schema or kind: {relative}"
                )
            fingerprint = _recorded_hash(
                lock,
                "solver_fingerprint",
                "historical dependency lock",
            )
            unsigned = {
                key: value for key, value in lock.items() if key != "solver_fingerprint"
            }
            if canonical_sha256(unsigned) != fingerprint:
                raise RuntimeError(
                    f"historical dependency lock fingerprint mismatch: {relative}"
                )
            toolchain = lock.get("toolchain")
            toolchain_fingerprint = lock.get("toolchain_fingerprint")
            if (
                not isinstance(toolchain, dict)
                or not isinstance(toolchain_fingerprint, str)
                or not SHA256_PATTERN.fullmatch(toolchain_fingerprint)
                or canonical_sha256(toolchain) != toolchain_fingerprint.lower()
            ):
                raise RuntimeError(
                    f"historical dependency lock toolchain fingerprint mismatch: {relative}"
                )
            dependency_locks[sha256] = lock
        elif Path(relative).name == "staticpython-profile.json":
            profile = load_object(path, "historical resolved profile")
            if not isinstance(profile.get("third_party_library_versions"), dict):
                raise RuntimeError(
                    f"historical resolved profile has no integration versions: {relative}"
                )
            profile_metadata_count += 1
    if len(dependency_locks) != len(passed_results):
        raise RuntimeError("batch dependency lock coverage mismatch")
    if profile_metadata_count != len(passed_results):
        raise RuntimeError("batch resolved profile coverage mismatch")
    for key, result in passed_results.items():
        lock = dependency_locks.get(result["dependency_lock_sha256"].lower())
        if lock is None:
            raise RuntimeError(
                f"passed batch result dependency lock is not hash-linked: {key!r}"
            )
        if (
            lock.get("target_python_version") != result["python_version"]
            or lock.get("runtime_abi") != result["runtime_abi"]
            or lock.get("solver_fingerprint")
            != result["dependency_solver_fingerprint"].lower()
            or lock.get("toolchain_fingerprint")
            != result["dependency_toolchain_fingerprint"].lower()
        ):
            raise RuntimeError(f"passed batch result dependency lock mismatch: {key!r}")
        if [str(name).casefold() for name in lock.get("roots", [])] != [key[0]]:
            raise RuntimeError(
                f"passed batch result dependency lock root selection mismatch: {key!r}"
            )
        roots = [
            record
            for record in lock.get("integrations", [])
            if isinstance(record, dict)
            and str(record.get("name", "")).casefold() == key[0]
            and record.get("version") == key[1]
        ]
        if len(roots) != 1:
            raise RuntimeError(
                f"passed batch result dependency lock root mismatch: {key!r}"
            )

    combination_records: dict[tuple[str, object, object, str], dict] = {}
    pack_records: set[tuple[str, object, object]] = set()
    for relative, (path, _sha256) in validated_files.items():
        if Path(relative).name == "combination-evidence.v1.json":
            combination = load_object(path, "combination evidence")
            if (
                combination.get("schema_version") != SCHEMA_VERSION
                or combination.get("kind") != COMBINATION_EVIDENCE_KIND
            ):
                raise RuntimeError(
                    f"combination evidence has an unsupported schema or kind: {relative}"
                )
            combination_sha = _recorded_hash(
                combination, "evidence_sha256", "combination evidence"
            )
            key = (
                str(combination.get("library", "")).casefold(),
                combination.get("version"),
                combination.get("python_version"),
                str(combination.get("source_sha256", "")).lower(),
            )
            if key in combination_records:
                raise RuntimeError(f"duplicate combination evidence: {key!r}")
            result = passed_results.get(key)
            if result is None:
                raise RuntimeError(
                    f"combination evidence has no passed batch result: {key!r}"
                )
            expected_combination = {
                "status": "passed",
                "runtime_sdk_sha256": runtime_sdk_sha.lower(),
                "runtime_abi": result["runtime_abi"],
                "pack_sha256": result["pack_sha256"].lower(),
                "dependency_lock_sha256": result["dependency_lock_sha256"].lower(),
                "dependency_solver_fingerprint": result[
                    "dependency_solver_fingerprint"
                ].lower(),
                "dependency_toolchain_fingerprint": result[
                    "dependency_toolchain_fingerprint"
                ].lower(),
                "evidence_sha256": result["combination_evidence_sha256"].lower(),
            }
            actual_combination = {
                "status": combination.get("status"),
                "runtime_sdk_sha256": str(
                    combination.get("runtime_sdk_sha256", "")
                ).lower(),
                "runtime_abi": combination.get("runtime_abi"),
                "pack_sha256": str(combination.get("pack_sha256", "")).lower(),
                "dependency_lock_sha256": str(
                    combination.get("dependency_lock_sha256", "")
                ).lower(),
                "dependency_solver_fingerprint": str(
                    combination.get("dependency_solver_fingerprint", "")
                ).lower(),
                "dependency_toolchain_fingerprint": str(
                    combination.get("dependency_toolchain_fingerprint", "")
                ).lower(),
                "evidence_sha256": combination_sha,
            }
            if actual_combination != expected_combination:
                raise RuntimeError(f"combination evidence mismatch: {key!r}")
            combination_records[key] = combination
        elif Path(relative).name == "pack-metadata.json":
            metadata = load_object(path, "history pack metadata")
            key = (
                str(metadata.get("name", "")).casefold(),
                metadata.get("version"),
                metadata.get("cpython_version"),
            )
            if key in pack_records:
                raise RuntimeError(f"duplicate history pack metadata: {key!r}")
            if metadata.get("verification", {}).get("status") != "passed":
                raise RuntimeError(f"history pack metadata is not verified: {key!r}")
            pack_records.add(key)

    if set(combination_records) != set(passed_results):
        raise RuntimeError("batch combination evidence coverage mismatch")
    expected_pack_records = {
        (key[0], key[1], key[2]) for key in passed_results
    }
    if pack_records != expected_pack_records:
        raise RuntimeError("batch pack metadata coverage mismatch")
    all_passed = all(result.get("status") == "passed" for result in results)
    if all_passed and not evidence.get("files"):
        raise RuntimeError("passed batch evidence has no immutable files")
    expected_status = "passed" if all_passed else "failed"
    if evidence.get("status") != expected_status:
        raise RuntimeError(
            f"batch evidence aggregate status mismatch: {batch['batch_id']}"
        )
    return evidence_sha


def validate_shard_evidence(
    evidence: dict,
    contract: dict,
    manifest: dict,
    shard: dict,
) -> str:
    if (
        evidence.get("schema_version") != SCHEMA_VERSION
        or evidence.get("kind") != SHARD_EVIDENCE_KIND
    ):
        raise RuntimeError("shard evidence has an unsupported schema or kind")
    evidence_sha = _recorded_hash(
        evidence, "evidence_sha256", "history shard evidence"
    )
    expected_identity = {
        "contract_sha256": manifest["contract_sha256"],
        "manifest_sha256": manifest["manifest_sha256"],
        "shard_index": shard["shard_index"],
        "shard_sha256": shard["shard_sha256"],
        "expected_batch_count": shard["batch_count"],
        "expected_combination_count": shard["combination_count"],
    }
    mismatches = [
        key for key, expected in expected_identity.items() if evidence.get(key) != expected
    ]
    if mismatches:
        raise RuntimeError(
            "shard evidence identity mismatch: " + ", ".join(mismatches)
        )

    expected_batches = {
        batch["batch_id"]: batch
        for batch in manifest["batches"]
        if batch["run_shard_index"] == shard["shard_index"]
    }
    records = evidence.get("batches")
    blockers = evidence.get("blockers")
    if not isinstance(records, list) or not isinstance(blockers, list):
        raise RuntimeError("shard evidence batches and blockers must be arrays")
    for blocker in blockers:
        if (
            not isinstance(blocker, dict)
            or not isinstance(blocker.get("code"), str)
            or not blocker["code"]
        ):
            raise RuntimeError("shard evidence has an invalid blocker record")

    seen: set[str] = set()
    passed_batch_count = 0
    passed_combination_count = 0
    for record in records:
        if not isinstance(record, dict):
            raise RuntimeError("shard evidence batch records must be objects")
        batch_id = record.get("batch_id")
        if not isinstance(batch_id, str) or batch_id in seen:
            raise RuntimeError(
                f"shard evidence has an invalid or duplicate batch ID: {batch_id!r}"
            )
        seen.add(batch_id)
        batch = expected_batches.get(batch_id)
        if batch is None:
            raise RuntimeError(f"shard evidence contains an unexpected batch: {batch_id}")
        expected_record = {
            "batch_sha256": batch["batch_sha256"],
            "python_version": batch["python_version"],
            "combination_count": batch["combination_count"],
        }
        for key, expected in expected_record.items():
            if record.get(key) != expected:
                raise RuntimeError(
                    f"shard evidence batch {batch_id} {key} mismatch"
                )
        batch_evidence_sha = record.get("evidence_sha256")
        if not isinstance(batch_evidence_sha, str) or not SHA256_PATTERN.fullmatch(
            batch_evidence_sha
        ):
            raise RuntimeError(
                f"shard evidence batch {batch_id} has no valid evidence SHA-256"
            )
        runtime_sdk_sha = record.get("runtime_sdk_sha256")
        if not isinstance(runtime_sdk_sha, str) or not SHA256_PATTERN.fullmatch(
            runtime_sdk_sha
        ):
            raise RuntimeError(
                f"shard evidence batch {batch_id} has no valid runtime SDK SHA-256"
            )
        artifact = record.get("artifact")
        if not isinstance(artifact, str) or not artifact:
            raise RuntimeError(
                f"shard evidence batch {batch_id} has no immutable artifact name"
            )
        status = record.get("status")
        if status not in {"passed", "failed"}:
            raise RuntimeError(
                f"shard evidence batch {batch_id} has invalid status: {status!r}"
            )
        results = record.get("results")
        if not isinstance(results, list):
            raise RuntimeError(
                f"shard evidence batch {batch_id} results must be an array"
            )
        expected_results = {
            (
                expected["library"].casefold(),
                expected["version"],
                expected["python_version"],
                expected["source_sha256"],
            )
            for expected in expected_combinations(contract, batch)
        }
        result_keys: set[tuple[str, object, object, str]] = set()
        result_statuses: list[str] = []
        for result in results:
            if not isinstance(result, dict):
                raise RuntimeError(
                    f"shard evidence batch {batch_id} result must be an object"
                )
            result_key = (
                str(result.get("library", "")).casefold(),
                result.get("version"),
                result.get("python_version"),
                str(result.get("source_sha256", "")).lower(),
            )
            if result_key in result_keys:
                raise RuntimeError(
                    f"shard evidence batch {batch_id} repeats a result: {result_key!r}"
                )
            result_keys.add(result_key)
            result_status = result.get("status")
            if result_status not in {"passed", "failed"}:
                raise RuntimeError(
                    f"shard evidence batch {batch_id} result has invalid status"
                )
            result_statuses.append(result_status)
            if result_status == "passed":
                for field in (
                    "pack_sha256",
                    "runtime_sdk_sha256",
                    "verifier_report_sha256",
                    "combination_evidence_sha256",
                ):
                    value = result.get(field)
                    if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(
                        value
                    ):
                        raise RuntimeError(
                            f"shard evidence batch {batch_id} result has no valid {field}"
                        )
                if result["runtime_sdk_sha256"].lower() != runtime_sdk_sha.lower():
                    raise RuntimeError(
                        f"shard evidence batch {batch_id} result runtime SDK mismatch"
                    )
            elif not isinstance(result.get("failure"), dict):
                raise RuntimeError(
                    f"shard evidence batch {batch_id} failed result has no failure"
                )
        if result_keys != expected_results:
            raise RuntimeError(
                f"shard evidence batch {batch_id} result coverage mismatch"
            )
        expected_status = (
            "passed" if all(value == "passed" for value in result_statuses) else "failed"
        )
        if status != expected_status:
            raise RuntimeError(
                f"shard evidence batch {batch_id} aggregate status mismatch"
            )
        if status == "passed":
            passed_batch_count += 1
            passed_combination_count += batch["combination_count"]

    if evidence.get("passed_batch_count") != passed_batch_count:
        raise RuntimeError("shard evidence passed_batch_count mismatch")
    if evidence.get("passed_combination_count") != passed_combination_count:
        raise RuntimeError("shard evidence passed_combination_count mismatch")
    status = evidence.get("status")
    if status not in {"passed", "failed"}:
        raise RuntimeError(f"shard evidence has invalid status: {status!r}")
    if status == "passed":
        if blockers:
            raise RuntimeError("passed shard evidence contains blockers")
        if seen != set(expected_batches):
            raise RuntimeError("passed shard evidence does not cover every expected batch")
        if passed_batch_count != len(expected_batches):
            raise RuntimeError("passed shard evidence contains a failed batch")
    elif not blockers:
        raise RuntimeError("failed shard evidence has no structured blocker")
    return evidence_sha


def finalize_shard(
    contract_path: Path,
    manifest_path: Path,
    evidence_root: Path,
    shard_index: int,
    output_path: Path,
    *,
    provenance: dict | None = None,
) -> dict:
    contract = load_object(contract_path, "history contract")
    manifest = load_object(manifest_path, "history manifest")
    manifest_sha = validate_manifest(manifest, contract)
    if shard_index < 0 or shard_index >= len(manifest["run_shards"]):
        raise RuntimeError(f"history shard index is out of range: {shard_index}")
    expected_batches = {
        batch["batch_id"]: batch
        for batch in manifest["batches"]
        if batch["run_shard_index"] == shard_index
    }
    found: dict[str, tuple[dict, Path]] = {}
    blockers: list[dict] = []
    for path in sorted(evidence_root.rglob("library-history-batch-evidence.v1.json")):
        try:
            evidence = load_object(path, "history batch evidence")
            batch_id = evidence.get("batch_id")
            if not isinstance(batch_id, str):
                raise RuntimeError("batch evidence has no batch_id")
            if batch_id in found:
                blockers.append(
                    {"code": "duplicate-batch-evidence", "batch_id": batch_id}
                )
                continue
            found[batch_id] = (evidence, path)
        except Exception as exc:
            blockers.append(
                {
                    "code": "unreadable-batch-evidence",
                    "path": path.relative_to(evidence_root).as_posix(),
                    "error": str(exc),
                }
            )

    batch_records: list[dict] = []
    passed_combinations = 0
    for batch_id, batch in expected_batches.items():
        item = found.pop(batch_id, None)
        if item is None:
            blockers.append({"code": "missing-batch-evidence", "batch_id": batch_id})
            continue
        evidence, path = item
        try:
            evidence_sha = validate_batch_evidence(
                evidence,
                path.parent,
                contract,
                manifest,
                batch,
            )
        except Exception as exc:
            blockers.append(
                {
                    "code": "invalid-batch-evidence",
                    "batch_id": batch_id,
                    "error": str(exc),
                }
            )
            continue
        batch_records.append(
            {
                "batch_id": batch_id,
                "batch_sha256": batch["batch_sha256"],
                "evidence_sha256": evidence_sha,
                "artifact": evidence.get("provenance", {}).get("artifact"),
                "python_version": batch["python_version"],
                "runtime_sdk_sha256": evidence["runtime_sdk_sha256"],
                "status": evidence["status"],
                "combination_count": batch["combination_count"],
                "results": evidence["results"],
            }
        )
        if evidence["status"] == "passed":
            passed_combinations += batch["combination_count"]
        else:
            blockers.append({"code": "failed-batch", "batch_id": batch_id})
    for batch_id in sorted(found):
        blockers.append({"code": "unexpected-batch-evidence", "batch_id": batch_id})

    shard = manifest["run_shards"][shard_index]
    payload = {
        "schema_version": SCHEMA_VERSION,
        "kind": SHARD_EVIDENCE_KIND,
        "contract_sha256": manifest["contract_sha256"],
        "manifest_sha256": manifest_sha,
        "shard_index": shard_index,
        "shard_sha256": shard["shard_sha256"],
        "expected_batch_count": shard["batch_count"],
        "passed_batch_count": sum(
            record["status"] == "passed" for record in batch_records
        ),
        "expected_combination_count": shard["combination_count"],
        "passed_combination_count": passed_combinations,
        "batches": sorted(
            batch_records, key=lambda record: record["batch_id"].casefold()
        ),
        "blockers": blockers,
        "status": "passed" if not blockers else "failed",
        "provenance": {
            key: value
            for key, value in (provenance or {}).items()
            if value not in (None, "")
        },
    }
    payload["evidence_sha256"] = canonical_sha256(payload)
    write_object(output_path, payload)
    return payload


def _load_previous_support_catalog(root: Path) -> tuple[dict, dict | None]:
    index = load_object(root / "index.v1.json", "previous history support index")
    if (
        index.get("schema_version") != SCHEMA_VERSION
        or index.get("kind") != SUPPORT_INDEX_KIND
    ):
        raise RuntimeError(
            "previous history support index has an unsupported schema or kind"
        )
    _recorded_hash(index, "index_sha256", "previous history support index")
    active = index.get("active")
    if active is None:
        return index, None
    if not isinstance(active, dict):
        raise RuntimeError(
            "previous history support active record must be an object or null"
        )
    support_path = _safe_relative(
        root, active.get("support"), "previous active support path"
    )
    if not support_path.is_file():
        raise RuntimeError("previous active support document is missing")
    support = load_object(support_path, "previous active support")
    if (
        support.get("schema_version") != SCHEMA_VERSION
        or support.get("kind") != SUPPORT_KIND
    ):
        raise RuntimeError("previous active support has an unsupported schema or kind")
    support_sha = _recorded_hash(support, "support_sha256", "previous active support")
    if active.get("support_sha256") != support_sha:
        raise RuntimeError("previous active support SHA-256 does not match its index")
    if support.get("status") != "verified":
        raise RuntimeError("previous active support is not verified")
    for field in ("contract_sha256", "manifest_sha256"):
        if active.get(field) != support.get(field):
            raise RuntimeError(
                f"previous active support {field} does not match its index"
            )
    active_directory = active.get("directory")
    if active_directory is not None:
        directory_path = _safe_relative(
            root, active_directory, "previous active support directory"
        )
        if not directory_path.is_dir():
            raise RuntimeError("previous active support directory is missing")
        try:
            support_path.relative_to(directory_path)
        except ValueError as exc:
            raise RuntimeError(
                "previous active support document is outside its active directory"
            ) from exc
        contract_path = _safe_relative(
            root, active.get("contract"), "previous active contract path"
        )
        manifest_path = _safe_relative(
            root, active.get("manifest"), "previous active manifest path"
        )
        evidence_path = _safe_relative(
            root, active.get("evidence"), "previous active promotion evidence path"
        )
        shards_path = _safe_relative(
            root, active.get("shards"), "previous active shards path"
        )
        for path, description in (
            (contract_path, "contract"),
            (manifest_path, "manifest"),
            (evidence_path, "promotion evidence"),
        ):
            try:
                path.relative_to(directory_path)
            except ValueError as exc:
                raise RuntimeError(
                    f"previous active {description} is outside its active directory"
                ) from exc
            if not path.is_file():
                raise RuntimeError(f"previous active {description} is missing")
        try:
            shards_path.relative_to(directory_path)
        except ValueError as exc:
            raise RuntimeError(
                "previous active shards are outside its active directory"
            ) from exc
        if not shards_path.is_dir():
            raise RuntimeError("previous active shards directory is missing")

        previous_contract = load_object(contract_path, "previous active contract")
        previous_manifest = load_object(manifest_path, "previous active manifest")
        previous_manifest_sha = validate_manifest(
            previous_manifest, previous_contract
        )
        if (
            previous_contract.get("contract_sha256") != active.get("contract_sha256")
            or previous_manifest_sha != active.get("manifest_sha256")
        ):
            raise RuntimeError(
                "previous active contract or manifest hash does not match its index"
            )
        if (
            support.get("expected_combination_count")
            != support.get("verified_combination_count")
            or support.get("expected_batch_count")
            != support.get("verified_batch_count")
            or support.get("expected_shard_count")
            != support.get("verified_shard_count")
            or support.get("verified_combination_count")
            != active.get("verified_combination_count")
        ):
            raise RuntimeError("previous active support coverage is incomplete")
        contract_source_relative = active.get("contract_source")
        if contract_source_relative is not None:
            contract_source_path = _safe_relative(
                root,
                contract_source_relative,
                "previous active contract source path",
            )
            try:
                contract_source_path.relative_to(directory_path)
            except ValueError as exc:
                raise RuntimeError(
                    "previous active contract source is outside its active directory"
                ) from exc
            if not contract_source_path.is_file():
                raise RuntimeError("previous active contract source is missing")
            if file_sha256(contract_source_path) != support.get(
                "contract_source_sha256"
            ):
                raise RuntimeError("previous active contract source SHA-256 mismatch")
            load_object(contract_source_path, "previous active contract source")
        promotion_evidence = load_object(
            evidence_path, "previous active promotion evidence"
        )
        if (
            promotion_evidence.get("schema_version") != SCHEMA_VERSION
            or promotion_evidence.get("kind") != PROMOTION_EVIDENCE_KIND
        ):
            raise RuntimeError(
                "previous active promotion evidence has an unsupported schema or kind"
            )
        promotion_evidence_sha = _recorded_hash(
            promotion_evidence,
            "evidence_sha256",
            "previous active promotion evidence",
        )
        if active.get("evidence_sha256") != promotion_evidence_sha:
            raise RuntimeError(
                "previous active promotion evidence SHA-256 does not match its index"
            )
        if (
            promotion_evidence.get("contract_sha256")
            != active.get("contract_sha256")
            or promotion_evidence.get("manifest_sha256")
            != active.get("manifest_sha256")
            or promotion_evidence.get("decision", {}).get("status") != "promoted"
            or promotion_evidence.get("decision", {}).get("gate") != "passed"
            or promotion_evidence.get("decision", {}).get("blockers")
        ):
            raise RuntimeError("previous active promotion evidence is not promotable")
        shard_records = support.get("shards")
        if not isinstance(shard_records, list):
            raise RuntimeError("previous active support has no shard records")
        expected_shards = {
            shard["shard_index"]: shard
            for shard in previous_manifest["run_shards"]
        }
        seen_shards: set[int] = set()
        expected_shard_files: set[str] = set()
        for shard_record in shard_records:
            if not isinstance(shard_record, dict) or not isinstance(
                shard_record.get("shard_index"), int
            ):
                raise RuntimeError("previous active support has an invalid shard record")
            shard_index = shard_record["shard_index"]
            if shard_index in seen_shards or shard_index not in expected_shards:
                raise RuntimeError(
                    "previous active support has duplicate or unexpected shard records"
                )
            seen_shards.add(shard_index)
            if shard_record.get("status") != "passed":
                raise RuntimeError("previous active support contains a failed shard")
            shard_name = (
                f"shard-{shard_index:04d}.evidence.v1.json"
            )
            expected_shard_files.add(shard_name.casefold())
            shard_file = shards_path / shard_name
            if not shard_file.is_file():
                raise RuntimeError(f"previous active shard evidence is missing: {shard_name}")
            shard_evidence = load_object(
                shard_file, "previous active shard evidence"
            )
            shard_evidence_sha = _recorded_hash(
                shard_evidence,
                "evidence_sha256",
                "previous active shard evidence",
            )
            if shard_evidence_sha != shard_record.get("evidence_sha256"):
                raise RuntimeError(
                    f"previous active shard evidence SHA-256 mismatch: {shard_name}"
                )
            validate_shard_evidence(
                shard_evidence,
                previous_contract,
                previous_manifest,
                expected_shards[shard_index],
            )
        if seen_shards != set(expected_shards):
            raise RuntimeError("previous active support shard coverage is incomplete")
        actual_shard_files = {
            path.name.casefold()
            for path in shards_path.iterdir()
            if path.is_file()
        }
        if actual_shard_files != expected_shard_files:
            raise RuntimeError("previous active shards directory coverage mismatch")
    return index, support


def _copy_previous_active_payload(
    previous_root: Path,
    output_root: Path,
    active: dict,
) -> None:
    active_directory = active.get("directory")
    if isinstance(active_directory, str) and active_directory:
        source = _safe_relative(
            previous_root, active_directory, "previous active support directory"
        )
        destination = _safe_relative(
            output_root, active_directory, "retained active support directory"
        )
        if destination.exists():
            raise RuntimeError(
                "retained active support directory collides with the new candidate"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source, destination)
        return
    source = _safe_relative(
        previous_root, active.get("support"), "previous active support path"
    )
    destination = _safe_relative(
        output_root, active.get("support"), "retained active support path"
    )
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def promote_support_catalog(
    contract_path: Path,
    manifest_path: Path,
    shard_evidence_root: Path,
    output_root: Path,
    *,
    previous_catalog_root: Path | None = None,
    contract_source_path: Path | None = None,
    mode: str = "preview",
    provenance: dict | None = None,
) -> dict:
    if mode not in {"preview", "promote"}:
        raise ValueError(f"unsupported history promotion mode: {mode!r}")
    contract = load_object(contract_path, "history contract")
    manifest = load_object(manifest_path, "history manifest")
    manifest_sha = validate_manifest(manifest, contract)
    contract_source = None
    contract_source_sha256 = None
    if contract_source_path is not None:
        contract_source = load_object(
            contract_source_path, "history contract source provenance"
        )
        contract_source_sha256 = file_sha256(contract_source_path)
    provenance = {
        key: value
        for key, value in (provenance or {}).items()
        if value not in (None, "")
    }
    previous_index: dict | None = None
    previous_active: dict | None = None
    if previous_catalog_root is not None:
        previous_index, _previous_support = _load_previous_support_catalog(
            previous_catalog_root
        )
        active = previous_index.get("active")
        previous_active = dict(active) if isinstance(active, dict) else None

    blockers: list[dict] = []
    found: dict[int, tuple[dict, Path, str]] = {}
    for path in sorted(
        shard_evidence_root.rglob("library-history-shard-evidence.v1.json")
    ):
        try:
            evidence = load_object(path, "history shard evidence")
            if (
                evidence.get("schema_version") != SCHEMA_VERSION
                or evidence.get("kind") != SHARD_EVIDENCE_KIND
            ):
                raise RuntimeError("unsupported schema or kind")
            evidence_sha = _recorded_hash(
                evidence, "evidence_sha256", "history shard evidence"
            )
            shard_index = evidence.get("shard_index")
            if not isinstance(shard_index, int):
                raise RuntimeError("shard evidence has no integer shard_index")
            if shard_index in found:
                blockers.append(
                    {"code": "duplicate-shard-evidence", "shard_index": shard_index}
                )
                continue
            found[shard_index] = (evidence, path, evidence_sha)
        except Exception as exc:
            blockers.append(
                {
                    "code": "invalid-shard-evidence",
                    "path": path.relative_to(shard_evidence_root).as_posix(),
                    "error": str(exc),
                }
            )

    shard_records: list[dict] = []
    shard_source_paths: dict[int, Path] = {}
    runtime_sdk_hashes: dict[str, set[str]] = {}
    passed_combinations = 0
    for shard in manifest["run_shards"]:
        shard_index = shard["shard_index"]
        item = found.pop(shard_index, None)
        if item is None:
            blockers.append(
                {"code": "missing-shard-evidence", "shard_index": shard_index}
            )
            continue
        evidence, evidence_path, evidence_sha = item
        shard_source_paths[shard_index] = evidence_path
        accepted = False
        try:
            validate_shard_evidence(evidence, contract, manifest, shard)
        except Exception as exc:
            blockers.append(
                {
                    "code": "invalid-shard-evidence",
                    "shard_index": shard_index,
                    "error": str(exc),
                }
            )
        else:
            if (
                evidence.get("status") != "passed"
                or evidence.get("passed_batch_count") != shard["batch_count"]
                or evidence.get("passed_combination_count")
                != shard["combination_count"]
            ):
                blockers.append({"code": "failed-shard", "shard_index": shard_index})
            else:
                passed_combinations += shard["combination_count"]
                for batch_record in evidence["batches"]:
                    runtime_sdk_hashes.setdefault(
                        batch_record["python_version"], set()
                    ).add(batch_record["runtime_sdk_sha256"].lower())
                accepted = True
        shard_records.append(
            {
                "shard_index": shard_index,
                "shard_sha256": shard["shard_sha256"],
                "evidence_sha256": evidence_sha,
                "status": "passed" if accepted else "failed",
                "batch_count": shard["batch_count"] if accepted else 0,
                "combination_count": shard["combination_count"] if accepted else 0,
            }
        )
    for shard_index in sorted(found):
        blockers.append(
            {"code": "unexpected-shard-evidence", "shard_index": shard_index}
        )
    if passed_combinations != manifest["combination_count"] and not any(
        blocker.get("code")
        in {"missing-shard-evidence", "failed-shard", "invalid-shard-evidence"}
        for blocker in blockers
    ):
        blockers.append(
            {
                "code": "combination-coverage-mismatch",
                "expected": manifest["combination_count"],
                "passed": passed_combinations,
            }
        )

    if (
        manifest.get("selection", {}).get("mode") == "full-history"
        and (
            manifest.get("combination_count") == 0
            or manifest.get("batch_count") == 0
            or manifest.get("run_shard_count") == 0
        )
    ):
        blockers.append({"code": "empty-full-history-selection"})

    runtime_sdks: list[dict] = []
    for python_version, hashes in sorted(runtime_sdk_hashes.items()):
        if len(hashes) != 1:
            blockers.append(
                {
                    "code": "runtime-sdk-hash-mismatch",
                    "python_version": python_version,
                    "sha256s": sorted(hashes),
                }
            )
            continue
        runtime_sdks.append(
            {"python_version": python_version, "sha256": next(iter(hashes))}
        )

    if blockers:
        decision_status = "frozen"
        gate = "failed"
    elif mode == "preview":
        decision_status = (
            "eligible"
            if manifest.get("selection", {}).get("mode") == "full-history"
            else "preview-passed"
        )
        gate = "passed"
    else:
        decision_status = "promoted"
        gate = "passed"
    if (
        mode == "promote"
        and manifest.get("selection", {}).get("mode") != "full-history"
    ):
        blockers.append({"code": "non-full-history-selection"})
        decision_status = "frozen"
        gate = "failed"
    decision = {
        "mode": mode,
        "status": decision_status,
        "gate": gate,
        "blockers": blockers,
    }
    support = {
        "schema_version": SCHEMA_VERSION,
        "kind": SUPPORT_KIND,
        "status": "verified" if not blockers else "failed",
        "contract_sha256": manifest["contract_sha256"],
        "manifest_sha256": manifest_sha,
        "selection": manifest.get("selection"),
        "contract_source": contract_source,
        "contract_source_sha256": contract_source_sha256,
        "expected_combination_count": manifest["combination_count"],
        "verified_combination_count": passed_combinations,
        "expected_batch_count": manifest["batch_count"],
        "verified_batch_count": sum(
            int(record.get("batch_count") or 0)
            for record in shard_records
            if record.get("status") == "passed"
        ),
        "expected_shard_count": manifest["run_shard_count"],
        "verified_shard_count": sum(
            record.get("status") == "passed" for record in shard_records
        ),
        "runtime_sdks": runtime_sdks,
        "shards": shard_records,
        "provenance": provenance,
    }
    support["support_sha256"] = canonical_sha256(support)

    promotion_evidence = {
        "schema_version": SCHEMA_VERSION,
        "kind": PROMOTION_EVIDENCE_KIND,
        "contract_sha256": manifest["contract_sha256"],
        "manifest_sha256": manifest_sha,
        "expected_shard_count": manifest["run_shard_count"],
        "received_shard_count": len(shard_records),
        "expected_combination_count": manifest["combination_count"],
        "passed_combination_count": passed_combinations,
        "runtime_sdks": runtime_sdks,
        "shards": shard_records,
        "decision": decision,
        "provenance": provenance,
    }
    promotion_evidence["evidence_sha256"] = canonical_sha256(promotion_evidence)

    candidate_directory = (
        f"candidates/{manifest['contract_sha256'][:16]}/{manifest_sha[:16]}/"
        f"{promotion_evidence['evidence_sha256'][:16]}"
    )
    candidate = {
        "contract_sha256": manifest["contract_sha256"],
        "manifest_sha256": manifest_sha,
        "selection": manifest.get("selection"),
        "directory": candidate_directory,
        "contract": f"{candidate_directory}/library-version-contract.json",
        "contract_source": (
            f"{candidate_directory}/contract-source.v1.json"
            if contract_source_path is not None
            else None
        ),
        "manifest": f"{candidate_directory}/library-history-manifest.json",
        "support": f"{candidate_directory}/library-history-support.v1.json",
        "support_sha256": support["support_sha256"],
        "evidence": f"{candidate_directory}/promotion-evidence.v1.json",
        "evidence_sha256": promotion_evidence["evidence_sha256"],
        "shards": f"{candidate_directory}/shards",
        "status": decision_status,
        "provenance": provenance,
    }
    active = previous_active
    proposed_active = None
    if decision_status == "promoted":
        active = {
            "contract_sha256": manifest["contract_sha256"],
            "manifest_sha256": manifest_sha,
            "directory": candidate["directory"],
            "contract": candidate["contract"],
            "contract_source": candidate["contract_source"],
            "manifest": candidate["manifest"],
            "support": candidate["support"],
            "support_sha256": support["support_sha256"],
            "evidence": candidate["evidence"],
            "evidence_sha256": candidate["evidence_sha256"],
            "shards": candidate["shards"],
            "verified_combination_count": manifest["combination_count"],
            "provenance": provenance,
        }
    elif decision_status == "eligible":
        proposed_active = {
            "contract_sha256": manifest["contract_sha256"],
            "manifest_sha256": manifest_sha,
            "directory": candidate["directory"],
            "contract": candidate["contract"],
            "contract_source": candidate["contract_source"],
            "manifest": candidate["manifest"],
            "support": candidate["support"],
            "support_sha256": support["support_sha256"],
            "evidence": candidate["evidence"],
            "evidence_sha256": candidate["evidence_sha256"],
            "shards": candidate["shards"],
            "verified_combination_count": manifest["combination_count"],
            "provenance": provenance,
        }
    index = {
        "schema_version": SCHEMA_VERSION,
        "kind": SUPPORT_INDEX_KIND,
        "status": "active" if active is not None else "uninitialized",
        "active": active,
        "candidate": candidate,
        "proposed_active": proposed_active,
        "previous_active_manifest_sha256": (
            previous_active.get("manifest_sha256")
            if previous_active is not None
            else None
        ),
        "decision": decision,
    }
    index["index_sha256"] = canonical_sha256(index)

    if output_root.exists():
        shutil.rmtree(output_root)
    if (
        previous_active is not None
        and previous_catalog_root is not None
        and decision_status != "promoted"
    ):
        _copy_previous_active_payload(
            previous_catalog_root,
            output_root,
            previous_active,
        )
    candidate_root = output_root / candidate_directory
    candidate_root.mkdir(parents=True, exist_ok=False)
    shutil.copy2(contract_path, candidate_root / "library-version-contract.json")
    shutil.copy2(manifest_path, candidate_root / "library-history-manifest.json")
    if contract_source_path is not None:
        shutil.copy2(contract_source_path, candidate_root / "contract-source.v1.json")
    write_object(candidate_root / "library-history-support.v1.json", support)
    write_object(candidate_root / "promotion-evidence.v1.json", promotion_evidence)
    shard_output = candidate_root / "shards"
    shard_output.mkdir(parents=True, exist_ok=True)
    for evidence in shard_records:
        shutil.copy2(
            shard_source_paths[evidence["shard_index"]],
            shard_output / f"shard-{evidence['shard_index']:04d}.evidence.v1.json",
        )
    write_object(output_root / "index.v1.json", index)
    (output_root / "promotion-summary.md").write_text(
        build_promotion_summary(index, promotion_evidence),
        encoding="utf-8",
        newline="\n",
    )
    return index


def build_promotion_summary(index: dict, evidence: dict) -> str:
    decision = index["decision"]
    active = index.get("active")
    proposed = index.get("proposed_active")
    lines = [
        "## StaticPython weekly history support promotion",
        "",
        f"- Decision: `{decision['status']}` (`{decision['gate']}`)",
        f"- Contract: `{evidence['contract_sha256']}`",
        f"- Manifest: `{evidence['manifest_sha256']}`",
        f"- Shards: `{evidence['received_shard_count']}/{evidence['expected_shard_count']}`",
        f"- Combinations: `{evidence['passed_combination_count']}/{evidence['expected_combination_count']}`",
        f"- Active manifest: `{active.get('manifest_sha256') if isinstance(active, dict) else '<none>'}`",
        f"- Proposed manifest: `{proposed.get('manifest_sha256') if isinstance(proposed, dict) else '<none>'}`",
        "",
    ]
    if decision["blockers"]:
        lines.extend(["### Promotion blockers", ""])
        for blocker in decision["blockers"]:
            identity = blocker.get("shard_index", blocker.get("batch_id", ""))
            suffix = f" ({identity})" if identity != "" else ""
            lines.append(f"- `{blocker.get('code', 'unknown')}`{suffix}")
        lines.append("")
    return "\n".join(lines)


def _provenance(args: argparse.Namespace) -> dict:
    return {
        "repository": getattr(args, "repository", None),
        "run_id": getattr(args, "run_id", None),
        "run_attempt": getattr(args, "run_attempt", None),
        "run_url": getattr(args, "run_url", None),
        "source_commit": getattr(args, "source_commit", None),
        "source_ref": getattr(args, "source_ref", None),
        "event_name": getattr(args, "event_name", None),
        "artifact": getattr(args, "artifact", None),
    }


def _add_provenance_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--repository")
    parser.add_argument("--run-id")
    parser.add_argument("--run-attempt")
    parser.add_argument("--run-url")
    parser.add_argument("--source-commit")
    parser.add_argument("--source-ref")
    parser.add_argument("--event-name")
    parser.add_argument("--artifact")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Plan, finalize, and promote immutable StaticPython history evidence."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    prepare = commands.add_parser("prepare-shard")
    prepare.add_argument("--contract", type=Path, required=True)
    prepare.add_argument("--manifest", type=Path, required=True)
    prepare.add_argument("--shard-index", type=int, required=True)
    prepare.add_argument("--plan-artifact", required=True)
    prepare.add_argument("--artifact-suffix")
    prepare.add_argument("--plan-output", type=Path, required=True)
    prepare.add_argument("--matrix-output", type=Path, required=True)
    prepare.add_argument("--github-output", type=Path)

    finalize = commands.add_parser("finalize-shard")
    finalize.add_argument("--contract", type=Path, required=True)
    finalize.add_argument("--manifest", type=Path, required=True)
    finalize.add_argument("--evidence-root", type=Path, required=True)
    finalize.add_argument("--shard-index", type=int, required=True)
    finalize.add_argument("--output", type=Path, required=True)
    _add_provenance_arguments(finalize)

    promote = commands.add_parser("promote")
    promote.add_argument("--contract", type=Path, required=True)
    promote.add_argument("--manifest", type=Path, required=True)
    promote.add_argument("--shard-evidence-root", type=Path, required=True)
    promote.add_argument("--previous-catalog", type=Path)
    promote.add_argument("--contract-source", type=Path)
    promote.add_argument("--mode", choices=("preview", "promote"), required=True)
    promote.add_argument("--output", type=Path, required=True)
    _add_provenance_arguments(promote)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.command == "prepare-shard":
        contract = load_object(args.contract, "history contract")
        manifest = load_object(args.manifest, "history manifest")
        plan, matrix = prepare_shard_plan(
            contract,
            manifest,
            args.shard_index,
            plan_artifact=args.plan_artifact,
            artifact_suffix=args.artifact_suffix,
        )
        write_object(args.plan_output, plan)
        write_object(args.matrix_output, matrix)
        if args.github_output is not None:
            args.github_output.parent.mkdir(parents=True, exist_ok=True)
            with args.github_output.open("a", encoding="utf-8", newline="\n") as output:
                output.write(
                    "matrix="
                    + json.dumps(
                        matrix,
                        ensure_ascii=False,
                        sort_keys=True,
                        separators=(",", ":"),
                    )
                    + "\n"
                )
                output.write(f"has_batches={str(bool(matrix['include'])).lower()}\n")
                output.write(f"shard_sha256={plan['shard']['shard_sha256']}\n")
        print(
            f"[library-history] shard {args.shard_index}: {len(matrix['include'])} batch job(s)"
        )
        return 0
    if args.command == "finalize-shard":
        evidence = finalize_shard(
            args.contract,
            args.manifest,
            args.evidence_root,
            args.shard_index,
            args.output,
            provenance=_provenance(args),
        )
        print(
            f"[library-history] shard {args.shard_index} evidence: {evidence['status']} "
            f"({evidence['passed_combination_count']}/"
            f"{evidence['expected_combination_count']})"
        )
        return 0
    index = promote_support_catalog(
        args.contract,
        args.manifest,
        args.shard_evidence_root,
        args.output,
        previous_catalog_root=args.previous_catalog,
        contract_source_path=args.contract_source,
        mode=args.mode,
        provenance=_provenance(args),
    )
    print(
        f"[library-history] support promotion {index['decision']['status']}: "
        f"active={index['active']['manifest_sha256'] if index['active'] else '<none>'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
