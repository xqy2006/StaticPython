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
    payload = json.loads(path.read_text(encoding="utf-8"))
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


def runtime_artifact_name(contract_sha256: str, python_version: str) -> str:
    if not SHA256_PATTERN.fullmatch(contract_sha256):
        raise RuntimeError("runtime artifact contract SHA-256 is invalid")
    if not re.fullmatch(
        r"3\.(11|12|13|14|15)\.[0-9]+(?:(?:a|b|rc)[0-9]+)?", python_version
    ):
        raise RuntimeError(
            f"runtime artifact Python version is invalid: {python_version!r}"
        )
    return f"library-history-runtime-{contract_sha256[:16].lower()}-py{python_version}"


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
    selected = history_batches.candidate_combinations(
        contract,
        smoke_library=selection.get("smoke_library"),
        smoke_python_series=selection.get("smoke_python_series"),
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
                manifest["contract_sha256"], batch["python_version"]
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


def _validate_file_records(evidence_root: Path, records: object) -> None:
    if not isinstance(records, list):
        raise RuntimeError("batch evidence files must be an array")
    seen: set[str] = set()
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
            ):
                value = result.get(field)
                if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
                    raise RuntimeError(
                        f"passed batch result has no valid {field}: {key!r}"
                    )
            if result["runtime_sdk_sha256"].lower() != runtime_sdk_sha.lower():
                raise RuntimeError(f"passed batch result runtime SDK mismatch: {key!r}")
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
    _validate_file_records(evidence_root, evidence.get("files"))
    all_passed = all(result.get("status") == "passed" for result in results)
    if all_passed and not evidence.get("files"):
        raise RuntimeError("passed batch evidence has no immutable files")
    expected_status = "passed" if all_passed else "failed"
    if evidence.get("status") != expected_status:
        raise RuntimeError(
            f"batch evidence aggregate status mismatch: {batch['batch_id']}"
        )
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
                "status": evidence["status"],
                "combination_count": batch["combination_count"],
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
    return index, support


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
    previous_support: dict | None = None
    previous_active: dict | None = None
    if previous_catalog_root is not None:
        previous_index, previous_support = _load_previous_support_catalog(
            previous_catalog_root
        )
        active = previous_index.get("active")
        previous_active = dict(active) if isinstance(active, dict) else None

    blockers: list[dict] = []
    found: dict[int, dict] = {}
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
            evidence = dict(evidence)
            evidence["_path"] = path
            evidence["_validated_sha256"] = evidence_sha
            found[shard_index] = evidence
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
    passed_combinations = 0
    for shard in manifest["run_shards"]:
        shard_index = shard["shard_index"]
        evidence = found.pop(shard_index, None)
        if evidence is None:
            blockers.append(
                {"code": "missing-shard-evidence", "shard_index": shard_index}
            )
            continue
        shard_source_paths[shard_index] = evidence["_path"]
        accepted = False
        mismatches = [
            key
            for key, expected in (
                ("contract_sha256", manifest["contract_sha256"]),
                ("manifest_sha256", manifest_sha),
                ("shard_sha256", shard["shard_sha256"]),
                ("expected_batch_count", shard["batch_count"]),
                ("expected_combination_count", shard["combination_count"]),
            )
            if evidence.get(key) != expected
        ]
        if mismatches:
            blockers.append(
                {
                    "code": "shard-evidence-mismatch",
                    "shard_index": shard_index,
                    "fields": mismatches,
                }
            )
        elif (
            evidence.get("status") != "passed"
            or evidence.get("passed_batch_count") != shard["batch_count"]
            or evidence.get("passed_combination_count") != shard["combination_count"]
        ):
            blockers.append({"code": "failed-shard", "shard_index": shard_index})
        else:
            passed_combinations += shard["combination_count"]
            accepted = True
        shard_records.append(
            {
                "shard_index": shard_index,
                "shard_sha256": shard["shard_sha256"],
                "evidence_sha256": evidence["_validated_sha256"],
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
        in {"missing-shard-evidence", "failed-shard", "shard-evidence-mismatch"}
        for blocker in blockers
    ):
        blockers.append(
            {
                "code": "combination-coverage-mismatch",
                "expected": manifest["combination_count"],
                "passed": passed_combinations,
            }
        )

    if blockers:
        decision_status = "frozen"
        gate = "failed"
    elif mode == "preview":
        decision_status = "eligible"
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
        "shards": shard_records,
        "provenance": provenance,
    }
    support["support_sha256"] = canonical_sha256(support)

    candidate_directory = f"candidates/{manifest['contract_sha256']}/{manifest_sha}"
    promotion_evidence = {
        "schema_version": SCHEMA_VERSION,
        "kind": PROMOTION_EVIDENCE_KIND,
        "contract_sha256": manifest["contract_sha256"],
        "manifest_sha256": manifest_sha,
        "expected_shard_count": manifest["run_shard_count"],
        "received_shard_count": len(shard_records),
        "expected_combination_count": manifest["combination_count"],
        "passed_combination_count": passed_combinations,
        "shards": shard_records,
        "decision": decision,
        "provenance": provenance,
    }
    promotion_evidence["evidence_sha256"] = canonical_sha256(promotion_evidence)

    active = previous_active
    active_support = previous_support
    proposed_active = None
    if decision_status == "promoted":
        active_support = support
        active = {
            "contract_sha256": manifest["contract_sha256"],
            "manifest_sha256": manifest_sha,
            "support": "active/library-history-support.v1.json",
            "support_sha256": support["support_sha256"],
            "verified_combination_count": manifest["combination_count"],
            "provenance": provenance,
        }
    elif decision_status == "eligible":
        proposed_active = {
            "contract_sha256": manifest["contract_sha256"],
            "manifest_sha256": manifest_sha,
            "support_sha256": support["support_sha256"],
            "verified_combination_count": manifest["combination_count"],
            "provenance": provenance,
        }

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
        "evidence": f"{candidate_directory}/promotion-evidence.v1.json",
        "status": decision_status,
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
    candidate_root = output_root / candidate_directory
    candidate_root.mkdir(parents=True, exist_ok=True)
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
    if active_support is not None:
        write_object(
            output_root / "active" / "library-history-support.v1.json", active_support
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
