from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable


SCRIPT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_ROOT.parent
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build_library_contract_config as contract_config  # noqa: E402
import library_contract_build as contract_build  # noqa: E402
import library_history_evidence as history_evidence  # noqa: E402


SHA256_PATTERN = re.compile(r"^[0-9a-fA-F]{64}$")
CombinationExecutor = Callable[[dict, dict], tuple[dict, list[Path]]]


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip(".-")
    if not slug:
        raise RuntimeError(
            f"could not create a safe history result slug from {value!r}"
        )
    return slug[:160]


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def _validate_verifier_report(
    report: dict,
    *,
    runtime_sdk_sha256: str,
    pack_path: Path,
    library: str,
    version: str,
    python_version: str,
) -> dict:
    if report.get("status") != "passed" or report.get("failures"):
        raise RuntimeError("SDK-linked pack verifier did not pass")
    runtime = report.get("runtime_sdk")
    if not isinstance(runtime, dict):
        raise RuntimeError("SDK-linked pack verifier has no runtime_sdk record")
    expected_runtime = {
        "archive_sha256": runtime_sdk_sha256,
        "cpython_version": python_version,
        "runtime_abi": "staticpython-pack-v1-cp"
        + "".join(python_version.split(".")[:2]),
    }
    for key, expected in expected_runtime.items():
        if runtime.get(key) != expected:
            raise RuntimeError(
                f"SDK-linked pack verifier runtime {key} mismatch: "
                f"expected {expected!r}, got {runtime.get(key)!r}"
            )
    packs = report.get("packs")
    if not isinstance(packs, list) or len(packs) != 1 or not isinstance(packs[0], dict):
        raise RuntimeError("SDK-linked pack verifier must describe exactly one pack")
    expected_pack_sha = history_evidence.file_sha256(pack_path)
    expected_pack = {"name": library, "version": version}
    for key, expected in expected_pack.items():
        if packs[0].get(key) != expected:
            raise RuntimeError(
                f"SDK-linked pack verifier pack {key} mismatch: "
                f"expected {expected!r}, got {packs[0].get(key)!r}"
            )
    provisional_pack_sha = packs[0].get("sha256")
    if not isinstance(provisional_pack_sha, str) or not SHA256_PATTERN.fullmatch(
        provisional_pack_sha
    ):
        raise RuntimeError("SDK-linked pack verifier has no provisional pack SHA-256")
    pe_audit = report.get("pe_audit")
    dependencies = pe_audit.get("dependencies") if isinstance(pe_audit, dict) else None
    if (
        not isinstance(pe_audit, dict)
        or pe_audit.get("status") != "passed"
        or not isinstance(dependencies, list)
        or not dependencies
    ):
        raise RuntimeError("SDK-linked pack verifier has no passed PE dependency audit")
    smoke_tests = report.get("integration_smoke_tests")
    if not isinstance(smoke_tests, list) or not smoke_tests:
        raise RuntimeError("SDK-linked pack verifier has no integration smoke tests")
    failed_smokes = [
        record
        for record in smoke_tests
        if not isinstance(record, dict) or record.get("status") != "passed"
    ]
    if failed_smokes:
        raise RuntimeError(
            "SDK-linked pack verifier contains failed integration smoke tests"
        )
    executable_sha = report.get("executable_sha256")
    if not isinstance(executable_sha, str) or not SHA256_PATTERN.fullmatch(
        executable_sha
    ):
        raise RuntimeError("SDK-linked pack verifier has no executable SHA-256")
    return {
        "runtime_abi": runtime["runtime_abi"],
        "runtime_sdk_sha256": runtime_sdk_sha256,
        "pack_sha256": expected_pack_sha,
        "provisional_pack_sha256": provisional_pack_sha.lower(),
        "executable_sha256": executable_sha.lower(),
        "pe_dependencies": dependencies,
        "smoke_test_count": len(smoke_tests),
    }


