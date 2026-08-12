from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote
from zipfile import BadZipFile, ZipFile

from packaging.specifiers import InvalidSpecifier, SpecifierSet
from packaging.version import InvalidVersion, Version


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build import (
    RUNTIME_SDK_METADATA_RELATIVE_PATH,
    STATICPYTHON_PACK_METADATA_NAME,
    git_commit_or_none,
    sha256_file,
    staticpython_pack_release_family,
)
from pack_evidence import (
    file_sha256 as evidence_file_sha256,
    read_pack_metadata,
    validate_pack_verification_metadata,
    validate_promoted_pack_evidence,
)


TARGET_ABIS = ("cp311", "cp312", "cp313", "cp314", "cp315")
TOOLCHAIN_ABI_FIELDS = (
    "visual_studio_version",
    "vc_tools_version",
    "windows_sdk_version",
    "platform_toolset",
    "runtime_library",
)

# runtime-index.v1.json is a resolver and linker catalog, not a second copy of
# every asset's audit manifest.  Keep this projection explicit so adding a new
# build-relevant pack field requires a deliberate index contract change.  The
# complete metadata remains inside the immutable ZIP named by each record's
# SHA-256.
RUNTIME_INDEX_METADATA_FIELDS = (
    "schema_version",
    "kind",
    "runtime_abi",
    "cpython_version",
    "cpython_abi",
    "platform",
    "profile_name",
    "staticpython_commit",
    "cpython_commit",
    "cpython_tag",
    "cpython_source",
    "toolchain",
    "base_pack_symbol",
    "pack_registration_function",
    "include_directory",
    "library_directory",
    "core_library",
    "runtime_library",
    "link_libraries",
    "system_libraries",
    "builtin_module_registrations",
    "builtin_module_names",
    "frozen_module_names",
    "stdlib_top_level_import_names",
    "libraries",
    "verification",
)
PACK_INDEX_METADATA_FIELDS = (
    "schema_version",
    "kind",
    "name",
    "version",
    "project_name",
    "source_provider",
    "source_resolver",
    "source_tree_sha256",
    "staticpython_commit",
    "cpython_version",
    "cpython_commit",
    "cpython_tag",
    "cpython_source",
    "cpython_abi",
    "runtime_abi",
    "platform",
    "descriptor_symbol",
    "descriptor_source",
    "sources",
    "frozen_modules",
    "top_level_import_names",
    "builtin_modules",
    "resources",
    "dependencies",
    "dependency_constraints",
    "conflicts",
    "libraries",
    "wholearchive",
    "system_libraries",
    "suppressed_system_libraries",
    "trusted_object_origins",
    "link_order",
    "toolchain",
    "license",
    "verification",
)


def pack_family(name: str) -> str:
    return staticpython_pack_release_family(name)


def asset_url(repository: str, tag: str, filename: str) -> str:
    return f"https://github.com/{repository}/releases/download/{quote(tag, safe='')}/{quote(filename)}"


def read_json_member(path: Path, member_name: str) -> dict | None:
    try:
        with ZipFile(path) as archive:
            try:
                payload = archive.read(member_name)
            except KeyError:
                return None
    except BadZipFile as exc:
        raise RuntimeError(f"invalid release ZIP: {path}") from exc
    value = json.loads(payload.decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"{path}!/{member_name} must contain a JSON object")
    return value


def discover_assets(root: Path) -> tuple[list[tuple[Path, dict]], list[tuple[Path, dict]]]:
    runtimes: list[tuple[Path, dict]] = []
    packs: list[tuple[Path, dict]] = []
    for path in sorted(root.rglob("*.zip"), key=lambda item: item.name.casefold()):
        runtime = read_json_member(path, RUNTIME_SDK_METADATA_RELATIVE_PATH.as_posix())
        if runtime is not None:
            runtimes.append((path, runtime))
            continue
        pack = read_json_member(path, STATICPYTHON_PACK_METADATA_NAME)
        if pack is not None:
            packs.append((path, read_pack_metadata(path)))
    return runtimes, packs


