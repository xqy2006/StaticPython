from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Sequence
from urllib.parse import quote


DEFAULT_MAX_COMMAND_CHARS = 20_000


@dataclass(frozen=True)
class AssetSpec:
    path: Path
    name: str
    size: int
    sha256: str


@dataclass(frozen=True)
class ReleaseSpec:
    tag: str
    title: str
    notes: str
    assets: tuple[AssetSpec, ...]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _find_index(asset_root: Path, explicit: Path | None) -> Path:
    if explicit is not None:
        path = explicit.resolve()
        if not path.is_file():
            raise RuntimeError(f"runtime index does not exist: {path}")
        return path
    matches = sorted(asset_root.rglob("runtime-index.v1.json"))
    if len(matches) != 1:
        raise RuntimeError(
            f"expected exactly one runtime-index.v1.json below {asset_root}, found {len(matches)}"
        )
    return matches[0].resolve()


def _discover_zip_assets(asset_root: Path) -> dict[str, Path]:
    by_name: dict[str, Path] = {}
    for path in sorted(asset_root.rglob("*.zip")):
        if path.name in by_name:
            raise RuntimeError(f"duplicate release asset filename: {path.name}")
        by_name[path.name] = path.resolve()
    return by_name


def _asset_spec(record: dict, zip_by_name: dict[str, Path]) -> AssetSpec:
    name = record.get("filename")
    expected_size = record.get("size")
    expected_sha = record.get("sha256")
    if not isinstance(name, str) or not name:
        raise RuntimeError("release index contains an asset without a filename")
    if not isinstance(expected_size, int) or expected_size < 0:
        raise RuntimeError(f"release index contains an invalid size for {name}")
    if not isinstance(expected_sha, str) or re.fullmatch(r"[0-9a-f]{64}", expected_sha) is None:
        raise RuntimeError(f"release index contains an invalid SHA-256 for {name}")
    path = zip_by_name.get(name)
    if path is None:
        raise RuntimeError(f"release index references a missing ZIP asset: {name}")
    actual_size = path.stat().st_size
    if actual_size != expected_size:
        raise RuntimeError(f"release asset size mismatch for {name}: {actual_size} != {expected_size}")
    actual_sha = sha256_file(path)
    if actual_sha != expected_sha:
        raise RuntimeError(f"release asset SHA-256 mismatch for {name}: {actual_sha} != {expected_sha}")
    return AssetSpec(path=path, name=name, size=actual_size, sha256=actual_sha)