def execute_combination(record: dict, context: dict) -> tuple[dict, list[Path]]:
    runtime_sdk = Path(context["runtime_sdk"])
    runtime_sdk_sha = context["runtime_sdk_sha256"]
    result_root = Path(context["result_root"])
    build_root = Path(context["build_root"])
    source_cache = Path(context["source_cache"])
    build_workers = int(context["build_workers"])
    version_slug = _safe_slug(f"{record['version']}-{record['source_sha256'][:12]}")
    combination_root = result_root / "combinations" / version_slug
    combination_root.mkdir(parents=True, exist_ok=True)
    expected_source_cache = (REPO_ROOT / "downloads").resolve()
    if source_cache.resolve() != expected_source_cache:
        raise RuntimeError(
            "history source cache must be the repository downloads directory so build.py "
            "consumes the exact staged archive"
        )

    base_config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
    generated_config, canonical_library = contract_config.build_contract_config(
        base_config,
        record["library"],
        record["version"],
    )
    if canonical_library != record["library"]:
        raise RuntimeError(
            f"history contract library casing mismatch: {record['library']!r} != "
            f"{canonical_library!r}"
        )
    config_path = combination_root / "config.json"
    _write_json(config_path, generated_config)

    contract_build.stage_source_archive(
        source_cache,
        record["project_name"],
        record["version"],
        record["source_filename"],
        record["source_url"],
        record["source_sha256"],
    )
    version_build_root = build_root / version_slug
    pack_dir = combination_root / "packs"
    pack_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(REPO_ROOT / "build.py"),
        "--cpython-version",
        record["python_version"],
        "--download-root",
        str(version_build_root),
        "--config",
        str(config_path),
        "--profile",
        "library-contract",
        "--pack-only",
        "--pack-runtime-sdk",
        str(runtime_sdk),
        "--build-workers",
        str(build_workers),
        "--output-pack-dir",
        str(pack_dir),
        "--output-pack-name",
        record["library"],
    ]
    subprocess.run(command, cwd=REPO_ROOT, check=True)

    source_archive = contract_build.verify_source_archive(
        source_cache,
        record["project_name"],
        record["version"],
        record["source_filename"],
        record["source_sha256"],
    )
    pack_path = contract_build.verify_pack(
        pack_dir,
        record["library"],
        record["version"],
        record["python_version"],
    )
    source_root = version_build_root / f"cpython-{record['python_version']}"
    verifier_path = source_root / "PCbuild" / "staticpython-pack-verify-report.json"
    if not verifier_path.is_file():
        raise RuntimeError(
            f"SDK-linked pack verifier report is missing: {verifier_path}"
        )
    verifier = json.loads(verifier_path.read_text(encoding="utf-8"))
    if not isinstance(verifier, dict):
        raise RuntimeError("SDK-linked pack verifier report must be an object")
    verification = _validate_verifier_report(
        verifier,
        runtime_sdk_sha256=runtime_sdk_sha,
        pack_path=pack_path,
        library=record["library"],
        version=record["version"],
        python_version=record["python_version"],
    )
    pack_metadata, _pack_members = contract_build._pack_metadata(pack_path)
    pack_metadata_path = combination_root / "pack-metadata.json"
    _write_json(pack_metadata_path, pack_metadata)
    copied_verifier = combination_root / "staticpython-pack-verify-report.json"
    shutil.copy2(verifier_path, copied_verifier)
    normalized_report = {
        "schema_version": 1,
        "kind": history_evidence.COMBINATION_EVIDENCE_KIND,
        "library": record["library"],
        "project_name": record["project_name"],
        "version": record["version"],
        "python_version": record["python_version"],
        "source_filename": record["source_filename"],
        "source_sha256": history_evidence.file_sha256(source_archive),
        **verification,
        "status": "passed",
    }
    normalized_report["evidence_sha256"] = history_evidence.canonical_sha256(
        normalized_report
    )
    normalized_path = combination_root / "combination-evidence.v1.json"
    _write_json(normalized_path, normalized_report)
    result = {
        "library": record["library"],
        "version": record["version"],
        "python_version": record["python_version"],
        "source_sha256": record["source_sha256"],
        "pack_sha256": verification["pack_sha256"],
        "runtime_sdk_sha256": runtime_sdk_sha,
        "verifier_report_sha256": history_evidence.file_sha256(copied_verifier),
        "combination_evidence_sha256": normalized_report["evidence_sha256"],
        "status": "passed",
    }
    return result, [config_path, pack_metadata_path, copied_verifier, normalized_path]