def _asset_record(path: Path, metadata: dict, repository: str, tag: str) -> dict:
    return {
        "filename": path.name,
        "url": asset_url(repository, tag, path.name),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "metadata": metadata,
    }


def validate_pack_promotion_reports(
    root: Path,
    pack_assets: list[tuple[Path, dict]],
    runtimes: dict[str, dict],
) -> dict[Path, dict]:
    if not pack_assets:
        return {}
    packs_by_name: dict[str, Path] = {}
    for path, _metadata in pack_assets:
        if path.name in packs_by_name:
            raise RuntimeError(f"duplicate pack asset filename: {path.name}")
        packs_by_name[path.name] = path
    report_paths = sorted(
        root.rglob("staticpython-pack-verification-*.json"),
        key=lambda path: path.name.casefold(),
    )
    if not report_paths:
        raise RuntimeError("verified pack assets have no SDK promotion reports")

    covered: dict[Path, dict] = {}
    report_names: set[str] = set()
    for report_path in report_paths:
        if report_path.name in report_names:
            raise RuntimeError(f"duplicate pack promotion report filename: {report_path.name}")
        report_names.add(report_path.name)
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise RuntimeError(f"invalid pack promotion report {report_path.name}: {exc}") from exc
        if not isinstance(report, dict):
            raise RuntimeError(f"pack promotion report must be an object: {report_path.name}")
        promotion = report.get("promotion")
        records = promotion.get("packs") if isinstance(promotion, dict) else None
        if not isinstance(records, list) or not records:
            raise RuntimeError(f"pack promotion report has no final assets: {report_path.name}")
        selected: list[Path] = []
        for record in records:
            asset_name = record.get("asset") if isinstance(record, dict) else None
            if not isinstance(asset_name, str) or asset_name not in packs_by_name:
                raise RuntimeError(
                    f"pack promotion report {report_path.name} references unknown asset {asset_name!r}"
                )
            pack_path = packs_by_name[asset_name]
            if pack_path in covered:
                raise RuntimeError(f"pack asset has multiple promotion reports: {asset_name}")
            selected.append(pack_path)
        validate_promoted_pack_evidence(report, selected)
        report_sha = evidence_file_sha256(report_path)
        runtime = report.get("runtime_sdk", {})
        pe_audit = report.get("pe_audit", {})
        provisional_by_identity = {
            (record.get("name"), record.get("version")): record
            for record in report["packs"]
        }
        promotion_by_asset = {record["asset"]: record for record in records}
        promoted_families = {
            pack_family(read_pack_metadata(pack_path)["name"])
            for pack_path in selected
        }
        if len(promoted_families) != 1:
            raise RuntimeError(
                f"pack promotion report {report_path.name} spans release families: "
                f"{sorted(promoted_families)}"
            )
        report_family = next(iter(promoted_families))
        for pack_path in selected:
            metadata = read_pack_metadata(pack_path)
            identity = (metadata["name"], metadata["version"])
            provisional = provisional_by_identity[identity]
            final = promotion_by_asset[pack_path.name]
            abi = metadata.get("cpython_abi")
            runtime_record = runtimes.get(abi)
            if not isinstance(runtime_record, dict):
                raise RuntimeError(
                    f"pack promotion report {report_path.name} has no indexed runtime for {abi}"
                )
            runtime_metadata = runtime_record.get("metadata", {})
            expected_runtime = {
                "archive_sha256": runtime_record.get("sha256"),
                "cpython_version": runtime_metadata.get("cpython_version"),
                "runtime_abi": runtime_metadata.get("runtime_abi"),
                "staticpython_commit": runtime_metadata.get("staticpython_commit"),
            }
            if not isinstance(runtime, dict) or any(
                runtime.get(field) != expected
                for field, expected in expected_runtime.items()
            ):
                raise RuntimeError(
                    f"pack promotion report {report_path.name} does not match its {abi} runtime SDK"
                )
            covered[pack_path] = {
                "report_filename": report_path.name,
                "report_size": report_path.stat().st_size,
                "report_sha256": report_sha,
                "report_family": report_family,
                "runtime_sdk_sha256": runtime.get("archive_sha256"),
                "provisional_pack_sha256": provisional["sha256"],
                "final_pack_sha256": final["final_sha256"],
                "pe_dependencies": pe_audit["dependencies"],
            }

    missing = sorted(
        path.name for path, _metadata in pack_assets if path not in covered
    )
    if missing:
        raise RuntimeError("verified pack assets lack promotion evidence: " + ", ".join(missing))
    return covered


