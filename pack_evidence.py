from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
from pathlib import Path, PurePosixPath
from zipfile import BadZipFile, ZipFile


PACK_METADATA_NAME = "pack.json"
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")
COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}")
VERIFICATION_FIELDS = frozenset(
    {
        "status",
        "smoke_tests",
        "provisional_pack_sha256",
        "payload_manifest_sha256",
        "metadata_without_verification_sha256",
    }
)
WINDOWS_RESERVED_BASENAMES = frozenset(
    {
        "CON",
        "PRN",
        "AUX",
        "NUL",
        "CONIN$",
        "CONOUT$",
        *{f"COM{index}" for index in range(1, 10)},
        *{f"LPT{index}" for index in range(1, 10)},
    }
)
WINDOWS_INVALID_COMPONENT_CHARACTERS = frozenset('<>:"|?*')


def canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pack_payload_manifest_sha256(metadata: dict) -> str:
    files = metadata.get("files")
    if not isinstance(files, list):
        raise RuntimeError("pack metadata files must be a list")
    return canonical_json_sha256({"schema_version": 1, "files": files})


def pack_metadata_without_verification_sha256(metadata: dict) -> str:
    if not isinstance(metadata, dict):
        raise RuntimeError("pack metadata must be an object")
    payload = dict(metadata)
    payload.pop("verification", None)
    return canonical_json_sha256(payload)


def _validate_smoke_record(record: object, *, require_integration: bool) -> bool:
    if not isinstance(record, dict):
        return False
    required = (
        ("name", "kind", "integration")
        if require_integration
        else ("name", "kind")
    )
    if any(not isinstance(record.get(field), str) or not record[field] for field in required):
        return False
    if record.get("status") != "passed":
        return False
    if require_integration and (
        type(record.get("returncode")) is not int
        or record["returncode"] != 0
        or record.get("timed_out") is not False
        or record.get("released_files") != []
    ):
        return False
    skip_group = record.get("skip_group")
    return skip_group is None or isinstance(skip_group, str) and bool(skip_group)


def safe_archive_member_name(value: object, *, description: str = "archive member") -> str:
    if (
        not isinstance(value, str)
        or not value
        or "\\" in value
        or "\0" in value
    ):
        raise RuntimeError(f"unsafe {description}: {value!r}")
    relative = value[:-1] if value.endswith("/") else value
    parts = relative.split("/")
    path = PurePosixPath(relative)
    if (
        not relative
        or path.is_absolute()
        or any(
            part in {"", ".", ".."}
            or part[-1:] in {".", " "}
            or part.split(".", 1)[0].upper() in WINDOWS_RESERVED_BASENAMES
            or any(
                character in WINDOWS_INVALID_COMPONENT_CHARACTERS
                or ord(character) < 32
                for character in part
            )
            for part in parts
        )
        or path.as_posix() != relative
    ):
        raise RuntimeError(f"unsafe {description}: {value!r}")
    return path.as_posix()