def build_release_specs(
    asset_root: Path,
    index_path: Path,
    repository: str,
    source_commit: str,
) -> tuple[ReleaseSpec, ...]:
    if re.fullmatch(r"[0-9a-fA-F]{40}", source_commit) is None:
        raise RuntimeError("source commit must be a full 40-character Git commit")
    source_commit = source_commit.lower()
    index = json.loads(index_path.read_text(encoding="utf-8"))
    if index.get("schema_version") != 1 or index.get("kind") != "staticpython-runtime-index":
        raise RuntimeError("release artifact is not a StaticPython runtime index v1")
    if index.get("status") != "verified":
        raise RuntimeError("release artifact index is not verified")
    if index.get("staticpython_repository") != repository:
        raise RuntimeError("release artifact index belongs to a different repository")
    if index.get("staticpython_commit") != source_commit:
        raise RuntimeError("release artifact index belongs to a different StaticPython commit")

    zip_by_name = _discover_zip_assets(asset_root)
    referenced_names: set[str] = set()
    specs: list[ReleaseSpec] = []
    short_commit = source_commit[:12]
    packs = index.get("packs")
    families = index.get("release_families")
    if not isinstance(packs, dict) or not isinstance(families, dict) or not families:
        raise RuntimeError("release artifact index has no library-pack families")

    for family, family_record in sorted(families.items()):
        if not isinstance(family_record, dict):
            raise RuntimeError(f"release family {family} has invalid metadata")
        tag = family_record.get("tag")
        if not isinstance(tag, str) or not tag:
            raise RuntimeError(f"release family {family} has no tag")
        assets: list[AssetSpec] = []
        for versions in packs.values():
            if not isinstance(versions, dict):
                raise RuntimeError("release index has invalid pack version metadata")
            for by_abi in versions.values():
                if not isinstance(by_abi, dict):
                    raise RuntimeError("release index has invalid pack ABI metadata")
                for record in by_abi.values():
                    if isinstance(record, dict) and record.get("release_family") == family:
                        asset = _asset_spec(record, zip_by_name)
                        if asset.name in referenced_names:
                            raise RuntimeError(f"release index references asset more than once: {asset.name}")
                        referenced_names.add(asset.name)
                        assets.append(asset)
        assets.sort(key=lambda item: item.name.casefold())
        if len(assets) != family_record.get("asset_count"):
            raise RuntimeError(
                f"release family {family} contains {len(assets)} assets, "
                f"index declares {family_record.get('asset_count')}"
            )
        specs.append(
            ReleaseSpec(
                tag=tag,
                title=f"StaticPython packs {family} ({short_commit})",
                notes=f"Immutable verified library-pack family for commit {source_commit}.",
                assets=tuple(assets),
            )
        )

    runtimes = index.get("runtimes")
    runtime_tag = index.get("runtime_release_tag")
    if not isinstance(runtimes, dict) or not runtimes:
        raise RuntimeError("release artifact index has no runtime SDK assets")
    if not isinstance(runtime_tag, str) or not runtime_tag:
        raise RuntimeError("release artifact index has no runtime release tag")
    runtime_assets: list[AssetSpec] = []
    for record in runtimes.values():
        if not isinstance(record, dict):
            raise RuntimeError("release index has invalid runtime metadata")
        asset = _asset_spec(record, zip_by_name)
        if asset.name in referenced_names:
            raise RuntimeError(f"release index references asset more than once: {asset.name}")
        referenced_names.add(asset.name)
        runtime_assets.append(asset)
    index_asset = AssetSpec(
        path=index_path.resolve(),
        name=index_path.name,
        size=index_path.stat().st_size,
        sha256=sha256_file(index_path),
    )
    runtime_assets.append(index_asset)
    runtime_assets.sort(key=lambda item: item.name.casefold())
    specs.append(
        ReleaseSpec(
            tag=runtime_tag,
            title=f"StaticPython runtime ({short_commit})",
            notes=f"Immutable verified runtime SDK and library index for commit {source_commit}.",
            assets=tuple(runtime_assets),
        )
    )

    unreferenced = sorted(set(zip_by_name) - referenced_names)
    if unreferenced:
        raise RuntimeError("release artifact contains unreferenced ZIP assets: " + ", ".join(unreferenced))
    return tuple(specs)


def chunk_assets(
    assets: Sequence[AssetSpec],
    *,
    base_command_chars: int,
    max_command_chars: int = DEFAULT_MAX_COMMAND_CHARS,
) -> tuple[tuple[AssetSpec, ...], ...]:
    if max_command_chars <= base_command_chars:
        raise ValueError("maximum command length does not leave room for asset paths")
    chunks: list[tuple[AssetSpec, ...]] = []
    current: list[AssetSpec] = []
    current_chars = base_command_chars
    for asset in assets:
        added_chars = len(str(asset.path)) + 3
        if added_chars + base_command_chars > max_command_chars:
            raise RuntimeError(f"release asset path is too long to upload safely: {asset.path}")
        if current and current_chars + added_chars > max_command_chars:
            chunks.append(tuple(current))
            current = []
            current_chars = base_command_chars
        current.append(asset)
        current_chars += added_chars
    if current:
        chunks.append(tuple(current))
    return tuple(chunks)


