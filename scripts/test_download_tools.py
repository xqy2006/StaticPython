from __future__ import annotations

import hashlib
import http.client
import io
import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from zipfile import ZipFile

import tools


REPO_ROOT = Path(__file__).resolve().parents[1]
PYFLTK_SETUP_SPEC = importlib.util.spec_from_file_location(
    "staticpython_test_pyfltk_setup",
    REPO_ROOT / "Lib" / "pyfltk" / "setup.py",
)
if PYFLTK_SETUP_SPEC is None or PYFLTK_SETUP_SPEC.loader is None:
    raise RuntimeError("could not load pyfltk setup module")
PYFLTK_SETUP = importlib.util.module_from_spec(PYFLTK_SETUP_SPEC)
PYFLTK_SETUP_SPEC.loader.exec_module(PYFLTK_SETUP)


def _zip_bytes(root: Path, name: str, content: str) -> bytes:
    archive = root / f"{name}.zip"
    with ZipFile(archive, "w") as output:
        output.writestr(f"{name}/payload.txt", content)
    return archive.read_bytes()


class DownloadFirstAvailableTests(unittest.TestCase):
    def test_download_file_retries_transient_disconnects_atomically(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "download.zip"
            temporary = Path(str(destination) + ".tmp")
            messages: list[str] = []
            with (
                mock.patch.object(
                    tools,
                    "urlopen",
                    side_effect=[
                        http.client.RemoteDisconnected("first disconnect"),
                        tools.URLError("second disconnect"),
                        io.BytesIO(b"archive payload"),
                    ],
                ) as urlopen,
                mock.patch.object(tools.time, "sleep") as sleep,
            ):
                tools.download_file(
                    messages.append,
                    "https://example.invalid/archive.zip",
                    destination,
                )

            self.assertEqual(destination.read_bytes(), b"archive payload")
            self.assertFalse(temporary.exists())
            self.assertEqual(urlopen.call_count, 3)
            sleep.assert_has_calls([mock.call(1), mock.call(2)])

    def test_download_file_exhausts_retries_without_partial_output(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            destination = Path(temp_dir) / "download.zip"
            temporary = Path(str(destination) + ".tmp")
            temporary.write_bytes(b"stale partial download")
            with (
                mock.patch.object(
                    tools,
                    "urlopen",
                    side_effect=http.client.RemoteDisconnected("disconnect"),
                ) as urlopen,
                mock.patch.object(tools.time, "sleep") as sleep,
                self.assertRaises(http.client.RemoteDisconnected),
            ):
                tools.download_file(
                    lambda _message: None,
                    "https://example.invalid/archive.zip",
                    destination,
                )

            self.assertFalse(destination.exists())
            self.assertFalse(temporary.exists())
            self.assertEqual(urlopen.call_count, tools.DOWNLOAD_MAX_ATTEMPTS)
            sleep.assert_has_calls([mock.call(1), mock.call(2), mock.call(4)])

    def test_valid_cached_archive_must_match_expected_sha256(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            expected = _zip_bytes(root, "expected", "trusted")
            destination = root / "download.zip"
            destination.write_bytes(expected)

            with mock.patch.object(tools, "download_file") as download:
                source = tools.download_first_available(
                    lambda _message: None,
                    ["https://example.invalid/archive.zip"],
                    destination,
                    expected_sha256=hashlib.sha256(expected).hexdigest(),
                )

            self.assertEqual(source, str(destination))
            download.assert_not_called()

    def test_hash_mismatch_falls_through_to_next_mirror(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            untrusted = _zip_bytes(root, "untrusted", "wrong")
            trusted = _zip_bytes(root, "trusted", "right")
            destination = root / "download.zip"
            destination.write_bytes(untrusted)
            urls = ["https://first.invalid/archive.zip", "https://second.invalid/archive.zip"]

            def fake_download(_log, url, target, *, force=False):
                self.assertTrue(force)
                target.write_bytes(trusted if url == urls[1] else untrusted)

            with mock.patch.object(tools, "download_file", side_effect=fake_download) as download:
                source = tools.download_first_available(
                    lambda _message: None,
                    urls,
                    destination,
                    expected_sha256=hashlib.sha256(trusted).hexdigest(),
                )

            self.assertEqual(source, urls[1])
            self.assertEqual(destination.read_bytes(), trusted)
            self.assertEqual(download.call_count, 2)

    def test_invalid_expected_sha256_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            payload = _zip_bytes(root, "payload", "data")
            destination = root / "download.zip"
            destination.write_bytes(payload)

            with self.assertRaisesRegex(ValueError, "invalid SHA-256"):
                tools.download_first_available(
                    lambda _message: None,
                    ["https://example.invalid/archive.zip"],
                    destination,
                    expected_sha256="not-a-digest",
                )


class PyFltkDownloadTests(unittest.TestCase):
    def test_swigwin_uses_two_mirrors_and_a_fixed_digest(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class Context:
                work_cache_root = root / "work"
                download_cache_root = root / "downloads"

                @staticmethod
                def log(_message: str) -> None:
                    pass

            def fake_download(_log, urls, destination, *, expected_sha256=None):
                self.assertEqual(
                    urls,
                    [
                        "https://prdownloads.sourceforge.net/swig/swigwin-4.3.1.zip",
                        "https://downloads.sourceforge.net/project/swig/swigwin/"
                        "swigwin-4.3.1/swigwin-4.3.1.zip",
                    ],
                )
                self.assertEqual(expected_sha256, PYFLTK_SETUP.SWIGWIN_SHA256)
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.touch()
                return urls[0]

            def fake_extract(_log, _archive, destination, *, final_name=None):
                tool_dir = destination / str(final_name)
                tool_dir.mkdir(parents=True, exist_ok=True)
                (tool_dir / "swig.exe").touch()

            with (
                mock.patch.object(
                    PYFLTK_SETUP,
                    "download_first_available",
                    side_effect=fake_download,
                ),
                mock.patch.object(
                    PYFLTK_SETUP,
                    "extract_source_archive",
                    side_effect=fake_extract,
                ),
            ):
                swig_exe = PYFLTK_SETUP.ensure_swigwin(Context())

            self.assertTrue(swig_exe.is_file())
            self.assertEqual(
                PYFLTK_SETUP.SWIGWIN_SHA256,
                "7ea5197c557af20b2f7780ffcfe803bbe0e2009f5846874112aea37e5f693417",
            )


if __name__ == "__main__":
    unittest.main()
