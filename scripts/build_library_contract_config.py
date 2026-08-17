from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build
import libs
from packaging.version import Version


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
        canonical_name: release_version,
    }
    profile["third_party_dependency_resolution"] = {
        "mode": libs.HISTORICAL_DEPENDENCY_SOLVER,
        "root": canonical_name,
    }
    # Disable only the monolithic full-profile script. Per-integration import,
    # resource and behavior smokes still run through verify.py.
    profile["verification"] = {"enabled": False}

    result = copy.deepcopy(base_config)
    result["profiles"][profile_name] = profile
    return result, canonical_name


def resolve_contract_dependency_lock(
    config: dict,
    target_python_version: str,
    *,
    profile_name: str = "library-contract",
) -> dict:
    profiles = config.get("profiles")
    if not isinstance(profiles, dict) or not isinstance(profiles.get(profile_name), dict):
        raise RuntimeError(f"config must define the {profile_name!r} profile")
    profile = profiles[profile_name]
    resolution = profile.get("third_party_dependency_resolution")
    if not isinstance(resolution, dict):
        raise RuntimeError("historical contract profile has no dependency resolution settings")
    mode = resolution.get("mode")
    if mode != libs.HISTORICAL_DEPENDENCY_SOLVER:
        raise RuntimeError(f"unsupported historical dependency solver: {mode!r}")
    selected = profile.get("third_party_libraries")
    if not isinstance(selected, list) or len(selected) != 1:
        raise RuntimeError("historical contract profile must select exactly one root library")
    target_version = Version(target_python_version)
    catalog = build.profile_library_catalog(
        config,
        profile,
        "third_party_library_catalog",
    )
    integrations = libs.load_integrations(
        build.LIB_PATCH_ROOT,
        selected,
        target_version=target_version,
        version_overrides=profile.get("third_party_library_version_overrides"),
        library_catalog=catalog,
        dependency_resolution_mode=mode,
    )
    lock = libs.dependency_resolution_lock(
        integrations,
        target_version=target_version,
        solver=mode,
        roots=selected,
    )
    profile["third_party_library_version_overrides"] = {
        record["name"]: record["version"]
        for record in lock["integrations"]
    }
    resolution["lock"] = lock
    return lock


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a minimal profile for one historical library version contract."
    )
    parser.add_argument("--base-config", type=Path, default=REPO_ROOT / "config.json")
    parser.add_argument("--library", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--profile-name", default="library-contract")
    parser.add_argument("--target-python-version", required=True)
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
    lock = resolve_contract_dependency_lock(
        payload,
        args.target_python_version,
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
                "dependency_solver_fingerprint": (
                    lock.get("solver_fingerprint") if isinstance(lock, dict) else None
                ),
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