def read_pack_metadata(pack_path: Path) -> dict:
    try:
        with ZipFile(pack_path) as archive:
            all_records = archive.infolist()
            names: list[str] = []
            records_by_name = {}
            casefold_names: set[str] = set()
            for record in all_records:
                name = safe_archive_member_name(
                    record.filename,
                    description="pack ZIP member",
                )
                folded = name.casefold()
                if folded in casefold_names:
                    raise RuntimeError(
                        f"pack contains duplicate or case-colliding ZIP members: {pack_path.name}"
                    )
                if stat.S_ISLNK(record.external_attr >> 16):
                    raise RuntimeError(f"pack contains a symbolic link: {name}")
                casefold_names.add(folded)
                if record.is_dir():
                    continue
                names.append(name)
                records_by_name[name] = record
            if names.count(PACK_METADATA_NAME) != 1:
                raise RuntimeError(f"pack must contain one root pack.json: {pack_path.name}")
            try:
                metadata = json.loads(archive.read(PACK_METADATA_NAME))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise RuntimeError(f"could not read pack metadata {pack_path.name}: {exc}") from exc
            if not isinstance(metadata, dict):
                raise RuntimeError(f"pack metadata must be an object: {pack_path.name}")
            files = metadata.get("files")
            if not isinstance(files, list):
                raise RuntimeError(f"pack files must be a list: {pack_path.name}")
            recorded_paths: set[str] = set()
            for record in files:
                if not isinstance(record, dict):
                    raise RuntimeError(f"pack has an invalid file record: {pack_path.name}")
                relative = record.get("path")
                expected_size = record.get("size")
                expected_sha = record.get("sha256")
                if not isinstance(relative, str):
                    raise RuntimeError(f"pack has an invalid recorded path: {relative!r}")
                relative = safe_archive_member_name(
                    relative,
                    description="pack file record",
                )
                if relative in recorded_paths or relative not in records_by_name:
                    raise RuntimeError(f"pack has an invalid recorded path: {relative!r}")
                if not isinstance(expected_size, int) or expected_size < 0:
                    raise RuntimeError(f"pack has an invalid recorded size: {relative}")
                if not isinstance(expected_sha, str) or not SHA256_PATTERN.fullmatch(expected_sha):
                    raise RuntimeError(f"pack has an invalid recorded SHA-256: {relative}")
                archive_record = records_by_name[relative]
                if archive_record.file_size != expected_size:
                    raise RuntimeError(f"pack payload does not match its manifest: {relative}")
                digest = hashlib.sha256()
                with archive.open(archive_record, "r") as payload:
                    for chunk in iter(lambda: payload.read(1024 * 1024), b""):
                        digest.update(chunk)
                if digest.hexdigest() != expected_sha:
                    raise RuntimeError(f"pack payload does not match its manifest: {relative}")
                recorded_paths.add(relative)
            unrecorded = sorted(set(names) - {PACK_METADATA_NAME} - recorded_paths)
            if unrecorded:
                raise RuntimeError(f"pack contains unrecorded files: {unrecorded}")
    except BadZipFile as exc:
        raise RuntimeError(f"invalid pack ZIP: {pack_path}") from exc
    return metadata


def validate_pack_verification_metadata(metadata: dict) -> dict:
    name = metadata.get("name")
    version = metadata.get("version")
    if metadata.get("schema_version") != 1 or metadata.get("kind") != "staticpython-library-pack":
        raise RuntimeError("verified pack has an unsupported schema or kind")
    if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
        raise RuntimeError("verified pack has an invalid name or version")
    verification = metadata.get("verification")
    if not isinstance(verification, dict) or set(verification) != VERIFICATION_FIELDS:
        raise RuntimeError(f"pack {name} {version} has incomplete or unknown verification fields")
    if verification.get("status") != "passed":
        raise RuntimeError(f"pack {name} {version} is not verification=passed")
    smoke_tests = verification.get("smoke_tests")
    if not isinstance(smoke_tests, list) or not smoke_tests:
        raise RuntimeError(f"pack {name} {version} has no behavior smoke evidence")
    failed_smokes = [
        record
        for record in smoke_tests
        if not _validate_smoke_record(record, require_integration=False)
    ]
    if failed_smokes:
        raise RuntimeError(f"pack {name} {version} has invalid or non-passing smoke evidence")
    smoke_names = [record["name"] for record in smoke_tests]
    if len(smoke_names) != len(set(smoke_names)):
        raise RuntimeError(f"pack {name} {version} repeats behavior smoke evidence")
    for field in VERIFICATION_FIELDS - {"status", "smoke_tests"}:
        value = verification.get(field)
        if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
            raise RuntimeError(f"pack {name} {version} has invalid {field}")
    if verification["payload_manifest_sha256"] != pack_payload_manifest_sha256(metadata):
        raise RuntimeError(f"pack {name} {version} payload manifest evidence does not match")
    if (
        verification["metadata_without_verification_sha256"]
        != pack_metadata_without_verification_sha256(metadata)
    ):
        raise RuntimeError(f"pack {name} {version} metadata evidence does not match")
    return verification


