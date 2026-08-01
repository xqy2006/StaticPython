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


TARGET_ABIS = ("cp311", "cp312", "cp313", "cp314", "cp315")
TOOLCHAIN_ABI_FIELDS = (
    "visual_studio_version",
    "vc_tools_version",
    "windows_sdk_version",
    "platform_toolset",
    "runtime_library",
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
            packs.append((path, pack))
    return runtimes, packs


def _asset_record(path: Path, metadata: dict, repository: str, tag: str) -> dict:
    return {
        "filename": path.name,
        "url": asset_url(repository, tag, path.name),
        "size": path.stat().st_size,
        "sha256": sha256_file(path),
        "metadata": metadata,
    }


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
        runtimes[abi] = _asset_record(path, metadata, repository, runtime_tag)

    missing_targets = sorted(set(TARGET_ABIS) - set(runtimes))
    if require_all_targets and missing_targets:
        raise RuntimeError("release index is missing runtime SDKs: " + ", ".join(missing_targets))

    packs: dict[str, dict[str, dict[str, dict]]] = {}
    release_families: dict[str, dict] = {}
    family_counts: dict[str, int] = {}
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
        if require_verified and metadata.get("license", {}).get("status") != "complete":
            raise RuntimeError(f"pack asset {path.name} has incomplete license metadata")
        if require_verified:
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
        family_counts[family] = family_counts.get(family, 0) + 1
        record = _asset_record(path, metadata, repository, tag)
        record["release_family"] = family
        by_abi = packs.setdefault(name, {}).setdefault(version, {})
        if abi in by_abi:
            raise RuntimeError(f"duplicate pack asset for {name} {version} {abi}")
        by_abi[abi] = record

    for family, count in sorted(family_counts.items()):
        if count > 900:
            raise RuntimeError(f"release family {family} has {count} assets; maximum is 900")
        release_families[family] = {
            "tag": f"{pack_tag_prefix}-{family}",
            "asset_count": count,
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
        "runtimes": dict(sorted(runtimes.items())),
        "packs": {
            name: {
                version: dict(sorted(by_abi.items()))
                for version, by_abi in sorted(versions.items())
            }
            for name, versions in sorted(packs.items(), key=lambda item: item[0].casefold())
        },
    }


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
    args.output.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
