from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath


BATCH_EVIDENCE_NAME = "library-history-batch-evidence.v1.json"
SHA256_LENGTH = 64


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative_path(value: object) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\\" in value:
        raise RuntimeError(f"invalid history evidence path: {value!r}")
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(
        part in {"", ".", ".."} for part in relative.parts
    ):
        raise RuntimeError(f"unsafe history evidence path: {value!r}")
    if relative.as_posix() == BATCH_EVIDENCE_NAME:
        raise RuntimeError("batch evidence cannot include itself in its file manifest")
    return relative


def stage_evidence(evidence_root: Path, output_root: Path) -> dict:
    source_root = evidence_root.resolve()
    batch_path = source_root / BATCH_EVIDENCE_NAME
    if not batch_path.is_file():
        raise RuntimeError(f"history batch evidence is missing: {batch_path}")
    try:
        payload = json.loads(batch_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"could not read history batch evidence: {batch_path}"
        ) from exc
    if not isinstance(payload, dict) or not isinstance(payload.get("files"), list):
        raise RuntimeError("history batch evidence has no file manifest")

    destination_root = output_root.resolve()
    if destination_root.exists() and any(destination_root.iterdir()):
        raise RuntimeError(
            f"history evidence staging directory is not empty: {output_root}"
        )
    destination_root.mkdir(parents=True, exist_ok=True)

    seen: set[str] = set()
    staged_paths = [BATCH_EVIDENCE_NAME]
    shutil.copy2(batch_path, destination_root / BATCH_EVIDENCE_NAME)
    for record in payload["files"]:
        if not isinstance(record, dict):
            raise RuntimeError(
                "history batch evidence contains a non-object file record"
            )
        relative = _safe_relative_path(record.get("path"))
        key = relative.as_posix().casefold()
        if key in seen:
            raise RuntimeError(
                f"duplicate history evidence path: {relative.as_posix()}"
            )
        seen.add(key)
        expected_sha = record.get("sha256")
        if (
            not isinstance(expected_sha, str)
            or len(expected_sha) != SHA256_LENGTH
            or any(character not in "0123456789abcdef" for character in expected_sha)
        ):
            raise RuntimeError(
                f"invalid SHA-256 for history evidence path {relative.as_posix()}"
            )
        source = (source_root / Path(*relative.parts)).resolve()
        try:
            source.relative_to(source_root)
        except ValueError as exc:
            raise RuntimeError(
                f"history evidence path escapes its source root: {relative.as_posix()}"
            ) from exc
        if not source.is_file():
            raise RuntimeError(
                f"history evidence file is missing: {relative.as_posix()}"
            )
        actual_sha = _sha256(source)
        if actual_sha != expected_sha:
            raise RuntimeError(
                f"history evidence SHA-256 mismatch for {relative.as_posix()}: "
                f"expected {expected_sha}, got {actual_sha}"
            )
        destination = destination_root / Path(*relative.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        if _sha256(destination) != expected_sha:
            raise RuntimeError(
                f"staged history evidence SHA-256 mismatch for {relative.as_posix()}"
            )
        staged_paths.append(relative.as_posix())

    actual_paths = sorted(
        path.relative_to(destination_root).as_posix()
        for path in destination_root.rglob("*")
        if path.is_file()
    )
    if actual_paths != sorted(staged_paths):
        raise RuntimeError(
            "staged history evidence does not match its exact file manifest"
        )
    return {
        "batch_id": payload.get("batch_id"),
        "evidence_sha256": payload.get("evidence_sha256"),
        "file_count": len(actual_paths),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Stage one exact StaticPython history batch artifact."
    )
    parser.add_argument("--evidence-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    result = stage_evidence(args.evidence_root, args.output_root)
    print(
        "[history-evidence-stage] "
        f"batch {result['batch_id']}: staged {result['file_count']} exact files "
        f"({result['evidence_sha256']})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
