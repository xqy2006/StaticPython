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

PYZMQ_SETUP_SPEC = importlib.util.spec_from_file_location(
    "staticpython_test_pyzmq_setup",
    REPO_ROOT / "Lib" / "pyzmq" / "setup.py",
)
if PYZMQ_SETUP_SPEC is None or PYZMQ_SETUP_SPEC.loader is None:
    raise RuntimeError("could not load pyzmq setup module")
PYZMQ_SETUP = importlib.util.module_from_spec(PYZMQ_SETUP_SPEC)
PYZMQ_SETUP_SPEC.loader.exec_module(PYZMQ_SETUP)

MATPLOTLIB_SETUP_SPEC = importlib.util.spec_from_file_location(
    "staticpython_test_matplotlib_setup",
    REPO_ROOT / "Lib" / "matplotlib" / "setup.py",
)
if MATPLOTLIB_SETUP_SPEC is None or MATPLOTLIB_SETUP_SPEC.loader is None:
    raise RuntimeError("could not load matplotlib setup module")
MATPLOTLIB_SETUP = importlib.util.module_from_spec(MATPLOTLIB_SETUP_SPEC)
MATPLOTLIB_SETUP_SPEC.loader.exec_module(MATPLOTLIB_SETUP)

DEARPYGUI_SETUP_SPEC = importlib.util.spec_from_file_location(
    "staticpython_test_dearpygui_setup",
    REPO_ROOT / "Lib" / "dearpygui" / "setup.py",
)
if DEARPYGUI_SETUP_SPEC is None or DEARPYGUI_SETUP_SPEC.loader is None:
    raise RuntimeError("could not load DearPyGui setup module")
DEARPYGUI_SETUP = importlib.util.module_from_spec(DEARPYGUI_SETUP_SPEC)
DEARPYGUI_SETUP_SPEC.loader.exec_module(DEARPYGUI_SETUP)

LIBFFI_SETUP_SPEC = importlib.util.spec_from_file_location(
    "staticpython_test_libffi_setup",
    REPO_ROOT / "Core" / "libffi" / "setup.py",
)
if LIBFFI_SETUP_SPEC is None or LIBFFI_SETUP_SPEC.loader is None:
    raise RuntimeError("could not load libffi setup module")
LIBFFI_SETUP = importlib.util.module_from_spec(LIBFFI_SETUP_SPEC)
LIBFFI_SETUP_SPEC.loader.exec_module(LIBFFI_SETUP)

OPENSSL_SETUP_SPEC = importlib.util.spec_from_file_location(
    "staticpython_test_openssl_setup",
    REPO_ROOT / "Core" / "openssl" / "setup.py",
)
if OPENSSL_SETUP_SPEC is None or OPENSSL_SETUP_SPEC.loader is None:
    raise RuntimeError("could not load OpenSSL setup module")
