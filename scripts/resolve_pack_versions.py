from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build
import libs
from packaging.version import Version


PACK_VERSION_LOCK_SCHEMA = 1


def resolve_pack_versions(config: dict, target_python_version: str) -> dict:
    target_version = Version(target_python_version)
    _profile_name, profile = build.resolve_profile(config, "full")
    selected_libraries = profile.get("third_party_libraries")
    if not isinstance(selected_libraries, list) or not selected_libraries:
        raise RuntimeError("full.third_party_libraries must be a non-empty explicit list")
    catalog = build.profile_library_catalog(
        config,
        profile,
        "third_party_library_catalog",
    )
    integrations = libs.load_integrations(
        build.LIB_PATCH_ROOT,
        selected_libraries,
        target_version=target_version,
        version_overrides=profile.get("third_party_library_version_overrides"),
        library_catalog=catalog,
    )

    missing_versions = [
        integration.name
        for integration in integrations
        if integration.release_version is None
    ]
    if missing_versions:
        raise RuntimeError(
            "globally resolved pack integrations are missing versions: "
            + ", ".join(sorted(missing_versions, key=str.casefold))
        )

    records = [
        {
            "name": integration.name,
            "project_name": integration.project_name,
            "source_provider": integration.source_provider,
            "version": integration.release_version,
            "dependencies": integration.dependencies,
            "dependency_constraints": integration.dependency_constraints,
        }
        for integration in sorted(integrations, key=lambda item: item.name.casefold())
    ]
    return {
        "schema_version": PACK_VERSION_LOCK_SCHEMA,
        "kind": "staticpython-pack-version-lock",
        "status": "resolved",
        "target_python_version": target_python_version,
        "versions": {
            record["name"]: record["version"]
            for record in records
        },
        "integrations": records,
    }


def load_pack_version_lock(
    path: Path,
    *,
    target_python_version: str | None = None,
) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if (
        not isinstance(payload, dict)
        or payload.get("schema_version") != PACK_VERSION_LOCK_SCHEMA
        or payload.get("kind") != "staticpython-pack-version-lock"
        or payload.get("status") != "resolved"
    ):
        raise RuntimeError(f"invalid StaticPython pack version lock: {path}")
    observed_target = payload.get("target_python_version")
    if target_python_version is not None and observed_target != target_python_version:
        raise RuntimeError(
            f"pack version lock targets Python {observed_target}, expected {target_python_version}"
        )
    versions = payload.get("versions")
    if not isinstance(versions, dict) or not versions:
        raise RuntimeError(f"pack version lock has no versions: {path}")
    invalid = [
        str(name)
        for name, version in versions.items()
        if not isinstance(name, str)
        or not name
        or not isinstance(version, str)
        or not version
    ]
    if invalid:
        raise RuntimeError(
            "pack version lock contains invalid version entries: "
            + ", ".join(sorted(invalid, key=str.casefold))
        )
    return payload


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve one globally consistent current pack version set."
    )
    parser.add_argument("--target-python-version", required=True)
    parser.add_argument("--config", type=Path, default=REPO_ROOT / "config.json")
    parser.add_argument("--output", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = json.loads(args.config.read_text(encoding="utf-8"))
    payload = resolve_pack_versions(config, args.target_python_version)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "target_python_version": args.target_python_version,
                "integration_count": len(payload["versions"]),
                "output": str(args.output),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
