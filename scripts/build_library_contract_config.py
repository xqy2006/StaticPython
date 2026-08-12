from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def build_contract_config(
    base_config: dict,
    library_name: str,
    release_version: str,
    *,
    profile_name: str = "library-contract",
) -> tuple[dict, str]:
    profiles = base_config.get("profiles")
    if not isinstance(profiles, dict) or not isinstance(profiles.get("full"), dict):
        raise RuntimeError("config must define a full profile")
    full_profile = profiles["full"]
    libraries = full_profile.get("third_party_libraries")
    if not isinstance(libraries, list):
        raise RuntimeError("full.third_party_libraries must be a list")
    historical_libraries = full_profile.get("historical_library_contract_libraries", [])
    if not isinstance(historical_libraries, list):
        raise RuntimeError("full.historical_library_contract_libraries must be a list")
    by_name = {
        name.casefold(): name
        for name in [*libraries, *historical_libraries]
        if isinstance(name, str) and name
    }
    canonical_name = by_name.get(library_name.casefold())
    if canonical_name is None:
        raise RuntimeError(
            f"library {library_name!r} is not in the current or historical contract catalog"
        )
    if not release_version:
        raise RuntimeError("release version must not be empty")

    profile = copy.deepcopy(full_profile)
    profile["description"] = (
        f"Historical version contract build for {canonical_name} {release_version}; "
        "dependencies are resolved transitively and behavior smoke tests remain enabled."
    )
    profile["third_party_libraries"] = [canonical_name]
    overrides = profile.get("third_party_library_version_overrides", {})
    if not isinstance(overrides, dict):
        raise RuntimeError("full.third_party_library_version_overrides must be an object")
    profile["third_party_library_version_overrides"] = {
        **overrides,
        canonical_name: release_version,
    }
    # Disable only the monolithic full-profile script. Per-integration import,
    # resource and behavior smokes still run through verify.py.
    profile["verification"] = {"enabled": False}

    result = copy.deepcopy(base_config)
    result["profiles"][profile_name] = profile
    return result, canonical_name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a minimal profile for one historical library version contract."
    )
    parser.add_argument("--base-config", type=Path, default=REPO_ROOT / "config.json")
    parser.add_argument("--library", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--profile-name", default="library-contract")
    parser.add_argument("--output-config", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    base_config = json.loads(args.base_config.read_text(encoding="utf-8"))
    payload, canonical_name = build_contract_config(
        base_config,
        args.library,
        args.version,
        profile_name=args.profile_name,
    )
    args.output_config.parent.mkdir(parents=True, exist_ok=True)
    args.output_config.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        json.dumps(
            {
                "library": canonical_name,
                "version": args.version,
                "profile": args.profile_name,
                "output": str(args.output_config),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
