from __future__ import annotations

import argparse
import copy
import json
import sys
from pathlib import Path


SCRIPT_ROOT = Path(__file__).resolve().parent
REPO_ROOT = SCRIPT_ROOT.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(SCRIPT_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPT_ROOT))

from build import staticpython_pack_release_family
from resolve_pack_versions import load_pack_version_lock


PACK_FAMILIES = ("a-f", "g-l", "m-r", "s-z", "other")


def build_shard_config(
    base_config: dict,
    family: str,
    profile_name: str = "pack-shard",
    *,
    version_overrides: dict[str, str] | None = None,
) -> tuple[dict, list[str]]:
    if family not in PACK_FAMILIES:
        raise RuntimeError(f"unknown pack family {family!r}")
    profiles = base_config.get("profiles")
    if not isinstance(profiles, dict):
        raise RuntimeError("config profiles must be an object")
    full_profile = profiles.get("full")
    if not isinstance(full_profile, dict):
        raise RuntimeError("config must define the full profile used as the current pack catalog")
    current_libraries = full_profile.get("third_party_libraries")
    if not isinstance(current_libraries, list):
        raise RuntimeError("full.third_party_libraries must be an explicit list")

    seen: set[str] = set()
    duplicates: list[str] = []
    for name in current_libraries:
        if not isinstance(name, str) or not name:
            raise RuntimeError("full.third_party_libraries entries must be non-empty strings")
        key = name.casefold()
        if key in seen:
            duplicates.append(name)
        seen.add(key)
    if duplicates:
        raise RuntimeError("duplicate libraries in the full profile: " + ", ".join(duplicates))

    selected = [name for name in current_libraries if staticpython_pack_release_family(name) == family]
    if not selected:
        raise RuntimeError(f"pack family {family!r} has no current integrations")

    shard_config = copy.deepcopy(base_config)
    shard_profile = copy.deepcopy(full_profile)
    shard_profile["description"] = (
        f"Release-only modular pack build for family {family}; dependencies are linked for verification "
        "but only root integrations are exported."
    )
    shard_profile["third_party_libraries"] = selected
    if version_overrides is not None:
        existing_overrides = shard_profile.get("third_party_library_version_overrides", {})
        if not isinstance(existing_overrides, dict):
            raise RuntimeError("full.third_party_library_version_overrides must be an object")
        conflicting = sorted(
            name
            for name, version in existing_overrides.items()
            if name in version_overrides and version_overrides[name] != version
        )
        if conflicting:
            raise RuntimeError(
                "pack version lock conflicts with configured overrides: "
                + ", ".join(conflicting)
            )
        shard_profile["third_party_library_version_overrides"] = {
            **version_overrides,
            **existing_overrides,
        }
    shard_profile["verification"] = {"enabled": False}
    shard_config["profiles"][profile_name] = shard_profile
    return shard_config, selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate a modular StaticPython library-pack shard profile.")
    parser.add_argument("--base-config", type=Path, default=REPO_ROOT / "config.json")
    parser.add_argument("--family", choices=PACK_FAMILIES, required=True)
    parser.add_argument("--profile-name", default="pack-shard")
    parser.add_argument("--version-lock", type=Path)
    parser.add_argument("--target-python-version")
    parser.add_argument("--output-config", type=Path, required=True)
    parser.add_argument("--output-pack-names", type=Path, required=True)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    base_config = json.loads(args.base_config.read_text(encoding="utf-8"))
    if (args.version_lock is None) != (args.target_python_version is None):
        raise RuntimeError(
            "--version-lock and --target-python-version must be provided together"
        )
    version_overrides = None
    if args.version_lock is not None:
        lock = load_pack_version_lock(
            args.version_lock,
            target_python_version=args.target_python_version,
        )
        version_overrides = lock["versions"]
    shard_config, selected = build_shard_config(
        base_config,
        args.family,
        args.profile_name,
        version_overrides=version_overrides,
    )
    args.output_config.parent.mkdir(parents=True, exist_ok=True)
    args.output_pack_names.parent.mkdir(parents=True, exist_ok=True)
    args.output_config.write_text(
        json.dumps(shard_config, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    args.output_pack_names.write_text(
        "".join(f"{name}\n" for name in selected),
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "family": args.family,
                "profile": args.profile_name,
                "pack_count": len(selected),
                "version_lock_count": len(version_overrides or {}),
            }
        )
    )


if __name__ == "__main__":
    main()