def _metadata_projection(metadata: dict, fields: tuple[str, ...]) -> dict:
    return {field: metadata[field] for field in fields if field in metadata}


def runtime_index_metadata(metadata: dict) -> dict:
    """Return the runtime metadata needed before the SDK is downloaded."""
    return _metadata_projection(metadata, RUNTIME_INDEX_METADATA_FIELDS)


def pack_index_metadata(metadata: dict, path: Path) -> dict:
    """Return resolver/link metadata while leaving full audit data in pack.json."""
    projected = _metadata_projection(metadata, PACK_INDEX_METADATA_FIELDS)
    resources = metadata.get("resources")
    if resources is None:
        return projected
    if not isinstance(resources, list):
        raise RuntimeError(f"pack asset {path.name} has invalid resources metadata")
    resource_paths = []
    for record in resources:
        if (
            not isinstance(record, dict)
            or not isinstance(record.get("path"), str)
            or not record["path"]
        ):
            raise RuntimeError(f"pack asset {path.name} has an invalid resource record")
        resource_paths.append({"path": record["path"]})
    projected["resources"] = resource_paths
    return projected


def _is_full_commit(value: object) -> bool:
    return isinstance(value, str) and re.fullmatch(r"[0-9a-fA-F]{40}", value) is not None


def _validate_verified_provenance(metadata: dict, path: Path) -> None:
    version = metadata.get("cpython_version")
    if not _is_full_commit(metadata.get("cpython_commit")):
        raise RuntimeError(f"verified asset {path.name} has no exact CPython commit")
    if not isinstance(version, str) or metadata.get("cpython_tag") != f"v{version}":
        raise RuntimeError(f"verified asset {path.name} has inconsistent CPython tag metadata")
    source = metadata.get("cpython_source", {})
    if not isinstance(source, dict) or source.get("commit") != metadata.get("cpython_commit"):
        raise RuntimeError(f"verified asset {path.name} has inconsistent CPython source provenance")
    if not isinstance(source.get("archive_sha256"), str) or len(source["archive_sha256"]) != 64:
        raise RuntimeError(f"verified asset {path.name} has no CPython source archive hash")
    toolchain = metadata.get("toolchain", {})
    required_toolchain = (
        "visual_studio_version",
        "vscmd_version",
        "vc_tools_version",
        "windows_sdk_version",
        "platform_toolset",
        "runtime_library",
    )
    missing = [name for name in required_toolchain if not toolchain.get(name)]
    if missing:
        raise RuntimeError(f"verified asset {path.name} is missing toolchain fields: {', '.join(missing)}")


def toolchain_abi_fingerprint(metadata: dict) -> dict[str, object]:
    """Return only toolchain properties that affect binary compatibility.

    VSCMD_VER identifies the Visual Studio developer-command bootstrap script,
    not the selected compiler or Windows SDK. GitHub's windows-2022 pool can
    carry different VsDevCmd servicing revisions while selecting identical VC
    tools, SDK, toolset, and CRT settings, so it remains provenance metadata but
    is deliberately excluded from the ABI comparison.
    """
    toolchain = metadata.get("toolchain", {})
    if not isinstance(toolchain, dict):
        return {}
    return {field: toolchain.get(field) for field in TOOLCHAIN_ABI_FIELDS}


