from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

from packaging.version import Version

from libs import load_integrations

PROFILE_METADATA_RELATIVE_PATH = Path("PCbuild") / "staticpython-profile.json"


def log(message: str) -> None:
    text = f"[staticpython-verify] {message}"
    encoding = sys.stdout.encoding or "utf-8"
    safe_text = text.encode(encoding, errors="backslashreplace").decode(encoding, errors="replace")
    print(safe_text, flush=True)


def load_manifest(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8"))
    base_path = Path(__file__).resolve().parent / "config.json"
    if path.resolve() == base_path.resolve() or not base_path.exists():
        return config

    base_config = json.loads(base_path.read_text(encoding="utf-8"))
    for key in ("core_library_catalog", "third_party_library_catalog", "verification"):
        if key in base_config and key not in config:
            config[key] = base_config[key]
    return config


def profile_metadata_path(source_root: Path) -> Path:
    return source_root / PROFILE_METADATA_RELATIVE_PATH


def load_profile_metadata(source_root: Path) -> dict | None:
    path = profile_metadata_path(source_root)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def integration_names(integrations: list) -> list[str]:
    return [integration.name for integration in integrations]


def _normalized_name_list(values: list[str] | None) -> list[str]:
    if not values:
        return []
    return sorted(str(value) for value in values)


def resolve_profile(config: dict, profile_name: str | None) -> tuple[str, dict]:
    profiles = config.get("profiles", {})
    selected_name = profile_name or config.get("default_profile") or "full"
    if selected_name not in profiles:
        available = ", ".join(sorted(profiles)) or "<none>"
        raise RuntimeError(f"unknown profile {selected_name!r}; available profiles: {available}")
    profile = profiles[selected_name]
    if not isinstance(profile, dict):
        raise RuntimeError(f"profile {selected_name!r} must be an object")
    return selected_name, profile


def profile_library_catalog(config: dict, profile: dict, key: str) -> object | None:
    return profile.get(key, config.get(key))


def profile_verification_config(config: dict, profile: dict) -> dict:
    root_config = config.get("verification", {})
    if root_config is None:
        root_config = {}
    if not isinstance(root_config, dict):
        raise RuntimeError("config verification must be an object")
    profile_config = profile.get("verification")
    if profile_config is None:
        return dict(root_config)
    if not isinstance(profile_config, dict):
        raise RuntimeError("profile verification must be an object")
    merged = dict(root_config)
    merged.update(profile_config)
    return merged


def verify_profile_metadata(
    source_root: Path,
    profile_name: str,
    core_integrations: list,
    third_party_integrations: list,
) -> list[dict]:
    metadata = load_profile_metadata(source_root)
    if metadata is None:
        return [
            {
                "step": "profile-metadata",
                "name": "build-profile",
                "error_type": "MissingProfileMetadata",
                "error": (
                    "build profile metadata is missing; rerun build.py so verify can confirm the "
                    "materialized source tree matches the requested profile"
                ),
                "details": [str(profile_metadata_path(source_root))],
                "traceback": "",
                "stdout": "",
                "stderr": "",
                "command": "",
            }
        ]

    expected_core = integration_names(core_integrations)
    expected_third_party = integration_names(third_party_integrations)
    expected_core_normalized = _normalized_name_list(expected_core)
    expected_third_party_normalized = _normalized_name_list(expected_third_party)
    recorded_core = metadata.get("core_libraries")
    recorded_third_party = metadata.get("third_party_libraries")
    recorded_core_normalized = _normalized_name_list(recorded_core)
    recorded_third_party_normalized = _normalized_name_list(recorded_third_party)
    details = []
    if metadata.get("profile_name") != profile_name:
        details.append(f"expected profile name: {profile_name}")
        details.append(f"recorded profile name: {metadata.get('profile_name')}")
    if recorded_core_normalized != expected_core_normalized:
        details.append(f"expected core libraries: {expected_core_normalized}")
        details.append(f"recorded core libraries: {recorded_core_normalized}")
    if recorded_third_party_normalized != expected_third_party_normalized:
        details.append(f"expected third-party libraries: {expected_third_party_normalized}")
        details.append(f"recorded third-party libraries: {recorded_third_party_normalized}")

    if not details:
        return []

    return [
        {
            "step": "profile-metadata",
            "name": "build-profile",
            "error_type": "ProfileMismatch",
            "error": (
                "the patched CPython tree does not match the requested verification profile; "
                "rerun build.py for this profile before trusting the verification result"
            ),
            "details": details,
            "traceback": "",
            "stdout": "",
            "stderr": "",
            "command": "",
        }
    ]


def _to_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_capture(cmd: list[str], *, cwd: Path, timeout: float, env: dict[str, str] | None = None) -> dict:
    display = subprocess.list2cmdline([str(part) for part in cmd])
    log(f"RUN {display}")
    try:
        completed = subprocess.run(
            cmd,
            cwd=str(cwd),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return {
            "ok": False,
            "timeout": True,
            "returncode": None,
            "stdout": _to_text(exc.stdout),
            "stderr": _to_text(exc.stderr),
            "error": f"timed out after {timeout} seconds",
            "display": display,
        }
    return {
        "ok": completed.returncode == 0,
        "timeout": False,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stderr": completed.stderr,
        "display": display,
    }


def make_process_failure(step: str, result: dict, name: str | None = None) -> dict:
    return {
        "step": step,
        "name": name or step,
        "error_type": "TimeoutExpired" if result.get("timeout") else "SubprocessError",
        "error": result.get("error") or f"command exited with code {result.get('returncode')}",
        "traceback": "",
        "stdout": result.get("stdout", ""),
        "stderr": result.get("stderr", ""),
        "command": result.get("display"),
    }


def run_command_step(
    step: str,
    cmd: list[str],
    cwd: Path,
    timeout: float,
    *,
    env: dict[str, str] | None = None,
) -> list[dict]:
    result = run_capture(cmd, cwd=cwd, timeout=timeout, env=env)
    if result.get("ok"):
        log(f"{step}: passed")
        return []
    return [make_process_failure(step, result)]


def build_target_command_prefix(python_exe: Path, *, source_mode: bool) -> list[str]:
    prefix = [str(python_exe)]
    if source_mode:
        prefix.extend(["-X", "frozen_modules=off"])
    return prefix


def build_target_env(source_root: Path, *, source_mode: bool) -> dict[str, str] | None:
    if not source_mode:
        return None
    env = os.environ.copy()
    env["PYTHONHOME"] = str(source_root)
    env["PYTHONPATH"] = str(source_root / "Lib")
    return env


def verify_profile_script(
    python_cmd_prefix: list[str],
    target_env: dict[str, str] | None,
    repo_root: Path,
    verification_config: dict,
    skipped_groups: set[str],
) -> list[dict]:
    if not verification_config.get("enabled", False):
        log("skip profile verification script because verification.enabled is false")
        return []

    step = verification_config.get("script")
    if step is None:
        log("skip profile verification script because verification.script is not configured")
        return []
    if not isinstance(step, dict):
        raise RuntimeError("verification.script must be an object")
    if step.get("kind", "script") != "script":
        raise RuntimeError("verification.script.kind must be 'script'")

    skip_group = step.get("skip_group")
    if skip_group and skip_group in skipped_groups:
        log(f"skip profile verification script {step.get('name', '<unnamed>')} because --skip-{skip_group} was requested")
        return []

    script = step.get("script")
    if not script:
        raise RuntimeError("verification.script.script is required")
    script_path = Path(script)
    if not script_path.is_absolute():
        script_path = repo_root / script_path
    if not script_path.exists():
        raise RuntimeError(f"verification script not found: {script_path}")

    timeout = float(step.get("timeout", 600))
    args = [str(arg) for arg in step.get("args", [])]
    return run_command_step(
        step.get("name") or script_path.name,
        [*python_cmd_prefix, str(script_path), *args],
        repo_root,
        timeout,
        env=target_env,
    )


def verification_coverage(integrations: list, verification_config: dict) -> dict:
    script = verification_config.get("script")
    return {
        "library_count": len(integrations),
        "profile_script_enabled": bool(verification_config.get("enabled", False)),
        "profile_script_name": script.get("name") if isinstance(script, dict) else None,
    }


def emit_failure(failure: dict, index: int, total: int) -> None:
    header = f"[{index}/{total}] {failure['step']}::{failure['name']}"
    log(header)
    log(f"  {failure.get('error_type', 'Error')}: {failure.get('error', 'unknown error')}")
    command = failure.get("command")
    if command:
        log(f"  command: {command}")
    details = failure.get("details", [])
    if details:
        log("  details:")
        for line in details:
            log(f"    {line}")
    traceback_text = failure.get("traceback", "").strip()
    if traceback_text:
        log("  traceback:")
        for line in traceback_text.splitlines():
            log(f"    {line}")
    stdout_text = failure.get("stdout", "").strip()
    if stdout_text:
        log("  stdout:")
        for line in stdout_text.splitlines():
            log(f"    {line}")
    stderr_text = failure.get("stderr", "").strip()
    if stderr_text:
        log("  stderr:")
        for line in stderr_text.splitlines():
            log(f"    {line}")


def write_report(path: Path, python_exe: Path, failures: list[dict], coverage: dict) -> None:
    report = {
        "python_exe": str(python_exe),
        "failure_count": len(failures),
        "failures": failures,
        "verification_coverage": coverage,
    }
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    log(f"wrote verification report to {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Verify a single-file Python runtime using the configured profile script.")
    parser.add_argument("--python-exe", type=Path, required=True, help="Path to the built single-file python.exe")
    parser.add_argument("--manifest", type=Path, required=True, help="Path to manifest.json")
    parser.add_argument("--config", type=Path, help="Path to config.json")
    parser.add_argument("--repo-root", type=Path, required=True, help="Path to the builder repository root")
    parser.add_argument("--source-root", type=Path, required=True, help="Path to the patched CPython source tree")
    parser.add_argument("--profile", help="Build profile from config.json. Defaults to config.default_profile.")
    parser.add_argument("--skip-crypto", action="store_true", help="Skip the full Crypto.SelfTest suite")
    parser.add_argument("--skip-gui", action="store_true", help="Skip libui smoke and GUI tests")
    parser.add_argument(
        "--target-source-mode",
        action="store_true",
        help=(
            "Run the target python.exe against --source-root via PYTHONHOME/PYTHONPATH and "
            "-X frozen_modules=off. Useful for manually reproducing stale-binary failures with "
            "the current patched sources."
        ),
    )
    parser.add_argument("--report-json", type=Path, help="Optional path to write a JSON verification report")
    return parser.parse_args()


def _emit_failures(
    failures: list[dict],
    *,
    python_exe: Path,
    coverage: dict,
    report_json: Path | None,
    summary_prefix: str = "verification failed with",
) -> None:
    if report_json:
        write_report(report_json.resolve(), python_exe, failures, coverage)
    log(f"{summary_prefix} {len(failures)} issue(s)")
    for index, failure in enumerate(failures, start=1):
        emit_failure(failure, index, len(failures))


def _target_version(source_root: Path) -> Version:
    metadata = load_profile_metadata(source_root) or {}
    version_text = metadata.get("version_full")
    if version_text:
        return Version(version_text)

    patchlevel = source_root / "Include" / "patchlevel.h"
    patchlevel_text = patchlevel.read_text(encoding="utf-8")
    major = int(next(line.split()[-1] for line in patchlevel_text.splitlines() if line.startswith("#define PY_MAJOR_VERSION")))
    minor = int(next(line.split()[-1] for line in patchlevel_text.splitlines() if line.startswith("#define PY_MINOR_VERSION")))
    micro = int(next(line.split()[-1] for line in patchlevel_text.splitlines() if line.startswith("#define PY_MICRO_VERSION")))
    return Version(f"{major}.{minor}.{micro}")


def main() -> None:
    args = parse_args()
    python_exe = args.python_exe.resolve()
    load_manifest(args.manifest.resolve())
    repo_root = args.repo_root.resolve()
    config = load_config((args.config or (repo_root / "config.json")).resolve())
    profile_name, profile = resolve_profile(config, args.profile)
    source_root = args.source_root.resolve()

    if not python_exe.exists():
        raise RuntimeError(f"python executable not found: {python_exe}")

    target_version = _target_version(source_root)
    core_library_catalog = profile_library_catalog(config, profile, "core_library_catalog")
    third_party_library_catalog = profile_library_catalog(config, profile, "third_party_library_catalog")
    verification_config = profile_verification_config(config, profile)
    core_integrations = load_integrations(
        repo_root / "Core",
        profile.get("core_libraries", "all"),
        target_version=target_version,
        library_catalog=core_library_catalog,
    )
    integrations = load_integrations(
        repo_root / "Lib",
        profile.get("third_party_libraries", "all"),
        target_version=target_version,
        library_catalog=third_party_library_catalog,
    )
    log(
        f"verification profile: {profile_name} "
        f"({len(core_integrations)} core integration(s), {len(integrations)} third-party integration(s))"
    )

    target_source_mode = args.target_source_mode
    python_cmd_prefix = build_target_command_prefix(python_exe, source_mode=target_source_mode)
    target_env = build_target_env(source_root, source_mode=target_source_mode)
    if target_source_mode:
        log(
            "target source mode enabled: running the target python.exe with "
            f"PYTHONHOME={source_root} PYTHONPATH={source_root / 'Lib'} and -X frozen_modules=off"
        )

    coverage = verification_coverage(integrations, verification_config)
    if coverage["profile_script_enabled"]:
        log(f"profile verification script: {coverage['profile_script_name'] or '<unnamed>'}")
    else:
        log("profile verification script: disabled")

    skipped_groups = set()
    if args.skip_crypto:
        skipped_groups.add("crypto")
    if args.skip_gui:
        skipped_groups.add("gui")
    if skipped_groups:
        target_env = dict(os.environ if target_env is None else target_env)
        if "crypto" in skipped_groups:
            target_env["STATICPYTHON_VERIFY_SKIP_CRYPTO"] = "1"
        if "gui" in skipped_groups:
            target_env["STATICPYTHON_VERIFY_SKIP_GUI"] = "1"

    failures = verify_profile_metadata(source_root, profile_name, core_integrations, integrations)
    if failures:
        _emit_failures(
            failures,
            python_exe=python_exe,
            coverage=coverage,
            report_json=args.report_json,
            summary_prefix="verification profile checks failed with",
        )
        raise SystemExit(1)

    failures.extend(verify_profile_script(python_cmd_prefix, target_env, repo_root, verification_config, skipped_groups))

    if args.report_json:
        write_report(args.report_json.resolve(), python_exe, failures, coverage)

    if failures:
        _emit_failures(
            failures,
            python_exe=python_exe,
            coverage=coverage,
            report_json=None,
        )
        raise SystemExit(1)

    log("all verification steps passed")


if __name__ == "__main__":
    main()