def run_history_batch(
    contract: dict,
    manifest: dict,
    batch_id: str,
    context: dict,
    *,
    executor: CombinationExecutor = execute_combination,
) -> dict:
    manifest_sha = history_evidence.validate_manifest(manifest, contract)
    matching = [
        batch for batch in manifest["batches"] if batch.get("batch_id") == batch_id
    ]
    if len(matching) != 1:
        raise RuntimeError(
            f"history manifest must contain exactly one batch {batch_id!r}"
        )
    batch = matching[0]
    runtime_sdk = Path(context["runtime_sdk"])
    if not runtime_sdk.is_file():
        raise RuntimeError(f"history runtime SDK is missing: {runtime_sdk}")
    runtime_sdk_sha = history_evidence.file_sha256(runtime_sdk)
    context = {**context, "runtime_sdk_sha256": runtime_sdk_sha}
    result_root = Path(context["result_root"])
    result_root.mkdir(parents=True, exist_ok=True)
    results: list[dict] = []
    files: list[Path] = []
    for record in history_evidence.expected_combinations(contract, batch):
        try:
            result, result_files = executor(record, context)
            results.append(result)
            files.extend(result_files)
        except Exception as exc:
            results.append(
                {
                    "library": record["library"],
                    "version": record["version"],
                    "python_version": record["python_version"],
                    "source_sha256": record["source_sha256"],
                    "status": "failed",
                    "failure": {
                        "type": type(exc).__name__,
                        "message": str(exc),
                    },
                }
            )
    file_records = []
    for path in sorted(set(files), key=lambda item: item.as_posix().casefold()):
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(result_root.resolve()).as_posix()
        except ValueError as exc:
            raise RuntimeError(
                f"history evidence file is outside the result root: {path}"
            ) from exc
        if not resolved.is_file():
            raise RuntimeError(f"history evidence file is missing: {path}")
        file_records.append(
            {
                "path": relative,
                "sha256": history_evidence.file_sha256(resolved),
            }
        )
    status = (
        "passed"
        if all(result["status"] == "passed" for result in results)
        else "failed"
    )
    provenance = {
        key: value
        for key, value in context.get("provenance", {}).items()
        if value not in (None, "")
    }
    payload = {
        "schema_version": history_evidence.SCHEMA_VERSION,
        "kind": history_evidence.BATCH_EVIDENCE_KIND,
        "contract_sha256": manifest["contract_sha256"],
        "manifest_sha256": manifest_sha,
        "batch_id": batch["batch_id"],
        "batch_sha256": batch["batch_sha256"],
        "shard_index": batch["run_shard_index"],
        "runtime_sdk_sha256": runtime_sdk_sha,
        "results": results,
        "files": file_records,
        "status": status,
        "provenance": provenance,
    }
    payload["evidence_sha256"] = history_evidence.canonical_sha256(payload)
    _write_json(result_root / "library-history-batch-evidence.v1.json", payload)
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build every locked combination in one StaticPython history batch."
    )
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--batch-id", required=True)
    parser.add_argument("--runtime-sdk", type=Path, required=True)
    parser.add_argument("--build-root", type=Path, required=True)
    parser.add_argument("--source-cache", type=Path, required=True)
    parser.add_argument("--result-root", type=Path, required=True)
    parser.add_argument("--build-workers", type=int, default=2)
    parser.add_argument("--repository")
    parser.add_argument("--run-id")
    parser.add_argument("--run-attempt")
    parser.add_argument("--run-url")
    parser.add_argument("--source-commit")
    parser.add_argument("--source-ref")
    parser.add_argument("--event-name")
    parser.add_argument("--artifact")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    contract = history_evidence.load_object(args.contract, "history contract")
    manifest = history_evidence.load_object(args.manifest, "history manifest")
    evidence = run_history_batch(
        contract,
        manifest,
        args.batch_id,
        {
            "runtime_sdk": args.runtime_sdk,
            "build_root": args.build_root,
            "source_cache": args.source_cache,
            "result_root": args.result_root,
            "build_workers": args.build_workers,
            "provenance": {
                "repository": args.repository,
                "run_id": args.run_id,
                "run_attempt": args.run_attempt,
                "run_url": args.run_url,
                "source_commit": args.source_commit,
                "source_ref": args.source_ref,
                "event_name": args.event_name,
                "artifact": args.artifact,
            },
        },
    )
    print(
        f"[library-history] batch {args.batch_id}: {evidence['status']} "
        f"({sum(record['status'] == 'passed' for record in evidence['results'])}/"
        f"{len(evidence['results'])})"
    )
    return 0 if evidence["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
