from __future__ import annotations

import argparse
from pathlib import Path
import sys

from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parents[1]
repo_root_text = str(REPO_ROOT)
if repo_root_text not in sys.path:
    sys.path.insert(0, repo_root_text)

import build as staticpython_build


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resume a StaticPython build from an already prepared CPython source tree."
    )
    parser.add_argument("source_root", type=Path, help="Prepared CPython source tree")
    parser.add_argument("--config", type=Path, default=staticpython_build.CONFIG_PATH, help="Config JSON path")
    parser.add_argument("--profile", help="Profile name from the selected config")
    parser.add_argument("--host-python", default="python", help="Host python used for helper scripts")
    parser.add_argument("--configuration", default="Release")
    parser.add_argument("--platform", default="x64")
    parser.add_argument("--build-workers", type=int, default=2)
    parser.add_argument("--output-dir", type=Path, help="Optional artifact export directory")
    parser.add_argument("--skip-verify", action="store_true")
    parser.add_argument("--skip-export", action="store_true")
    parser.add_argument("--verify-report-json", type=Path, help="Optional verify.py JSON report path")
    return parser.parse_args()


def resume_freeze_modules(
    source_root: Path,
    host_python: str,
    configuration: str,
    platform: str,
    version_info: tuple[int, int, int],
    build_workers: int,
) -> None:
    freeze_exe = staticpython_build.get_pcbuild_output_dir(source_root, platform) / "_freeze_module.exe"
    if freeze_exe.exists():
        staticpython_build.log(
            f"reusing existing {freeze_exe.relative_to(source_root)} and skipping _freeze_module.vcxproj rebuild"
        )
    else:
        freeze_exe = staticpython_build.ensure_freeze_module_exe(
            source_root,
            configuration,
            platform,
            build_workers,
        )

    staticpython_build.run(
        [host_python, str(source_root / "Tools" / "build" / "freeze_modules.py"), "--step=0"],
        cwd=source_root,
    )
    staticpython_build.run(
        [host_python, str(source_root / "Tools" / "build" / "freeze_modules.py"), "--step=1"],
        cwd=source_root,
    )
    staticpython_build.maybe_freeze_getpath_header(source_root, freeze_exe)
    if staticpython_build.supports_pyrepl(version_info):
        staticpython_build.run(
            [
                str(freeze_exe),
                "_pyrepl",
                str(source_root / "Lib" / "_pyrepl" / "__main__.py"),
                str(source_root / "Python" / "frozen_modules" / "_pyrepl.h"),
            ],
            cwd=source_root,
        )
    else:
        staticpython_build.log("skip standalone _pyrepl freezing for CPython < 3.13")


def main() -> int:
    args = parse_args()
    source_root = args.source_root.resolve()
    staticpython_build.verify_source_root(source_root)

    version_info, version_mm, version_full = staticpython_build.parse_cpython_version(source_root)
    build_workers = staticpython_build.resolve_build_workers(args.build_workers)
    config_path = args.config.resolve()
    config = staticpython_build.load_config(config_path)
    profile_name, profile = staticpython_build.resolve_profile(config, args.profile)
    target_version = Version(version_full)

    core_version_overrides = profile.get("core_library_version_overrides")
    third_party_version_overrides = profile.get("third_party_library_version_overrides")
    core_integrations = staticpython_build.load_integrations(
        staticpython_build.CORE_PATCH_ROOT,
        profile.get("core_libraries", "all"),
        target_version=target_version,
        version_overrides=core_version_overrides,
    )
    third_party_integrations = staticpython_build.load_integrations(
        staticpython_build.LIB_PATCH_ROOT,
        profile.get("third_party_libraries", "all"),
        target_version=target_version,
        version_overrides=third_party_version_overrides,
    )
    integrations = [*core_integrations, *third_party_integrations]
    manifest = staticpython_build.load_manifest()

    staticpython_build.log(f"resuming prepared build for CPython {version_full}")
    staticpython_build.log(
        f"resume profile: {profile_name} "
        f"({len(core_integrations)} core integration(s), {len(third_party_integrations)} third-party integration(s))"
    )
    staticpython_build.log(f"resume build workers: {build_workers}")

    staticpython_build.maybe_restore_getpath_header(source_root, version_info)
    staticpython_build.log("resuming freeze tool build and frozen module regeneration")
    resume_freeze_modules(
        source_root,
        args.host_python,
        args.configuration,
        args.platform,
        version_info,
        build_workers,
    )
    staticpython_build.maybe_restore_getpath_header(source_root, version_info)
    staticpython_build.verify_runtime_resource_modules_frozen(source_root)
    staticpython_build.log("resuming frozen module bytecode split")
    staticpython_build.split_frozen_modules(source_root)
    staticpython_build.log("resuming static library and python.exe build")
    staticpython_build.build_python(
        source_root,
        args.configuration,
        args.platform,
        manifest,
        integrations,
        version_info,
        version_mm,
        version_full,
        build_workers=build_workers,
    )

    built_exe = staticpython_build.get_pcbuild_output_dir(source_root, args.platform) / "python.exe"
    if not built_exe.exists():
        raise RuntimeError(f"build did not produce {built_exe}")

    if args.output_dir and not args.skip_export:
        staticpython_build.export_built_python(
            built_exe,
            args.output_dir.resolve(),
            version_full,
            args.platform,
            profile_name,
        )

    if not args.skip_verify:
        verify_cmd = [
            args.host_python,
            str(staticpython_build.REPO_ROOT / "verify.py"),
            "--python-exe",
            str(built_exe),
            "--manifest",
            str(staticpython_build.MANIFEST_PATH),
            "--repo-root",
            str(staticpython_build.REPO_ROOT),
            "--source-root",
            str(source_root),
            "--profile",
            profile_name,
            "--config",
            str(config_path),
        ]
        if args.verify_report_json:
            verify_cmd.extend(["--report-json", str(args.verify_report_json.resolve())])
        staticpython_build.log("running resumed post-build verification")
        staticpython_build.run(verify_cmd, cwd=staticpython_build.REPO_ROOT, timeout=60 * 20)

    staticpython_build.log("resume build done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