def validate_expected_pack_matrix(packs: dict, expected_pack_names: list[str]) -> None:
    expected_by_key: dict[str, str] = {}
    for name in expected_pack_names:
        if not isinstance(name, str) or not name:
            raise RuntimeError("expected pack names must be non-empty strings")
        key = name.casefold()
        if key in expected_by_key:
            raise RuntimeError(f"duplicate expected pack name: {name}")
        expected_by_key[key] = name
    actual_by_key = {name.casefold(): name for name in packs}
    missing = [expected_by_key[key] for key in sorted(set(expected_by_key) - set(actual_by_key))]
    unexpected = [actual_by_key[key] for key in sorted(set(actual_by_key) - set(expected_by_key))]
    if missing:
        raise RuntimeError("release index is missing current library packs: " + ", ".join(missing))
    if unexpected:
        raise RuntimeError("release index contains packs outside the current catalog: " + ", ".join(unexpected))

    for key, expected_name in sorted(expected_by_key.items()):
        versions = packs[actual_by_key[key]]
        covered_abis = {
            abi
            for by_abi in versions.values()
            for abi in by_abi
        }
        missing_abis = sorted(set(TARGET_ABIS) - covered_abis)
        if missing_abis:
            raise RuntimeError(
                f"release index pack {expected_name} is missing target ABIs: "
                + ", ".join(missing_abis)
            )


def validate_pack_dependency_assets(packs: dict) -> None:
    actual_by_key = {name.casefold(): name for name in packs}
    for owner, versions in packs.items():
        for owner_version, by_abi in versions.items():
            for abi, record in by_abi.items():
                metadata = record.get("metadata", {})
                dependencies = metadata.get("dependencies", [])
                constraints = metadata.get("dependency_constraints", {})
                if not isinstance(dependencies, list) or not all(
                    isinstance(name, str) and name for name in dependencies
                ):
                    raise RuntimeError(f"pack {owner} {owner_version} {abi} has invalid dependencies")
                if not isinstance(constraints, dict):
                    raise RuntimeError(f"pack {owner} {owner_version} {abi} has invalid dependency constraints")
                for dependency in dependencies:
                    dependency_name = actual_by_key.get(dependency.casefold())
                    if dependency_name is None:
                        raise RuntimeError(
                            f"pack {owner} {owner_version} {abi} requires unpublished pack {dependency}"
                        )
                    raw_specifier = constraints.get(dependency, "")
                    if not isinstance(raw_specifier, str):
                        raise RuntimeError(
                            f"pack {owner} {owner_version} {abi} has an invalid constraint for {dependency}"
                        )
                    try:
                        specifier = SpecifierSet(raw_specifier)
                    except InvalidSpecifier as exc:
                        raise RuntimeError(
                            f"pack {owner} {owner_version} {abi} has invalid constraint "
                            f"{dependency}{raw_specifier}"
                        ) from exc
                    compatible = False
                    for dependency_version, dependency_by_abi in packs[dependency_name].items():
                        if abi not in dependency_by_abi:
                            continue
                        try:
                            parsed_version = Version(dependency_version)
                        except InvalidVersion:
                            continue
                        if parsed_version in specifier:
                            compatible = True
                            break
                    if not compatible:
                        raise RuntimeError(
                            f"pack {owner} {owner_version} {abi} has no published {dependency}{raw_specifier} "
                            f"asset for {abi}"
                        )


