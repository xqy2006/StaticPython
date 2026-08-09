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

import library_history_evidence as history_evidence
import library_version_contract as version_contract


SCHEMA_VERSION = 1
INDEX_KIND = "staticpython-library-contract-index"
EVIDENCE_KIND = "staticpython-library-contract-promotion-evidence"
SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
DEFERRED_REASON = "weekly-history-shards"
MATRIX_LIMIT = 256
MAX_CANDIDATES_PER_BATCH = 2
SAFE_ARTIFACT_SLUG_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")


def _canonical_sha256(payload: dict) -> str:
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_object(path: Path, description: str) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError(f"{description} must be a JSON object: {path}")
    return payload


def _safe_catalog_path(root: Path, relative: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise RuntimeError("catalog path must be a non-empty string")
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise RuntimeError(f"catalog path escapes its root: {relative!r}") from exc
    return candidate


def _record_identity(record: dict, *, require_source: bool = False) -> tuple[str, str, str, str | None]:
    library = record.get("library")
    version = record.get("version")
    python_version = record.get("python_version")
    if not all(isinstance(value, str) and value for value in (library, version, python_version)):
        raise RuntimeError(f"contract combination has invalid identity fields: {record!r}")
    source_sha256: str | None = None
    source = record.get("source")
    if isinstance(source, dict):
        raw_sha256 = source.get("sha256")
        if isinstance(raw_sha256, str) and SHA256_PATTERN.fullmatch(raw_sha256):
            source_sha256 = raw_sha256.lower()
    if require_source and source_sha256 is None:
        raise RuntimeError(
            f"contract combination has no verifiable source SHA-256: {library} {version} {python_version}"
        )
    return library.casefold(), version, python_version, source_sha256


def _matrix_identity(record: dict) -> tuple[str, str, str, str]:
    library = record.get("library")
    version = record.get("version")
    python_version = record.get("python_version")
    source_sha256 = record.get("source_sha256")
    if not all(isinstance(value, str) and value for value in (library, version, python_version)):
        raise RuntimeError(f"validation matrix record has invalid identity fields: {record!r}")
    if not isinstance(source_sha256, str) or not SHA256_PATTERN.fullmatch(source_sha256):
        raise RuntimeError(f"validation matrix record has invalid source SHA-256: {record!r}")
    return library.casefold(), version, python_version, source_sha256.lower()


def _verified_identity(record: dict) -> tuple[str, str, str, str]:
    library = record.get("library")
    version = record.get("version")
    python_version = record.get("python_version")
    source_sha256 = record.get("source_sha256")
    if not all(isinstance(value, str) and value for value in (library, version, python_version)):
        raise RuntimeError(f"verified combination has invalid identity fields: {record!r}")
    if not isinstance(source_sha256, str) or not SHA256_PATTERN.fullmatch(source_sha256):
        raise RuntimeError(f"verified combination has invalid source SHA-256: {record!r}")
    return library.casefold(), version, python_version, source_sha256.lower()


def _normalized_verified_record(matrix_record: dict, report: dict) -> dict:
    return {
        "library": matrix_record["library"],
        "version": matrix_record["version"],
        "python_version": matrix_record["python_version"],
        "source_sha256": matrix_record["source_sha256"].lower(),
        "pack_sha256": str(report["pack_sha256"]).lower(),
        "validation_reason": matrix_record.get("validation_reason"),
    }


def _load_previous_catalog(root: Path) -> tuple[dict | None, dict | None]:
    index_path = root / "index.v1.json"
    if not index_path.is_file():
        raise RuntimeError(f"previous catalog has no index.v1.json: {root}")
    index = _load_object(index_path, "previous catalog index")
    if index.get("schema_version") != SCHEMA_VERSION or index.get("kind") != INDEX_KIND:
        raise RuntimeError("previous catalog index has an unsupported schema or kind")
    recorded_index_sha = index.get("index_sha256")
    if not isinstance(recorded_index_sha, str) or not SHA256_PATTERN.fullmatch(recorded_index_sha):
        raise RuntimeError("previous catalog index has no valid index_sha256")
    canonical_index = {key: value for key, value in index.items() if key != "index_sha256"}
    if _canonical_sha256(canonical_index) != recorded_index_sha.lower():
        raise RuntimeError("previous catalog index SHA-256 mismatch")

    active = index.get("active")
    if active is None:
        return index, None
    if not isinstance(active, dict):
        raise RuntimeError("previous catalog active record must be an object or null")
    contract_path = _safe_catalog_path(root, active.get("contract"))
    if not contract_path.is_file():
        raise RuntimeError(f"previous active contract is missing: {contract_path}")
    contract = _load_object(contract_path, "previous active contract")
    version_contract.validate_contract_integrity(contract)
    if active.get("contract_sha256") != contract.get("contract_sha256"):
        raise RuntimeError("previous active contract hash does not match its index")
    verified = active.get("verified_combinations")
    if not isinstance(verified, list):
        raise RuntimeError("previous active record has no verified_combinations array")
    for record in verified:
        if not isinstance(record, dict):
            raise RuntimeError("previous verified combination must be an object")
        _verified_identity(record)
    return index, contract


def _matching_history_validation(root: Path, candidate: dict) -> dict | None:
    index, support = history_evidence._load_previous_support_catalog(root)
    active = index.get("active")
    if not isinstance(active, dict) or not isinstance(support, dict):
        return None
    candidate_sha = candidate.get("contract_sha256")
    if active.get("contract_sha256") != candidate_sha:
        return None
    # Legacy support records without an immutable active directory receive a
    # deliberately narrower compatibility check in the history loader. They
    # remain useful as last-known-good context, but are not sufficient proof
    # for adopting a deferred discovery contract.
    if not isinstance(active.get("directory"), str) or not active["directory"]:
        return None
    if support.get("selection", {}).get("mode") != "full-history":
        return None
    contract_path = history_evidence._safe_relative(
        root,
        active.get("contract"),
        "history-validated contract path",
    )
    history_contract = history_evidence.load_object(
        contract_path,
        "history-validated contract",
    )
    if history_contract != candidate:
        raise RuntimeError(
            "history support contract payload does not match the exact candidate contract"
        )
    return {
        "contract_sha256": candidate_sha,
        "index_sha256": index.get("index_sha256"),
        "manifest_sha256": active.get("manifest_sha256"),
        "support_sha256": active.get("support_sha256"),
        "evidence_sha256": active.get("evidence_sha256"),
        "verified_combination_count": active.get("verified_combination_count"),
        "selection": support.get("selection"),
        "provenance": active.get("provenance"),
    }


def _legacy_active(contract: dict) -> dict:
    return {
        "contract_sha256": contract["contract_sha256"],
        "contract": "active/library-version-contract.json",
        "promotion_basis": "legacy-discovery-baseline",
        "verified_combinations": [],
        "provenance": {
            "status": "legacy-workflow-artifact",
            "embedded_run_provenance": False,
        },
    }


def _validation_reports(root: Path | None) -> tuple[dict[tuple[str, str, str], dict], list[dict]]:
    if root is None or not root.exists():
        return {}, []
    reports: dict[tuple[str, str, str], dict] = {}
    duplicates: list[dict] = []
    for path in sorted(root.rglob("library-contract-build-report.json")):
        report = _load_object(path, "library validation report")
        identity_values = (
            report.get("library"),
            report.get("version"),
            report.get("python_version"),
        )
        if not all(isinstance(value, str) and value for value in identity_values):
            duplicates.append(
                {
                    "reason": "invalid-report-identity",
                    "report": path.relative_to(root).as_posix(),
                }
            )
            continue
        key = (str(identity_values[0]).casefold(), str(identity_values[1]), str(identity_values[2]))
        normalized = {
            "library": identity_values[0],
            "version": identity_values[1],
            "python_version": identity_values[2],
            "status": report.get("status"),
            "source_archive_sha256": report.get("source_archive_sha256"),
            "pack_sha256": report.get("pack_sha256"),
            "pe_dependencies": report.get("pe_dependencies"),
            "report": path.relative_to(root).as_posix(),
            "report_sha256": _file_sha256(path),
        }
        if key in reports:
            duplicates.append(
                {
                    "reason": "duplicate-report",
                    "library": identity_values[0],
                    "version": identity_values[1],
                    "python_version": identity_values[2],
                    "reports": [reports[key]["report"], normalized["report"]],
                }
            )
            continue
        reports[key] = normalized
    return reports, duplicates


def _matrix_artifacts(matrix: dict, matrix_records: list[dict]) -> dict[str, str]:
    """Bind every candidate to the exact Actions artifact that carries its report."""
    include_by_slug: dict[str, dict] = {}
    for record in matrix_records:
        slug = record.get("slug")
        if not isinstance(slug, str) or SAFE_ARTIFACT_SLUG_PATTERN.fullmatch(slug) is None:
            raise RuntimeError(f"validation matrix record has an invalid artifact slug: {record!r}")
        if slug in include_by_slug:
            raise RuntimeError(f"validation matrix contains duplicate candidate slug: {slug}")
        include_by_slug[slug] = record

    raw_batches = matrix.get("batches")
    if raw_batches is None:
        # Compatibility for evidence produced before candidates were grouped into
        # bounded jobs. In that layout each candidate had its own artifact.
        return {slug: f"library-contract-{slug}" for slug in include_by_slug}
    if not isinstance(raw_batches, list):
        raise RuntimeError("validation matrix batches must be an array")

    artifact_by_candidate: dict[str, str] = {}
    seen_batch_slugs: set[str] = set()
    for batch in raw_batches:
        if not isinstance(batch, dict):
            raise RuntimeError("validation matrix batch records must be objects")
        batch_slug = batch.get("slug")
        if (
            not isinstance(batch_slug, str)
            or SAFE_ARTIFACT_SLUG_PATTERN.fullmatch(batch_slug) is None
        ):
            raise RuntimeError(f"validation matrix batch has an invalid artifact slug: {batch!r}")
        if batch_slug in seen_batch_slugs:
            raise RuntimeError(f"validation matrix contains duplicate batch slug: {batch_slug}")
        seen_batch_slugs.add(batch_slug)

        candidate_count = batch.get("candidate_count")
        if (
            not isinstance(candidate_count, int)
            or isinstance(candidate_count, bool)
            or not 1 <= candidate_count <= MAX_CANDIDATES_PER_BATCH
        ):
            raise RuntimeError(f"validation matrix batch has an invalid candidate count: {batch!r}")
        candidates_json = batch.get("candidates_json")
        if not isinstance(candidates_json, str) or not candidates_json:
            raise RuntimeError("validation matrix batch has no candidates_json payload")
        try:
            candidates = json.loads(candidates_json)
        except json.JSONDecodeError as exc:
            raise RuntimeError("validation matrix batch candidates_json is invalid") from exc
        if not isinstance(candidates, list) or len(candidates) != candidate_count:
            raise RuntimeError("validation matrix batch candidate count does not match its payload")

        artifact = f"library-contract-{batch_slug}"
        for candidate in candidates:
            if not isinstance(candidate, dict):
                raise RuntimeError("validation matrix batch candidates must be objects")
            candidate_slug = candidate.get("slug")
            if not isinstance(candidate_slug, str) or candidate_slug not in include_by_slug:
                raise RuntimeError("validation matrix batch contains an unknown candidate slug")
            if candidate != include_by_slug[candidate_slug]:
                raise RuntimeError(
                    f"validation matrix batch payload differs from include record: {candidate_slug}"
                )
            if candidate_slug in artifact_by_candidate:
                raise RuntimeError(
                    f"validation matrix candidate appears in multiple batches: {candidate_slug}"
                )
            artifact_by_candidate[candidate_slug] = artifact

    missing = sorted(set(include_by_slug) - set(artifact_by_candidate))
    if missing:
        raise RuntimeError(
            "validation matrix batches omit candidate artifacts: " + ", ".join(missing)
        )
    return artifact_by_candidate


def _validate_matrix_and_reports(
    delta: dict,
    matrix: dict | None,
    validation_root: Path | None,
) -> tuple[dict, list[dict], list[dict]]:
    blockers: list[dict] = []
    matrix_records: list[dict] = []
    artifact_by_candidate: dict[str, str] = {}
    raw_deferred = None
    if matrix is None:
        if delta.get("new_candidates") and not (delta.get("drifted_candidates") or delta.get("regressions")):
            blockers.append({"code": "missing-validation-matrix", "count": 1})
    else:
        include = matrix.get("include")
        if not isinstance(include, list):
            raise RuntimeError("validation matrix include must be an array")
        if any(not isinstance(record, dict) for record in include):
            raise RuntimeError("validation matrix records must be objects")
        matrix_records = list(include)
        artifact_by_candidate = _matrix_artifacts(matrix, matrix_records)
        raw_deferred = matrix.get("deferred")

    delta_candidates = delta.get("new_candidates")
    if not isinstance(delta_candidates, list):
        raise RuntimeError("delta new_candidates must be an array")
    delta_identities = {
        _record_identity(record, require_source=True)
        for record in delta_candidates
        if isinstance(record, dict)
    }
    matrix_new_identities = {
        _matrix_identity(record)
        for record in matrix_records
        if record.get("validation_reason") == "new-candidate"
    }
    deferred = None
    if raw_deferred is not None:
        matrix_limit = (
            raw_deferred.get("matrix_limit") if isinstance(raw_deferred, dict) else None
        )
        max_candidates_per_batch = (
            raw_deferred.get("max_candidates_per_batch")
            if isinstance(raw_deferred, dict)
            else None
        )
        incremental_candidate_limit = (
            raw_deferred.get("incremental_candidate_limit")
            if isinstance(raw_deferred, dict)
            else None
        )
        valid_deferred = (
            isinstance(raw_deferred, dict)
            and raw_deferred.get("reason") == DEFERRED_REASON
            and raw_deferred.get("candidate_count") == len(delta_candidates)
            and raw_deferred.get("candidate_count") == len(delta_identities)
            and raw_deferred.get("contract_sha256") == delta.get("current_contract_sha256")
            and isinstance(matrix_limit, int)
            and not isinstance(matrix_limit, bool)
            and 0 < matrix_limit <= MATRIX_LIMIT
            and isinstance(max_candidates_per_batch, int)
            and not isinstance(max_candidates_per_batch, bool)
            and 0 < max_candidates_per_batch <= MAX_CANDIDATES_PER_BATCH
            and isinstance(incremental_candidate_limit, int)
            and not isinstance(incremental_candidate_limit, bool)
            and incremental_candidate_limit == matrix_limit * max_candidates_per_batch
            and not matrix_new_identities
            and len(delta_candidates) > incremental_candidate_limit
        )
        if valid_deferred:
            deferred = dict(raw_deferred)
        else:
            blockers.append({"code": "invalid-history-deferral", "count": 1})
    if deferred is None and delta_identities != matrix_new_identities and not (
        matrix is None and (delta.get("drifted_candidates") or delta.get("regressions"))
    ):
        blockers.append(
            {
                "code": "matrix-delta-mismatch",
                "delta_candidate_count": len(delta_identities),
                "matrix_candidate_count": len(matrix_new_identities),
            }
        )

    reports, duplicate_reports = _validation_reports(validation_root)
    if duplicate_reports:
        blockers.append(
            {
                "code": "invalid-validation-reports",
                "count": len(duplicate_reports),
                "records": duplicate_reports,
            }
        )

    expected_keys: set[tuple[str, str, str]] = set()
    passed: list[dict] = []
    missing: list[dict] = []
    failed: list[dict] = []
    verified_new: list[dict] = []
    for matrix_record in matrix_records:
        identity = _matrix_identity(matrix_record)
        matrix_slug = matrix_record["slug"]
        key = identity[:3]
        if key in expected_keys:
            blockers.append(
                {
                    "code": "duplicate-matrix-identity",
                    "library": matrix_record.get("library"),
                    "version": matrix_record.get("version"),
                    "python_version": matrix_record.get("python_version"),
                }
            )
            continue
        expected_keys.add(key)
        report = reports.get(key)
        identity_record = {
            "library": matrix_record.get("library"),
            "version": matrix_record.get("version"),
            "python_version": matrix_record.get("python_version"),
            "source_sha256": identity[3],
            "validation_reason": matrix_record.get("validation_reason"),
            "artifact": artifact_by_candidate[matrix_slug],
        }
        if report is None:
            missing.append(identity_record)
            continue
        source_sha = report.get("source_archive_sha256")
        pack_sha = report.get("pack_sha256")
        pe_dependencies = report.get("pe_dependencies")
        if (
            report.get("status") != "passed"
            or not isinstance(source_sha, str)
            or source_sha.lower() != identity[3]
            or not isinstance(pack_sha, str)
            or not SHA256_PATTERN.fullmatch(pack_sha)
            or not isinstance(pe_dependencies, list)
            or not pe_dependencies
        ):
            failed.append({**identity_record, "report": report})
            continue
        passed_record = {**identity_record, "report": report}
        passed.append(passed_record)
        if matrix_record.get("validation_reason") == "new-candidate":
            verified_new.append(_normalized_verified_record(matrix_record, report))

    unexpected = [
        report
        for key, report in sorted(reports.items())
        if key not in expected_keys
    ]
    if missing:
        blockers.append({"code": "missing-validation", "count": len(missing)})
    if failed:
        blockers.append({"code": "failed-validation", "count": len(failed)})
    if unexpected:
        blockers.append({"code": "unexpected-validation", "count": len(unexpected)})

    validation = {
        "expected_count": len(matrix_records),
        "passed_count": len(passed),
        "missing": missing,
        "failed": failed,
        "unexpected": unexpected,
        "passed": passed,
        "deferred": deferred,
    }
    return validation, verified_new, blockers


def _merge_verified(previous: list[dict], added: list[dict]) -> list[dict]:
    records: dict[tuple[str, str, str, str], dict] = {}
    for record in [*previous, *added]:
        identity = _verified_identity(record)
        records[identity] = dict(record)
    return [records[key] for key in sorted(records)]


def promote_catalog(
    candidate_contract_path: Path,
    delta_path: Path,
    output_root: Path,
    *,
    matrix_path: Path | None = None,
    validation_root: Path | None = None,
    previous_catalog_root: Path | None = None,
    legacy_baseline_contract_path: Path | None = None,
    history_support_catalog_root: Path | None = None,
    mode: str = "preview",
    provenance: dict | None = None,
) -> dict:
    if mode not in {"preview", "promote"}:
        raise ValueError(f"unsupported promotion mode: {mode!r}")
    if previous_catalog_root is not None and legacy_baseline_contract_path is not None:
        raise ValueError("provide either a previous catalog or a legacy baseline, not both")

    provenance = {key: value for key, value in (provenance or {}).items() if value not in (None, "")}
    candidate = _load_object(candidate_contract_path, "candidate contract")
    version_contract.validate_contract_integrity(candidate)
    delta = _load_object(delta_path, "candidate delta")
    if delta.get("current_contract_sha256") != candidate.get("contract_sha256"):
        raise RuntimeError("candidate delta does not describe the candidate contract")
    matrix = None
    if matrix_path is not None and matrix_path.is_file():
        matrix = _load_object(matrix_path, "candidate validation matrix")

    previous_index: dict | None = None
    previous_contract: dict | None = None
    previous_active: dict | None = None
    if previous_catalog_root is not None:
        previous_index, previous_contract = _load_previous_catalog(previous_catalog_root)
        previous_active = previous_index.get("active")
    elif legacy_baseline_contract_path is not None:
        previous_contract = _load_object(legacy_baseline_contract_path, "legacy baseline contract")
        version_contract.validate_contract_integrity(previous_contract)
        previous_active = _legacy_active(previous_contract)

    blockers: list[dict] = []
    calculated_delta = version_contract.contract_delta(candidate, previous_contract)
    supplied_delta = delta
    if supplied_delta != calculated_delta:
        blockers.append({"code": "delta-integrity-mismatch", "count": 1})
    delta = calculated_delta
    drifted = delta.get("drifted_candidates")
    regressions = delta.get("regressions")
    new_unbuildable = delta.get("new_unbuildable")
    for name, records in (
        ("drifted_candidates", drifted),
        ("regressions", regressions),
        ("new_unbuildable", new_unbuildable),
    ):
        if not isinstance(records, list):
            raise RuntimeError(f"delta {name} must be an array")
    if drifted:
        blockers.append({"code": "source-drift", "count": len(drifted)})
    if regressions:
        blockers.append({"code": "candidate-regression", "count": len(regressions)})

    validation, verified_new, validation_blockers = _validate_matrix_and_reports(
        delta,
        matrix,
        validation_root,
    )
    blockers.extend(validation_blockers)
    history_validation = None
    if (
        validation.get("deferred") is not None
        and history_support_catalog_root is not None
    ):
        history_validation = _matching_history_validation(
            history_support_catalog_root,
            candidate,
        )

    bootstrap = previous_contract is None and bool(delta.get("baseline"))
    if previous_contract is None and not bootstrap:
        blockers.append({"code": "missing-last-known-good", "count": 1})

    previous_verified = []
    if isinstance(previous_active, dict):
        previous_verified = previous_active.get("verified_combinations", [])
    verified_keys = {
        _verified_identity(record)[:3]
        for record in previous_verified
        if isinstance(record, dict)
    }
    verified_regressions = [
        record
        for record in regressions
        if isinstance(record, dict) and _record_identity(record)[:3] in verified_keys
    ]
    verified_source_drift = [
        record
        for record in drifted
        if isinstance(record, dict) and _record_identity(record)[:3] in verified_keys
    ]

    candidate_sha = candidate["contract_sha256"]
    previous_sha = previous_contract.get("contract_sha256") if previous_contract is not None else None
    if blockers:
        decision_status = "frozen"
        gate_status = "failed"
    elif validation.get("deferred") is not None and history_validation is None:
        decision_status = "deferred"
        gate_status = "passed"
    elif previous_sha == candidate_sha:
        decision_status = "unchanged"
        gate_status = "passed"
    elif mode == "preview":
        decision_status = "eligible"
        gate_status = "passed"
    else:
        decision_status = "promoted"
        gate_status = "passed"

    decision = {
        "mode": mode,
        "status": decision_status,
        "gate": gate_status,
        "blockers": blockers,
    }
    evidence = {
        "schema_version": SCHEMA_VERSION,
        "kind": EVIDENCE_KIND,
        "candidate_contract_sha256": candidate_sha,
        "previous_active_contract_sha256": previous_sha,
        "provenance": provenance,
        "delta": {
            "baseline": bool(delta.get("baseline")),
            "new_candidates": delta.get("new_candidates", []),
            "new_unbuildable": new_unbuildable,
            "drifted_candidates": drifted,
            "regressions": regressions,
            "verified_source_drift": verified_source_drift,
            "verified_regressions": verified_regressions,
        },
        "supplied_delta_sha256": _canonical_sha256(supplied_delta),
        "calculated_delta_sha256": _canonical_sha256(calculated_delta),
        "validation": validation,
        "history_validation": history_validation,
        "decision": decision,
    }
    evidence["evidence_sha256"] = _canonical_sha256(evidence)

    candidate_directory = f"candidates/{candidate_sha}"
    candidate_record = {
        "contract_sha256": candidate_sha,
        "directory": candidate_directory,
        "contract": f"{candidate_directory}/library-version-contract.json",
        "delta": f"{candidate_directory}/library-version-delta.json",
        "evidence": f"{candidate_directory}/promotion-evidence.v1.json",
        "status": decision_status,
        "provenance": provenance,
    }

    active = dict(previous_active) if isinstance(previous_active, dict) else None
    active_contract = previous_contract
    if decision_status == "promoted":
        if bootstrap:
            promotion_basis = "discovery-baseline"
        elif history_validation is not None:
            promotion_basis = "weekly-history-validation"
        elif verified_new:
            promotion_basis = "incremental-validation"
        elif new_unbuildable:
            promotion_basis = "unbuildable-evidence-update"
        else:
            promotion_basis = "contract-metadata-update"
        active = {
            "contract_sha256": candidate_sha,
            "contract": "active/library-version-contract.json",
            "promotion_basis": promotion_basis,
            "verified_combinations": _merge_verified(previous_verified, verified_new),
            "history_validation": history_validation,
            "provenance": provenance,
        }
        active_contract = candidate

    proposed_active = None
    if decision_status == "eligible":
        proposed_active = {
            "contract_sha256": candidate_sha,
            "promotion_basis": (
                "discovery-baseline"
                if bootstrap
                else "weekly-history-validation"
                if history_validation is not None
                else "incremental-validation"
                if verified_new
                else "unbuildable-evidence-update"
                if new_unbuildable
                else "contract-metadata-update"
            ),
            "verified_combinations": _merge_verified(previous_verified, verified_new),
            "history_validation": history_validation,
            "provenance": provenance,
        }

    index = {
        "schema_version": SCHEMA_VERSION,
        "kind": INDEX_KIND,
        "status": "active" if active is not None else "uninitialized",
        "active": active,
        "candidate": candidate_record,
        "proposed_active": proposed_active,
        "previous_active_contract_sha256": previous_sha,
        "decision": decision,
    }
    index["index_sha256"] = _canonical_sha256(index)

    if output_root.exists():
        shutil.rmtree(output_root)
    candidate_root = output_root / candidate_directory
    candidate_root.mkdir(parents=True, exist_ok=True)
    shutil.copy2(candidate_contract_path, candidate_root / "library-version-contract.json")
    shutil.copy2(delta_path, candidate_root / "library-version-delta.json")
    (candidate_root / "promotion-evidence.v1.json").write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    if active_contract is not None:
        active_root = output_root / "active"
        active_root.mkdir(parents=True, exist_ok=True)
        (active_root / "library-version-contract.json").write_text(
            json.dumps(active_contract, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
            newline="\n",
        )
    (output_root / "index.v1.json").write_text(
        json.dumps(index, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    (output_root / "promotion-summary.md").write_text(
        build_summary(index, evidence),
        encoding="utf-8",
        newline="\n",
    )
    return index


def build_summary(index: dict, evidence: dict) -> str:
    decision = index["decision"]
    validation = evidence["validation"]
    delta = evidence["delta"]
    active = index.get("active")
    proposed = index.get("proposed_active")
    deferred = validation.get("deferred")
    history_validation = evidence.get("history_validation")
    lines = [
        "## StaticPython library contract promotion",
        "",
        f"- Decision: `{decision['status']}` (`{decision['gate']}`)",
        f"- Candidate: `{evidence['candidate_contract_sha256']}`",
        f"- Active: `{active.get('contract_sha256') if isinstance(active, dict) else '<none>'}`",
        f"- Proposed active: `{proposed.get('contract_sha256') if isinstance(proposed, dict) else '<none>'}`",
        f"- Validation: `{validation['passed_count']}/{validation['expected_count']}` passed",
        f"- Deferred to weekly history shards: `{deferred.get('candidate_count', 0) if isinstance(deferred, dict) else 0}`",
        f"- Matching full-history validation: `{bool(history_validation)}`",
        f"- New evidence-backed unbuildable records: `{len(delta['new_unbuildable'])}`",
        f"- Source drift records: `{len(delta['drifted_candidates'])}`",
        f"- Regression records: `{len(delta['regressions'])}`",
        f"- Blocking reasons: `{len(decision['blockers'])}`",
        "",
    ]
    if decision["blockers"]:
        lines.extend(["### Blocking reasons", ""])
        for blocker in decision["blockers"]:
            lines.append(f"- `{blocker.get('code', 'unknown')}`: {blocker.get('count', 1)}")
        lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Promote a validated library contract or freeze the last-known-good catalog."
    )
    parser.add_argument("--candidate-contract", type=Path, required=True)
    parser.add_argument("--delta", type=Path, required=True)
    parser.add_argument("--matrix", type=Path)
    parser.add_argument("--validation-root", type=Path)
    parser.add_argument("--history-support-catalog", type=Path)
    previous = parser.add_mutually_exclusive_group()
    previous.add_argument("--previous-catalog", type=Path)
    previous.add_argument("--legacy-baseline-contract", type=Path)
    parser.add_argument("--mode", choices=("preview", "promote"), required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository")
    parser.add_argument("--run-id")
    parser.add_argument("--run-attempt")
    parser.add_argument("--run-url")
    parser.add_argument("--source-commit")
    parser.add_argument("--source-ref")
    parser.add_argument("--event-name")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    provenance = {
        "repository": args.repository,
        "run_id": args.run_id,
        "run_attempt": args.run_attempt,
        "run_url": args.run_url,
        "source_commit": args.source_commit,
        "source_ref": args.source_ref,
        "event_name": args.event_name,
    }
    index = promote_catalog(
        args.candidate_contract,
        args.delta,
        args.output,
        matrix_path=args.matrix,
        validation_root=args.validation_root,
        previous_catalog_root=args.previous_catalog,
        legacy_baseline_contract_path=args.legacy_baseline_contract,
        history_support_catalog_root=args.history_support_catalog,
        mode=args.mode,
        provenance=provenance,
    )
    print(
        f"[library-contract-promotion] {index['decision']['status']}: "
        f"candidate={index['candidate']['contract_sha256']} "
        f"active={index['active']['contract_sha256'] if index['active'] else '<none>'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