def _provisional_record(report: dict, name: object, version: object) -> dict:
    records = report.get("packs")
    if not isinstance(records, list):
        raise RuntimeError("SDK verification report has no provisional pack records")
    matching = [
        record
        for record in records
        if isinstance(record, dict)
        and record.get("name") == name
        and record.get("version") == version
    ]
    if len(matching) != 1:
        raise RuntimeError(f"promoted pack {name} {version} has {len(matching)} provisional records")
    record = matching[0]
    for field in (
        "sha256",
        "provisional_sha256",
        "payload_manifest_sha256",
        "metadata_without_verification_sha256",
    ):
        value = record.get(field)
        if not isinstance(value, str) or not SHA256_PATTERN.fullmatch(value):
            raise RuntimeError(f"provisional pack {name} {version} has invalid {field}")
    if record["sha256"] != record["provisional_sha256"]:
        raise RuntimeError(f"provisional pack {name} {version} SHA-256 aliases disagree")
    return record


def _expected_smoke_tests(report: dict, name: object, version: object) -> list[dict]:
    records = report.get("integration_smoke_tests")
    if not isinstance(records, list):
        raise RuntimeError("SDK verification report has no integration smoke tests")
    projected = [
        {
            key: record[key]
            for key in ("name", "kind", "status", "skip_group")
            if key in record
        }
        for record in records
        if isinstance(record, dict) and record.get("integration") == name
    ]
    if not projected:
        raise RuntimeError(f"provisional pack {name} {version} has no behavior smoke evidence")
    if any(record.get("status") != "passed" for record in projected):
        raise RuntimeError(f"provisional pack {name} {version} has non-passing smoke evidence")
    return projected


def validate_sdk_verification_report(report: dict) -> None:
    if report.get("schema_version") != 1:
        raise RuntimeError("pack promotion requires SDK verification report schema version 1")
    if (
        report.get("kind") != "staticpython-pack-sdk-verification"
        or report.get("status") != "passed"
    ):
        raise RuntimeError("pack promotion requires a passed SDK verification report")
    if report.get("failures") != []:
        raise RuntimeError("pack promotion report contains failures")
    runtime = report.get("runtime_sdk")
    if (
        not isinstance(runtime, dict)
        or not isinstance(runtime.get("archive_sha256"), str)
        or not SHA256_PATTERN.fullmatch(runtime["archive_sha256"])
        or not isinstance(runtime.get("cpython_version"), str)
        or not runtime["cpython_version"]
        or not isinstance(runtime.get("runtime_abi"), str)
        or not runtime["runtime_abi"].startswith("staticpython-pack-v1-cp")
        or not isinstance(runtime.get("staticpython_commit"), str)
        or not COMMIT_PATTERN.fullmatch(runtime["staticpython_commit"])
    ):
        raise RuntimeError("pack promotion report has invalid runtime SDK provenance")
    executable_sha = report.get("executable_sha256")
    if not isinstance(executable_sha, str) or not SHA256_PATTERN.fullmatch(executable_sha):
        raise RuntimeError("pack promotion report has no verified executable SHA-256")
    pe_audit = report.get("pe_audit")
    dependencies = pe_audit.get("dependencies") if isinstance(pe_audit, dict) else None
    clean_fields = (
        "forbidden_dependencies",
        "non_system_dependencies",
        "forbidden_entry_symbols",
        "main_object_records",
    )
    if (
        not isinstance(pe_audit, dict)
        or pe_audit.get("status") != "passed"
        or not isinstance(dependencies, list)
        or not dependencies
        or any(
            not isinstance(value, str)
            or not value.casefold().endswith(".dll")
            for value in dependencies
        )
        or len(dependencies) != len({value.casefold() for value in dependencies})
        or any(pe_audit.get(field) != [] for field in clean_fields)
        or pe_audit.get("failures", []) != []
        or pe_audit.get("executable_sha256") != executable_sha
        or not isinstance(pe_audit.get("map_sha256"), str)
        or not SHA256_PATTERN.fullmatch(pe_audit["map_sha256"])
    ):
        raise RuntimeError("pack promotion requires a passed, non-empty PE dependency audit")
    packs = report.get("packs")
    if not isinstance(packs, list) or not packs:
        raise RuntimeError("SDK verification report has no provisional pack records")
    identities: set[tuple[str, str]] = set()
    names_casefold: set[str] = set()
    for record in packs:
        if not isinstance(record, dict):
            raise RuntimeError("SDK verification report has an invalid provisional pack record")
        name = record.get("name")
        version = record.get("version")
        if not isinstance(name, str) or not name or not isinstance(version, str) or not version:
            raise RuntimeError("SDK verification report has an invalid provisional pack identity")
        identity = (name, version)
        if identity in identities:
            raise RuntimeError(f"SDK verification report repeats provisional pack {name} {version}")
        if name.casefold() in names_casefold:
            raise RuntimeError(f"SDK verification report repeats provisional pack name {name}")
        identities.add(identity)
        names_casefold.add(name.casefold())
        _provisional_record(report, name, version)
    smoke_tests = report.get("integration_smoke_tests")
    if not isinstance(smoke_tests, list) or not smoke_tests:
        raise RuntimeError("SDK verification report has no integration smoke tests")
    if any(
        not _validate_smoke_record(record, require_integration=True)
        for record in smoke_tests
    ):
        raise RuntimeError("SDK verification report contains invalid or non-passing smoke evidence")
    smoke_identities = [
        (record["integration"], record["name"])
        for record in smoke_tests
    ]
    if len(smoke_identities) != len(set(smoke_identities)):
        raise RuntimeError("SDK verification report repeats integration smoke evidence")
    pack_names = {name for name, _version in identities}
    smoke_names = {record["integration"] for record in smoke_tests}
    if smoke_names != pack_names:
        raise RuntimeError(
            "SDK verification report smoke integrations do not match its packs: "
            f"packs={sorted(pack_names)}, smokes={sorted(smoke_names)}"
        )


