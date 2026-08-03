from __future__ import annotations

import hashlib
import json


def canonical_json_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


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