class GitHubPublisher:
    def __init__(self, repository: str, source_commit: str, max_command_chars: int) -> None:
        self.repository = repository
        self.source_commit = source_commit.lower()
        self.max_command_chars = max_command_chars

    @staticmethod
    def _run_gh(arguments: Iterable[str], *, allow_not_found: bool = False) -> str | None:
        command = ["gh", *arguments]
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if completed.returncode == 0:
            return completed.stdout
        diagnostic = (completed.stderr + "\n" + completed.stdout).strip()
        if allow_not_found and ("HTTP 404" in diagnostic or "release not found" in diagnostic.lower()):
            return None
        raise RuntimeError(f"GitHub CLI failed ({' '.join(command)}):\n{diagnostic}")

    def _release(self, tag: str) -> dict | None:
        endpoint = f"repos/{self.repository}/releases/tags/{quote(tag, safe='')}"
        output = self._run_gh(("api", endpoint), allow_not_found=True)
        return None if output is None else json.loads(output)

    def _resolved_tag_commit(self, tag: str) -> str:
        endpoint = f"repos/{self.repository}/commits/{quote(tag, safe='')}"
        output = self._run_gh(("api", endpoint))
        assert output is not None
        return str(json.loads(output).get("sha", "")).lower()

    def _validate_release(self, spec: ReleaseSpec, release: dict) -> dict[str, dict]:
        if release.get("tag_name") != spec.tag:
            raise RuntimeError(f"release tag mismatch for {spec.tag}")
        if release.get("draft") or not release.get("prerelease"):
            raise RuntimeError(f"release {spec.tag} must be a published prerelease")
        if str(release.get("target_commitish", "")).lower() != self.source_commit:
            raise RuntimeError(f"release {spec.tag} targets a different commit")
        if self._resolved_tag_commit(spec.tag) != self.source_commit:
            raise RuntimeError(f"release tag {spec.tag} does not resolve to {self.source_commit}")
        assets: dict[str, dict] = {}
        for record in release.get("assets", []):
            name = record.get("name")
            if not isinstance(name, str) or not name:
                raise RuntimeError(f"release {spec.tag} contains an unnamed asset")
            if name in assets:
                raise RuntimeError(f"release {spec.tag} contains duplicate asset {name}")
            assets[name] = record
        expected_names = {asset.name for asset in spec.assets}
        extras = sorted(set(assets) - expected_names)
        if extras:
            raise RuntimeError(f"release {spec.tag} contains unexpected assets: {', '.join(extras)}")
        return assets

    @staticmethod
    def _validate_existing_asset(tag: str, expected: AssetSpec, actual: dict) -> None:
        if actual.get("size") != expected.size:
            raise RuntimeError(f"release {tag} asset {expected.name} has a different size")
        if actual.get("digest") != f"sha256:{expected.sha256}":
            raise RuntimeError(f"release {tag} asset {expected.name} has a different SHA-256")

    def publish(self, spec: ReleaseSpec) -> None:
        release = self._release(spec.tag)
        if release is None:
            self._run_gh(
                (
                    "release",
                    "create",
                    spec.tag,
                    "--repo",
                    self.repository,
                    "--target",
                    self.source_commit,
                    "--title",
                    spec.title,
                    "--prerelease",
                    "--notes",
                    spec.notes,
                )
            )
            release = self._release(spec.tag)
            if release is None:
                raise RuntimeError(f"release {spec.tag} was not visible after creation")

        existing = self._validate_release(spec, release)
        missing: list[AssetSpec] = []
        for asset in spec.assets:
            current = existing.get(asset.name)
            if current is None:
                missing.append(asset)
            else:
                self._validate_existing_asset(spec.tag, asset, current)

        base_chars = len(f"gh release upload {spec.tag} --repo {self.repository}") + 16
        for batch in chunk_assets(
            missing,
            base_command_chars=base_chars,
            max_command_chars=self.max_command_chars,
        ):
            arguments = ["release", "upload", spec.tag]
            arguments.extend(str(asset.path) for asset in batch)
            arguments.extend(("--repo", self.repository))
            self._run_gh(arguments)

        final_release = self._release(spec.tag)
        if final_release is None:
            raise RuntimeError(f"release {spec.tag} disappeared after upload")
        final_assets = self._validate_release(spec, final_release)
        expected_names = {asset.name for asset in spec.assets}
        if set(final_assets) != expected_names:
            missing_names = sorted(expected_names - set(final_assets))
            raise RuntimeError(f"release {spec.tag} is missing assets: {', '.join(missing_names)}")
        for asset in spec.assets:
            self._validate_existing_asset(spec.tag, asset, final_assets[asset.name])
        print(f"published and verified {spec.tag}: {len(spec.assets)} assets")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish resumable immutable StaticPython prereleases")
    parser.add_argument("--asset-root", type=Path, required=True)
    parser.add_argument("--index", type=Path)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", "xqy2006/StaticPython"))
    parser.add_argument("--source-commit", default=os.environ.get("GITHUB_SHA"))
    parser.add_argument("--max-command-chars", type=int, default=DEFAULT_MAX_COMMAND_CHARS)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    asset_root = args.asset_root.resolve()
    if not asset_root.is_dir():
        raise RuntimeError(f"release asset root does not exist: {asset_root}")
    if not args.source_commit:
        raise RuntimeError("--source-commit or GITHUB_SHA is required")
    index_path = _find_index(asset_root, args.index)
    specs = build_release_specs(asset_root, index_path, args.repository, args.source_commit)
    publisher = GitHubPublisher(args.repository, args.source_commit, args.max_command_chars)
    for spec in specs:
        publisher.publish(spec)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
