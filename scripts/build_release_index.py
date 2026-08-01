from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from urllib.parse import quote
from zipfile import BadZipFile, ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build import RUNTIME_SDK_METADATA_RELATIVE_PATH, STATICPYTHON_PACK_METADATA_NAME, git_commit_or_none, sha256_file


TARGET_ABIS = ("cp311", "cp312", "cp313", "cp314", "cp315")
PACK_FAMILIES = (
    ("a-f", set("abcdef")),
    ("g-l", set("ghijkl")),
    ("m-r", set("mnopqr")),
    ("s-z", set("stuvwxyz")),
)


def pack_family(name: str) -> str:
    first = name[:1].casefold()
    for family, initials in PACK_FAMILIES:
        if first in initials:
            return family
    return "other"


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


def build_index(
    asset_root: Path,
    repository: str,
    staticpython_commit: str,
    runtime_tag: str,
    pack_tag_prefix: str,
    *,
    require_all_targets: bool = True,
    require_verified: bool = True,
) -> dict:
    runtime_assets, pack_assets = discover_assets(asset_root)
    runtimes: dict[str, dict] = {}
    for path, metadata in runtime_assets:
        abi = metadata.get("cpython_abi")
        if abi not in TARGET_ABIS:
            raise RuntimeError(f"runtime asset {path.name} has unsupported ABI {abi!r}")
        if abi in runtimes:
            raise RuntimeError(f"multiple runtime SDK assets were found for {abi}")
        if metadata.get("staticpython_commit") not in {None, staticpython_commit}:
            raise RuntimeError(f"runtime asset {path.name} was built from a different StaticPython commit")
        if require_verified and metadata.get("verification", {}).get("status") != "passed":
            raise RuntimeError(f"runtime asset {path.name} is not verified")
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
        if metadata.get("staticpython_commit") not in {None, staticpython_commit}:
            raise RuntimeError(f"pack asset {path.name} was built from a different StaticPython commit")
        if require_verified and metadata.get("verification", {}).get("status") != "passed":
            raise RuntimeError(f"pack asset {path.name} is not verified")
        if require_verified and metadata.get("license", {}).get("status") != "complete":
            raise RuntimeError(f"pack asset {path.name} has incomplete license metadata")
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

    return {
        "schema_version": 1,
        "kind": "staticpython-runtime-index",
        "status": "verified" if require_verified else "development",
        "staticpython_repository": repository,
        "staticpython_commit": staticpython_commit,
        "target_platform": "windows-x64",
        "target_cpython_abis": list(TARGET_ABIS),
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
    index = build_index(
        args.asset_root.resolve(),
        args.repository,
        commit.lower(),
        runtime_tag,
        pack_tag_prefix,
        require_all_targets=not args.allow_partial,
        require_verified=not args.allow_unverified,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(index, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
