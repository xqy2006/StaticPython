from __future__ import annotations

import ast
import http.client
import json
import hashlib
import io
import importlib.util
import math
import os
import sys
import tarfile
import tempfile
import unittest
from unittest import mock
from pathlib import Path
from types import SimpleNamespace
from urllib.error import HTTPError
from zipfile import ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build
import libs
import pack_evidence
import verify as staticpython_verify

_INDEX_SPEC = importlib.util.spec_from_file_location(
    "staticpython_build_release_index",
    REPO_ROOT / "scripts" / "build_release_index.py",
)
assert _INDEX_SPEC is not None and _INDEX_SPEC.loader is not None
build_release_index = importlib.util.module_from_spec(_INDEX_SPEC)
_INDEX_SPEC.loader.exec_module(build_release_index)

_SHARD_SPEC = importlib.util.spec_from_file_location(
    "staticpython_build_pack_shard_config",
    REPO_ROOT / "scripts" / "build_pack_shard_config.py",
)
assert _SHARD_SPEC is not None and _SHARD_SPEC.loader is not None
build_pack_shard_config = importlib.util.module_from_spec(_SHARD_SPEC)
_SHARD_SPEC.loader.exec_module(build_pack_shard_config)
import resolve_pack_versions as pack_version_resolver

_LICENSE_AUDIT_SPEC = importlib.util.spec_from_file_location(
    "staticpython_audit_library_licenses",
    REPO_ROOT / "scripts" / "audit_library_licenses.py",
)
assert _LICENSE_AUDIT_SPEC is not None and _LICENSE_AUDIT_SPEC.loader is not None
audit_library_licenses = importlib.util.module_from_spec(_LICENSE_AUDIT_SPEC)
_LICENSE_AUDIT_SPEC.loader.exec_module(audit_library_licenses)

_RESOURCE_SCAN_SPEC = importlib.util.spec_from_file_location(
    "staticpython_scan_library_resources",
    REPO_ROOT / "scripts" / "scan_library_resources.py",
)
assert _RESOURCE_SCAN_SPEC is not None and _RESOURCE_SCAN_SPEC.loader is not None
scan_library_resources = importlib.util.module_from_spec(_RESOURCE_SCAN_SPEC)
sys.modules[_RESOURCE_SCAN_SPEC.name] = scan_library_resources
_RESOURCE_SCAN_SPEC.loader.exec_module(scan_library_resources)


def _passed_pe_audit() -> dict:
    return {
        "status": "passed",
        "dependencies": ["KERNEL32.dll"],
        "forbidden_dependencies": [],
        "non_system_dependencies": [],
        "forbidden_entry_symbols": [],
        "main_object_records": [],
        "executable_sha256": "e" * 64,
        "map_sha256": "f" * 64,
    }


def _passed_report_smoke(integration: str, name: str, kind: str) -> dict:
    return {
        "integration": integration,
        "name": name,
        "kind": kind,
        "status": "passed",
        "returncode": 0,
        "timed_out": False,
        "released_files": [],
    }


def _passed_runtime_sdk() -> dict:
    return {
        "archive_sha256": "9" * 64,
        "cpython_version": "3.13.0",
        "runtime_abi": "staticpython-pack-v1-cp313",
        "staticpython_commit": "d" * 40,
    }


def load_template_function(path: Path, name: str, globals_: dict):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    namespace = dict(globals_)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


class RuntimeSDKTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def test_download_file_retries_transient_disconnects_atomically(self) -> None:
        destination = self.root / "source.zip"
        with (
            mock.patch.object(
                build,
                "urlopen",
                side_effect=[
                    build.http.client.RemoteDisconnected("first disconnect"),
                    build.URLError("second disconnect"),
                    io.BytesIO(b"archive payload"),
                ],
            ) as urlopen,
            mock.patch.object(build.time, "sleep") as sleep,
        ):
            build.download_file("https://example.invalid/source.zip", destination)

        self.assertEqual(destination.read_bytes(), b"archive payload")
        self.assertFalse(Path(str(destination) + ".tmp").exists())
        self.assertEqual(urlopen.call_count, 3)
        sleep.assert_has_calls([mock.call(1), mock.call(2)])

    def test_download_file_exhausts_retries_without_partial_output(self) -> None:
        destination = self.root / "source.zip"
        temporary = Path(str(destination) + ".tmp")
        temporary.write_bytes(b"stale partial download")
        with (
            mock.patch.object(
                build,
                "urlopen",
                side_effect=build.http.client.RemoteDisconnected("disconnect"),
            ) as urlopen,
            mock.patch.object(build.time, "sleep") as sleep,
            self.assertRaises(build.http.client.RemoteDisconnected),
        ):
            build.download_file("https://example.invalid/source.zip", destination)

        self.assertFalse(destination.exists())
        self.assertFalse(temporary.exists())
        self.assertEqual(urlopen.call_count, build.DOWNLOAD_MAX_ATTEMPTS)
        sleep.assert_has_calls([mock.call(1), mock.call(2), mock.call(4)])

    def test_library_download_is_atomic_and_cleans_failed_temporary_file(self) -> None:
        destination = self.root / "source.zip"
        temporary = Path(str(destination) + ".tmp")
        temporary.write_bytes(b"stale partial download")

        with (
            mock.patch.object(libs, "_read_url_bytes", side_effect=OSError("disconnect")),
            self.assertRaisesRegex(OSError, "disconnect"),
        ):
            libs._download_file("https://example.invalid/source.zip", destination)

        self.assertFalse(destination.exists())
        self.assertFalse(temporary.exists())

    def test_library_http_reader_retries_only_transient_failures(self) -> None:
        with (
            mock.patch.object(
                libs,
                "urlopen",
                side_effect=[
                    http.client.RemoteDisconnected("disconnect"),
                    io.BytesIO(b"payload"),
                ],
            ) as urlopen,
            mock.patch.object(libs.time, "sleep") as sleep,
        ):
            payload = libs._read_url_bytes("https://example.invalid/source.zip")

        self.assertEqual(payload, b"payload")
        self.assertEqual(urlopen.call_count, 2)
        sleep.assert_called_once_with(1.0)

        not_found = HTTPError(
            "https://example.invalid/missing.zip",
            404,
            "not found",
            None,
            None,
        )
        with (
            mock.patch.object(libs, "urlopen", side_effect=not_found) as urlopen,
            mock.patch.object(libs.time, "sleep") as sleep,
            self.assertRaises(HTTPError),
        ):
            libs._read_url_bytes("https://example.invalid/missing.zip")

        urlopen.assert_called_once()
        sleep.assert_not_called()

    def test_default_github_archives_have_codeload_fallback(self) -> None:
        self.assertEqual(
            libs._github_archive_urls(
                "owner/project",
                "v1.2.3",
                "tags",
                None,
                {},
            ),
            [
                "https://github.com/owner/project/archive/refs/tags/v1.2.3.zip",
                "https://codeload.github.com/owner/project/zip/refs/tags/v1.2.3",
            ],
        )

    def test_custom_github_archive_does_not_invent_a_mirror(self) -> None:
        self.assertEqual(
            libs._github_archive_urls(
                "owner/project",
                "v1.2.3",
                "tags",
                "https://sources.example/{repo}/{ref}.zip",
                {},
            ),
            ["https://sources.example/owner/project/v1.2.3.zip"],
        )

    def test_cpython_download_falls_back_and_records_actual_source(self) -> None:
        version = "3.15.0rc1"
        fixture_root = self.root / "fixture" / f"Python-{version}"
        (fixture_root / "Include").mkdir(parents=True)
        (fixture_root / "Include" / "patchlevel.h").write_text(
            "#define PY_VERSION \"3.15.0rc1\"\n",
            encoding="utf-8",
        )
        fallback_archive = self.root / "fallback.tgz"
        with build.tarfile.open(fallback_archive, "w:gz") as archive:
            archive.add(fixture_root, arcname=fixture_root.name)

        requested_urls: list[str] = []

        def fake_download(url: str, destination: Path, *, force: bool = False) -> None:
            del force
            requested_urls.append(url)
            if "python.org" not in url:
                raise build.http.client.RemoteDisconnected("unavailable")
            destination.write_bytes(fallback_archive.read_bytes())

        commit = "a" * 40
        with (
            mock.patch.object(build, "download_file", side_effect=fake_download),
            mock.patch.object(build, "resolve_cpython_tag_commit", return_value=commit),
        ):
            source_root = build.download_cpython_source(
                version,
                self.root / "downloads",
                None,
            )

        self.assertEqual(source_root.name, f"cpython-{version}")
        self.assertTrue((source_root / "Include" / "patchlevel.h").is_file())
        self.assertEqual(len(requested_urls), 3)
        self.assertEqual(
            requested_urls[-1],
            "https://www.python.org/ftp/python/3.15.0/Python-3.15.0rc1.tgz",
        )
        provenance = json.loads(
            (source_root / build.CPYTHON_SOURCE_PROVENANCE_RELATIVE_PATH).read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(provenance["archive_url"], requested_urls[-1])
        self.assertEqual(provenance["commit"], commit)
        self.assertEqual(
            provenance["archive_sha256"],
            build.sha256_file(self.root / "downloads" / f"cpython-v{version}-python-org.tgz"),
        )

    def test_safe_tar_extraction_rejects_links_and_special_members(self) -> None:
        for member_type in (
            build.tarfile.SYMTYPE,
            build.tarfile.LNKTYPE,
            build.tarfile.FIFOTYPE,
            build.tarfile.CHRTYPE,
            build.tarfile.BLKTYPE,
        ):
            archive_path = self.root / f"unsafe-{member_type.hex()}.tar"
            with build.tarfile.open(archive_path, "w") as archive:
                member = build.tarfile.TarInfo("source/unsafe")
                member.type = member_type
                if member_type in {build.tarfile.SYMTYPE, build.tarfile.LNKTYPE}:
                    member.linkname = "../../outside"
                archive.addfile(member)
            destination = self.root / f"extract-{member_type.hex()}"
            destination.mkdir()
            with (
                build.tarfile.open(archive_path, "r:") as archive,
                self.assertRaisesRegex(RuntimeError, "unsupported link or special member"),
            ):
                build.safe_extract_tar(archive, destination)
            self.assertFalse((destination / "source" / "unsafe").exists())

    def _write_pack_promotion_fixture(self) -> tuple[dict, Path, dict]:
        staging = self.root / "promotion-fixture"
        staging.mkdir(exist_ok=True)
        payload = b"verified payload"
        (staging / "payload.bin").write_bytes(payload)
        provisional_metadata = {
            "schema_version": 1,
            "kind": "staticpython-library-pack",
            "name": "demo",
            "version": "1.0",
            "platform": "x64",
            "cpython_abi": "cp313",
            "cpython_version": "3.13.0",
            "runtime_abi": "staticpython-pack-v1-cp313",
            "staticpython_commit": "d" * 40,
            "cpython_commit": "c" * 40,
            "cpython_tag": "v3.13.0",
            "cpython_source": {
                "commit": "c" * 40,
                "archive_sha256": "a" * 64,
            },
            "toolchain": {
                "visual_studio_version": "17.0",
                "vscmd_version": "17.14.36",
                "vc_tools_version": "14.44.35207",
                "windows_sdk_version": "10.0.26100.0\\",
                "platform_toolset": "v143",
                "runtime_library": "MultiThreaded",
            },
            "license": {"status": "complete"},
            "files": [{
                "path": "payload.bin",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }],
            "verification": {"status": "not-run", "smoke_tests": []},
        }
        (staging / "pack.json").write_text(json.dumps(provisional_metadata), encoding="utf-8")
        provisional = self.root / "fixture-provisional.zip"
        build.write_deterministic_zip(staging, provisional)
        provisional_sha = build.sha256_file(provisional)
        payload_sha = build.pack_payload_manifest_sha256(provisional_metadata)
        metadata_sha = build.pack_metadata_without_verification_sha256(provisional_metadata)
        report = {
            "schema_version": 1,
            "kind": "staticpython-pack-sdk-verification",
            "status": "passed",
            "failures": [],
            "runtime_sdk": _passed_runtime_sdk(),
            "pe_audit": _passed_pe_audit(),
            "executable_sha256": "e" * 64,
            "packs": [{
                "name": "demo",
                "version": "1.0",
                "sha256": provisional_sha,
                "provisional_sha256": provisional_sha,
                "payload_manifest_sha256": payload_sha,
                "metadata_without_verification_sha256": metadata_sha,
            }],
            "integration_smoke_tests": [
                _passed_report_smoke("demo", "demo-behavior", "script"),
            ],
        }
        final_metadata = dict(provisional_metadata)
        final_metadata["verification"] = {
            "status": "passed",
            "smoke_tests": [{"name": "demo-behavior", "kind": "script", "status": "passed"}],
            "provisional_pack_sha256": provisional_sha,
            "payload_manifest_sha256": payload_sha,
            "metadata_without_verification_sha256": metadata_sha,
        }
        (staging / "pack.json").write_text(json.dumps(final_metadata), encoding="utf-8")
        final = self.root / "fixture-final.zip"
        build.write_deterministic_zip(staging, final)
        return report, final, final_metadata

    def test_runtime_sdk_profile_is_minimal(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        profile = config["profiles"]["runtime-sdk"]
        self.assertEqual(profile["build_type"], "runtime-sdk")
        self.assertEqual(profile["core_libraries"], "all")
        self.assertEqual(profile["third_party_libraries"], [])

    def test_release_and_contract_workflows_use_pack_only_runtime_sdk_evidence(self) -> None:
        release = (REPO_ROOT / ".github" / "workflows" / "release.yml").read_text(
            encoding="utf-8"
        )
        self.assertIn(
            "needs: [unit-tests, resolve-cpython-matrix, resolve-pack-versions, runtime-sdk]",
            release,
        )
        self.assertIn('"--pack-only"', release)
        self.assertIn('"--pack-runtime-sdk", $runtimeSdk[0].FullName', release)
        self.assertIn("python @evidenceArgs", release)

        daily = (
            REPO_ROOT / ".github" / "workflows" / "library-version-discovery.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("runtime_versions: ${{ steps.matrix.outputs.runtime_versions }}", daily)
        self.assertIn("build-contract-runtime-sdks:", daily)
        self.assertIn("needs: [discover, build-contract-runtime-sdks]", daily)
        self.assertIn("@($batch.candidates_json | ConvertFrom-Json)", daily)
        self.assertIn("pattern: contract-runtime-sdk-*", daily)
        self.assertIn("path: ${{ runner.temp }}/contract-runtime-sdks", daily)
        self.assertIn('"contract-runtime-sdk-$($candidate.python_version)"', daily)
        self.assertIn("--pack-only", daily)
        self.assertIn("--pack-runtime-sdk $runtimeSdk[0].FullName", daily)
        self.assertIn("python .\\pack_evidence.py --report $reportPath", daily)
        self.assertIn("staticpython-pack-verify-report.json", daily)

        history_shard = (
            REPO_ROOT / ".github" / "workflows" / "library-history-shard.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            '$batchKey = "${{ matrix.batch_sha256 }}".Substring(0, 12)',
            history_shard,
        )
        self.assertIn('$buildRoot = Join-Path $env:RUNNER_TEMP "h-$batchKey"', history_shard)
        self.assertNotIn(
            '"library-history-build-${{ matrix.batch_id }}"',
            history_shard,
        )

        history_weekly = (
            REPO_ROOT / ".github" / "workflows" / "library-history-weekly.yml"
        ).read_text(encoding="utf-8")
        self.assertIn(
            "artifact_suffix: ${{ steps.plan.outputs.artifact_suffix }}",
            history_weekly,
        )
        self.assertIn(
            '"artifact_suffix=$artifactSuffix" >> $env:GITHUB_OUTPUT',
            history_weekly,
        )
        self.assertIn(
            "artifact_suffix: ${{ needs.plan.outputs.artifact_suffix }}",
            history_weekly,
        )
        self.assertNotIn(
            "artifact_suffix: a${{ github.run_attempt }}",
            history_weekly,
        )
        self.assertGreaterEqual(history_weekly.count("overwrite: true"), 2)
        self.assertGreaterEqual(history_shard.count("overwrite: true"), 2)

    def test_verifier_applies_profile_version_overrides(self) -> None:
        profile = {
            "core_libraries": ["core-demo"],
            "third_party_libraries": ["third-demo"],
            "core_library_version_overrides": {"core-demo": "1.2.3"},
            "third_party_library_version_overrides": {"third-demo": "4.5.6"},
        }
        with mock.patch.object(
            staticpython_verify,
            "load_integrations",
            side_effect=(["core"], ["third"]),
        ) as load_integrations:
            core, third_party = staticpython_verify.load_profile_integrations(
                self.root,
                {},
                profile,
                libs.Version("3.12.13"),
            )

        self.assertEqual(core, ["core"])
        self.assertEqual(third_party, ["third"])
        self.assertEqual(
            load_integrations.call_args_list[0].kwargs["version_overrides"],
            {"core-demo": "1.2.3"},
        )
        self.assertEqual(
            load_integrations.call_args_list[1].kwargs["version_overrides"],
            {"third-demo": "4.5.6"},
        )

    def test_runtime_sdk_links_pythoncore_registry_and_security_apis(self) -> None:
        manifest = build.load_manifest()
        dependencies = {
            build.normalize_library_name(name).casefold()
            for name in manifest["python_link_dependencies_release_x64"]
        }
        self.assertIn("advapi32.lib", dependencies)

    def test_scipy_bracket_reports_function_calls(self) -> None:
        bracket = load_template_function(
            REPO_ROOT / "Lib" / "scipy" / "optimize_template.py",
            "bracket",
            {
                "math": math,
                "_ensure_tuple": lambda value: (
                    value if isinstance(value, tuple) else (value,)
                ),
            },
        )
        calls: list[float] = []

        def objective(value: float) -> float:
            calls.append(value)
            return (value - 2.0) ** 2

        result = bracket(objective, xa=0.0, xb=1.0)

        self.assertEqual(len(result), 7)
        xa, xb, xc, fa, fb, fc, funcalls = result
        self.assertLess(xa, xb)
        self.assertLess(xb, xc)
        self.assertLess(fb, fa)
        self.assertLess(fb, fc)
        self.assertEqual(funcalls, len(calls))

    def test_scipy_bracket_grow_limit_is_bounded_and_fails_closed(self) -> None:
        bracket = load_template_function(
            REPO_ROOT / "Lib" / "scipy" / "optimize_template.py",
            "bracket",
            {
                "math": math,
                "_ensure_tuple": lambda value: (
                    value if isinstance(value, tuple) else (value,)
                ),
            },
        )
        calls: list[float] = []

        def decreasing(value: float) -> float:
            calls.append(value)
            return -value

        with self.assertRaisesRegex(RuntimeError, "grow_limit"):
            bracket(
                decreasing,
                xa=0.0,
                xb=1.0,
                grow_limit=3.0,
                maxiter=1000,
            )

        self.assertLess(len(calls), 10)

    def test_scipy_cg_counts_attempted_iteration_before_breakdown(self) -> None:
        source = (
            REPO_ROOT / "Lib" / "scipy" / "sparse_linalg_template.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "iterations += 1\n        matvec = operator.matvec(direction)",
            source,
        )
        self.assertEqual(source.count("return x, iterations"), 3)
        self.assertNotIn("return x, -1", source)

    def test_scipy_declares_bundled_array_api_licenses(self) -> None:
        path = REPO_ROOT / "Lib" / "scipy" / "setup.py"
        spec = importlib.util.spec_from_file_location(
            "staticpython_scipy_setup_test",
            path,
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        integration = module.LIBRARY_INTEGRATION

        self.assertEqual(integration.license_expression, "BSD-3-Clause AND MIT")
        self.assertEqual(
            [record["filename"] for record in integration.license_sources],
            [
                "LICENSE-array-api-compat.txt",
                "LICENSE-array-api-extra.txt",
            ],
        )
        self.assertEqual(
            [record["sha256"] for record in integration.license_sources],
            [
                "4ffd978e3fa18d058d98c66771cfea7ed634aaf7023cf9612b8b55eee9a8f0fe",
                "58494398fe147fdce76a68b2decd4c08ce3a1ea237b6d6785001c15f822c6ed6",
            ],
        )

    def test_pack_only_build_compiles_only_integration_owned_projects(self) -> None:
        pcbuild = self.root / "PCbuild"
        pcbuild.mkdir(parents=True)
        (pcbuild / "demo_static.vcxproj").write_text("<Project />", encoding="utf-8")
        (pcbuild / "pythoncore.vcxproj").write_text("<Project />", encoding="utf-8")
        (pcbuild / "python.vcxproj").write_text("<Project />", encoding="utf-8")
        integration = libs.LibraryIntegration(
            name="demo",
            static_library_projects_release_x64=["demo_static.vcxproj"],
        )
        with (
            mock.patch.object(build, "stage_pack_build_pyconfig_header") as stage_pyconfig,
            mock.patch.object(build, "run_pre_build_hooks") as pre_build,
            mock.patch.object(build, "stage_static_libraries") as stage,
            mock.patch.object(build, "resolve_msbuild_exe", return_value=Path("msbuild.exe")),
            mock.patch.object(
                build,
                "msbuild_args",
                return_value=["/p:Configuration=Release"],
            ) as msbuild_args,
            mock.patch.object(build, "run") as run,
        ):
            build.build_pack_static_libraries(
                self.root,
                "Release",
                "x64",
                [integration],
                (3, 13, 14),
                "3.13",
                "3.13.14",
                2,
            )
        stage_pyconfig.assert_called_once_with(
            self.root,
            (3, 13, 14),
            "Release",
            "x64",
        )
        pre_build.assert_called_once()
        stage.assert_called_once_with(self.root, "x64", {}, [integration])
        self.assertEqual(run.call_count, 1)
        command = run.call_args.args[0]
        self.assertIn(str(pcbuild / "demo_static.vcxproj"), command)
        self.assertNotIn(str(pcbuild / "pythoncore.vcxproj"), command)
        self.assertNotIn(str(pcbuild / "python.vcxproj"), command)
        self.assertIn("BuildProjectReferences=false", msbuild_args.call_args.args)

    def test_runtime_sdk_prefers_generated_pyconfig_header(self) -> None:
        generated = build.get_pcbuild_output_dir(self.root, "x64") / "pyconfig.h"
        generated.parent.mkdir(parents=True)
        generated.write_text("generated", encoding="utf-8")
        source = self.root / "PC" / "pyconfig.h"
        source.parent.mkdir(parents=True)
        source.write_text("legacy", encoding="utf-8")
        self.assertEqual(build.resolve_runtime_sdk_pyconfig_header(self.root, "x64"), generated)

    def test_pack_only_build_stages_freezer_generated_pyconfig_header(self) -> None:
        generated = build.generated_pyconfig_header_path(
            self.root,
            (3, 13, 15),
            "Release",
            "x64",
            "_freeze_module",
        )
        generated.parent.mkdir(parents=True)
        generated.write_text("#define STATICPYTHON_TEST 1\n", encoding="utf-8")
        target = build.stage_pack_build_pyconfig_header(
            self.root,
            (3, 13, 15),
            "Release",
            "x64",
        )
        self.assertEqual(
            target,
            build.generated_pyconfig_header_path(
                self.root,
                (3, 13, 15),
                "Release",
                "x64",
                "pythoncore",
            ),
        )
        self.assertEqual(target.read_bytes(), generated.read_bytes())

    def test_pack_only_build_rejects_missing_generated_pyconfig_header(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "did not produce a usable pyconfig.h"):
            build.stage_pack_build_pyconfig_header(
                self.root,
                (3, 13, 15),
                "Release",
                "x64",
            )

    def test_parse_cpython_version_preserves_prerelease_suffix(self) -> None:
        include = self.root / "Include"
        include.mkdir()
        (include / "patchlevel.h").write_text(
            '#define PY_MAJOR_VERSION 3\n'
            '#define PY_MINOR_VERSION 15\n'
            '#define PY_MICRO_VERSION 0\n'
            '#define PY_VERSION "3.15.0b4"\n',
            encoding="utf-8",
        )
        self.assertEqual(
            build.parse_cpython_version(self.root),
            ((3, 15, 0), "3.15", "3.15.0b4"),
        )

    def test_runtime_frozen_module_names_come_from_runtime_tables_only(self) -> None:
        frozen = self.root / "Python" / "frozen.c"
        frozen.parent.mkdir(parents=True)
        frozen.write_text(
            '''
static const struct _frozen bootstrap_modules[] = {
    {"importlib._bootstrap", bootstrap, 1, false},
    {0, 0, 0} /* bootstrap sentinel */
};
static const struct _frozen stdlib_modules[] = {
    {"asyncio", asyncio_data, 1, true},
    {"asyncio.tasks", asyncio_tasks_data, 1, false},
    {0, 0, 0} /* stdlib sentinel */
};
static const struct _frozen test_modules[] = {
    {"test.should_not_ship", test_data, 1, false},
    {0, 0, 0} /* test sentinel */
};
const struct _module_alias aliases[] = {
    {"os.path", "ntpath"},
    {0, 0} /* aliases sentinel */
};
''',
            encoding="utf-8",
        )
        self.assertEqual(
            build.runtime_frozen_module_names(self.root),
            ["asyncio", "asyncio.tasks", "importlib._bootstrap", "os.path"],
        )

    def test_runtime_builtin_module_names_come_from_target_inittab(self) -> None:
        config = self.root / "PC" / "config.c"
        config.parent.mkdir(parents=True)
        config.write_text(
            '''
static struct _inittab unrelated[] = {
    {"must_not_ship", PyInit_must_not_ship},
    {0, 0}
};
struct _inittab _PyImport_Inittab[] = {
    {"_abc", PyInit__abc},
    {"builtins", NULL},
    {"sys", NULL},
    {0, 0} /* Sentinel */
};
''',
            encoding="utf-8",
        )
        self.assertEqual(
            build.runtime_builtin_module_names(self.root),
            ["_abc", "builtins", "sys"],
        )

    def test_cpython_tag_resolution_prefers_peeled_commit(self) -> None:
        direct = "1" * 40
        peeled = "2" * 40
        result = SimpleNamespace(
            returncode=0,
            stdout=(
                f"{direct}\trefs/tags/v3.13.14\n"
                f"{peeled}\trefs/tags/v3.13.14^{{}}\n"
            ),
            stderr="",
        )
        with mock.patch("build.subprocess.run", return_value=result):
            self.assertEqual(build.resolve_cpython_tag_commit("3.13.14"), peeled)

    def test_cpython_source_dependency_tags_skip_custom_integrations(self) -> None:
        script = self.root / "PCbuild" / "get_externals.bat"
        script.parent.mkdir(parents=True)
        script.write_text(
            "\n".join(
                [
                    "set libraries=",
                    "set libraries=%libraries% bzip2-1.0.8",
                    'if NOT "%IncludeLibffiSrc%"=="false" set libraries=%libraries% libffi-3.4.4',
                    'if NOT "%IncludeSSLSrc%"=="false" set libraries=%libraries% openssl-3.0.16',
                    'if NOT "%IncludeTkinterSrc%"=="false" set libraries=%libraries% tcl-core-8.6.15.0',
                    "set libraries=%libraries% sqlite-3.49.1.0",
                    "set libraries=%libraries% xz-5.2.5",
                    "set libraries=%libraries% zlib-1.3.1",
                ]
            ),
            encoding="utf-8",
        )
        self.assertEqual(
            build.cpython_source_dependency_tags(self.root),
            ["bzip2-1.0.8", "sqlite-3.49.1.0", "xz-5.2.5", "zlib-1.3.1"],
        )

    def test_get_externals_uses_mirror_and_validates_materialized_sources(self) -> None:
        script = self.root / "PCbuild" / "get_externals.bat"
        script.parent.mkdir(parents=True)
        script.write_text(
            "set libraries=\nset libraries=%libraries% zlib-1.3.1\n",
            encoding="utf-8",
        )
        used_urls: list[str] = []

        def fake_download(urls, destination):
            used_urls.extend(urls)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"archive")
            return urls[-1]

        def fake_extract(_archive, destination_root, *, final_name=None):
            destination = destination_root / final_name
            destination.mkdir(parents=True)
            (destination / "adler32.c").write_text("", encoding="utf-8")
            (destination / "zlib.h").write_text("", encoding="utf-8")
            return destination

        with (
            mock.patch.object(build, "DOWNLOAD_ROOT", self.root / "downloads"),
            mock.patch.object(build, "download_first_available", side_effect=fake_download),
            mock.patch.object(build, "extract_source_archive", side_effect=fake_extract),
        ):
            build.maybe_get_externals(self.root)

        self.assertEqual(len(used_urls), 2)
        self.assertIn("github.com/python/cpython-source-deps", used_urls[0])
        self.assertIn("codeload.github.com/python/cpython-source-deps", used_urls[1])
        self.assertTrue((self.root / "externals" / "zlib-1.3.1" / "zlib.h").is_file())

    def test_get_externals_rejects_unreviewed_dependency(self) -> None:
        script = self.root / "PCbuild" / "get_externals.bat"
        script.parent.mkdir(parents=True)
        script.write_text(
            "set libraries=\nset libraries=%libraries% surprise-1.0\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "unreviewed source dependency"):
            build.maybe_get_externals(self.root)

    def test_get_externals_rejects_incomplete_materialized_source(self) -> None:
        script = self.root / "PCbuild" / "get_externals.bat"
        script.parent.mkdir(parents=True)
        script.write_text(
            "set libraries=\nset libraries=%libraries% zlib-1.3.1\n",
            encoding="utf-8",
        )

        def fake_download(urls, destination):
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"archive")
            return urls[0]

        def fake_extract(_archive, destination_root, *, final_name=None):
            destination = destination_root / final_name
            destination.mkdir(parents=True)
            (destination / "zlib.h").write_text("", encoding="utf-8")
            return destination

        with (
            mock.patch.object(build, "DOWNLOAD_ROOT", self.root / "downloads"),
            mock.patch.object(build, "download_first_available", side_effect=fake_download),
            mock.patch.object(build, "extract_source_archive", side_effect=fake_extract),
            self.assertRaisesRegex(RuntimeError, r"zlib-1\.3\.1 is incomplete; missing: adler32\.c"),
        ):
            build.maybe_get_externals(self.root)

    def test_prompt_toolkit_3053_lazy_version_patch_is_strict(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_prompt_toolkit_setup_test",
            REPO_ROOT / "Lib" / "prompt_toolkit" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.LIBRARY_INTEGRATION.release_version = "3.0.53"
        source = (
            "from importlib import metadata\n"
            "import re\n\n"
            "def _load_version():\n"
            '    version = metadata.version("prompt_toolkit")\n'
            "    assert re.fullmatch(pep440_pattern, version)\n"
        )
        patched = module._patch_prompt_toolkit_init(source)
        self.assertIn("except metadata.PackageNotFoundError:", patched)
        self.assertIn('version = "3.0.53"', patched)
        self.assertEqual(module._patch_prompt_toolkit_init(patched), patched)

    def test_portalocker_400_optional_win32_needs_no_legacy_patch(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_portalocker_setup_test",
            REPO_ROOT / "Lib" / "portalocker" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = (
            "    class MsvcrtLocker(BaseLocker):\n"
            "        _win32_locker: Win32Locker | None\n"
            "        def __init__(self) -> None:\n"
            "            try:\n"
            "                self._win32_locker = Win32Locker()\n"
            "            except ImportError:\n"
            "                self._win32_locker = None\n"
            "        def lock(self, file_obj, flags):\n"
            "            if flags:\n"
            "                win32_locker = self._win32_locker\n"
            "                if win32_locker is None:\n"
            "                    raise ImportError(\n"
            "                        'pywin32 is optional'\n"
            "                    )\n"
        )
        target = self.root / "Lib" / "portalocker" / "portalocker.py"
        target.parent.mkdir(parents=True)
        target.write_text(source, encoding="utf-8")
        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        module.patch_portalocker_sources(context)
        self.assertEqual(target.read_text(encoding="utf-8"), source)

    def test_ujson_project_defines_the_resolved_release_version(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_ujson_setup_test",
            REPO_ROOT / "Lib" / "ujson" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        project = module._render_ujson_project(["python/ujson.c"], ["python"], "5.13.0")
        self.assertIn("UJSON_VERSION=&quot;5.13.0&quot;", project)

    def test_hypothesis_native_compatibility_is_frozen_and_functional(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_hypothesis_setup_test",
            REPO_ROOT / "Lib" / "hypothesis" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual(module.LIBRARY_INTEGRATION.release_version, "6.164.0")
        self.assertEqual(module.LIBRARY_INTEGRATION.license_expression, "MPL-2.0")
        self.assertIn(
            "Lib/_hypothesis_globals.py",
            module.LIBRARY_INTEGRATION.materialized_paths,
        )
        self.assertIn(
            "_hypothesis_globals",
            module.LIBRARY_INTEGRATION.python_packages,
        )
        self.assertIn(
            "_hypothesis_globals",
            module.LIBRARY_INTEGRATION.top_level_import_names,
        )

        frozen = self.root / "Python" / "frozen_modules"
        frozen.mkdir(parents=True)
        (frozen / "_hypothesis_globals.h").write_text(
            "const unsigned char _Py_M___hypothesis_globals[] = {1, 2, 3,};\n",
            encoding="utf-8",
        )
        (frozen / "hypothesis.h").write_text(
            "const unsigned char _Py_M__hypothesis[] = {4, 5, 6,};\n",
            encoding="utf-8",
        )
        self.assertEqual(
            [
                record["name"]
                for record in build._integration_frozen_modules(
                    self.root,
                    module.LIBRARY_INTEGRATION,
                )
            ],
            ["_hypothesis_globals", "hypothesis"],
        )
        module._configure_hypothesis_globals_module(False)
        self.assertNotIn(
            "Lib/_hypothesis_globals.py",
            module.LIBRARY_INTEGRATION.materialized_paths,
        )
        self.assertNotIn(
            "_hypothesis_globals",
            module.LIBRARY_INTEGRATION.python_packages,
        )
        self.assertNotIn(
            "_hypothesis_globals",
            module.LIBRARY_INTEGRATION.top_level_import_names,
        )
        module._configure_hypothesis_globals_module(True)

        internal = self.root / "Lib" / "hypothesis" / "internal"
        internal.mkdir(parents=True)
        (internal / "floats.py").write_text(
            "from hypothesis._native.internal.floats import (\n    float_of,\n)\n",
            encoding="utf-8",
        )
        (self.root / "Lib" / "hypothesis" / "version.py").write_text(
            "from hypothesis._native import __version__ as __version__\n",
            encoding="utf-8",
        )
        core = self.root / "Lib" / "hypothesis" / "strategies" / "_internal" / "core.py"
        core.parent.mkdir(parents=True)
        core.write_text(
            "from hypothesis._native.internal.cathetus import cathetus\n",
            encoding="utf-8",
        )
        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        module._install_hypothesis_native_compatibility(context)

        floats_path = self.root / "Lib" / "hypothesis" / "_native" / "internal" / "floats.py"
        floats_spec = importlib.util.spec_from_file_location(
            "staticpython_hypothesis_floats_test",
            floats_path,
        )
        assert floats_spec is not None and floats_spec.loader is not None
        floats = importlib.util.module_from_spec(floats_spec)
        floats_spec.loader.exec_module(floats)
        negative_zero = floats.int_to_float(floats.float_to_int(-0.0), 64)
        self.assertLess(floats.math.copysign(1.0, negative_zero), 0.0)
        self.assertGreater(floats.next_up(0.0), 0.0)
        self.assertEqual(floats.width_smallest_normals(32), 2.0**-126)

        cathetus_path = floats_path.with_name("cathetus.py")
        cathetus_spec = importlib.util.spec_from_file_location(
            "staticpython_hypothesis_cathetus_test",
            cathetus_path,
        )
        assert cathetus_spec is not None and cathetus_spec.loader is not None
        cathetus = importlib.util.module_from_spec(cathetus_spec)
        cathetus_spec.loader.exec_module(cathetus)
        self.assertEqual(cathetus.cathetus(5.0, 4.0), 3.0)
        self.assertTrue(cathetus.math.isnan(cathetus.cathetus(1.0, 2.0)))

        before = floats_path.read_text(encoding="utf-8")
        module._install_hypothesis_native_compatibility(context)
        self.assertEqual(floats_path.read_text(encoding="utf-8"), before)

    def test_hypothesis_native_compatibility_routes_transition_and_legacy_versions(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_hypothesis_transition_test",
            REPO_ROOT / "Lib" / "hypothesis" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        original_version = module.LIBRARY_INTEGRATION.release_version
        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)

        module.LIBRARY_INTEGRATION.release_version = "6.155.7"
        try:
            module._install_hypothesis_native_compatibility(context)

            module.LIBRARY_INTEGRATION.release_version = "6.157.1"
            internal = self.root / "Lib" / "hypothesis" / "internal"
            internal.mkdir(parents=True)
            (internal / "floats.py").write_text("FLOATS_ARE_PYTHON = True\n", encoding="utf-8")
            (self.root / "Lib" / "hypothesis" / "version.py").write_text(
                "from hypothesis._native import __version__ as __version__\n",
                encoding="utf-8",
            )
            core = self.root / "Lib" / "hypothesis" / "strategies" / "_internal" / "core.py"
            core.parent.mkdir(parents=True)
            core.write_text(
                "from hypothesis._native.internal.cathetus import cathetus\n",
                encoding="utf-8",
            )
            module._install_hypothesis_native_compatibility(context)
        finally:
            module.LIBRARY_INTEGRATION.release_version = original_version

        native = self.root / "Lib" / "hypothesis" / "_native"
        self.assertTrue((native / "__init__.py").is_file())
        self.assertTrue((native / "internal" / "cathetus.py").is_file())
        self.assertFalse((native / "internal" / "floats.py").exists())

    def test_hypothesis_native_compatibility_rejects_partial_upstream_drift(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_hypothesis_drift_test",
            REPO_ROOT / "Lib" / "hypothesis" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        internal = self.root / "Lib" / "hypothesis" / "internal"
        internal.mkdir(parents=True)
        (internal / "floats.py").write_text(
            "from hypothesis._native.internal.floats import (\n    float_of,\n)\n",
            encoding="utf-8",
        )
        (self.root / "Lib" / "hypothesis" / "version.py").write_text(
            "__version__ = 'changed'\n",
            encoding="utf-8",
        )
        core = self.root / "Lib" / "hypothesis" / "strategies" / "_internal" / "core.py"
        core.parent.mkdir(parents=True)
        core.write_text(
            "from hypothesis._native.internal.cathetus import cathetus\n",
            encoding="utf-8",
        )
        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        with self.assertRaisesRegex(RuntimeError, "anchors changed"):
            module._install_hypothesis_native_compatibility(context)

    def test_cppy_frozen_runtime_patch_is_strict_and_idempotent(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_cppy_setup_test",
            REPO_ROOT / "Lib" / "cppy" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        source = "import os\nfrom setuptools.command.build_ext import build_ext\n"
        patched = module._patch_cppy_setuptools_import(source)
        compile(patched, "<cppy-patch>", "exec")
        self.assertIn("Unavailable build command placeholder", patched)

        original_import = __import__

        def import_without_setuptools(name, *args, **kwargs):
            if name == "setuptools" or name.startswith("setuptools."):
                raise ModuleNotFoundError("No module named 'setuptools'", name="setuptools")
            return original_import(name, *args, **kwargs)

        namespace = {}
        with mock.patch("builtins.__import__", side_effect=import_without_setuptools):
            exec(compile(patched, "<cppy-no-setuptools>", "exec"), namespace)
        with self.assertRaisesRegex(RuntimeError, "requires setuptools"):
            namespace["build_ext"]()

        self.assertEqual(module._patch_cppy_setuptools_import(patched), patched)
        with self.assertRaisesRegex(RuntimeError, "expected snippet"):
            module._patch_cppy_setuptools_import("import os\n")

        legacy_version = module.LIBRARY_INTEGRATION.release_version
        module.LIBRARY_INTEGRATION.release_version = "1.1.0"
        try:
            module.patch_cppy_sources(
                SimpleNamespace(source_root=self.root, log=lambda _message: None)
            )
        finally:
            module.LIBRARY_INTEGRATION.release_version = legacy_version

    def test_pybind11_frozen_version_matches_header_and_is_strict(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_pybind11_setup_test",
            REPO_ROOT / "Lib" / "pybind11" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        header = self.root / "pybind11_builtin" / "include" / "pybind11" / "detail" / "common.h"
        header.parent.mkdir(parents=True)
        header.write_text(
            "#define PYBIND11_VERSION_MAJOR 3\n"
            "#define PYBIND11_VERSION_MINOR 0\n"
            "#define PYBIND11_VERSION_PATCH 4\n",
            encoding="utf-8",
        )
        version_file = self.root / "Lib" / "pybind11" / "_version.py"
        version_file.parent.mkdir(parents=True)
        version_file.write_text(
            "# This file will be replaced in the wheel with a hard-coded version.\n"
            "from pathlib import Path\n"
            "DIR = Path(__file__).parent.resolve()\n"
            'input_file = DIR.parent / "include/pybind11/detail/common.h"\n'
            'match = regex.search(input_file.read_text(encoding="utf-8"))\n',
            encoding="utf-8",
        )
        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        module.patch_pybind11_sources(context)
        rendered = version_file.read_text(encoding="utf-8")
        namespace = {}
        exec(compile(rendered, "<pybind11-version>", "exec"), namespace)
        self.assertEqual(namespace["__version__"], "3.0.4")
        self.assertEqual(namespace["version_info"], (3, 0, 4))
        module.patch_pybind11_sources(context)
        self.assertEqual(version_file.read_text(encoding="utf-8"), rendered)

        header.write_text(
            "#define PYBIND11_VERSION_MAJOR 3\n"
            "#define PYBIND11_VERSION_MINOR 0\n"
            "#define PYBIND11_VERSION_PATCH 5\n",
            encoding="utf-8",
        )
        with self.assertRaisesRegex(RuntimeError, "does not match"):
            module.patch_pybind11_sources(context)

        legacy_version = module.LIBRARY_INTEGRATION.release_version
        module.LIBRARY_INTEGRATION.release_version = "2.13.6"
        try:
            module.patch_pybind11_sources(
                SimpleNamespace(source_root=self.root, log=lambda _message: None)
            )
        finally:
            module.LIBRARY_INTEGRATION.release_version = legacy_version

    def test_aiohttp_pack_metadata_tracks_generated_extension_layout(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_aiohttp_layout_test",
            REPO_ROOT / "Lib" / "aiohttp" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        aiohttp = self.root / "Lib" / "aiohttp"
        websocket = aiohttp / "_websocket"
        websocket.mkdir(parents=True)
        for relative in (
            "_http_parser.c",
            "_find_header.c",
            "_http_writer.c",
            "_websocket/mask.c",
            "_websocket/reader_c.c",
        ):
            path = aiohttp / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("/* test */\n", encoding="utf-8")
        llhttp = self.root / "aiohttp_builtin" / "vendor" / "llhttp"
        for relative in ("build/c/llhttp.c", "src/native/api.c", "src/native/http.c"):
            path = llhttp / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("/* test */\n", encoding="utf-8")

        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        module.prepare_aiohttp_projects(context)
        selected_names = [
            "aiohttp._http_parser",
            "aiohttp._http_writer",
            "aiohttp._websocket.mask",
            "aiohttp._websocket.reader_c",
        ]
        integration = module.LIBRARY_INTEGRATION
        self.assertEqual(
            integration.static_library_projects_release_x64,
            [f"{name}.vcxproj" for name in selected_names],
        )
        self.assertEqual(
            [item["name"] for item in integration.builtin_module_registrations],
            selected_names,
        )
        self.assertEqual(
            integration.python_link_dependencies_release_x64,
            [f"{name}.lib" for name in selected_names],
        )

        output = self.root / "PCbuild" / "amd64"
        output.mkdir(parents=True)
        for name in selected_names:
            (output / f"{name}.lib").write_bytes(b"library")
        native_records, _wholearchive, _system = build._integration_native_libraries(
            self.root,
            "x64",
            integration,
        )
        self.assertEqual(
            [record["logical_name"] for record in native_records],
            [f"{name}.lib" for name in selected_names],
        )

    def test_freezer_preserves_nested_runtime_docs_packages(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_freeze_modules_test",
            REPO_ROOT / "assets" / "overlay" / "Tools" / "build" / "freeze_modules.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for relative in (
            "Lib/docs/__init__.py",
            "Lib/botocore/__init__.py",
            "Lib/botocore/docs/__init__.py",
            "Lib/botocore/docs/bcdoc.py",
            "Lib/botocore/tests/__init__.py",
        ):
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# test\n", encoding="utf-8")

        names = {item.fullname for item in module.find_python_modules(str(self.root))}
        self.assertIn("botocore.docs", names)
        self.assertIn("botocore.docs.bcdoc", names)
        self.assertNotIn("docs", names)
        self.assertNotIn("botocore.tests", names)

    def test_freezer_package_header_works_without_file(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_freeze_modules_header_without_file_test",
            REPO_ROOT / "assets" / "overlay" / "Tools" / "build" / "freeze_modules.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        transformed, changed = module._inject_package_header(
            b"VALUE = 1\n",
            "encodings",
        )
        namespace = {
            "__name__": "encodings",
            "__spec__": SimpleNamespace(submodule_search_locations=[]),
        }

        exec(compile(transformed, "<frozen encodings>", "exec"), namespace)

        self.assertTrue(changed)
        self.assertNotIn(b"dirname(__file__)", transformed)
        self.assertEqual(namespace["__path__"], ["encodings"])
        self.assertEqual(
            module._inject_package_header(transformed, "encodings"),
            (transformed, False),
        )

    def test_freezer_package_header_preserves_virtual_file_directory(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_freeze_modules_virtual_file_test",
            REPO_ROOT / "assets" / "overlay" / "Tools" / "build" / "freeze_modules.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        transformed, _changed = module._inject_package_header(b"VALUE = 1\n", "wx")
        namespace = {
            "__file__": "staticpython-resource:///Lib/wx/__init__.py",
            "__name__": "wx",
            "__spec__": SimpleNamespace(submodule_search_locations=[]),
        }

        exec(compile(transformed, "<frozen wx>", "exec"), namespace)

        self.assertEqual(namespace["__path__"], ["staticpython-resource:///Lib/wx"])

    def test_wxpython_pack_declares_gdiplus_provider_and_behavior_smokes(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_wxpython_pack_test",
            REPO_ROOT / "Lib" / "wxpython" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        integration = module.LIBRARY_INTEGRATION
        self.assertEqual(integration.release_version, "4.2.5")
        self.assertEqual(integration.minimum_release_version, "4.2.5")
        self.assertEqual(integration.license_expression, "wxWindows")
        self.assertEqual(
            integration.suppressed_system_libraries_release_x64,
            ["gdiplus.lib"],
        )
        self.assertEqual(
            integration.trusted_object_origins,
            [{"library": "wxbase32u.lib", "object": "main.obj"}],
        )
        self.assertEqual(
            [
                name
                for name in module.WXPYTHON_SYSTEM_LIBRARIES
                if not build.is_windows_system_library(name)
                and not build.is_windows_sdk_library(name)
            ],
            [],
        )
        self.assertEqual(
            [test["name"] for test in integration.smoke_tests],
            ["wx-native-modules", "wx-window-lifecycle"],
        )

    def test_libui_pack_declares_required_gdi_system_library(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_libui_pack_test",
            REPO_ROOT / "Lib" / "libui" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        integration = module.LIBRARY_INTEGRATION
        self.assertIn("gdi32.lib", integration.python_link_dependencies_release_x64)
        self.assertTrue(build.is_windows_system_library("gdi32.lib"))

    def test_libui_native_module_embeds_static_common_controls_manifest(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_libui_manifest_patch_test",
            REPO_ROOT / "Lib" / "libui" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        for source in (
            '#include "module.h"\nPyMODINIT_FUNC PyInit_core(void);\n',
            (
                '#include "module.h"\n'
                "#ifdef _WIN32\n"
                "#include <windows.h>\n"
                "#endif\n"
                "PyMODINIT_FUNC PyInit_core(void);\n"
            ),
        ):
            with self.subTest(has_windows_include="#include <windows.h>" in source):
                patched = module._patch_libui_native_module_text(source)

                self.assertIn("PyInit__libui_core", patched)
                self.assertNotIn("PyInit_core", patched)
                self.assertIn(module.LIBUI_COMMON_CONTROLS_MANIFEST_PRAGMA, patched)
                self.assertIn("Microsoft.Windows.Common-Controls", patched)
                self.assertIn("version='6.0.0.0'", patched)
                self.assertEqual(patched.count("/manifestdependency:"), 1)
                self.assertEqual(module._patch_libui_native_module_text(patched), patched)

    def test_wxpython_link_metadata_tracks_bundled_wxwidgets_version(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_wxpython_versioned_libraries_test",
            REPO_ROOT / "Lib" / "wxpython" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        header = self.root / "wxpython_builtin" / "wxWidgets" / "include" / "wx" / "version.h"
        header.parent.mkdir(parents=True)
        header.write_text(
            "#define wxMAJOR_VERSION 3\n#define wxMINOR_VERSION 3\n",
            encoding="utf-8",
        )
        messages: list[str] = []
        context = SimpleNamespace(source_root=self.root, log=messages.append)
        libraries = module._synchronize_wxwidgets_link_metadata(context)

        self.assertIn("wxbase33u.lib", libraries)
        self.assertIn("wxmsw33u_core.lib", libraries)
        self.assertNotIn("wxbase32u.lib", libraries)
        self.assertEqual(
            module.LIBRARY_INTEGRATION.trusted_object_origins,
            [{"library": "wxbase33u.lib", "object": "main.obj"}],
        )
        self.assertEqual(
            module.LIBRARY_INTEGRATION.python_link_dependencies_release_x64,
            [
                *module.WXPYTHON_MODULE_LIBRARIES,
                *libraries,
                *module.WXPYTHON_SYSTEM_LIBRARIES,
            ],
        )
        self.assertEqual(messages, ["using wxWidgets 3.3 static library names"])

    def test_wxpython_version_header_drift_fails_closed(self) -> None:
        spec = importlib.util.spec_from_file_location(
            "staticpython_wxpython_version_header_drift_test",
            REPO_ROOT / "Lib" / "wxpython" / "setup.py",
        )
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)

        header = self.root / "wxpython_builtin" / "wxWidgets" / "include" / "wx" / "version.h"
        header.parent.mkdir(parents=True)
        header.write_text(
            "#define wxMAJOR_VERSION 3\n"
            "#define wxMAJOR_VERSION 4\n"
            "#define wxMINOR_VERSION 3\n",
            encoding="utf-8",
        )
        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        with self.assertRaisesRegex(RuntimeError, "wxMAJOR_VERSION exactly once"):
            module._synchronize_wxwidgets_link_metadata(context)

    def test_native_wheels_are_never_source_inputs(self) -> None:
        files = [
            {
                "filename": "demo-1.0-cp313-cp313-win_amd64.whl",
                "packagetype": "bdist_wheel",
                "requires_python": ">=3.11",
                "yanked": False,
            }
        ]
        compatible = libs._compatible_pypi_files(
            files,
            project_requires_python=None,
            target_version=libs.Version("3.13"),
        )
        self.assertEqual(compatible, [])

    def test_sdist_and_universal_wheel_are_valid_source_inputs(self) -> None:
        files = [
            {
                "filename": "demo-1.0.tar.gz",
                "packagetype": "sdist",
                "requires_python": ">=3.11",
                "yanked": False,
            },
            {
                "filename": "demo-1.0-py3-none-any.whl",
                "packagetype": "bdist_wheel",
                "requires_python": ">=3.11",
                "yanked": False,
            },
        ]
        compatible = libs._compatible_pypi_files(
            files,
            project_requires_python=None,
            target_version=libs.Version("3.13"),
        )
        self.assertEqual([item["packagetype"] for item in compatible], ["sdist", "bdist_wheel"])
        wheel_first = libs._compatible_pypi_files(
            files,
            project_requires_python=None,
            target_version=libs.Version("3.13"),
            source_resolver="pypi-universal-wheel",
        )
        self.assertEqual(
            [item["packagetype"] for item in wheel_first],
            ["bdist_wheel", "sdist"],
        )
        with self.assertRaisesRegex(RuntimeError, "unsupported PyPI source resolver"):
            libs._compatible_pypi_files(
                files,
                project_requires_python=None,
                target_version=libs.Version("3.13"),
                source_resolver="native-wheel",
            )

    def test_universal_wheel_lock_requires_immutable_sdist_license_source(self) -> None:
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            project_name="demo",
            release_version="1.0",
            source_resolver="pypi-universal-wheel",
            dependency_resolution={
                "solver": libs.HISTORICAL_DEPENDENCY_SOLVER,
                "source": {
                    "filename": "demo-1.0-py3-none-any.whl",
                    "url": "https://files.example/demo-1.0-py3-none-any.whl",
                    "sha256": "a" * 64,
                    "size": 100,
                    "packagetype": "bdist_wheel",
                    "requires_python": ">=3.11",
                },
                "license_source": {
                    "filename": "demo-1.0.tar.gz",
                    "url": "https://files.example/demo-1.0.tar.gz",
                    "sha256": "b" * 64,
                    "size": 200,
                    "packagetype": "sdist",
                    "requires_python": ">=3.11",
                },
            },
        )
        lock = libs.dependency_resolution_lock(
            [integration],
            target_version=libs.Version("3.13.14"),
            solver=libs.HISTORICAL_DEPENDENCY_SOLVER,
            roots=["demo"],
        )
        self.assertEqual(
            lock["integrations"][0]["source_resolver"],
            "pypi-universal-wheel",
        )
        self.assertEqual(
            lock["integrations"][0]["license_source"]["sha256"],
            "b" * 64,
        )
        records = libs._locked_dependency_records(
            lock,
            target_version=libs.Version("3.13.14"),
            solver=libs.HISTORICAL_DEPENDENCY_SOLVER,
            selected_names=["demo"],
        )
        self.assertEqual(records["demo"]["license_source"]["packagetype"], "sdist")

        tampered = json.loads(json.dumps(lock))
        tampered["integrations"][0].pop("license_source")
        unsigned = {
            key: value
            for key, value in tampered.items()
            if key != "solver_fingerprint"
        }
        tampered["solver_fingerprint"] = hashlib.sha256(
            json.dumps(
                unsigned,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        with self.assertRaisesRegex(RuntimeError, "no sdist license source"):
            libs._locked_dependency_records(
                tampered,
                target_version=libs.Version("3.13.14"),
                solver=libs.HISTORICAL_DEPENDENCY_SOLVER,
                selected_names=["demo"],
            )

    def test_requires_python_accepts_target_cpython_release_candidate(self) -> None:
        self.assertTrue(
            libs._supports_target_python(">=3.9", libs.Version("3.15.0rc1"))
        )
        self.assertFalse(
            libs._supports_target_python(">=3.16", libs.Version("3.15.0rc1"))
        )

    def test_automatic_version_scan_excludes_prerelease_and_dev(self) -> None:
        releases = {"2.0rc1": [], "2.0.dev1": [], "1.9": [], "1.8": []}
        self.assertEqual(libs._sorted_release_versions(releases), ["1.9", "1.8"])

    def test_pypi_release_catalog_is_cached_within_history_batch(self) -> None:
        payload = {
            "info": {"requires_python": ">=3.11"},
            "releases": {
                "1.0": [
                    {
                        "filename": "demo-1.0.tar.gz",
                        "url": "https://files.example/demo-1.0.tar.gz",
                        "packagetype": "sdist",
                        "requires_python": ">=3.11",
                        "yanked": False,
                    }
                ]
            },
        }
        with (
            mock.patch.object(libs, "DOWNLOAD_CACHE_ROOT", self.root / "downloads"),
            mock.patch.object(libs, "_http_get_json", return_value=payload) as fetch,
        ):
            first = libs._iter_pypi_distribution_candidates(
                "demo", libs.Version("3.13.14")
            )
            second = libs._iter_pypi_distribution_candidates(
                "demo", libs.Version("3.13.14")
            )
        self.assertEqual(first, second)
        self.assertEqual(fetch.call_count, 1)

    def test_historical_candidate_does_not_inherit_latest_requires_python(self) -> None:
        payload = {
            "info": {"requires_python": ">=3.16"},
            "releases": {
                "1.0": [
                    {
                        "filename": "demo-1.0.tar.gz",
                        "url": "https://files.example/demo-1.0.tar.gz",
                        "packagetype": "sdist",
                        "requires_python": None,
                        "yanked": False,
                    }
                ]
            },
        }
        with mock.patch.object(
            libs,
            "_load_pypi_release_payload",
            return_value=payload,
        ):
            candidates = libs._iter_pypi_distribution_candidates(
                "demo", libs.Version("3.11.16")
            )
        self.assertEqual([version for version, _file in candidates], ["1.0"])

    def test_patch_rules_are_strict_and_idempotent(self) -> None:
        target = self.root / "Lib" / "demo.py"
        target.parent.mkdir(parents=True)
        target.write_text("VALUE = 1\n", encoding="utf-8")
        integration = libs.LibraryIntegration(
            name="demo",
            release_version="1.2.0",
            patch_rules=[
                {
                    "package": ">=1,<2",
                    "python": ">=3.11,<3.16",
                    "path": "Lib/demo.py",
                    "replacements": [{"old": "VALUE = 1", "new": "VALUE = 2", "count": 1}],
                }
            ],
        )
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=self.root,
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=self.root / "work",
            asset_overlay_root=REPO_ROOT / "assets" / "overlay",
            log=lambda _message: None,
        )
        libs.run_pre_patch_hooks([integration], context)
        libs.run_pre_patch_hooks([integration], context)
        self.assertEqual(target.read_text(encoding="utf-8"), "VALUE = 2\n")
        target.write_text("VALUE = 3\n", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "anchor mismatch"):
            libs.run_pre_patch_hooks([integration], context)

    def test_runtime_pythoncore_patch_removes_main_and_legacy_resource_store(self) -> None:
        project = self.root / "PCbuild" / "pythoncore.vcxproj"
        project.parent.mkdir(parents=True)
        project.write_text(
            """<?xml version="1.0" encoding="utf-8"?>
<Project xmlns="http://schemas.microsoft.com/developer/msbuild/2003">
  <PropertyGroup><ConfigurationType>DynamicLibrary</ConfigurationType></PropertyGroup>
  <ItemGroup>
    <ClCompile Include="..\\Modules\\main.c" />
    <ClCompile Include="..\\Python\\frozen.c" />
    <ClCompile Include="..\\Python\\staticpython_resource_store.c" />
  </ItemGroup>
</Project>
""",
            encoding="utf-8",
        )
        build.patch_pythoncore_vcxproj(self.root, runtime_sdk=True)
        text = project.read_text(encoding="utf-8")
        self.assertIn("<ConfigurationType>StaticLibrary</ConfigurationType>", text)
        self.assertNotIn("Modules\\main.c", text)
        self.assertNotIn("Python\\staticpython_resource_store.c", text)

    def test_pack_registration_validates_before_mutating_cpython_tables(self) -> None:
        text = (
            REPO_ROOT / "assets" / "overlay" / "Python" / "staticpython_pack_runtime.c"
        ).read_text(encoding="utf-8")
        hook_call = text.index("packs[index]->before_initialize()")
        table_allocation = text.index("staticpython_frozen_modules = (struct _frozen *)calloc")
        extend_inittab = text.index("PyImport_ExtendInittab(staticpython_builtin_modules)")
        self.assertLess(hook_call, table_allocation)
        self.assertLess(table_allocation, extend_inittab)
        self.assertIn("duplicate builtin module name", text)
        self.assertIn("builtin module conflicts with the runtime SDK", text)
        self.assertIn("_PyImport_FrozenStdlib", text)
        self.assertIn("required dependency pack is missing", text)

    def test_pack_resource_descriptor_is_sorted_and_uses_v1(self) -> None:
        build._write_staticpython_pack_resource_store_c(
            self.root,
            target_records=[
                ("Lib/z/data.bin", "shard_z", "sha256:z", 2),
                ("Lib/a/data.bin", "shard_a", "sha256:a", 3),
            ],
        )
        text = (self.root / build.RUNTIME_RESOURCE_STORE_C_RELATIVE_PATH).read_text(encoding="utf-8")
        self.assertIn("StaticPython_BaseResourcePackV1", text)
        self.assertIn("STATICPYTHON_PACK_ABI_VERSION", text)
        self.assertLess(text.index("Lib/a/data.bin"), text.index("Lib/z/data.bin"))

    def test_deterministic_zip_is_byte_stable(self) -> None:
        staging = self.root / "staging"
        staging.mkdir()
        (staging / "b.txt").write_text("b\n", encoding="utf-8")
        (staging / "a.txt").write_text("a\n", encoding="utf-8")
        first = self.root / "first.zip"
        second = self.root / "second.zip"
        build.write_deterministic_zip(staging, first)
        build.write_deterministic_zip(staging, second)
        self.assertEqual(build.sha256_file(first), build.sha256_file(second))
        with ZipFile(first) as archive:
            self.assertEqual(archive.namelist(), ["a.txt", "b.txt"])

    def test_library_pack_contains_only_selected_modules_and_resources(self) -> None:
        frozen = self.root / "Python" / "frozen_modules"
        frozen.mkdir(parents=True)
        (frozen / "demo.h").write_text(
            "const unsigned char _Py_M__demo[] = {1, 2, 3,};\n",
            encoding="utf-8",
        )
        (frozen / "other.h").write_text(
            "const unsigned char _Py_M__other[] = {4, 5,};\n",
            encoding="utf-8",
        )
        package = self.root / "Lib" / "demo"
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")
        (package / "data.json").write_text('{"ok": true}\n', encoding="utf-8")
        (package / "LICENSE.txt").write_text("demo license\n", encoding="utf-8")
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            source_resolver="pypi-sdist",
            project_name="demo-project",
            release_version="1.2.3",
            source_archive_sha256="a" * 64,
            python_packages=["demo"],
            top_level_import_names=["demo"],
            materialized_paths=["Lib/demo"],
            suppressed_system_libraries_release_x64=["GdiPlus.lib"],
            python_link_dependencies_release_x64=["demo-native.lib"],
            trusted_object_origins=[
                {"library": "demo-native.lib", "object": "MAIN.OBJ"},
            ],
            license_expression="MIT",
            license_files=["Lib/demo/LICENSE.txt"],
            toolchain_metadata={
                "rust": {
                    "cargo_version": "cargo 1.88.0",
                    "crt_static": True,
                    "target": "x86_64-pc-windows-msvc",
                }
            },
        )
        native_output = self.root / "PCbuild" / "amd64"
        native_output.mkdir(parents=True)
        (native_output / "demo-native.lib").write_bytes(b"library")
        provisional_output = self.root / "provisional-dist"
        provisional_path = build.export_library_pack(
            self.root,
            provisional_output,
            (3, 13, 0),
            "3.13.0",
            "x64",
            integration,
        )
        with ZipFile(provisional_path) as archive:
            provisional_metadata = json.loads(archive.read("pack.json"))
        verification_report = {
            "schema_version": 1,
            "kind": "staticpython-pack-sdk-verification",
            "status": "passed",
            "failures": [],
            "runtime_sdk": _passed_runtime_sdk(),
            "pe_audit": _passed_pe_audit(),
            "executable_sha256": "e" * 64,
            "packs": [{
                "name": "demo",
                "version": "1.2.3",
                "sha256": (provisional_sha := build.sha256_file(provisional_path)),
                "provisional_sha256": provisional_sha,
                "payload_manifest_sha256": build.pack_payload_manifest_sha256(provisional_metadata),
                "metadata_without_verification_sha256": (
                    build.pack_metadata_without_verification_sha256(provisional_metadata)
                ),
            }],
            "integration_smoke_tests": [
                _passed_report_smoke("demo", "import-demo", "import"),
            ],
        }
        output = self.root / "dist"
        archive_path = build.export_library_pack(
            self.root,
            output,
            (3, 13, 0),
            "3.13.0",
            "x64",
            integration,
            verification_status="passed",
            verification_report=verification_report,
        )
        with ZipFile(archive_path) as archive:
            metadata = json.loads(archive.read("pack.json"))
            descriptor = archive.read("src/pack.c").decode("utf-8")
            frozen_header = archive.read("src/frozen/demo.h").decode("utf-8")
            pack_frozen_symbol = build.staticpython_pack_frozen_symbol(
                "demo",
                "1.2.3",
                "demo",
            )
            self.assertEqual(metadata["frozen_modules"], ["demo"])
            self.assertNotIn("other", metadata["frozen_modules"])
            self.assertIn("Lib/demo/data.json", [item["path"] for item in metadata["resources"]])
            self.assertEqual(metadata["license"]["status"], "complete")
            self.assertEqual(metadata["source_archive_sha256"], "a" * 64)
            self.assertEqual(
                metadata["toolchain"]["rust"],
                {
                    "cargo_version": "cargo 1.88.0",
                    "crt_static": True,
                    "target": "x86_64-pc-windows-msvc",
                },
            )
            self.assertEqual(metadata["verification"]["status"], "passed")
            self.assertEqual(metadata["suppressed_system_libraries"], ["gdiplus.lib"])
            self.assertEqual(
                metadata["trusted_object_origins"],
                [{"library": "demo-native.lib", "object": "main.obj"}],
            )
            self.assertEqual(
                metadata["verification"]["smoke_tests"],
                [{"name": "import-demo", "kind": "import", "status": "passed"}],
            )
            self.assertEqual(
                metadata["verification"]["provisional_pack_sha256"],
                build.sha256_file(provisional_path),
            )
            self.assertIn('"demo"', descriptor)
            self.assertIn(pack_frozen_symbol, descriptor)
            self.assertIn(pack_frozen_symbol, frozen_header)
            self.assertNotIn("_Py_M__demo[]", frozen_header)
            self.assertIn("staticpython_pack_demo_resource_", descriptor)
            self.assertNotIn('_Py_M__other', descriptor)
        bound = build.bind_promoted_pack_evidence(verification_report, [archive_path])
        self.assertEqual(bound["promotion"]["packs"][0]["final_sha256"], build.sha256_file(archive_path))

    def test_pack_frozen_symbols_do_not_alias_cpython_module_encoding(self) -> None:
        stdlib_symbol = "_Py_M__importlib_metadata"
        backport_symbol = build.staticpython_pack_frozen_symbol(
            "importlib-metadata",
            "8.7.0",
            "importlib_metadata",
        )
        dotted_symbol = build.staticpython_pack_frozen_symbol(
            "example-pack",
            "1.0",
            "importlib.metadata",
        )
        self.assertNotEqual(backport_symbol, stdlib_symbol)
        self.assertNotEqual(dotted_symbol, stdlib_symbol)
        self.assertNotEqual(backport_symbol, dotted_symbol)

    def test_promoted_pack_evidence_binds_final_archive_to_verified_payload(self) -> None:
        staging = self.root / "pack-stage"
        staging.mkdir()
        (staging / "payload.bin").write_bytes(b"verified payload")
        payload_record = {
            "path": "payload.bin",
            "size": 16,
            "sha256": hashlib.sha256(b"verified payload").hexdigest(),
        }
        provisional_metadata = {
            "schema_version": 1,
            "kind": "staticpython-library-pack",
            "name": "demo",
            "version": "1.0",
            "files": [payload_record],
            "verification": {"status": "not-run", "smoke_tests": []},
        }
        (staging / "pack.json").write_text(json.dumps(provisional_metadata), encoding="utf-8")
        provisional = self.root / "provisional.zip"
        build.write_deterministic_zip(staging, provisional)
        payload_manifest_sha = build.pack_payload_manifest_sha256(provisional_metadata)
        metadata_sha = build.pack_metadata_without_verification_sha256(provisional_metadata)
        report = {
            "schema_version": 1,
            "kind": "staticpython-pack-sdk-verification",
            "status": "passed",
            "failures": [],
            "runtime_sdk": _passed_runtime_sdk(),
            "pe_audit": _passed_pe_audit(),
            "executable_sha256": "e" * 64,
            "packs": [{
                "name": "demo",
                "version": "1.0",
                "sha256": (provisional_sha := build.sha256_file(provisional)),
                "provisional_sha256": provisional_sha,
                "payload_manifest_sha256": payload_manifest_sha,
                "metadata_without_verification_sha256": metadata_sha,
            }],
            "integration_smoke_tests": [
                _passed_report_smoke("demo", "demo", "import"),
            ],
        }
        final_metadata = dict(provisional_metadata)
        final_metadata["verification"] = {
            "status": "passed",
            "smoke_tests": [{"name": "demo", "kind": "import", "status": "passed"}],
            "provisional_pack_sha256": build.sha256_file(provisional),
            "payload_manifest_sha256": payload_manifest_sha,
            "metadata_without_verification_sha256": metadata_sha,
        }
        (staging / "pack.json").write_text(json.dumps(final_metadata), encoding="utf-8")
        final = self.root / "final.zip"
        build.write_deterministic_zip(staging, final)

        bound = build.bind_promoted_pack_evidence(report, [final])

        self.assertEqual(bound["promotion"]["status"], "passed")
        self.assertEqual(bound["promotion"]["packs"][0]["final_sha256"], build.sha256_file(final))

    def test_promoted_pack_evidence_rejects_payload_drift(self) -> None:
        staging = self.root / "pack-stage"
        staging.mkdir()
        (staging / "payload.bin").write_bytes(b"changed")
        changed_record = {
            "path": "payload.bin",
            "size": 7,
            "sha256": hashlib.sha256(b"changed").hexdigest(),
        }
        metadata = {
            "schema_version": 1,
            "kind": "staticpython-library-pack",
            "name": "demo",
            "version": "1.0",
            "files": [changed_record],
            "verification": {
                "status": "passed",
                "smoke_tests": [
                    {"name": "demo", "kind": "import", "status": "passed"}
                ],
                "provisional_pack_sha256": "a" * 64,
                "payload_manifest_sha256": "b" * 64,
                "metadata_without_verification_sha256": "c" * 64,
            },
        }
        (staging / "pack.json").write_text(json.dumps(metadata), encoding="utf-8")
        final = self.root / "final.zip"
        build.write_deterministic_zip(staging, final)
        report = {
            "schema_version": 1,
            "kind": "staticpython-pack-sdk-verification",
            "status": "passed",
            "failures": [],
            "runtime_sdk": _passed_runtime_sdk(),
            "pe_audit": _passed_pe_audit(),
            "executable_sha256": "e" * 64,
            "packs": [{
                "name": "demo",
                "version": "1.0",
                "sha256": "a" * 64,
                "provisional_sha256": "a" * 64,
                "payload_manifest_sha256": "b" * 64,
                "metadata_without_verification_sha256": "c" * 64,
            }],
            "integration_smoke_tests": [
                _passed_report_smoke("demo", "demo", "import"),
            ],
        }

        with self.assertRaisesRegex(RuntimeError, "payload manifest evidence does not match"):
            build.bind_promoted_pack_evidence(report, [final])

    def test_promoted_pack_evidence_rejects_smoke_projection_drift(self) -> None:
        report, final, metadata = self._write_pack_promotion_fixture()
        metadata["verification"]["smoke_tests"] = [
            {"name": "forged-smoke", "kind": "script", "status": "passed"},
        ]
        staging = self.root / "promotion-fixture"
        (staging / "pack.json").write_text(json.dumps(metadata), encoding="utf-8")
        build.write_deterministic_zip(staging, final)

        with self.assertRaisesRegex(RuntimeError, "verification metadata does not match"):
            build.bind_promoted_pack_evidence(report, [final])

    def test_promoted_pack_evidence_rejects_non_verification_metadata_drift(self) -> None:
        report, final, metadata = self._write_pack_promotion_fixture()
        metadata["platform"] = "arm64"
        staging = self.root / "promotion-fixture"
        (staging / "pack.json").write_text(json.dumps(metadata), encoding="utf-8")
        build.write_deterministic_zip(staging, final)

        with self.assertRaisesRegex(RuntimeError, "metadata evidence does not match"):
            build.bind_promoted_pack_evidence(report, [final])

    def test_promoted_pack_evidence_rejects_provisional_report_drift(self) -> None:
        report, final, _metadata = self._write_pack_promotion_fixture()
        report["packs"][0]["payload_manifest_sha256"] = "b" * 64

        with self.assertRaisesRegex(RuntimeError, "verification metadata does not match"):
            build.bind_promoted_pack_evidence(report, [final])

    def test_promoted_pack_validator_rejects_recorded_final_sha_drift(self) -> None:
        report, final, _metadata = self._write_pack_promotion_fixture()
        bound = build.bind_promoted_pack_evidence(report, [final])
        bound["promotion"]["packs"][0]["final_sha256"] = "f" * 64

        with self.assertRaisesRegex(RuntimeError, "recorded pack promotion evidence"):
            pack_evidence.validate_promoted_pack_evidence(bound, [final])

    def test_pack_reader_rejects_windows_drive_and_ads_members(self) -> None:
        for index, unsafe_name in enumerate(
            ("C:evil", "dir/file:stream", "C:evil/", "NUL.txt", "trailing.")
        ):
            with self.subTest(unsafe_name=unsafe_name):
                archive_path = self.root / f"unsafe-{index}.zip"
                with ZipFile(archive_path, "w") as archive:
                    archive.writestr(unsafe_name, b"")
                    archive.writestr("pack.json", json.dumps({"files": []}))
                with self.assertRaisesRegex(RuntimeError, "unsafe .*ZIP member"):
                    pack_evidence.read_pack_metadata(archive_path)

    def test_pack_promotion_rejects_contradictory_verifier_status(self) -> None:
        for mutation, message in (
            (lambda report: report["failures"].append({"kind": "smoke"}), "contains failures"),
            (
                lambda report: report["runtime_sdk"].pop("archive_sha256"),
                "runtime SDK provenance",
            ),
            (lambda report: report["pe_audit"].update(status="failed"), "PE dependency audit"),
            (
                lambda report: report["pe_audit"]["forbidden_dependencies"].append(
                    "python313.dll"
                ),
                "PE dependency audit",
            ),
            (
                lambda report: report["pe_audit"].update(
                    executable_sha256="0" * 64
                ),
                "PE dependency audit",
            ),
        ):
            with self.subTest(message=message):
                report, final, _metadata = self._write_pack_promotion_fixture()
                mutation(report)
                with self.assertRaisesRegex(RuntimeError, message):
                    build.bind_promoted_pack_evidence(report, [final])

    def test_pack_evidence_rejects_malformed_smoke_records(self) -> None:
        report, _final, metadata = self._write_pack_promotion_fixture()
        metadata["verification"]["smoke_tests"] = [{"status": "passed"}]
        with self.assertRaisesRegex(RuntimeError, "invalid or non-passing smoke"):
            pack_evidence.validate_pack_verification_metadata(metadata)

        report["integration_smoke_tests"] = [
            {"integration": "demo", "status": "passed"}
        ]
        with self.assertRaisesRegex(RuntimeError, "invalid or non-passing smoke"):
            pack_evidence.validate_sdk_verification_report(report)

        for field, value in (
            ("returncode", 17),
            ("timed_out", True),
            ("released_files", ["secret.tmp"]),
        ):
            with self.subTest(field=field):
                report, _final, _metadata = self._write_pack_promotion_fixture()
                report["integration_smoke_tests"][0][field] = value
                with self.assertRaisesRegex(RuntimeError, "invalid or non-passing smoke"):
                    pack_evidence.validate_sdk_verification_report(report)

    def test_release_index_binds_every_pack_to_its_runtime_promotion_report(self) -> None:
        report, final, metadata = self._write_pack_promotion_fixture()
        staticpython_commit = "d" * 40
        assets = self.root / "verified-assets"
        runtime_stage = self.root / "verified-runtime"
        (runtime_stage / "metadata").mkdir(parents=True)
        assets.mkdir()
        runtime_metadata = {
            "cpython_abi": "cp313",
            "cpython_version": "3.13.0",
            "runtime_abi": "staticpython-pack-v1-cp313",
            "staticpython_commit": staticpython_commit,
            "verification": {"status": "passed"},
            "cpython_commit": "c" * 40,
            "cpython_tag": "v3.13.0",
            "cpython_source": {
                "commit": "c" * 40,
                "archive_sha256": "a" * 64,
            },
            "toolchain": metadata["toolchain"],
        }
        (runtime_stage / build.RUNTIME_SDK_METADATA_RELATIVE_PATH).write_text(
            json.dumps(runtime_metadata), encoding="utf-8"
        )
        runtime_asset = assets / "runtime.zip"
        build.write_deterministic_zip(runtime_stage, runtime_asset)
        runtime_sha = build.sha256_file(runtime_asset)
        final_asset = assets / final.name
        final_asset.write_bytes(final.read_bytes())
        report["runtime_sdk"] = {
            "archive_sha256": runtime_sha,
            "cpython_version": "3.13.0",
            "runtime_abi": "staticpython-pack-v1-cp313",
            "staticpython_commit": staticpython_commit,
        }
        build.bind_promoted_pack_evidence(report, [final_asset])
        report_path = assets / "staticpython-pack-verification-3.13.0-a-f.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        runtimes = {
            "cp313": {
                "sha256": runtime_sha,
                "metadata": {
                    "cpython_version": "3.13.0",
                    "runtime_abi": "staticpython-pack-v1-cp313",
                    "staticpython_commit": staticpython_commit,
                },
            }
        }

        evidence = build_release_index.validate_pack_promotion_reports(
            assets,
            [(final_asset, metadata)],
            runtimes,
        )

        self.assertEqual(
            evidence[final_asset]["final_pack_sha256"], build.sha256_file(final_asset)
        )
        self.assertEqual(evidence[final_asset]["runtime_sdk_sha256"], runtime_sha)
        index = build_release_index.build_index(
            assets,
            "xqy2006/StaticPython",
            staticpython_commit,
            "runtime-tag",
            "pack-tag",
            require_all_targets=False,
            require_verified=True,
        )
        indexed_pack = index["packs"]["demo"]["1.0"]["cp313"]
        self.assertEqual(
            indexed_pack["verification_evidence"]["report"]["filename"],
            report_path.name,
        )
        self.assertEqual(index["release_families"]["a-f"]["asset_count"], 2)
        self.assertEqual(index["verification_reports"]["a-f"][0]["filename"], report_path.name)

        report_path.unlink()
        with self.assertRaisesRegex(RuntimeError, "no SDK promotion reports"):
            build_release_index.validate_pack_promotion_reports(
                assets,
                [(final_asset, metadata)],
                runtimes,
            )

    def test_system_library_suppression_resolves_pack_link_collisions(self) -> None:
        consumer = libs.LibraryIntegration(
            name="consumer",
            python_link_dependencies_release_x64=["gdiplus.lib", "user32.lib"],
        )
        provider = libs.LibraryIntegration(
            name="provider",
            suppressed_system_libraries_release_x64=["GDIPLUS.LIB"],
        )
        dependencies = build.iter_python_link_dependencies(
            self.root,
            {"python_link_dependencies_release_x64": []},
            [consumer, provider],
        )
        self.assertEqual(dependencies, ["user32.lib"])

        provider.suppressed_system_libraries_release_x64 = ["private.lib"]
        with self.assertRaisesRegex(RuntimeError, "only name Windows system libraries"):
            build.iter_python_link_dependencies(
                self.root,
                {"python_link_dependencies_release_x64": []},
                [consumer, provider],
            )

    def test_trusted_object_origin_must_name_a_pack_owned_library(self) -> None:
        integration = libs.LibraryIntegration(
            name="demo",
            trusted_object_origins=[
                {"library": "outside.lib", "object": "main.obj"},
            ],
        )
        with self.assertRaisesRegex(RuntimeError, "not owned by the pack"):
            build._integration_trusted_object_origins(
                integration,
                [{"logical_name": "owned.lib"}],
            )


    def test_library_pack_rejects_toolchain_base_key_override(self) -> None:
        integration = libs.LibraryIntegration(
            name="demo",
            toolchain_metadata={"runtime_library": "MultiThreadedDLL"},
        )
        with self.assertRaisesRegex(RuntimeError, "cannot override base key"):
            build._pack_toolchain_metadata(integration)

    def test_source_archive_sha256_pin_rejects_drift(self) -> None:
        archive = self.root / "demo-1.2.3.tar.gz"
        archive.write_bytes(b"locked source archive")
        observed = hashlib.sha256(archive.read_bytes()).hexdigest()
        integration = libs.LibraryIntegration(
            name="demo",
            source_archive_sha256_by_version={"1.2.3": observed},
        )
        with mock.patch.object(
            Path,
            "read_bytes",
            side_effect=AssertionError("source archives must be hashed as a stream"),
        ):
            self.assertEqual(
                libs._record_source_archive_sha256(integration, "1.2.3", archive),
                observed,
            )
        self.assertEqual(integration.source_archive_sha256, observed)

        integration.source_archive_sha256_by_version["1.2.3"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "source archive hash mismatch"):
            libs._record_source_archive_sha256(integration, "1.2.3", archive)

    def test_prepare_hooks_finalize_custom_pypi_license_metadata(self) -> None:
        source_root = self.root / "source"
        package = source_root / "Lib" / "demo"
        package.mkdir(parents=True)
        cache_root = self.root / "work"
        upstream = cache_root / "pypi" / "demo-project" / "1.2.3" / "extracted" / "demo-1.2.3"
        upstream.mkdir(parents=True)
        (upstream / "LICENSE.txt").write_text("upstream license\n", encoding="utf-8")

        def prepare_demo(_context: libs.LibraryHookContext) -> None:
            (package / "__init__.py").write_text("VALUE = 1\n", encoding="utf-8")

        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            project_name="demo-project",
            release_version="1.2.3",
            materialized_paths=["Lib/demo"],
            prepare_source_hooks=[prepare_demo],
        )
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=source_root,
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=cache_root,
            asset_overlay_root=self.root / "assets",
            log=lambda _message: None,
        )
        with mock.patch.object(
            libs,
            "_load_pypi_release_payload",
            return_value={"info": {"license_expression": "Apache-2.0"}},
        ):
            libs.run_prepare_source_hooks([integration], context)

        self.assertEqual(integration.license_expression, "Apache-2.0")
        self.assertEqual(len(integration.license_files), 1)
        copied_license = source_root / integration.license_files[0]
        self.assertEqual(copied_license.read_text(encoding="utf-8"), "upstream license\n")

    def test_temporary_pypi_release_cache_discards_only_selected_release(self) -> None:
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=self.root / "source",
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=self.root / "work",
            asset_overlay_root=self.root / "assets",
            log=lambda _message: None,
        )
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            project_name="demo-project",
        )
        selected_roots = []
        sibling_roots = []
        for cache_root in (context.download_cache_root, context.work_cache_root):
            selected = cache_root / "pypi" / "demo-project" / "1.2.3"
            selected.mkdir(parents=True)
            (selected / "payload.bin").write_bytes(b"selected")
            selected_roots.append(selected)
            sibling = cache_root / "pypi" / "demo-project" / "1.2.4"
            sibling.mkdir(parents=True)
            (sibling / "payload.bin").write_bytes(b"sibling")
            sibling_roots.append(sibling)

        with libs.temporary_pypi_release_cache(context, integration, "1.2.3"):
            self.assertTrue(all(path.exists() for path in selected_roots))

        self.assertTrue(all(not path.exists() for path in selected_roots))
        self.assertTrue(all(path.exists() for path in sibling_roots))

    def test_temporary_pypi_release_cache_discards_after_failure(self) -> None:
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=self.root / "source",
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=self.root / "work",
            asset_overlay_root=self.root / "assets",
            log=lambda _message: None,
        )
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            project_name="demo-project",
        )
        selected_roots = []
        for cache_root in (context.download_cache_root, context.work_cache_root):
            selected = cache_root / "pypi" / "demo-project" / "1.2.3"
            selected.mkdir(parents=True)
            (selected / "payload.bin").write_bytes(b"selected")
            selected_roots.append(selected)

        with self.assertRaisesRegex(RuntimeError, "version failed"):
            with libs.temporary_pypi_release_cache(context, integration, "1.2.3"):
                raise RuntimeError("version failed")

        self.assertTrue(all(not path.exists() for path in selected_roots))

    def test_temporary_pypi_release_cache_rejects_path_traversal(self) -> None:
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=self.root / "source",
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=self.root / "work",
            asset_overlay_root=self.root / "assets",
            log=lambda _message: None,
        )
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            project_name="demo-project",
        )
        protected = context.download_cache_root / "pypi" / "protected"
        protected.mkdir(parents=True)
        (protected / "payload.bin").write_bytes(b"keep")
        entered = False

        with self.assertRaisesRegex(RuntimeError, "unsafe PyPI cache release version"):
            with libs.temporary_pypi_release_cache(context, integration, ".."):
                entered = True

        self.assertFalse(entered)
        self.assertEqual((protected / "payload.bin").read_bytes(), b"keep")

    def test_temporary_pypi_release_cache_rejects_unsafe_project_name(self) -> None:
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=self.root / "source",
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=self.root / "work",
            asset_overlay_root=self.root / "assets",
            log=lambda _message: None,
        )
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            project_name="../demo-project",
        )

        with self.assertRaisesRegex(RuntimeError, "unsafe normalized PyPI cache project"):
            with libs.temporary_pypi_release_cache(context, integration, "1.2.3"):
                self.fail("unsafe project cache scope was entered")

    def test_declared_license_source_is_versioned_and_hash_verified(self) -> None:
        payload = b"fallback license\n"
        digest = hashlib.sha256(payload).hexdigest()
        source_root = self.root / "source"
        source_root.mkdir()
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            project_name="demo-project",
            release_version="1.2.3",
            license_expression="MIT",
            license_sources=[
                {
                    "filename": "LICENSE",
                    "url": "https://example.invalid/demo/v{release_version}/LICENSE",
                    "sha256": digest,
                }
            ],
        )
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=source_root,
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=self.root / "work",
            asset_overlay_root=self.root / "assets",
            log=lambda _message: None,
        )
        with mock.patch.object(libs, "_read_url_bytes", return_value=payload) as read:
            libs._finalize_integration_license_metadata(context, integration)

        read.assert_called_once_with("https://example.invalid/demo/v1.2.3/LICENSE")
        self.assertEqual(integration.license_files, ["licenses/demo/LICENSE"])
        self.assertEqual((source_root / integration.license_files[0]).read_bytes(), payload)
        self.assertEqual(
            build.resolved_license_sources(integration),
            [
                {
                    "filename": "LICENSE",
                    "url": "https://example.invalid/demo/v1.2.3/LICENSE",
                    "sha256": digest,
                }
            ],
        )

    def test_declared_license_source_rejects_hash_drift(self) -> None:
        source_root = self.root / "source"
        source_root.mkdir()
        integration = libs.LibraryIntegration(
            name="demo",
            release_version="1.2.3",
            license_sources=[
                {
                    "filename": "LICENSE",
                    "url": "https://example.invalid/LICENSE",
                    "sha256": "0" * 64,
                }
            ],
        )
        context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=source_root,
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=self.root / "downloads",
            work_cache_root=self.root / "work",
            asset_overlay_root=self.root / "assets",
            log=lambda _message: None,
        )
        with mock.patch.object(libs, "_read_url_bytes", return_value=b"changed\n"):
            with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
                libs._materialize_declared_license_sources(context, integration)

    def test_license_expression_inference_prefers_specific_metadata(self) -> None:
        cases = {
            "Apache-2.0 AND MIT": "Apache-2.0 AND MIT",
            "BSD-2-Clause": "BSD-2-Clause",
            "3-Clause BSD License": "BSD-3-Clause",
            "Apache License, Version 2.0": "Apache-2.0",
            "MIT OR Apache-2.0": "MIT OR Apache-2.0",
            "MPL-2.0 AND MIT": "MPL-2.0 AND MIT",
            "Unlicense": "Unlicense",
        }
        for raw_license, expected in cases.items():
            with self.subTest(raw_license=raw_license):
                self.assertEqual(
                    libs._infer_license_expression(
                        {
                            "license": raw_license,
                            "classifiers": ["License :: OSI Approved :: BSD License"],
                        }
                    ),
                    expected,
                )

    def test_ambiguous_library_licenses_are_declared_explicitly(self) -> None:
        config = build.load_config()
        _profile_name, profile = build.resolve_profile(config, "full")
        catalog = build.profile_library_catalog(config, profile, "third_party_library_catalog")
        integrations = libs.load_integration_definitions(
            build.LIB_PATCH_ROOT,
            library_catalog=catalog,
        )
        by_name = {integration.name: integration for integration in integrations}
        expected = {
            "Crypto": "BSD-2-Clause AND LicenseRef-Public-Domain",
            "dateutil": "Apache-2.0 OR BSD-3-Clause",
            "dearpygui": "MIT",
            "dialite": "BSD-2-Clause",
            "exceptiongroup": "MIT",
            "fsspec": "BSD-3-Clause",
            "glfw": "Zlib",
            "jwt": "MIT",
            "mypy_extensions": "MIT",
            "pscript": "BSD-2-Clause",
            "pyglet": "BSD-3-Clause",
            "pystray": "LGPL-3.0-only",
            "socks": "BSD-3-Clause",
            "text_unidecode": "GPL-1.0-or-later OR Artistic-1.0-Perl",
            "tomli": "MIT",
        }
        for name, expression in expected.items():
            with self.subTest(name=name):
                self.assertEqual(by_name[name].license_expression, expression)

        fallback_sources = {
            "humanize",
            "jwt",
            "loguru",
            "tqdm",
            "ua_parser_builtins",
            "webencodings",
        }
        for name in fallback_sources:
            with self.subTest(license_source=name):
                self.assertEqual(len(by_name[name].license_sources), 1)
                self.assertRegex(by_name[name].license_sources[0]["sha256"], r"^[0-9a-f]{64}$")

    def test_library_license_audit_reports_all_incomplete_integrations(self) -> None:
        source_root = self.root / "source"
        license_path = source_root / "licenses" / "good" / "LICENSE"
        license_path.parent.mkdir(parents=True)
        license_path.write_text("permission notice\n", encoding="utf-8")
        integrations = [
            libs.LibraryIntegration(
                name="good",
                release_version="1.0",
                license_expression="MIT",
                license_files=["licenses/good/LICENSE"],
            ),
            libs.LibraryIntegration(name="missing-expression", release_version="2.0"),
            libs.LibraryIntegration(
                name="missing-file",
                release_version="3.0",
                license_expression="Apache-2.0",
                license_files=["licenses/missing/LICENSE"],
            ),
        ]

        summary = audit_library_licenses.audit_integration_licenses(
            source_root,
            integrations,
        )

        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["integration_count"], 3)
        self.assertEqual(summary["failure_count"], 2)
        self.assertEqual(
            {failure["name"] for failure in summary["failures"]},
            {"missing-expression", "missing-file"},
        )
        self.assertEqual(summary["integrations"][0]["status"], "passed")
        self.assertEqual(len(summary["integrations"][0]["files"][0]["sha256"]), 64)

    def test_distribution_license_scan_prunes_ignored_deep_test_trees(self) -> None:
        distribution = self.root / "distribution"
        distribution.mkdir()
        license_path = distribution / "LICENSE"
        license_path.write_text("runtime license\n", encoding="utf-8")
        deep = distribution / "package" / "tests"
        for index in range(12):
            deep /= f"nested-{index:02d}-with-a-deliberately-long-component"
        os.makedirs(libs._long_path(deep), exist_ok=True)
        ignored_license = deep / "LICENSE-vendored"
        with open(libs._long_path(ignored_license), "wb") as stream:
            stream.write(b"test-only license\n")

        try:
            candidates = libs._distribution_license_candidates(
                distribution,
                maximum_depth=4,
                ignore_patterns=["tests"],
            )
            self.assertEqual([path.name for path in candidates], ["LICENSE"])
        finally:
            libs._remove_tree(distribution / "package" / "tests")

    def test_license_collision_names_are_independent_of_source_paths(self) -> None:
        def materialize(label: str, first_payload: bytes, second_payload: bytes) -> dict[str, bytes]:
            upstream = self.root / f"upstream-{label}"
            first = upstream / "a" / "LICENSE"
            second = upstream / "z" / "LICENSE"
            first.parent.mkdir(parents=True)
            second.parent.mkdir(parents=True)
            first.write_bytes(first_payload)
            second.write_bytes(second_payload)
            source_root = self.root / f"source-{label}"
            source_root.mkdir()
            context = libs.LibraryHookContext(
                repo_root=REPO_ROOT,
                source_root=source_root,
                version_info=(3, 13, 0),
                version_mm="3.13",
                version_full="3.13.0",
                download_cache_root=self.root / "downloads",
                work_cache_root=self.root / "work",
                asset_overlay_root=self.root / "assets",
                log=lambda _message: None,
            )
            integration = libs.LibraryIntegration(name="demo")
            libs._materialize_license_candidates(
                context,
                integration,
                [first, second],
            )
            return {
                relative: (source_root / relative).read_bytes()
                for relative in integration.license_files
            }

        first = materialize("one", b"alpha\n", b"beta\n")
        second = materialize("two", b"beta\n", b"alpha\n")
        self.assertEqual(first, second)

    def test_native_only_pack_does_not_require_a_frozen_module(self) -> None:
        (self.root / "Python" / "frozen_modules").mkdir(parents=True)
        integration = libs.LibraryIntegration(
            name="native_demo",
            python_packages=["native_demo"],
            top_level_import_names=["native_demo"],
            builtin_module_registrations=[
                {"name": "native_demo", "pyinit": "PyInit_native_demo"}
            ],
        )
        self.assertEqual(build._integration_frozen_modules(self.root, integration), [])

    def test_release_pack_ownership_covers_auxiliary_top_level_modules(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        integrations = libs.load_integration_definitions(
            REPO_ROOT / "Lib",
            library_catalog=config["third_party_library_catalog"],
        )
        by_name = {integration.name: integration for integration in integrations}
        expected_ownership = {
            "black": {"_black_version", "black", "blackd", "blib2to3"},
            "ipykernel": {"ipykernel", "ipykernel_launcher"},
            "matplotlib": {"matplotlib", "mpl_toolkits", "pylab"},
            "plotly": {"_plotly_utils", "plotly"},
            "pytest": {"_pytest", "pytest"},
        }
        for name, expected in expected_ownership.items():
            self.assertTrue(
                expected.issubset(set(by_name[name].python_packages)),
                name,
            )
        self.assertEqual(
            by_name["black"].top_level_import_names,
            ["black", "blackd", "blib2to3"],
        )
        self.assertEqual(by_name["ipykernel"].top_level_import_names, ["ipykernel"])
        self.assertEqual(
            by_name["matplotlib"].top_level_import_names,
            ["matplotlib", "mpl_toolkits"],
        )
        self.assertEqual(by_name["plotly"].top_level_import_names, ["plotly"])
        self.assertEqual(by_name["pytest"].top_level_import_names, ["pytest"])

        unowned_roots: list[str] = []
        for integration in integrations:
            for raw_path in integration.materialized_paths:
                path = Path(raw_path.replace("\\", "/"))
                if len(path.parts) < 2 or path.parts[0].casefold() != "lib":
                    continue
                root = path.parts[1]
                if root.casefold() in {"test", "tests"}:
                    continue
                module_root = root[:-3] if root.endswith(".py") else root
                if not any(
                    package == module_root
                    or package.startswith(module_root + ".")
                    or module_root.startswith(package + ".")
                    for package in integration.python_packages
                ):
                    unowned_roots.append(f"{integration.name}:{raw_path}")
        self.assertEqual(unowned_roots, [])

    def test_optional_auxiliary_module_ownership_tracks_selected_source(self) -> None:
        black_spec = importlib.util.spec_from_file_location(
            "staticpython_black_ownership_test",
            REPO_ROOT / "Lib" / "black" / "setup.py",
        )
        assert black_spec is not None and black_spec.loader is not None
        black = importlib.util.module_from_spec(black_spec)
        black_spec.loader.exec_module(black)
        black._configure_black_version_module(False)
        self.assertNotIn("_black_version", black.LIBRARY_INTEGRATION.python_packages)
        self.assertIn("Lib/_black_version.py", black.LIBRARY_INTEGRATION.cleanup_paths)
        black._configure_black_version_module(True)
        self.assertIn("_black_version", black.LIBRARY_INTEGRATION.python_packages)
        self.assertNotIn(
            "_black_version",
            black.LIBRARY_INTEGRATION.top_level_import_names,
        )

        plotly_spec = importlib.util.spec_from_file_location(
            "staticpython_plotly_ownership_test",
            REPO_ROOT / "Lib" / "plotly" / "setup.py",
        )
        assert plotly_spec is not None and plotly_spec.loader is not None
        plotly = importlib.util.module_from_spec(plotly_spec)
        plotly_spec.loader.exec_module(plotly)
        context = SimpleNamespace(source_root=self.root)
        plotly.configure_plotly_auxiliary_modules(context)
        self.assertNotIn("_plotly_utils", plotly.LIBRARY_INTEGRATION.python_packages)
        (self.root / "Lib" / "_plotly_utils").mkdir(parents=True)
        plotly.configure_plotly_auxiliary_modules(context)
        self.assertIn("_plotly_utils", plotly.LIBRARY_INTEGRATION.python_packages)
        self.assertNotIn(
            "_plotly_utils",
            plotly.LIBRARY_INTEGRATION.top_level_import_names,
        )

    def test_pack_shards_partition_current_full_catalog(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        expected = config["profiles"]["full"]["third_party_libraries"]
        observed: list[str] = []
        for family in ("a-f", "g-l", "m-r", "s-z"):
            shard_config, selected = build_pack_shard_config.build_shard_config(config, family)
            self.assertTrue(selected)
            self.assertEqual(shard_config["profiles"]["pack-shard"]["third_party_libraries"], selected)
            self.assertEqual(shard_config["profiles"]["pack-shard"]["verification"], {"enabled": False})
            self.assertTrue(all(build_release_index.pack_family(name) == family for name in selected))
            observed.extend(selected)
        self.assertCountEqual(observed, expected)
        self.assertEqual(len({name.casefold() for name in observed}), len(observed))

        globally_resolved = {"mpmath": "1.3.0", "sympy": "1.14.0"}
        shard_config, _selected = build_pack_shard_config.build_shard_config(
            config,
            "m-r",
            version_overrides=globally_resolved,
        )
        self.assertEqual(
            shard_config["profiles"]["pack-shard"]["third_party_library_version_overrides"],
            globally_resolved,
        )

    def test_current_profile_has_one_canonical_pack_per_distribution(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        catalog = {
            item["name"]: item
            for item in config["third_party_library_catalog"]["libraries"]
        }
        full = config["profiles"]["full"]["third_party_libraries"]
        historical = config["profiles"]["full"][
            "historical_library_contract_libraries"
        ]
        self.assertIn("attr", catalog)
        self.assertNotIn("attr", full)
        self.assertIn("attr", historical)
        self.assertEqual(catalog["attrs"]["python_packages"], ["attrs", "attr"])
        self.assertIn("cattr", catalog)
        self.assertNotIn("cattr", full)
        self.assertIn("cattr", historical)
        self.assertEqual(catalog["cattrs"]["python_packages"], ["cattrs", "cattr"])
        self.assertEqual(
            catalog["cattrs"]["top_level_import_names"],
            ["cattrs", "cattr"],
        )
        self.assertEqual(
            catalog["cattrs"]["source_mapping"],
            {
                "cattrs||src/cattrs||cattr||src/cattr": "Lib/cattrs",
                "?cattr||?src/cattr||?cattrs||?src/cattrs": "Lib/cattr",
            },
        )

    def test_pack_verification_groups_isolate_native_dependency_closures(self) -> None:
        assets = self.root / "group-assets"
        assets.mkdir()

        def write_pack(name: str, *, dependencies: list[str] | None = None, native: bool = False) -> Path:
            staging = self.root / f"group-{name}"
            staging.mkdir()
            metadata = {
                "name": name,
                "version": "1.0",
                "dependencies": list(dependencies or []),
                "libraries": [f"{name}.lib"] if native else [],
                "builtin_modules": [{"name": f"{name}._native"}] if native else [],
                "files": [],
            }
            (staging / "pack.json").write_text(json.dumps(metadata), encoding="utf-8")
            destination = assets / f"{name}.zip"
            build.write_deterministic_zip(staging, destination)
            return destination

        pure_dependency = write_pack("pure_dependency")
        pure_first = write_pack("pure_first", dependencies=["pure_dependency"])
        pure_second = write_pack("pure_second")
        native_dependency = write_pack("native_dependency", native=True)
        native_root = write_pack("native_root", dependencies=["native_dependency"])

        groups = build.pack_verification_groups(
            [pure_dependency, pure_first, pure_second, native_dependency, native_root],
            ["pure_first", "pure_second", "native_root"],
        )

        self.assertEqual(groups[0]["roots"], ["pure_first", "pure_second"])
        self.assertEqual(
            [build.read_pack_metadata(path)["name"] for path in groups[0]["packs"]],
            ["pure_dependency", "pure_first", "pure_second"],
        )
        self.assertEqual(groups[1]["roots"], ["native_root"])
        self.assertEqual(
            [build.read_pack_metadata(path)["name"] for path in groups[1]["packs"]],
            ["native_dependency", "native_root"],
        )

    def test_pack_verification_report_set_preserves_each_root_evidence(self) -> None:
        def report(root: str, dependency: str | None, suffix: str) -> dict:
            names = [name for name in (dependency, root) if name]
            return {
                "schema_version": 1,
                "kind": "staticpython-pack-sdk-verification",
                "status": "passed",
                "failures": [],
                "runtime_sdk": _passed_runtime_sdk(),
                "verification_roots": [root],
                "packs": [
                    {
                        "name": name,
                        "version": "1.0",
                        "sha256": suffix * 64,
                        "provisional_sha256": suffix * 64,
                        "payload_manifest_sha256": suffix * 64,
                        "metadata_without_verification_sha256": suffix * 64,
                    }
                    for name in names
                ],
                "namespace_packages": [],
                "executable_sha256": suffix * 64,
                "pe_audit": {
                    **_passed_pe_audit(),
                    "executable_sha256": suffix * 64,
                    "map_sha256": suffix * 64,
                },
                "integration_smoke_tests": [
                    _passed_report_smoke(name, "import-1", "import")
                    for name in names
                ],
            }

        first = report("first", "shared", "a")
        second = report("second", "shared", "a")
        first["integration_smoke_tests"][0]["duration_seconds"] = 0.125
        first["integration_smoke_tests"][0]["stdout"] = "first run"
        second["integration_smoke_tests"][0]["duration_seconds"] = 0.875
        second["integration_smoke_tests"][0]["stdout"] = "second run"
        aggregate = build._aggregate_pack_verification_reports([first, second])

        self.assertEqual(aggregate["status"], "passed")
        self.assertEqual(aggregate["verification_mode"], "dependency-closure-set")
        self.assertEqual(
            [record["name"] for record in aggregate["packs"]],
            ["first", "second", "shared"],
        )
        self.assertEqual(len(aggregate["closure_verifications"]), 2)
        self.assertEqual(aggregate["verification_roots"], ["first", "second"])
        self.assertTrue(
            all(
                "duration_seconds" not in record
                and "stdout" not in record
                and "stderr" not in record
                for record in aggregate["integration_smoke_tests"]
            )
        )
        pack_evidence.validate_sdk_verification_report(aggregate)

    def test_pack_promotion_rejects_dependency_only_evidence(self) -> None:
        report, final, _metadata = self._write_pack_promotion_fixture()
        report["packs"].append(
            {
                "name": "root",
                "version": "1.0",
                "sha256": "a" * 64,
                "provisional_sha256": "a" * 64,
                "payload_manifest_sha256": "b" * 64,
                "metadata_without_verification_sha256": "c" * 64,
            }
        )
        report["integration_smoke_tests"].append(
            _passed_report_smoke("root", "root-behavior", "script")
        )
        report["verification_roots"] = ["root"]

        with self.assertRaisesRegex(RuntimeError, "only a dependency"):
            build.bind_promoted_pack_evidence(report, [final])

    def test_global_pack_version_lock_preserves_cross_family_solution(self) -> None:
        config = build.load_config()
        integrations = [
            libs.LibraryIntegration(
                name="mpmath",
                source_provider="pypi",
                project_name="mpmath",
                release_version="1.3.0",
            ),
            libs.LibraryIntegration(
                name="sympy",
                source_provider="pypi",
                project_name="sympy",
                release_version="1.14.0",
                dependencies=["mpmath"],
                dependency_constraints={"mpmath": "<1.4,>=1.1.0"},
            ),
        ]
        with mock.patch.object(
            pack_version_resolver.libs,
            "load_integrations",
            return_value=integrations,
        ) as load:
            payload = pack_version_resolver.resolve_pack_versions(config, "3.11.15")

        self.assertEqual(payload["versions"]["mpmath"], "1.3.0")
        self.assertEqual(payload["versions"]["sympy"], "1.14.0")
        self.assertEqual(payload["target_python_version"], "3.11.15")
        selected = load.call_args.args[1]
        self.assertIn("mpmath", selected)
        self.assertIn("sympy", selected)

        lock_path = self.root / "pack-version-lock.json"
        lock_path.write_text(json.dumps(payload), encoding="utf-8")
        loaded = pack_version_resolver.load_pack_version_lock(
            lock_path,
            target_python_version="3.11.15",
        )
        self.assertEqual(loaded["versions"]["mpmath"], "1.3.0")
        with self.assertRaisesRegex(RuntimeError, "targets Python"):
            pack_version_resolver.load_pack_version_lock(
                lock_path,
                target_python_version="3.12.13",
            )

    def test_loading_cleanup_definitions_does_not_resolve_remote_dependencies(self) -> None:
        library_root = self.root / "Lib"
        library_root.mkdir()
        catalog = {
            "libraries": [
                {
                    "name": "demo",
                    "overlay_entries": ["Lib/demo"],
                    "source_provider": "pypi",
                }
            ]
        }
        with mock.patch.object(libs, "_resolve_selected_integrations") as resolver:
            definitions = libs.load_integration_definitions(
                library_root,
                library_catalog=catalog,
            )
        resolver.assert_not_called()
        self.assertEqual([integration.name for integration in definitions], ["demo"])

    def test_output_pack_filter_keeps_dependencies_linked_but_not_exported(self) -> None:
        dependency = SimpleNamespace(name="dependency")
        root = SimpleNamespace(name="root")
        selected = build.select_output_pack_integrations([dependency, root], ["root"])
        self.assertEqual(selected, [root])
        with self.assertRaisesRegex(RuntimeError, "did not match"):
            build.select_output_pack_integrations([dependency, root], ["missing"])

    def test_resolved_dependencies_are_canonicalized_for_pack_metadata(self) -> None:
        dependency = libs.LibraryIntegration(
            name="dependency",
            project_name="dependency-project",
            release_version="2.1",
        )
        root = libs.LibraryIntegration(
            name="root",
            source_provider="pypi",
            project_name="root-project",
            release_version="1.0",
            auto_resolve_dependencies=True,
        )
        with mock.patch.object(
            libs,
            "_pypi_dependency_requirements",
            return_value=[("dependency-project", ">=2")],
        ):
            selected = libs._resolve_selected_integrations(
                [root, dependency],
                ["root"],
                target_version=libs.Version("3.13"),
            )
        self.assertEqual([integration.name for integration in selected], ["dependency", "root"])
        self.assertEqual(root.dependencies, ["dependency"])
        self.assertEqual(root.dependency_constraints, {"dependency": ">=2"})

    def test_dependency_resolution_selects_latest_compatible_source_release(self) -> None:
        dependency = libs.LibraryIntegration(
            name="dependency",
            source_provider="pypi",
            project_name="dependency-project",
        )
        root = libs.LibraryIntegration(
            name="root",
            release_version="1.0",
            dependencies=["dependency"],
            dependency_constraints={"dependency": "<2"},
        )
        candidates = [("2.1", {"url": "new"}), ("1.5", {"url": "compatible"})]
        with mock.patch.object(libs, "_iter_pypi_distribution_candidates", return_value=candidates):
            selected = libs._resolve_selected_integrations(
                [root, dependency],
                ["root"],
                target_version=libs.Version("3.13"),
            )
        self.assertEqual([integration.name for integration in selected], ["dependency", "root"])
        self.assertEqual(dependency.release_version, "1.5")

    def test_historical_dependencies_fall_back_to_locked_legacy_requires_txt(self) -> None:
        archive = (
            self.root
            / "downloads"
            / "pypi"
            / "legacy-root"
            / "1.0"
            / "legacy_root-1.0.zip"
        )
        archive.parent.mkdir(parents=True)
        with ZipFile(archive, "w") as bundle:
            bundle.writestr(
                "legacy_root-1.0/legacy_root.egg-info/requires.txt",
                "\n".join(
                    [
                        "notebook>=4.2",
                        "[:python_version < '3.12']",
                        "entrypoints==0.4",
                        "[test]",
                        "pytest",
                        "[:python_version >= '3.12']",
                        "new-only",
                    ]
                ),
            )
        digest = hashlib.sha256(archive.read_bytes()).hexdigest()
        file_info = {
            "filename": archive.name,
            "url": "https://files.example/legacy_root-1.0.zip",
            "size": archive.stat().st_size,
            "packagetype": "sdist",
            "requires_python": None,
            "digests": {"sha256": digest},
        }
        integration = libs.LibraryIntegration(
            name="legacy_root",
            source_provider="pypi",
            project_name="legacy-root",
            release_version="1.0",
            auto_resolve_dependencies=True,
        )
        libs._PYPI_ARCHIVE_REQUIREMENTS_CACHE.clear()
        with (
            mock.patch.object(libs, "DOWNLOAD_CACHE_ROOT", self.root / "downloads"),
            mock.patch.object(
                libs,
                "_load_pypi_release_payload",
                return_value={"info": {"requires_dist": None}},
            ),
            mock.patch.object(
                libs,
                "_iter_pypi_distribution_candidates",
                return_value=[("1.0", file_info)],
            ),
        ):
            requirements = libs._pypi_dependency_requirements_for_release(
                integration,
                libs.Version("3.11.16"),
                "1.0",
            )
        self.assertEqual(
            requirements,
            [("notebook", ">=4.2"), ("entrypoints", "==0.4")],
        )

    def test_historical_dependency_metadata_ignores_vendored_pkg_info(self) -> None:
        archive = self.root / "legacy_root-1.0.zip"
        with ZipFile(archive, "w") as bundle:
            bundle.writestr(
                "legacy_root-1.0/PKG-INFO",
                "Metadata-Version: 1.2\nName: legacy-root\nVersion: 1.0\n",
            )
            bundle.writestr(
                "legacy_root-1.0/legacy_root.egg-info/requires.txt",
                "real-dependency>=1\n",
            )
            bundle.writestr(
                "legacy_root-1.0/vendor/legacy_root_addon.egg-info/PKG-INFO",
                "Metadata-Version: 2.1\nName: legacy-root-addon\nVersion: 2.0\n"
                "Requires-Dist: wrong-dependency>=9\n",
            )

        requirements = libs._requirements_from_distribution_archive(
            archive,
            "legacy-root",
            libs.Version("3.11.16"),
        )

        self.assertEqual(requirements, ["real-dependency>=1"])

    def test_historical_dependency_metadata_rejects_vendored_only_pkg_info(self) -> None:
        archive = self.root / "legacy_root-1.0.zip"
        with ZipFile(archive, "w") as bundle:
            bundle.writestr(
                "legacy_root-1.0/vendor/other.egg-info/PKG-INFO",
                "Metadata-Version: 2.1\nName: other\nVersion: 9.0\n"
                "Requires-Dist: wrong-dependency>=9\n",
            )

        with self.assertRaisesRegex(
            RuntimeError,
            "no dependency metadata owned by 'legacy-root'",
        ):
            libs._requirements_from_distribution_archive(
                archive,
                "legacy-root",
                libs.Version("3.11.16"),
            )

    def test_historical_dependency_metadata_rejects_archive_hash_drift(self) -> None:
        archive = (
            self.root
            / "downloads"
            / "pypi"
            / "drifted"
            / "1.0"
            / "drifted-1.0.zip"
        )
        archive.parent.mkdir(parents=True)
        with ZipFile(archive, "w") as bundle:
            bundle.writestr(
                "drifted-1.0/drifted.egg-info/requires.txt",
                "dependency>=1\n",
            )
        file_info = {
            "filename": archive.name,
            "url": "https://files.example/drifted-1.0.zip",
            "size": archive.stat().st_size,
            "packagetype": "sdist",
            "requires_python": None,
            "digests": {"sha256": "0" * 64},
        }
        integration = libs.LibraryIntegration(
            name="drifted",
            source_provider="pypi",
            project_name="drifted",
            release_version="1.0",
            auto_resolve_dependencies=True,
        )
        libs._PYPI_ARCHIVE_REQUIREMENTS_CACHE.clear()
        with (
            mock.patch.object(libs, "DOWNLOAD_CACHE_ROOT", self.root / "downloads"),
            mock.patch.object(
                libs,
                "_load_pypi_release_payload",
                return_value={"info": {"requires_dist": None}},
            ),
            mock.patch.object(
                libs,
                "_iter_pypi_distribution_candidates",
                return_value=[("1.0", file_info)],
            ),
            self.assertRaisesRegex(RuntimeError, "source hash mismatch"),
        ):
            libs._pypi_dependency_requirements_for_release(
                integration,
                libs.Version("3.11.16"),
                "1.0",
            )

    def test_historical_dependency_resolution_backtracks_transitive_versions(self) -> None:
        root = libs.LibraryIntegration(
            name="root",
            source_provider="pypi",
            project_name="root",
            release_version="1.0",
            auto_resolve_dependencies=True,
        )
        dependency = libs.LibraryIntegration(
            name="dependency",
            source_provider="pypi",
            project_name="dependency",
            release_version="2.0",
            auto_resolve_dependencies=True,
        )

        def file_info(project: str, version: str) -> dict:
            return {
                "filename": f"{project}-{version}.tar.gz",
                "url": f"https://files.example/{project}-{version}.tar.gz",
                "size": 123,
                "packagetype": "sdist",
                "requires_python": ">=3.11",
                "digests": {"sha256": ("a" if project == "root" else "b") * 64},
            }

        def candidates(project: str, _target: libs.Version, release_version: str | None = None):
            versions = {"root": ["1.0"], "dependency": ["2.0", "1.0"]}[project]
            if release_version is not None:
                versions = [version for version in versions if version == release_version]
            return [(version, file_info(project, version)) for version in versions]

        def metadata(project: str, version: str | None):
            requirements = {
                ("root", "1.0"): ["dependency>=1"],
                ("dependency", "2.0"): ["root>=2"],
                ("dependency", "1.0"): ["root<2"],
            }[(project, version)]
            return {"info": {"requires_dist": requirements}}

        with (
            mock.patch.object(libs, "_iter_pypi_distribution_candidates", side_effect=candidates),
            mock.patch.object(libs, "_load_pypi_release_payload", side_effect=metadata),
        ):
            selected = libs._resolve_selected_integrations(
                [root, dependency],
                ["root"],
                target_version=libs.Version("3.11.15"),
                dependency_resolution_mode=libs.HISTORICAL_DEPENDENCY_SOLVER,
                pinned_version_names={"root"},
            )
            lock = libs.dependency_resolution_lock(
                selected,
                target_version=libs.Version("3.11.15"),
                solver=libs.HISTORICAL_DEPENDENCY_SOLVER,
                roots=["root"],
            )

        self.assertEqual(dependency.release_version, "1.0")
        self.assertEqual(root.dependencies, ["dependency"])
        self.assertEqual(dependency.dependencies, ["root"])
        self.assertEqual(
            {record["name"]: record["version"] for record in lock["integrations"]},
            {"dependency": "1.0", "root": "1.0"},
        )
        self.assertRegex(lock["solver_fingerprint"], r"^[0-9a-f]{64}$")

    def test_historical_dependency_resolution_keeps_explicit_transitive_pin(self) -> None:
        root = libs.LibraryIntegration(
            name="root",
            release_version="1.0",
            dependencies=["dependency"],
            dependency_constraints={"dependency": "<2"},
        )
        dependency = libs.LibraryIntegration(
            name="dependency",
            source_provider="pypi",
            release_version="2.0",
        )
        with self.assertRaisesRegex(RuntimeError, "historical dependency resolution failed"):
            libs._resolve_selected_integrations(
                [root, dependency],
                ["root"],
                target_version=libs.Version("3.13.14"),
                dependency_resolution_mode=libs.HISTORICAL_DEPENDENCY_SOLVER,
                pinned_version_names={"root", "dependency"},
            )

    def test_historical_dependency_resolution_accepts_non_pep440_source_ref(self) -> None:
        root = libs.LibraryIntegration(
            name="root",
            source_provider="github",
            release_version="main",
        )
        selected = libs._resolve_selected_integrations(
            [root],
            ["root"],
            target_version=libs.Version("3.13.14"),
            dependency_resolution_mode=libs.HISTORICAL_DEPENDENCY_SOLVER,
            pinned_version_names={"root"},
        )
        self.assertEqual(selected, [root])

    def test_historical_dependency_resolution_backjumps_over_unrelated_choices(self) -> None:
        root = libs.LibraryIntegration(
            name="root",
            source_provider="pypi",
            release_version="1.0",
            dependencies=["unrelated", "problem"],
            auto_resolve_dependencies=False,
        )
        unrelated = libs.LibraryIntegration(
            name="unrelated",
            source_provider="pypi",
            release_version="2.0",
            auto_resolve_dependencies=True,
        )
        problem = libs.LibraryIntegration(
            name="problem",
            source_provider="pypi",
            release_version="2.0",
            auto_resolve_dependencies=True,
        )

        def info(project: str, version: str) -> dict:
            return {
                "filename": f"{project}-{version}.tar.gz",
                "url": f"https://files.example/{project}-{version}.tar.gz",
                "packagetype": "sdist",
                "digests": {"sha256": "c" * 64},
            }

        def candidates(project: str, _target: libs.Version, release_version: str | None = None):
            versions = ["1.0"] if project == "root" else ["2.0", "1.0"]
            if project == "problem":
                versions = ["2.0"]
            if release_version is not None:
                versions = [version for version in versions if version == release_version]
            return [(version, info(project, version)) for version in versions]

        metadata_calls: list[tuple[str, str | None]] = []

        def metadata(project: str, version: str | None):
            metadata_calls.append((project, version))
            requirements = ["root>=2"] if project == "problem" else []
            return {"info": {"requires_dist": requirements}}

        with (
            mock.patch.object(libs, "_iter_pypi_distribution_candidates", side_effect=candidates),
            mock.patch.object(libs, "_load_pypi_release_payload", side_effect=metadata),
            self.assertRaisesRegex(RuntimeError, "historical dependency resolution failed"),
        ):
            libs._resolve_selected_integrations(
                [root, unrelated, problem],
                ["root"],
                target_version=libs.Version("3.11.15"),
                dependency_resolution_mode=libs.HISTORICAL_DEPENDENCY_SOLVER,
                pinned_version_names={"root"},
            )

        self.assertIn(("unrelated", "2.0"), metadata_calls)
        self.assertNotIn(("unrelated", "1.0"), metadata_calls)

    def test_historical_dependency_resolution_tracks_unconstrained_dependency_owner(self) -> None:
        root = libs.LibraryIntegration(
            name="root",
            release_version="1.0",
            dependencies=["chooser"],
        )
        chooser = libs.LibraryIntegration(
            name="chooser",
            source_provider="pypi",
            release_version="2.0",
            auto_resolve_dependencies=True,
        )
        missing = libs.LibraryIntegration(
            name="missing",
            source_provider="pypi",
            auto_resolve_dependencies=True,
        )

        def source(version: str) -> dict:
            return {
                "filename": f"chooser-{version}.tar.gz",
                "url": f"https://files.example/chooser-{version}.tar.gz",
                "packagetype": "sdist",
                "digests": {"sha256": "f" * 64},
            }

        def candidates(project: str, _target: libs.Version, release_version: str | None = None):
            if project == "missing":
                return []
            versions = ["2.0", "1.0"]
            if release_version is not None:
                versions = [version for version in versions if version == release_version]
            return [(version, source(version)) for version in versions]

        def metadata(project: str, version: str | None):
            requirements = ["missing"] if project == "chooser" and version == "2.0" else []
            return {"info": {"requires_dist": requirements}}

        with (
            mock.patch.object(libs, "_iter_pypi_distribution_candidates", side_effect=candidates),
            mock.patch.object(libs, "_load_pypi_release_payload", side_effect=metadata),
        ):
            selected = libs._resolve_selected_integrations(
                [root, chooser, missing],
                ["root"],
                target_version=libs.Version("3.13.14"),
                dependency_resolution_mode=libs.HISTORICAL_DEPENDENCY_SOLVER,
                pinned_version_names={"root"},
            )

        self.assertEqual(chooser.release_version, "1.0")
        self.assertEqual([integration.name for integration in selected], ["chooser", "root"])

    def test_historical_dependency_resolution_backjumps_to_owner_after_child_exhaustion(self) -> None:
        root = libs.LibraryIntegration(name="root", release_version="1.0", dependencies=["parent"])
        parent = libs.LibraryIntegration(
            name="parent",
            source_provider="pypi",
            release_version="2.0",
            auto_resolve_dependencies=True,
        )
        child = libs.LibraryIntegration(
            name="child",
            source_provider="pypi",
            release_version="1.0",
            auto_resolve_dependencies=True,
        )
        missing = libs.LibraryIntegration(name="missing", source_provider="pypi")

        def source(project: str, version: str) -> dict:
            return {
                "filename": f"{project}-{version}.tar.gz",
                "url": f"https://files.example/{project}-{version}.tar.gz",
                "packagetype": "sdist",
                "digests": {"sha256": "1" * 64},
            }

        def candidates(project: str, _target: libs.Version, release_version: str | None = None):
            versions = {
                "parent": ["2.0", "1.0"],
                "child": ["1.0"],
                "missing": [],
            }[project]
            if release_version is not None:
                versions = [version for version in versions if version == release_version]
            return [(version, source(project, version)) for version in versions]

        def metadata(project: str, version: str | None):
            requirements = []
            if project == "parent" and version == "2.0":
                requirements = ["child"]
            elif project == "child":
                requirements = ["missing"]
            return {"info": {"requires_dist": requirements}}

        with (
            mock.patch.object(libs, "_iter_pypi_distribution_candidates", side_effect=candidates),
            mock.patch.object(libs, "_load_pypi_release_payload", side_effect=metadata),
        ):
            selected = libs._resolve_selected_integrations(
                [root, parent, child, missing],
                ["root"],
                target_version=libs.Version("3.13.14"),
                dependency_resolution_mode=libs.HISTORICAL_DEPENDENCY_SOLVER,
                pinned_version_names={"root"},
            )

        self.assertEqual(parent.release_version, "1.0")
        self.assertEqual([integration.name for integration in selected], ["parent", "root"])

    def test_historical_dependency_lock_replay_uses_locked_sources(self) -> None:
        def integration_pair() -> list[libs.LibraryIntegration]:
            return [
                libs.LibraryIntegration(
                    name="root",
                    source_provider="pypi",
                    release_version="1.0",
                    dependencies=["dependency"],
                    dependency_constraints={"dependency": "==1.5"},
                    auto_resolve_dependencies=True,
                ),
                libs.LibraryIntegration(
                    name="dependency",
                    source_provider="pypi",
                    release_version="1.5",
                    auto_resolve_dependencies=True,
                ),
            ]

        records = []
        for name, version, digest in (
            ("dependency", "1.5", "d" * 64),
            ("root", "1.0", "e" * 64),
        ):
            records.append(
                {
                    "name": name,
                    "project_name": None,
                    "source_provider": "pypi",
                    "version": version,
                    "dependencies": [] if name == "dependency" else ["dependency"],
                    "dependency_constraints": {} if name == "dependency" else {"dependency": "==1.5"},
                    "source": {
                        "filename": f"{name}-{version}.tar.gz",
                        "url": f"https://files.example/{name}-{version}.tar.gz",
                        "sha256": digest,
                        "size": 10,
                        "packagetype": "sdist",
                        "requires_python": None,
                    },
                }
            )
        toolchain = {
            "platform": "windows-x64",
            "platform_toolset": "v143",
            "runtime_library": "MultiThreaded",
            "visual_studio_version": os.environ.get("VisualStudioVersion"),
            "vscmd_version": os.environ.get("VSCMD_VER"),
            "vc_tools_version": os.environ.get("VCToolsVersion"),
            "windows_sdk_version": os.environ.get("WindowsSDKVersion"),
        }
        unsigned_lock = {
            "schema_version": 1,
            "kind": "staticpython-history-dependency-lock",
            "solver": libs.HISTORICAL_DEPENDENCY_SOLVER,
            "roots": ["root"],
            "target_python_version": "3.13.14",
            "runtime_abi": "staticpython-pack-v1-cp313",
            "toolchain": toolchain,
            "toolchain_fingerprint": hashlib.sha256(
                json.dumps(
                    toolchain,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
            "integrations": records,
        }
        lock = {
            **unsigned_lock,
            "solver_fingerprint": hashlib.sha256(
                json.dumps(
                    unsigned_lock,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest(),
        }

        with (
            mock.patch.object(
                libs,
                "_iter_pypi_distribution_candidates",
                side_effect=AssertionError("locked replay must not query PyPI project releases"),
            ),
            mock.patch.object(
                libs,
                "_load_pypi_release_payload",
                side_effect=AssertionError("locked replay must not query PyPI release metadata"),
            ),
        ):
            selected = libs._resolve_selected_integrations(
                integration_pair(),
                ["root"],
                target_version=libs.Version("3.13.14"),
                dependency_resolution_mode=libs.HISTORICAL_DEPENDENCY_SOLVER,
                pinned_version_names={"root", "dependency"},
                dependency_resolution_lock_payload=lock,
            )
        self.assertEqual(
            libs.dependency_resolution_lock(
                selected,
                target_version=libs.Version("3.13.14"),
                solver=libs.HISTORICAL_DEPENDENCY_SOLVER,
                roots=["root"],
            ),
            lock,
        )
        tampered = json.loads(json.dumps(lock))
        tampered["integrations"][0]["source"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(RuntimeError, "solver fingerprint mismatch"):
            libs._resolve_selected_integrations(
                integration_pair(),
                ["root"],
                target_version=libs.Version("3.13.14"),
                dependency_resolution_mode=libs.HISTORICAL_DEPENDENCY_SOLVER,
                pinned_version_names={"root", "dependency"},
                dependency_resolution_lock_payload=tampered,
            )

    def test_dependency_cycles_are_kept_as_stable_components(self) -> None:
        first = libs.LibraryIntegration(name="first", dependencies=["second"])
        second = libs.LibraryIntegration(name="second", dependencies=["first"])
        selected_from_first = libs.select_integrations([first, second], ["first"])
        selected_from_second = libs.select_integrations([first, second], ["second"])
        self.assertEqual([integration.name for integration in selected_from_first], ["first", "second"])
        self.assertEqual([integration.name for integration in selected_from_second], ["first", "second"])

    def test_catalog_declares_dependencies_missing_from_upstream_metadata(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        catalog = {
            item["name"]: item
            for item in config["third_party_library_catalog"]["libraries"]
        }
        historical = config["profiles"]["full"][
            "historical_library_contract_libraries"
        ]
        self.assertEqual(
            [
                name
                for name in historical
                if name
                in {
                    "entrypoints",
                    "ipython_genutils",
                    "jupyterlab_launcher",
                    "nbclassic",
                }
            ],
            ["entrypoints", "ipython_genutils", "jupyterlab_launcher", "nbclassic"],
        )
        self.assertEqual(
            catalog["entrypoints"]["source_mapping"],
            {"entrypoints.py": "Lib/entrypoints.py"},
        )
        self.assertEqual(
            catalog["ipython_genutils"]["project_name"],
            "ipython-genutils",
        )
        self.assertEqual(
            catalog["ipython_genutils"]["source_ignore_patterns"],
            ["tests"],
        )
        self.assertEqual(
            catalog["jupyterlab_launcher"]["project_name"],
            "jupyterlab-launcher",
        )
        self.assertEqual(
            catalog["jupyterlab_launcher"]["source_ignore_patterns"],
            ["tests"],
        )
        nbclassic_spec = importlib.util.spec_from_file_location(
            "staticpython_nbclassic_dependency_test",
            REPO_ROOT / "Lib" / "nbclassic" / "setup.py",
        )
        assert nbclassic_spec is not None and nbclassic_spec.loader is not None
        nbclassic_module = importlib.util.module_from_spec(nbclassic_spec)
        nbclassic_spec.loader.exec_module(nbclassic_module)
        nbclassic = nbclassic_module.LIBRARY_INTEGRATION
        self.assertEqual(nbclassic.release_version, "1.3.3")
        self.assertEqual(nbclassic.source_resolver, "pypi-universal-wheel")
        self.assertIn("Lib/nbclassic", nbclassic.materialized_paths)
        self.assertEqual(nbclassic.source_ignore_patterns, ["tests"])
        self.assertEqual(
            nbclassic.resource_rules,
            [
                {"action": "include", "path": "Lib/nbclassic/i18n"},
                {
                    "action": "include",
                    "path": "etc/jupyter/jupyter_server_config.d/nbclassic.json",
                },
            ],
        )
        jupyter_server_setup = (REPO_ROOT / "Lib" / "jupyter_server" / "setup.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('root_text.endswith("/nbclassic/static")', jupyter_server_setup)
        self.assertEqual(catalog["soupsieve"]["dependencies"], ["bs4"])
        self.assertEqual(catalog["webruntime"]["dependencies"], ["dialite"])
        self.assertEqual(catalog["bleach"]["release_version"], "6.4.0")

        self.assertEqual(catalog["bleach"]["dependencies"], ["tinycss2"])
        self.assertEqual(
            catalog["bleach"]["dependency_constraints"],
            {"tinycss2": ">=1.1.0"},
        )
        self.assertEqual(catalog["janus"]["release_version"], "2.0.0")
        self.assertEqual(catalog["janus"]["license_expression"], "Apache-2.0")

        dash_spec = importlib.util.spec_from_file_location(
            "staticpython_dash_dependency_test",
            REPO_ROOT / "Lib" / "dash" / "setup.py",
        )
        assert dash_spec is not None and dash_spec.loader is not None
        dash_module = importlib.util.module_from_spec(dash_spec)
        dash_spec.loader.exec_module(dash_module)
        self.assertEqual(dash_module.LIBRARY_INTEGRATION.dependencies, ["janus"])
        self.assertEqual(
            dash_module.LIBRARY_INTEGRATION.dependency_constraints,
            {"janus": ">=1.0.0"},
        )

    def test_nbclassic_embeds_ui_resources_without_thousands_of_pack_sources(self) -> None:
        setup_spec = importlib.util.spec_from_file_location(
            "staticpython_nbclassic_resource_test",
            REPO_ROOT / "Lib" / "nbclassic" / "setup.py",
        )
        assert setup_spec is not None and setup_spec.loader is not None
        setup_module = importlib.util.module_from_spec(setup_spec)
        setup_spec.loader.exec_module(setup_module)

        package_root = self.root / "Lib" / "nbclassic"
        (package_root / "static" / "base" / "js").mkdir(parents=True)
        (package_root / "static" / "base" / "js" / "page.js").write_bytes(
            b"console.log('nbclassic');\n"
        )
        (package_root / "static" / "favicon.ico").write_bytes(b"icon")
        (package_root / "templates").mkdir()
        (package_root / "templates" / "tree.html").write_text(
            "<!doctype html><title>Classic</title>\n",
            encoding="utf-8",
        )
        (package_root / "i18n").mkdir()
        (package_root / "i18n" / "nbjs.json").write_text(
            '{"domain": "nbclassic"}\n',
            encoding="utf-8",
        )
        context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        setup_module.embed_nbclassic_resources(context)

        generated_path = package_root / "_staticpython_resources.py"
        generated_spec = importlib.util.spec_from_file_location(
            "staticpython_generated_nbclassic_resources",
            generated_path,
        )
        assert generated_spec is not None and generated_spec.loader is not None
        generated = importlib.util.module_from_spec(generated_spec)
        generated_spec.loader.exec_module(generated)
        self.assertIn("tree.html", generated.TEMPLATES)
        self.assertEqual(generated.resource_bytes("static/favicon.ico"), b"icon")
        self.assertEqual(
            generated.resource_bytes("static/base/js/page.js"),
            b"console.log('nbclassic');\n",
        )

        resource_files = build.collect_runtime_resource_files(
            self.root,
            [setup_module.LIBRARY_INTEGRATION],
        )
        self.assertIn("Lib/nbclassic/i18n/nbjs.json", resource_files)
        self.assertIn(
            "etc/jupyter/jupyter_server_config.d/nbclassic.json",
            resource_files,
        )
        self.assertNotIn("Lib/nbclassic/static/favicon.ico", resource_files)
        self.assertNotIn("Lib/nbclassic/templates/tree.html", resource_files)

    def test_nbclassic_wheel_keeps_locked_sdist_vendor_notices(self) -> None:
        setup_spec = importlib.util.spec_from_file_location(
            "staticpython_nbclassic_license_test",
            REPO_ROOT / "Lib" / "nbclassic" / "setup.py",
        )
        assert setup_spec is not None and setup_spec.loader is not None
        setup_module = importlib.util.module_from_spec(setup_spec)
        setup_spec.loader.exec_module(setup_module)
        integration = setup_module.LIBRARY_INTEGRATION

        target_root = self.root / "licenses" / "nbclassic"
        target_root.mkdir(parents=True)
        (target_root / "LICENSE").write_bytes(b"wheel license\n")
        integration.license_files = ["licenses/nbclassic/LICENSE"]
        archive_path = (
            self.root
            / "downloads"
            / "pypi"
            / "nbclassic"
            / "1.3.3"
            / "nbclassic-1.3.3.tar.gz"
        )
        archive_path.parent.mkdir(parents=True)
        with tarfile.open(archive_path, "w:gz") as archive:
            members = {
                "nbclassic-1.3.3/LICENSE": b"sdist license\n",
                **{
                    f"nbclassic-1.3.3/nbclassic/static/components/component-{index}/LICENSE-{index}":
                    f"component {index}\n".encode()
                    for index in range(10)
                },
                "nbclassic-1.3.3/node_modules/ignored/LICENSE": b"ignored\n",
            }
            for name, data in members.items():
                member = tarfile.TarInfo(name)
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        archive_sha256 = hashlib.sha256(archive_path.read_bytes()).hexdigest()
        integration.dependency_resolution = {
            "source": {"packagetype": "bdist_wheel"},
            "license_source": {
                "filename": archive_path.name,
                "url": "https://files.example/nbclassic-1.3.3.tar.gz",
                "sha256": archive_sha256,
                "packagetype": "sdist",
            },
        }
        context = SimpleNamespace(
            source_root=self.root,
            download_cache_root=self.root / "downloads",
            log=lambda _message: None,
        )
        setup_module.materialize_nbclassic_vendor_licenses(context)
        first_paths = list(integration.license_files)
        self.assertEqual(len(first_paths), 11)
        self.assertTrue(all((self.root / path).is_file() for path in first_paths))
        self.assertFalse(any("ignored" in path for path in first_paths))

        setup_module.materialize_nbclassic_vendor_licenses(context)
        self.assertEqual(integration.license_files, first_paths)

    def test_aws_sdk_catalog_declares_resource_behavior_smokes(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        catalog = {
            item["name"]: item
            for item in config["third_party_library_catalog"]["libraries"]
        }
        full = config["profiles"]["full"]["third_party_libraries"]
        self.assertEqual(
            [name for name in full if name in {"boto3", "botocore", "s3transfer"}],
            ["boto3", "botocore", "s3transfer"],
        )
        self.assertEqual(catalog["boto3"]["license_expression"], "Apache-2.0")
        self.assertEqual(catalog["botocore"]["license_expression"], "Apache-2.0")
        self.assertEqual(catalog["s3transfer"]["license_expression"], "Apache-2.0")
        self.assertEqual(
            [test["name"] for test in catalog["boto3"]["smoke_tests"]],
            ["s3-client-model"],
        )
        self.assertEqual(
            [test["name"] for test in catalog["botocore"]["smoke_tests"]],
            ["embedded-s3-service-model"],
        )
        self.assertEqual(
            [test["name"] for test in catalog["s3transfer"]["smoke_tests"]],
            ["transfer-config"],
        )

    def test_resource_scanner_loads_generic_catalog_integrations(self) -> None:
        config_path = self.root / "config.json"
        catalog = {
            "libraries": [
                {
                    "name": "demo",
                    "overlay_entries": ["Lib/demo"],
                    "source_provider": "pypi",
                }
            ]
        }
        config_path.write_text(
            json.dumps({
                "default_profile": "full",
                "third_party_library_catalog": catalog,
                "profiles": {"full": {"third_party_libraries": ["demo"]}},
            }),
            encoding="utf-8",
        )
        with mock.patch.object(scan_library_resources, "load_integrations", return_value=[]) as load:
            result = scan_library_resources.main([
                "--repo-root", str(self.root),
                "--config", str(config_path),
                "--profile", "full",
                "--python-version", "3.13",
                "--libraries", "demo",
                "--work-root", str(self.root / "work"),
                "--json", str(self.root / "report.json"),
                "--markdown", str(self.root / "report.md"),
            ])
        self.assertEqual(result, 0)
        self.assertEqual(load.call_args.kwargs["library_catalog"], catalog)

    def test_resource_scanner_recognizes_pack_roots_and_custom_pypi_hooks(self) -> None:
        resource = self.root / "service-2.json"
        resource.write_text("{}", encoding="utf-8")
        integration = SimpleNamespace(
            name="botocore",
            project_name="botocore",
            materialized_paths=["Lib/botocore"],
            prepare_source_hooks=[],
        )
        status, reason = scan_library_resources.classify_resource(
            resource,
            "Lib/botocore/data/s3/2006-03-01/service-2.json",
            "botocore/data/s3/2006-03-01/service-2.json",
            "",
            integration,
        )
        self.assertEqual(status, "handled")
        self.assertIn("StaticPythonPackV1", reason)

        source_info = scan_library_resources.pypi_source_info(SimpleNamespace(
            name="six",
            project_name="six",
            materialized_paths=["Lib/six"],
            prepare_source_hooks=[lambda _context: None],
        ))
        self.assertIsNotNone(source_info)
        assert source_info is not None
        self.assertEqual(source_info.source_mapping, {"six": "Lib/six"})

    def test_resource_scanner_keeps_root_library_catalog(self) -> None:
        profile_name, config, profile = scan_library_resources.read_config(
            REPO_ROOT / "config.json",
            "full",
        )
        self.assertEqual(profile_name, "full")
        catalog = profile.get(
            "third_party_library_catalog",
            config.get("third_party_library_catalog"),
        )
        integrations = libs.load_integration_definitions(
            REPO_ROOT / "Lib",
            library_catalog=catalog,
        )
        by_name = {integration.name: integration for integration in integrations}
        self.assertEqual(by_name["jwt"].project_name, "PyJWT")
        self.assertEqual(by_name["tomli"].top_level_import_names, ["tomli"])
        self.assertTrue(by_name["exceptiongroup"].auto_resolve_dependencies)

    def test_jwt_legacy_patch_rules_are_strict_and_idempotent(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        integrations = libs.load_integration_definitions(
            REPO_ROOT / "Lib",
            library_catalog=config["third_party_library_catalog"],
        )
        integration = next(item for item in integrations if item.name == "jwt")
        self.assertIn("inspect.signature(jwt.decode)", integration.smoke_tests[0]["code"])
        self.assertEqual(
            integration.license_sources,
            [
                {
                    "filename": "LICENSE-PyJWT-MIT",
                    "url": "https://raw.githubusercontent.com/jpadilla/pyjwt/0.4.1/LICENSE",
                    "sha256": "b9f95c496bd9dba93a2b6ee6382f4692918e8648f2d9dab03e93457f8b71ac4c",
                }
            ],
        )

        legacy_root = self.root / "legacy"
        legacy_module = legacy_root / "Lib" / "jwt" / "__init__.py"
        legacy_module.parent.mkdir(parents=True)
        legacy_module.write_text(
            """import hmac

from datetime import datetime
from calendar import timegm
from collections import Mapping

signing_methods = {
    'HS256': lambda msg, key: hmac.new(key, msg, None).digest(),
    'HS384': lambda msg, key: hmac.new(key, msg, None).digest(),
    'HS512': lambda msg, key: hmac.new(key, msg, None).digest(),
}

def constant_time_compare(val1, val2):
    result = 0
    for x, y in zip(val1, val2):
        result |= ord(x) ^ ord(y)
    return result == 0

def base64url_encode(input):
    return base64.urlsafe_b64encode(input).replace('=', '')
""",
            encoding="utf-8",
        )
        integration.release_version = "0.1.6"
        legacy_context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=legacy_root,
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=legacy_root / "downloads",
            work_cache_root=legacy_root / "work",
            asset_overlay_root=REPO_ROOT / "assets" / "overlay",
            log=lambda _message: None,
        )
        libs.run_pre_patch_hooks([integration], legacy_context)
        legacy_once = legacy_module.read_text(encoding="utf-8")
        libs.run_pre_patch_hooks([integration], legacy_context)
        legacy_text = legacy_module.read_text(encoding="utf-8")
        self.assertEqual(legacy_text, legacy_once)
        self.assertIn("from collections.abc import Mapping", legacy_text)
        self.assertIn("def _force_bytes(value):", legacy_text)
        self.assertEqual(legacy_text.count("def _force_bytes(value):"), 1)
        self.assertEqual(legacy_text.count("hmac.new(_force_bytes(key), _force_bytes(msg),"), 3)
        self.assertIn("x if isinstance(x, int) else ord(x)", legacy_text)
        self.assertIn(".replace(b'=', b'').decode('ascii')", legacy_text)

        early_root = self.root / "early"
        early_module = early_root / "Lib" / "jwt" / "__init__.py"
        early_module.parent.mkdir(parents=True)
        early_module.write_text(
            """import hmac

try:
    import json
except ImportError:
    import simplejson as json

signing_methods = {
    'HS256': lambda msg, key: hmac.new(key, msg, None).digest(),
    'HS384': lambda msg, key: hmac.new(key, msg, None).digest(),
    'HS512': lambda msg, key: hmac.new(key, msg, None).digest(),
}

def base64url_encode(input):
    return base64.urlsafe_b64encode(input).replace('=', '')

if not signature == signing_methods[header['alg']](signing_input, key):
    raise ValueError
""",
            encoding="utf-8",
        )
        integration.release_version = "0.1.1"
        early_context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=early_root,
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=early_root / "downloads",
            work_cache_root=early_root / "work",
            asset_overlay_root=REPO_ROOT / "assets" / "overlay",
            log=lambda _message: None,
        )
        libs.run_pre_patch_hooks([integration], early_context)
        early_once = early_module.read_text(encoding="utf-8")
        libs.run_pre_patch_hooks([integration], early_context)
        early_text = early_module.read_text(encoding="utf-8")
        self.assertEqual(early_text, early_once)
        self.assertEqual(early_text.count("def _force_bytes(value):"), 1)

        crypto_root = self.root / "optional-crypto"
        crypto_module = crypto_root / "Lib" / "jwt" / "__init__.py"
        crypto_module.parent.mkdir(parents=True)
        crypto_module.write_text(
            """from collections import Mapping

from Crypto.Signature import PKCS1_v1_5
from Crypto.Hash import SHA256
from Crypto.Hash import SHA384
from Crypto.Hash import SHA512
""",
            encoding="utf-8",
        )
        integration.release_version = "0.1.7"
        crypto_context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=crypto_root,
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=crypto_root / "downloads",
            work_cache_root=crypto_root / "work",
            asset_overlay_root=REPO_ROOT / "assets" / "overlay",
            log=lambda _message: None,
        )
        libs.run_pre_patch_hooks([integration], crypto_context)
        crypto_once = crypto_module.read_text(encoding="utf-8")
        libs.run_pre_patch_hooks([integration], crypto_context)
        crypto_text = crypto_module.read_text(encoding="utf-8")
        self.assertEqual(crypto_text, crypto_once)
        self.assertIn("except ImportError:", crypto_text)
        self.assertIn("from collections.abc import Mapping", crypto_text)

        positional_root = self.root / "positional"
        api_jws = positional_root / "Lib" / "jwt" / "api_jws.py"
        api_jwt = positional_root / "Lib" / "jwt" / "api_jwt.py"
        api_jws.parent.mkdir(parents=True)
        api_jws.write_text("from collections import Mapping\n", encoding="utf-8")
        api_jwt.write_text(
            "from collections import Mapping\n\n"
            "decoded = super(PyJWT, self).decode(jwt, key, algorithms, options,\n"
            + (" " * 44)
            + "**kwargs)\n",
            encoding="utf-8",
        )
        integration.release_version = "1.5.1"
        positional_context = libs.LibraryHookContext(
            repo_root=REPO_ROOT,
            source_root=positional_root,
            version_info=(3, 13, 0),
            version_mm="3.13",
            version_full="3.13.0",
            download_cache_root=positional_root / "downloads",
            work_cache_root=positional_root / "work",
            asset_overlay_root=REPO_ROOT / "assets" / "overlay",
            log=lambda _message: None,
        )
        libs.run_pre_patch_hooks([integration], positional_context)
        positional_jws_once = api_jws.read_text(encoding="utf-8")
        positional_jwt_once = api_jwt.read_text(encoding="utf-8")
        libs.run_pre_patch_hooks([integration], positional_context)
        self.assertEqual(api_jws.read_text(encoding="utf-8"), positional_jws_once)
        self.assertEqual(api_jwt.read_text(encoding="utf-8"), positional_jwt_once)
        self.assertIn(
            "jwt, key=key, algorithms=algorithms, options=options, **kwargs",
            api_jwt.read_text(encoding="utf-8"),
        )
        self.assertIn(
            "from collections.abc import Mapping",
            api_jws.read_text(encoding="utf-8"),
        )

    def test_default_integration_smoke_executes_real_import(self) -> None:
        integration = libs.LibraryIntegration(name="demo", top_level_import_names=["demo.api"])
        result = {
            "ok": True,
            "timeout": False,
            "returncode": 0,
            "stdout": "",
            "stderr": "",
            "display": "python -c import-demo",
            "duration_seconds": 0.01,
        }
        with mock.patch.object(staticpython_verify, "run_capture", return_value=result) as run_capture:
            failures, records = staticpython_verify.verify_integration_smoke_tests(
                ["python.exe"],
                None,
                REPO_ROOT,
                [integration],
                set(),
            )
        self.assertEqual(failures, [])
        self.assertEqual(records[0]["status"], "passed")
        command = run_capture.call_args.args[0]
        self.assertEqual(command[:2], ["python.exe", "-c"])
        self.assertIn("importlib.import_module('demo.api')", command[2])

    def test_release_index_uses_immutable_urls_and_pack_families(self) -> None:
        assets = self.root / "assets"
        runtime_stage = self.root / "runtime-stage"
        (runtime_stage / "metadata").mkdir(parents=True)
        commit = build.git_commit_or_none(REPO_ROOT)
        runtime_metadata = {
            "cpython_abi": "cp313",
            "cpython_version": "3.13.0",
            "runtime_abi": "staticpython-pack-v1-cp313",
            "staticpython_commit": commit,
            "verification": {"status": "passed"},
        }
        (runtime_stage / build.RUNTIME_SDK_METADATA_RELATIVE_PATH).write_text(
            json.dumps(runtime_metadata),
            encoding="utf-8",
        )
        assets.mkdir()
        runtime_zip = assets / "runtime.zip"
        build.write_deterministic_zip(runtime_stage, runtime_zip)

        pack_stage = self.root / "pack-stage"
        pack_stage.mkdir()
        pack_metadata = {
            "name": "attrs",
            "version": "25.1.0",
            "cpython_abi": "cp313",
            "staticpython_commit": commit,
            "trusted_object_origins": [
                {"library": "attrs.lib", "object": "main.obj"},
            ],
            "verification": {"status": "not-run"},
            "license": {"status": "complete"},
            "files": [],
        }
        (pack_stage / "pack.json").write_text(json.dumps(pack_metadata), encoding="utf-8")
        pack_zip = assets / "attrs.zip"
        build.write_deterministic_zip(pack_stage, pack_zip)

        index = build_release_index.build_index(
            assets,
            "xqy2006/StaticPython",
            commit,
            "staticpython-runtime-deadbeef",
            "staticpython-packs-deadbeef",
            require_all_targets=False,
            require_verified=False,
        )
        self.assertEqual(index["runtimes"]["cp313"]["sha256"], build.sha256_file(runtime_zip))
        pack = index["packs"]["attrs"]["25.1.0"]["cp313"]
        self.assertEqual(pack["release_family"], "a-f")
        self.assertIn("/staticpython-packs-deadbeef-a-f/attrs.zip", pack["url"])
        self.assertEqual(
            pack["metadata"]["trusted_object_origins"],
            [{"library": "attrs.lib", "object": "main.obj"}],
        )

    def test_release_index_keeps_only_resolver_metadata(self) -> None:
        runtime_metadata = {
            "runtime_abi": "staticpython-pack-v1-cp313",
            "link_libraries": ["pythoncore.lib"],
            "verification": {"status": "passed"},
            "files": [{"path": "lib/pythoncore.lib", "sha256": "a" * 64}],
        }
        self.assertEqual(
            build_release_index.runtime_index_metadata(runtime_metadata),
            {
                "runtime_abi": "staticpython-pack-v1-cp313",
                "link_libraries": ["pythoncore.lib"],
                "verification": {"status": "passed"},
            },
        )

        pack_path = self.root / "demo.zip"
        pack_metadata = {
            "name": "demo",
            "version": "1.0",
            "sources": ["src/pack.c", "src/resources/resource_000001.c"],
            "resources": [
                {
                    "path": "demo/data.json",
                    "symbol": "staticpython_pack_demo_resource_1",
                    "source": "src/resources/resource_000001.c",
                    "size": 42,
                    "compressed_size": 21,
                    "sha256": "b" * 64,
                }
            ],
            "libraries": ["demo.lib"],
            "suppressed_system_libraries": ["gdiplus.lib"],
            "trusted_object_origins": [
                {"library": "demo.lib", "object": "main.obj"},
            ],
            "source_files": [{"path": "demo/data.json", "sha256": "b" * 64}],
            "smoke_tests": [{"kind": "import", "module": "demo"}],
            "files": [{"path": "lib/demo.lib", "sha256": "c" * 64}],
        }
        projected = build_release_index.pack_index_metadata(pack_metadata, pack_path)
        self.assertEqual(projected["resources"], [{"path": "demo/data.json"}])
        self.assertEqual(projected["sources"], pack_metadata["sources"])
        self.assertEqual(projected["libraries"], ["demo.lib"])
        self.assertEqual(projected["suppressed_system_libraries"], ["gdiplus.lib"])
        self.assertEqual(
            projected["trusted_object_origins"],
            [{"library": "demo.lib", "object": "main.obj"}],
        )
        self.assertEqual(
            build_release_index.pack_index_metadata(
                {"trusted_object_origins": []},
                pack_path,
            )["trusted_object_origins"],
            [],
        )
        self.assertNotIn("source_files", projected)
        self.assertNotIn("smoke_tests", projected)
        self.assertNotIn("files", projected)
        self.assertEqual(
            pack_metadata["resources"][0]["symbol"],
            "staticpython_pack_demo_resource_1",
        )

    def test_release_index_rejects_resource_without_virtual_path(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "invalid resource record"):
            build_release_index.pack_index_metadata(
                {"resources": [{"source": "src/resources/resource_000001.c"}]},
                self.root / "demo.zip",
            )

    def test_release_index_serialization_is_compact_and_newline_terminated(self) -> None:
        self.assertEqual(
            build_release_index.serialize_index({"schema_version": 1, "values": [1, 2]}),
            '{"schema_version":1,"values":[1,2]}\n',
        )

    def test_release_index_requires_every_pack_for_every_target_abi(self) -> None:
        packs = {"demo": {"1.0": {"cp311": {}}}}
        with self.assertRaisesRegex(RuntimeError, "missing target ABIs"):
            build_release_index.validate_expected_pack_matrix(packs, ["demo"])
        packs["demo"]["1.0"].update({abi: {} for abi in build_release_index.TARGET_ABIS})
        build_release_index.validate_expected_pack_matrix(packs, ["demo"])
        with self.assertRaisesRegex(RuntimeError, "missing current library packs"):
            build_release_index.validate_expected_pack_matrix(packs, ["demo", "other"])

    def test_release_index_reports_every_incomplete_license_asset(self) -> None:
        assets = self.root / "assets"
        assets.mkdir()
        commit = build.git_commit_or_none(REPO_ROOT)
        for name in ("alpha", "beta"):
            stage = self.root / f"{name}-stage"
            stage.mkdir()
            metadata = {
                "name": name,
                "version": "1.0",
                "cpython_abi": "cp313",
                "staticpython_commit": commit,
                "verification": {"status": "passed"},
                "license": {"status": "missing"},
                "files": [],
            }
            (stage / "pack.json").write_text(json.dumps(metadata), encoding="utf-8")
            build.write_deterministic_zip(stage, assets / f"{name}.zip")

        with self.assertRaisesRegex(RuntimeError, r"alpha\.zip[\s\S]*beta\.zip"):
            build_release_index.build_index(
                assets,
                "xqy2006/StaticPython",
                commit,
                "runtime-tag",
                "pack-tag",
                require_all_targets=False,
                require_verified=True,
            )

    def test_release_index_rejects_pack_without_promotion_binding(self) -> None:
        assets = self.root / "binding-assets"
        runtime_stage = self.root / "binding-runtime"
        pack_stage = self.root / "binding-pack"
        (runtime_stage / "metadata").mkdir(parents=True)
        pack_stage.mkdir()
        assets.mkdir()
        commit = "d" * 40
        cpython_commit = "c" * 40
        toolchain = {
            "visual_studio_version": "17.0",
            "vscmd_version": "17.14.36",
            "vc_tools_version": "14.44.35207",
            "windows_sdk_version": "10.0.26100.0\\",
            "platform_toolset": "v143",
            "runtime_library": "MultiThreaded",
        }
        provenance = {
            "commit": cpython_commit,
            "archive_sha256": "a" * 64,
        }
        runtime_metadata = {
            "cpython_abi": "cp313",
            "cpython_version": "3.13.0",
            "runtime_abi": "staticpython-pack-v1-cp313",
            "staticpython_commit": commit,
            "verification": {"status": "passed"},
            "cpython_commit": cpython_commit,
            "cpython_tag": "v3.13.0",
            "cpython_source": provenance,
            "toolchain": toolchain,
        }
        (runtime_stage / build.RUNTIME_SDK_METADATA_RELATIVE_PATH).write_text(
            json.dumps(runtime_metadata), encoding="utf-8"
        )
        build.write_deterministic_zip(runtime_stage, assets / "runtime.zip")
        pack_metadata = {
            "schema_version": 1,
            "kind": "staticpython-library-pack",
            "name": "demo",
            "version": "1.0",
            "cpython_abi": "cp313",
            "cpython_version": "3.13.0",
            "runtime_abi": "staticpython-pack-v1-cp313",
            "staticpython_commit": commit,
            "verification": {
                "status": "passed",
                "smoke_tests": [
                    {"name": "behavior", "kind": "import", "status": "passed"}
                ],
            },
            "license": {"status": "complete"},
            "cpython_commit": cpython_commit,
            "cpython_tag": "v3.13.0",
            "cpython_source": provenance,
            "toolchain": toolchain,
            "files": [],
        }
        (pack_stage / "pack.json").write_text(
            json.dumps(pack_metadata), encoding="utf-8"
        )
        build.write_deterministic_zip(pack_stage, assets / "demo.zip")

        with self.assertRaisesRegex(RuntimeError, "incomplete or unknown verification"):
            build_release_index.build_index(
                assets,
                "xqy2006/StaticPython",
                commit,
                "runtime-tag",
                "pack-tag",
                require_all_targets=False,
                require_verified=True,
            )

    def test_release_index_requires_dependency_assets_for_the_same_abi(self) -> None:
        packs = {
            "root": {
                "1.0": {
                    "cp313": {
                        "metadata": {
                            "dependencies": ["dependency"],
                            "dependency_constraints": {"dependency": "<2"},
                        }
                    }
                }
            }
        }
        with self.assertRaisesRegex(RuntimeError, "requires unpublished pack"):
            build_release_index.validate_pack_dependency_assets(packs)
        packs["dependency"] = {
            "2.1": {"cp313": {"metadata": {"dependencies": [], "dependency_constraints": {}}}}
        }
        with self.assertRaisesRegex(RuntimeError, "no published dependency<2"):
            build_release_index.validate_pack_dependency_assets(packs)
        packs["dependency"]["1.5"] = {
            "cp313": {"metadata": {"dependencies": [], "dependency_constraints": {}}}
        }
        build_release_index.validate_pack_dependency_assets(packs)

    def test_release_index_toolchain_fingerprint_ignores_vscmd_servicing_revision(self) -> None:
        runtime = {
            "toolchain": {
                "visual_studio_version": "17.0",
                "vscmd_version": "17.14.36",
                "vc_tools_version": "14.44.35207",
                "windows_sdk_version": "10.0.26100.0\\",
                "platform_toolset": "v143",
                "runtime_library": "MultiThreaded",
            }
        }
        pack = json.loads(json.dumps(runtime))
        pack["toolchain"]["vscmd_version"] = "17.14.37"
        self.assertEqual(
            build_release_index.toolchain_abi_fingerprint(runtime),
            build_release_index.toolchain_abi_fingerprint(pack),
        )

    def test_release_index_toolchain_fingerprint_rejects_compiler_drift(self) -> None:
        runtime = {
            "toolchain": {
                "visual_studio_version": "17.0",
                "vscmd_version": "17.14.36",
                "vc_tools_version": "14.44.35207",
                "windows_sdk_version": "10.0.26100.0\\",
                "platform_toolset": "v143",
                "runtime_library": "MultiThreaded",
            }
        }
        pack = json.loads(json.dumps(runtime))
        pack["toolchain"]["vc_tools_version"] = "14.45.00000"
        self.assertNotEqual(
            build_release_index.toolchain_abi_fingerprint(runtime),
            build_release_index.toolchain_abi_fingerprint(pack),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