def expected_pack_promotion(report: dict, promoted_packs: list[Path]) -> dict:
    validate_sdk_verification_report(report)
    if not promoted_packs:
        raise RuntimeError("pack promotion requires at least one final pack")

    final_records: list[dict] = []
    identities: set[tuple[object, object]] = set()
    for pack_path in promoted_packs:
        metadata = read_pack_metadata(pack_path)
        name = metadata.get("name")
        version = metadata.get("version")
        identity = (name, version)
        if identity in identities:
            raise RuntimeError(f"pack promotion repeats final pack {name} {version}")
        identities.add(identity)
        provisional = _provisional_record(report, name, version)
        expected_verification = {
            "status": "passed",
            "smoke_tests": _expected_smoke_tests(report, name, version),
            "provisional_pack_sha256": provisional["sha256"],
            "payload_manifest_sha256": provisional["payload_manifest_sha256"],
            "metadata_without_verification_sha256": provisional[
                "metadata_without_verification_sha256"
            ],
        }
        if metadata.get("verification") != expected_verification:
            raise RuntimeError(
                f"promoted pack {name} {version} verification metadata does not match its verifier report"
            )
        validate_pack_verification_metadata(metadata)
        final_records.append(
            {
                "name": name,
                "version": version,
                "asset": pack_path.name,
                "provisional_sha256": provisional["sha256"],
                "final_sha256": file_sha256(pack_path),
                "payload_manifest_sha256": provisional["payload_manifest_sha256"],
                "metadata_without_verification_sha256": provisional[
                    "metadata_without_verification_sha256"
                ],
            }
        )

    return {
        "status": "passed",
        "policy": "verification-metadata-only",
        "packs": sorted(
            final_records,
            key=lambda record: (str(record["name"]).casefold(), str(record["version"]), record["asset"]),
        ),
    }


def bind_promoted_pack_evidence(report: dict, promoted_packs: list[Path]) -> dict:
    if "promotion" in report:
        raise RuntimeError("SDK verification report already contains pack promotion evidence")
    report["promotion"] = expected_pack_promotion(report, promoted_packs)
    return report


def validate_promoted_pack_evidence(report: dict, promoted_packs: list[Path]) -> dict:
    recorded = report.get("promotion")
    expected = expected_pack_promotion(report, promoted_packs)
    if recorded != expected:
        raise RuntimeError("recorded pack promotion evidence does not match the final pack assets")
    return report


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate final StaticPython packs against an SDK verification report."
    )
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--pack", type=Path, action="append", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = json.loads(args.report.read_text(encoding="utf-8"))
    if not isinstance(report, dict):
        raise RuntimeError("SDK verification report must be an object")
    validate_promoted_pack_evidence(report, [path.resolve() for path in args.pack])
    print(f"[pack-evidence] validated {len(args.pack)} promoted pack(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