OPENSSL_SETUP = importlib.util.module_from_spec(OPENSSL_SETUP_SPEC)
OPENSSL_SETUP_SPEC.loader.exec_module(OPENSSL_SETUP)


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
    def test_fltk_uses_github_and_codeload_mirrors(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class Context:
                source_root = root / "source"
                download_cache_root = root / "downloads"

                @staticmethod
                def log(_message: str) -> None:
                    pass

            def fake_download(_log, urls, destination, *, expected_sha256=None):
                self.assertIsNone(expected_sha256)
                self.assertEqual(
                    urls,
                    [
                        "https://github.com/fltk/fltk/archive/refs/tags/release-1.4.5.zip",
                        "https://codeload.github.com/fltk/fltk/zip/refs/tags/release-1.4.5",
                    ],
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.touch()
                return urls[1]

            def fake_extract(_log, _archive, destination, *, final_name=None):
                source_dir = destination / str(final_name)
                (source_dir / "FL").mkdir(parents=True)
                (source_dir / "FL" / "Fl.H").touch()

            with (
                mock.patch.object(PYFLTK_SETUP, "download_first_available", side_effect=fake_download),
                mock.patch.object(PYFLTK_SETUP, "extract_source_archive", side_effect=fake_extract),
            ):
                source_dir = PYFLTK_SETUP.ensure_fltk_source(Context())

            self.assertTrue((source_dir / "FL" / "Fl.H").is_file())

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


class PyZmqDownloadTests(unittest.TestCase):
    def test_native_dependencies_have_independent_codeload_mirrors(self) -> None:
        self.assertEqual(
            PYZMQ_SETUP.libsodium_archive_urls("1.0.20"),
            [
                "https://github.com/jedisct1/libsodium/releases/download/"
                "1.0.20-RELEASE/libsodium-1.0.20.tar.gz",
                "https://codeload.github.com/jedisct1/libsodium/tar.gz/"
                "refs/tags/1.0.20-RELEASE",
                "https://download.libsodium.org/libsodium/releases/"
                "libsodium-1.0.20.tar.gz",
            ],
        )
        self.assertEqual(
            PYZMQ_SETUP.libsodium_archive_urls("1.0.22-stable"),
            [
                "https://github.com/jedisct1/libsodium/releases/download/"
                "1.0.22-RELEASE/libsodium-1.0.22.tar.gz",
                "https://codeload.github.com/jedisct1/libsodium/tar.gz/"
                "refs/tags/1.0.22-RELEASE",
                "https://download.libsodium.org/libsodium/releases/"
                "libsodium-1.0.22-stable.tar.gz",
            ],
        )
        self.assertEqual(
            PYZMQ_SETUP.LIBZMQ_CODELOAD_URL_TEMPLATE.format(version="4.3.5"),
            "https://codeload.github.com/zeromq/libzmq/tar.gz/refs/tags/v4.3.5",
        )


class NativeDependencyMirrorTests(unittest.TestCase):
    def test_openssl_prefers_codeload_for_every_target_version(self) -> None:
        for version in ("3.0.15", "3.0.16", "3.0.21", "3.5.7"):
            with self.subTest(version=version):
                self.assertEqual(
                    OPENSSL_SETUP.openssl_archive_urls(version),
                    [
                        "https://codeload.github.com/openssl/openssl/"
                        f"tar.gz/refs/tags/openssl-{version}",
                        f"https://www.openssl.org/source/openssl-{version}.tar.gz",
                        "https://github.com/openssl/openssl/archive/refs/tags/"
                        f"openssl-{version}.tar.gz",
                    ],
                )

    def test_openssl_codeload_archive_must_contain_configure(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class Context:
                source_root = root / "source"
                download_cache_root = root / "downloads"

                @staticmethod
                def log(_message: str) -> None:
                    pass

            def fake_download(_log, urls, destination, *, expected_sha256=None):
                self.assertIsNone(expected_sha256)
                self.assertEqual(urls[0], OPENSSL_SETUP.openssl_archive_urls("3.5.7")[0])
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.touch()
                return urls[0]

            def fake_extract(_log, _archive, destination, *, final_name=None):
                source_dir = destination / str(final_name)
                source_dir.mkdir(parents=True)
                (source_dir / "Configure").touch()

            with (
                mock.patch.object(OPENSSL_SETUP, "download_first_available", side_effect=fake_download),
                mock.patch.object(OPENSSL_SETUP, "extract_source_archive", side_effect=fake_extract),
            ):
                source_dir = OPENSSL_SETUP.ensure_openssl_source(Context(), "3.5.7")

            self.assertTrue((source_dir / "Configure").is_file())

    def test_libffi_uses_hash_pinned_byte_identical_release_mirror(self) -> None:
        self.assertEqual(
            LIBFFI_SETUP.libffi_archive_urls("3.4.4"),
            [
                "https://github.com/libffi/libffi/releases/download/v3.4.4/libffi-3.4.4.tar.gz",
                "https://deb.debian.org/debian/pool/main/libf/libffi/libffi_3.4.4.orig.tar.gz",
            ],
        )
        self.assertEqual(
            LIBFFI_SETUP.libffi_archive_sha256("3.4.4"),
            "d66c56ad259a82cf2a9dfc408b32bf5da52371500b84745f7fb8b645712df676",
        )
        with self.assertRaisesRegex(RuntimeError, "no reviewed release archive SHA-256"):
            LIBFFI_SETUP.libffi_archive_sha256("9.9.9")

    def test_libffi_download_requires_release_generated_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)

            class Context:
                source_root = root / "source"
                download_cache_root = root / "downloads"

                @staticmethod
                def log(_message: str) -> None:
                    pass

            def fake_download(_log, urls, destination, *, expected_sha256=None):
                self.assertEqual(urls, LIBFFI_SETUP.libffi_archive_urls("3.4.4"))
                self.assertEqual(expected_sha256, LIBFFI_SETUP.libffi_archive_sha256("3.4.4"))
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.touch()
                return urls[1]

            def fake_extract(_log, _archive, destination, *, final_name=None):
                source_dir = destination / str(final_name)
                (source_dir / "include").mkdir(parents=True)
                (source_dir / "src" / "x86").mkdir(parents=True)
                (source_dir / "fficonfig.h.in").touch()
                (source_dir / "include" / "ffi.h.in").touch()
                (source_dir / "src" / "x86" / "ffiw64.c").touch()

            with (
                mock.patch.object(LIBFFI_SETUP, "download_first_available", side_effect=fake_download),
                mock.patch.object(LIBFFI_SETUP, "extract_source_archive", side_effect=fake_extract),
            ):
                source_dir = LIBFFI_SETUP.ensure_libffi_source(Context(), "3.4.4")

            self.assertTrue((source_dir / "fficonfig.h.in").is_file())

    def test_matplotlib_sdl_and_qhull_have_codeload_fallbacks(self) -> None:
        source = (REPO_ROOT / "Lib" / "matplotlib" / "setup.py").read_text(encoding="utf-8")
        self.assertIn(
            'f"https://codeload.github.com/libsdl-org/SDL/zip/refs/tags/release-{version}"',
            source,
        )
        self.assertIn(
            'f"https://codeload.github.com/qhull/qhull/tar.gz/refs/tags/v{QHULL_VERSION}"',
            source,
        )

    def test_dearpygui_submodules_have_codeload_fallbacks(self) -> None:
        for entry in DEARPYGUI_SETUP.DEARPYGUI_SUBMODULES:
            with self.subTest(name=entry["name"]):
                self.assertTrue(
                    any(url.startswith("https://codeload.github.com/") for url in entry["urls"])
                )


if __name__ == "__main__":
    unittest.main()