def build_index(
    asset_root: Path,
    repository: str,
    staticpython_commit: str,
    runtime_tag: str,
    pack_tag_prefix: str,
    *,
    require_all_targets: bool = True,
    require_verified: bool = True,
    expected_pack_names: list[str] | None = None,
) -> dict:
    runtime_assets, pack_assets = discover_assets(asset_root)
    runtimes: dict[str, dict] = {}
    for path, metadata in runtime_assets:
        abi = metadata.get("cpython_abi")
        if abi not in TARGET_ABIS:
            raise RuntimeError(f"runtime asset {path.name} has unsupported ABI {abi!r}")
        if abi in runtimes:
            raise RuntimeError(f"multiple runtime SDK assets were found for {abi}")
        if metadata.get("staticpython_commit") != staticpython_commit:
            raise RuntimeError(f"runtime asset {path.name} was built from a different StaticPython commit")
        if require_verified and metadata.get("verification", {}).get("status") != "passed":
            raise RuntimeError(f"runtime asset {path.name} is not verified")
        if require_verified:
            _validate_verified_provenance(metadata, path)
        runtimes[abi] = _asset_record(
            path,
            runtime_index_metadata(metadata),
            repository,
            runtime_tag,
        )

    missing_targets = sorted(set(TARGET_ABIS) - set(runtimes))
    if require_all_targets and missing_targets:
        raise RuntimeError("release index is missing runtime SDKs: " + ", ".join(missing_targets))

    packs: dict[str, dict[str, dict[str, dict]]] = {}
    release_families: dict[str, dict] = {}
    family_pack_counts: dict[str, int] = {}
    family_report_assets: dict[str, dict[str, dict]] = {}
    if require_verified:
        incomplete_licenses = [
            path.name
            for path, metadata in pack_assets
            if metadata.get("license", {}).get("status") != "complete"
        ]
        if incomplete_licenses:
            raise RuntimeError(
                "release index contains packs with incomplete license metadata:\n- "
                + "\n- ".join(incomplete_licenses)
            )
        for path, metadata in pack_assets:
            if metadata.get("verification", {}).get("status") != "passed":
                raise RuntimeError(f"pack asset {path.name} is not verified")
            validate_pack_verification_metadata(metadata)
        promotion_evidence = validate_pack_promotion_reports(
            asset_root,
            pack_assets,
            runtimes,
        )
    else:
        promotion_evidence = {}
    for path, metadata in pack_assets:
        name = metadata.get("name")
        version = metadata.get("version")
        abi = metadata.get("cpython_abi")
        if not all(isinstance(value, str) and value for value in (name, version, abi)):
            raise RuntimeError(f"pack asset {path.name} is missing name, version, or cpython_abi")
        if abi not in TARGET_ABIS:
            raise RuntimeError(f"pack asset {path.name} has unsupported ABI {abi!r}")
        if metadata.get("staticpython_commit") != staticpython_commit:
            raise RuntimeError(f"pack asset {path.name} was built from a different StaticPython commit")
        if require_verified and metadata.get("verification", {}).get("status") != "passed":
            raise RuntimeError(f"pack asset {path.name} is not verified")
        if require_verified:
            validate_pack_verification_metadata(metadata)
            _validate_verified_provenance(metadata, path)
            runtime_metadata = runtimes.get(abi, {}).get("metadata", {})
            if (
                metadata.get("cpython_commit") != runtime_metadata.get("cpython_commit")
                or metadata.get("cpython_tag") != runtime_metadata.get("cpython_tag")
            ):
                raise RuntimeError(f"pack asset {path.name} does not match its {abi} runtime source")
            if toolchain_abi_fingerprint(metadata) != toolchain_abi_fingerprint(runtime_metadata):
                raise RuntimeError(f"pack asset {path.name} does not match its {abi} runtime toolchain")
        family = pack_family(name)
        tag = f"{pack_tag_prefix}-{family}"
        family_pack_counts[family] = family_pack_counts.get(family, 0) + 1
        record = _asset_record(
            path,
            pack_index_metadata(metadata, path),
            repository,
            tag,
        )
        record["release_family"] = family
        if require_verified:
            evidence = dict(promotion_evidence[path])
            if evidence.pop("report_family") != family:
                raise RuntimeError(
                    f"pack asset {path.name} promotion report belongs to a different release family"
                )
            report_filename = evidence.pop("report_filename")
            report_asset = {
                "filename": report_filename,
                "url": asset_url(repository, tag, report_filename),
            }
            report_asset["size"] = evidence.pop("report_size")
            report_asset["sha256"] = evidence.pop("report_sha256")
            reports = family_report_assets.setdefault(family, {})
            previous = reports.setdefault(report_asset["filename"], report_asset)
            if previous != report_asset:
                raise RuntimeError(
                    f"release family {family} has conflicting report asset {report_asset['filename']}"
                )
            evidence["report"] = report_asset
            record["verification_evidence"] = evidence
        by_abi = packs.setdefault(name, {}).setdefault(version, {})
        if abi in by_abi:
            raise RuntimeError(f"duplicate pack asset for {name} {version} {abi}")
        by_abi[abi] = record

    for family, pack_count in sorted(family_pack_counts.items()):
        report_count = len(family_report_assets.get(family, {}))
        count = pack_count + report_count
        if count > 900:
            raise RuntimeError(f"release family {family} has {count} assets; maximum is 900")
        release_families[family] = {
            "tag": f"{pack_tag_prefix}-{family}",
            "asset_count": count,
            "pack_asset_count": pack_count,
            "verification_report_asset_count": report_count,
            "maximum_assets": 900,
        }

    if require_all_targets and expected_pack_names is not None:
        validate_expected_pack_matrix(packs, expected_pack_names)
    if require_all_targets:
        validate_pack_dependency_assets(packs)

    return {
        "schema_version": 1,
        "kind": "staticpython-runtime-index",
        "status": "verified" if require_verified else "development",
        "staticpython_repository": repository,
        "staticpython_commit": staticpython_commit,
        "target_platform": "windows-x64",
        "target_cpython_abis": list(TARGET_ABIS),
        "cpython_targets": {
            abi: {
                "version": record["metadata"].get("cpython_version"),
                "tag": record["metadata"].get("cpython_tag"),
                "commit": record["metadata"].get("cpython_commit"),
                "toolchain": record["metadata"].get("toolchain"),
                "verification_status": record["metadata"].get("verification", {}).get("status"),
            }
            for abi, record in sorted(runtimes.items())
        },
        "runtime_release_tag": runtime_tag,
        "release_families": release_families,
        "verification_reports": {
            family: [
                record
                for _name, record in sorted(
                    reports.items(), key=lambda item: item[0].casefold()
                )
            ]
            for family, reports in sorted(family_report_assets.items())
        },
        "runtimes": dict(sorted(runtimes.items())),
        "packs": {
            name: {
                version: dict(sorted(by_abi.items()))
                for version, by_abi in sorted(versions.items())
            }
            for name, versions in sorted(packs.items(), key=lambda item: item[0].casefold())
        },
    }


