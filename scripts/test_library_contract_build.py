from __future__ import annotations

import hashlib
import importlib.util
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zipfile import ZIP_DEFLATED, ZipFile


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SPEC = importlib.util.spec_from_file_location(
    "staticpython_library_contract_build",
    REPO_ROOT / "scripts" / "library_contract_build.py",
)
assert SPEC is not None and SPEC.loader is not None
contract_build = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract_build)
import pack_evidence


def _pack_metadata(payload: bytes = b"payload") -> dict:
    return {
        "schema_version": 1,
        "kind": "staticpython-library-pack",
        "name": "demo",
        "version": "1.0",
        "source_provider": "pypi",
        "source_tree_sha256": "b" * 64,
        "cpython_version": "3.13.14",
        "cpython_abi": "cp313",
        "runtime_abi": "staticpython-pack-v1-cp313",
        "platform": "x64",
        "license": {"status": "complete"},
        "verification": {
            "status": "passed",
            "smoke_tests": [
                {"name": "behavior", "kind": "import", "status": "passed"}
            ],
        },
        "files": [
            {
                "path": "src/payload.bin",
                "size": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        ],
    }


def _bind_metadata(metadata: dict) -> None:
    metadata["verification"].update(
        {
            "provisional_pack_sha256": "a" * 64,
            "payload_manifest_sha256": pack_evidence.pack_payload_manifest_sha256(
                metadata
            ),
            "metadata_without_verification_sha256": (
                pack_evidence.pack_metadata_without_verification_sha256(metadata)
            ),
        }
    )


def _write_pack(path: Path, *, extra_name: str | None = None) -> None:
    payload = b"payload"
    metadata = _pack_metadata(payload)
    if extra_name is not None:
        extra_payload = b"native"
        metadata["files"].append(
            {
                "path": extra_name,
                "size": len(extra_payload),
                "sha256": hashlib.sha256(extra_payload).hexdigest(),
            }
        )
    _bind_metadata(metadata)
    with ZipFile(path, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("src/payload.bin", payload)
        archive.writestr("pack.json", json.dumps(metadata))
        if extra_name is not None:
            archive.writestr(extra_name, extra_payload)


class LibraryContractBuildTests(unittest.TestCase):
    def test_stage_source_uses_locked_pypi_archive_and_hash(self) -> None:
        payload = b"source archive"
        expected = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.object(
                contract_build,
                "urlopen",
                return_value=io.BytesIO(payload),
            ):
                archive = contract_build.stage_source_archive(
                    root,
                    "Demo_Project",
                    "1.0",
                    "demo-1.0.tar.gz",
                    "https://files.pythonhosted.org/packages/demo-1.0.tar.gz",
                    expected,
                )
            self.assertEqual(
                archive,
                root / "pypi" / "demo-project" / "1.0" / "demo-1.0.tar.gz",
            )
            self.assertEqual(archive.read_bytes(), payload)
            self.assertEqual(
                contract_build.verify_source_archive(
                    root,
                    "Demo_Project",
                    "1.0",
                    "demo-1.0.tar.gz",
                    expected,
                ),
                archive,
            )

    def test_source_cache_rejects_an_unlocked_second_artifact(self) -> None:
        payload = b"source archive"
        expected = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            archive = contract_build.source_archive_path(
                root,
                "demo",
                "1.0",
                "demo-1.0.tar.gz",
            )
            archive.parent.mkdir(parents=True)
            archive.write_bytes(payload)
            (archive.parent / "fallback.whl").write_bytes(b"fallback")
            with self.assertRaisesRegex(RuntimeError, "outside the locked contract"):
                contract_build.verify_source_archive(
                    root,
                    "demo",
                    "1.0",
                    archive.name,
                    expected,
                )

    def test_stage_source_retries_transient_download_failure(self) -> None:
        payload = b"source archive"
        expected = hashlib.sha256(payload).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            with mock.patch.object(
                contract_build,
                "urlopen",
                side_effect=[OSError("transient"), io.BytesIO(payload)],
            ) as open_mock, mock.patch.object(contract_build.time, "sleep") as sleep_mock:
                archive = contract_build.stage_source_archive(
                    Path(temporary),
                    "demo",
                    "1.0",
                    "demo-1.0.tar.gz",
                    "https://files.pythonhosted.org/packages/demo-1.0.tar.gz",
                    expected,
                )
            self.assertTrue(archive.is_file())
            self.assertEqual(open_mock.call_count, 2)
            sleep_mock.assert_called_once_with(1)

    def test_verified_pack_requires_metadata_smokes_license_and_static_contents(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack = root / "demo.zip"
            _write_pack(pack)
            self.assertEqual(
                contract_build.verify_pack(root, "demo", "1.0", "3.13.14"),
                pack,
            )

    def test_pack_rejects_dynamic_native_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            _write_pack(root / "demo.zip", extra_name="lib/demo.pyd")
            with self.assertRaisesRegex(RuntimeError, "dynamic native artifacts"):
                contract_build.verify_pack(root, "demo", "1.0", "3.13.14")

    def test_pack_rejects_missing_promotion_binding(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            pack = root / "demo.zip"
            _write_pack(pack)
            with ZipFile(pack) as archive:
                payload = archive.read("src/payload.bin")
                metadata = json.loads(archive.read("pack.json"))
            metadata["verification"].pop("provisional_pack_sha256")
            with ZipFile(pack, "w", compression=ZIP_DEFLATED) as archive:
                archive.writestr("src/payload.bin", payload)
                archive.writestr("pack.json", json.dumps(metadata))
            with self.assertRaisesRegex(RuntimeError, "incomplete or unknown"):
                contract_build.verify_pack(root, "demo", "1.0", "3.13.14")

    def test_pe_audit_allows_system_dlls_and_rejects_vc_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            executable = root / "python.exe"
            executable.write_bytes(b"MZ")
            system32 = root / "System32"
            system32.mkdir()
            (system32 / "KERNEL32.dll").write_bytes(b"system")
            good_output = "Image has the following dependencies:\n    KERNEL32.dll\n    api-ms-win-core-file-l1-1-0.dll\n"
            with mock.patch.object(
                contract_build.subprocess,
                "run",
                return_value=mock.Mock(returncode=0, stdout=good_output, stderr=""),
            ):
                dependencies = contract_build.audit_pe_dependencies(
                    executable,
                    system_directory=system32,
                )
            self.assertEqual(
                dependencies,
                ["api-ms-win-core-file-l1-1-0.dll", "KERNEL32.dll"],
            )

            bad_output = "Image has the following dependencies:\n    VCRUNTIME140.dll\n"
            (system32 / "VCRUNTIME140.dll").write_bytes(b"forbidden")
            with mock.patch.object(
                contract_build.subprocess,
                "run",
                return_value=mock.Mock(returncode=0, stdout=bad_output, stderr=""),
            ):
                with self.assertRaisesRegex(RuntimeError, "VCRUNTIME140.dll"):
                    contract_build.audit_pe_dependencies(
                        executable,
                        system_directory=system32,
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