def serialize_index(index: dict) -> str:
    """Serialize the machine-consumed catalog without whitespace amplification."""
    return json.dumps(index, ensure_ascii=False, separators=(",", ":")) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build an immutable StaticPython runtime-index.v1.json")
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", default="xqy2006/StaticPython")
    parser.add_argument("--staticpython-commit")
    parser.add_argument("--runtime-tag")
    parser.add_argument("--pack-tag-prefix")
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config.json")
    parser.add_argument("--allow-partial", action="store_true")
    parser.add_argument("--allow-unverified", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    commit = args.staticpython_commit or git_commit_or_none(REPO_ROOT)
    if not commit or not re.fullmatch(r"[0-9a-fA-F]{40}", commit):
        raise RuntimeError("a full 40-character StaticPython commit is required")
    short_commit = commit[:12].lower()
    runtime_tag = args.runtime_tag or f"staticpython-runtime-{short_commit}"
    pack_tag_prefix = args.pack_tag_prefix or f"staticpython-packs-{short_commit}"
    config = json.loads(args.config.read_text(encoding="utf-8"))
    expected_pack_names = config.get("profiles", {}).get("full", {}).get("third_party_libraries")
    if not isinstance(expected_pack_names, list):
        raise RuntimeError("config full.third_party_libraries must be an explicit list")
    index = build_index(
        args.asset_root.resolve(),
        args.repository,
        commit.lower(),
        runtime_tag,
        pack_tag_prefix,
        require_all_targets=not args.allow_partial,
        require_verified=not args.allow_unverified,
        expected_pack_names=expected_pack_names,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        serialize_index(index),
        encoding="utf-8",
        newline="\n",
    )
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
