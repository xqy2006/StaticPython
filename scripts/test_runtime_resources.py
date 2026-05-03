from __future__ import annotations

import importlib
import importlib.resources
import json
import os
import pkgutil
import shutil
import stat
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = REPO_ROOT
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from build import collect_runtime_resource_files, verify_runtime_resource_modules_frozen, write_runtime_resource_module


def _write(path: Path, data: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        path.write_bytes(data)
    else:
        path.write_text(data, encoding="utf-8", newline="\n")


class RuntimeResourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.lib = self.root / "Lib"
        self.lib.mkdir(parents=True, exist_ok=True)
        shutil.copy2(
            REPO_ROOT / "assets" / "overlay" / "Lib" / "_staticpython_runtime.py",
            self.lib / "_staticpython_runtime.py",
        )
        _write(self.lib / "demo_pkg" / "__init__.py", "")
        _write(
            self.lib / "demo_pkg" / "reader.py",
            textwrap.dedent(
                """
                from pathlib import Path


                def read_relative_open():
                    with open("data/config.yaml", encoding="utf-8") as handle:
                        return handle.read()


                def read_relative_pathlib():
                    return Path("data/config.yaml").read_text(encoding="utf-8")
                """
            ),
        )
        _write(self.lib / "demo_pkg" / "data" / "config.yaml", "status: ok\n")
        _write(self.lib / "demo_pkg" / "data" / "config.schema", "{\"type\":\"object\"}\n")
        _write(self.lib / "demo_pkg" / "data" / "empty.bin", b"")
        _write(self.lib / "demo_pkg" / "data" / "marker.pyi", "VALUE: int\n")
        _write(self.lib / "demo_pkg" / "data" / "ignored.py", "SHOULD_NOT_EMBED = True\n")
        _write(self.lib / "demo_pkg" / "data" / "ignored.pyc", b"\0\0ignored")
        _write(self.lib / "demo_pkg" / "data" / "shared.txt", "demo shared\n")
        _write(self.lib / "demo_pkg" / "resources" / "UTC", b"TZif-demo")
        _write(self.lib / "demo_pkg" / "build" / "ignored.json", "{}\n")
        _write(self.lib / "other_pkg" / "__init__.py", "")
        _write(
            self.lib / "other_pkg" / "reader.py",
            textwrap.dedent(
                """
                def read_relative_open():
                    with open("assets/config.yaml", encoding="utf-8") as handle:
                        return handle.read()
                """
            ),
        )
        _write(self.lib / "other_pkg" / "assets" / "config.yaml", "other: ok\n")
        _write(self.lib / "other_pkg" / "assets" / "shared.txt", "other shared\n")
        _write(self.lib / "other_pkg" / "assets" / "deep" / "data.bin", b"\x00\x01\x02")
        _write(self.root / "share" / "jupyter" / "lab" / "static" / "index.html", "<html>OK</html>")
        _write(
            self.root / "etc" / "jupyter" / "jupyter_server_config.d" / "demo.json",
            json.dumps({"ServerApp": {"jpserver_extensions": {"demo": True}}}),
        )
        self.integration = SimpleNamespace(
            materialized_paths=[
                "Lib/demo_pkg",
                "Lib/other_pkg",
                "share/jupyter/lab/static",
                "etc/jupyter/jupyter_server_config.d",
            ]
        )

        write_runtime_resource_module(self.root, [self.integration])
        shutil.rmtree(self.lib / "demo_pkg" / "data")
        shutil.rmtree(self.lib / "demo_pkg" / "resources")
        shutil.rmtree(self.lib / "demo_pkg" / "build")
        shutil.rmtree(self.lib / "other_pkg" / "assets")
        shutil.rmtree(self.root / "share")
        shutil.rmtree(self.root / "etc")

        self._old_path = list(sys.path)
        sys.path.insert(0, str(self.lib))
        for name in list(sys.modules):
            if name.startswith("_staticpython_runtime") or name in {"demo_pkg", "demo_pkg.reader", "other_pkg", "other_pkg.reader"}:
                sys.modules.pop(name, None)
        importlib.invalidate_caches()
        import _staticpython_runtime

        _staticpython_runtime.install()
        self.runtime = _staticpython_runtime

    def tearDown(self) -> None:
        try:
            self.runtime.uninstall()
        except Exception:
            pass
        sys.path[:] = self._old_path
        self.temp_dir.cleanup()
        for name in list(sys.modules):
            if name.startswith("_staticpython_runtime") or name in {"demo_pkg", "demo_pkg.reader", "other_pkg", "other_pkg.reader"}:
                sys.modules.pop(name, None)

    def test_scanner_collects_all_non_python_resources_from_materialized_roots(self) -> None:
        self.runtime.uninstall()
        fresh_root = Path(tempfile.mkdtemp())
        try:
            (fresh_root / "Lib").mkdir(parents=True, exist_ok=True)
            shutil.copytree(self.lib / "demo_pkg", fresh_root / "Lib" / "demo_pkg")
            _write(fresh_root / "Lib" / "demo_pkg" / "data" / "config.yaml", "status: ok\n")
            _write(fresh_root / "Lib" / "demo_pkg" / "data" / "marker.pyi", "VALUE: int\n")
            _write(fresh_root / "Lib" / "demo_pkg" / "data" / "empty.bin", b"")
            _write(fresh_root / "Lib" / "demo_pkg" / "data" / "ignored.py", "SHOULD_NOT_EMBED = True\n")
            _write(fresh_root / "Lib" / "demo_pkg" / "data" / "ignored.pyc", b"\0\0ignored")
            _write(fresh_root / "Lib" / "demo_pkg" / "resources" / "UTC", b"TZif-demo")
            _write(fresh_root / "Lib" / "demo_pkg" / "build" / "ignored.json", "{}\n")
            files = collect_runtime_resource_files(fresh_root, [SimpleNamespace(materialized_paths=["Lib/demo_pkg"])])
            self.assertIn("Lib/demo_pkg/data/config.yaml", files)
            self.assertIn("Lib/demo_pkg/data/marker.pyi", files)
            self.assertIn("Lib/demo_pkg/data/empty.bin", files)
            self.assertIn("Lib/demo_pkg/resources/UTC", files)
            self.assertNotIn("Lib/demo_pkg/data/ignored.py", files)
            self.assertNotIn("Lib/demo_pkg/data/ignored.pyc", files)
            self.assertNotIn("Lib/demo_pkg/build/ignored.json", files)
        finally:
            shutil.rmtree(fresh_root)
            self.runtime.install()

    def test_generated_manifest_contains_targets_children_and_suffix_indexes(self) -> None:
        resources = importlib.import_module("_staticpython_runtime_resources")
        self.assertIn("Lib/demo_pkg/data/config.yaml", resources.RESOURCE_TARGETS)
        self.assertIn("Lib/demo_pkg/data/empty.bin", resources.RESOURCE_TARGETS)
        self.assertIn("Lib/demo_pkg/data", resources.RESOURCE_CHILDREN)
        self.assertIn("config.yaml", resources.RESOURCE_BASENAME_INDEX)
        self.assertIn("data", resources.RESOURCE_DIR_BASENAME_INDEX)
        payloads = dict(resources.iter_resource_payloads())
        self.assertEqual(len(payloads), len(resources.RESOURCE_TARGETS))
        self.assertEqual(payloads["Lib/demo_pkg/data/empty.bin"], ("",))

    def test_open_pathlib_and_stat_use_virtual_resource_for_absolute_paths(self) -> None:
        config_path = self.root / "Lib" / "demo_pkg" / "data" / "config.yaml"
        self.runtime.uninstall()
        try:
            self.assertFalse(config_path.exists())
            self.assertFalse(config_path.parent.exists())
        finally:
            self.runtime.install()
        self.assertTrue(config_path.exists())
        self.assertTrue(config_path.is_file())
        self.assertEqual(config_path.read_text(encoding="utf-8"), "status: ok\n")
        self.assertEqual(config_path.read_bytes(), b"status: ok\n")
        self.assertEqual((self.root / "Lib" / "demo_pkg" / "data" / "empty.bin").read_bytes(), b"")
        result = os.stat(config_path)
        self.assertTrue(stat.S_ISREG(result.st_mode))
        self.assertEqual(result.st_size, len(b"status: ok\n"))
        other_result = os.stat(self.root / "Lib" / "demo_pkg" / "data" / "config.schema")
        self.assertNotEqual(result.st_ino, other_result.st_ino)
        self.assertFalse(
            os.path.samefile(
                config_path,
                self.root / "Lib" / "demo_pkg" / "data" / "config.schema",
            )
        )

    def test_virtual_directories_support_exists_listdir_scandir_and_iterdir(self) -> None:
        data_dir = self.root / "Lib" / "demo_pkg" / "data"
        self.assertTrue(data_dir.exists())
        self.assertTrue(data_dir.is_dir())
        self.assertEqual(
            os.listdir(data_dir),
            ["config.schema", "config.yaml", "empty.bin", "marker.pyi", "shared.txt"],
        )
        self.assertEqual(
            sorted(entry.name for entry in os.scandir(data_dir)),
            ["config.schema", "config.yaml", "empty.bin", "marker.pyi", "shared.txt"],
        )
        self.assertEqual(
            sorted(path.name for path in data_dir.iterdir()),
            ["config.schema", "config.yaml", "empty.bin", "marker.pyi", "shared.txt"],
        )
        walked = list(os.walk(self.root / "Lib" / "demo_pkg"))
        walked_by_root = {Path(root).as_posix(): (sorted(dirs), sorted(files)) for root, dirs, files in walked}
        package_root = (self.root / "Lib" / "demo_pkg").as_posix()
        data_root = (self.root / "Lib" / "demo_pkg" / "data").as_posix()
        self.assertIn("data", walked_by_root[package_root][0])
        self.assertIn("resources", walked_by_root[package_root][0])
        self.assertEqual(
            walked_by_root[data_root][1],
            ["config.schema", "config.yaml", "empty.bin", "marker.pyi", "shared.txt"],
        )

    def test_virtual_directory_listing_merges_with_real_disk_entries(self) -> None:
        data_dir = self.root / "Lib" / "demo_pkg" / "data"
        data_dir.mkdir(parents=True)
        _write(data_dir / "real-only.txt", "real\n")
        self.assertEqual(
            os.listdir(data_dir),
            ["config.schema", "config.yaml", "empty.bin", "marker.pyi", "real-only.txt", "shared.txt"],
        )
        self.assertEqual((data_dir / "real-only.txt").read_text(encoding="utf-8"), "real\n")
        self.assertEqual((data_dir / "config.yaml").read_text(encoding="utf-8"), "status: ok\n")

    def test_share_and_etc_paths_are_available_after_disk_files_are_removed(self) -> None:
        index_path = self.root / "share" / "jupyter" / "lab" / "static" / "index.html"
        config_path = self.root / "etc" / "jupyter" / "jupyter_server_config.d" / "demo.json"
        self.assertEqual(index_path.read_text(encoding="utf-8"), "<html>OK</html>")
        self.assertTrue(json.loads(config_path.read_text(encoding="utf-8"))["ServerApp"]["jpserver_extensions"]["demo"])

    def test_suffix_matching_handles_unknown_prefixes(self) -> None:
        unknown_prefix = Path("Z:/unknown/install/root/demo_pkg/data/config.yaml")
        self.assertEqual(unknown_prefix.read_text(encoding="utf-8"), "status: ok\n")
        self.assertEqual(
            os.listdir("Z:/unknown/install/root/demo_pkg/data"),
            ["config.schema", "config.yaml", "empty.bin", "marker.pyi", "shared.txt"],
        )

    def test_suffix_matching_does_not_guess_between_equally_ambiguous_resources(self) -> None:
        with self.assertRaises(FileNotFoundError):
            Path("Z:/unknown/shared.txt").read_text(encoding="utf-8")
        self.assertEqual(
            Path("Z:/unknown/install/root/other_pkg/assets/shared.txt").read_text(encoding="utf-8"),
            "other shared\n",
        )

    def test_bytes_paths_and_lib_fragment_paths_are_supported(self) -> None:
        path = os.fsencode(self.root / "Lib" / "demo_pkg" / "data" / "config.yaml")
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"status: ok\n")
            self.assertTrue(handle.name.endswith(b"config.yaml") if isinstance(handle.name, bytes) else str(handle.name).endswith("config.yaml"))
        self.assertEqual(
            Path("C:/temporary/prefix/Lib/demo_pkg/data/config.yaml").read_text(encoding="utf-8"),
            "status: ok\n",
        )
        self.assertEqual(
            Path("C:/temporary/prefix/lib/DEMO_PKG/data/CONFIG.YAML").read_text(encoding="utf-8"),
            "status: ok\n",
        )

    def test_staticpython_resource_uri_reads_package_resource(self) -> None:
        with open("staticpython-resource://demo_pkg/data/config.yaml", encoding="utf-8") as handle:
            self.assertEqual(handle.read(), "status: ok\n")
        self.assertTrue(os.path.isfile("staticpython-resource://demo_pkg/data/config.yaml"))
        self.assertTrue(os.path.isdir("staticpython-resource://demo_pkg/data"))
        self.assertEqual(
            os.listdir("staticpython-resource://demo_pkg/data"),
            ["config.schema", "config.yaml", "empty.bin", "marker.pyi", "shared.txt"],
        )

    def test_relative_paths_are_resolved_from_calling_package(self) -> None:
        reader = importlib.import_module("demo_pkg.reader")
        other_reader = importlib.import_module("other_pkg.reader")
        self.assertEqual(reader.read_relative_open(), "status: ok\n")
        self.assertEqual(reader.read_relative_pathlib(), "status: ok\n")
        self.assertEqual(other_reader.read_relative_open(), "other: ok\n")

    def test_pkgutil_get_data_reads_package_relative_resources(self) -> None:
        self.assertEqual(pkgutil.get_data("demo_pkg", "data/config.yaml"), b"status: ok\n")
        self.assertEqual(pkgutil.get_data("demo_pkg", "resources/UTC"), b"TZif-demo")

    def test_importlib_resources_files_reads_virtual_package_tree(self) -> None:
        import demo_pkg

        root = importlib.resources.files(demo_pkg)
        self.assertTrue(root.joinpath("data").is_dir())
        self.assertTrue(root.joinpath("data", "config.yaml").is_file())
        self.assertEqual(root.joinpath("data", "config.yaml").read_text(encoding="utf-8"), "status: ok\n")
        self.assertEqual(root.joinpath("resources", "UTC").read_bytes(), b"TZif-demo")
        self.assertEqual(
            sorted(child.name for child in root.joinpath("data").iterdir()),
            ["config.schema", "config.yaml", "empty.bin", "marker.pyi", "shared.txt"],
        )
        with importlib.resources.as_file(root.joinpath("data", "config.yaml")) as resource_path:
            self.assertEqual(resource_path.read_text(encoding="utf-8"), "status: ok\n")

    def test_writes_are_not_redirected_to_embedded_resources(self) -> None:
        with self.assertRaises(FileNotFoundError):
            with open(self.root / "Lib" / "demo_pkg" / "data" / "config.yaml", "w", encoding="utf-8") as handle:
                handle.write("mutated")
        self.assertEqual((self.root / "Lib" / "demo_pkg" / "data" / "config.yaml").read_text(encoding="utf-8"), "status: ok\n")

    def test_open_modes_and_access_match_read_only_virtual_files(self) -> None:
        path = self.root / "Lib" / "demo_pkg" / "data" / "config.yaml"
        self.assertTrue(os.access(path, os.R_OK))
        self.assertFalse(os.access(path, os.W_OK))
        with open(path, "r", encoding="utf-8", newline="") as handle:
            self.assertEqual(handle.read(), "status: ok\n")
            self.assertTrue(str(handle.name).endswith("config.yaml"))
            self.assertEqual(handle.mode, "r")
        with open(path, "rb") as handle:
            self.assertEqual(handle.read(), b"status: ok\n")
            self.assertEqual(handle.mode, "rb")
        with self.assertRaises(FileNotFoundError):
            open(path, "a", encoding="utf-8").close()
        with self.assertRaises(FileNotFoundError):
            open(path, "x", encoding="utf-8").close()

    def test_uninstall_restores_all_monkey_patched_apis(self) -> None:
        import importlib.resources._common as common

        patched_get_data = pkgutil.get_data
        patched_from_package = common.from_package
        path = self.root / "Lib" / "demo_pkg" / "data" / "config.yaml"
        self.assertEqual(path.read_text(encoding="utf-8"), "status: ok\n")
        self.runtime.uninstall()
        try:
            self.assertIsNot(pkgutil.get_data, patched_get_data)
            self.assertIsNot(common.from_package, patched_from_package)
            self.assertFalse(path.exists())
            with self.assertRaises(FileNotFoundError):
                path.read_text(encoding="utf-8")
            self.runtime.install()
            self.assertEqual(path.read_text(encoding="utf-8"), "status: ok\n")
        finally:
            self.runtime.install()

    def test_empty_resource_table_installs_without_intercepting_missing_files(self) -> None:
        self.runtime.uninstall()
        fresh_root = Path(tempfile.mkdtemp())
        old_path = list(sys.path)
        try:
            lib_dir = fresh_root / "Lib"
            lib_dir.mkdir(parents=True)
            shutil.copy2(REPO_ROOT / "assets" / "overlay" / "Lib" / "_staticpython_runtime.py", lib_dir / "_staticpython_runtime.py")
            write_runtime_resource_module(fresh_root, [SimpleNamespace(materialized_paths=[])])
            sys.path.insert(0, str(lib_dir))
            for name in list(sys.modules):
                if name.startswith("_staticpython_runtime"):
                    sys.modules.pop(name, None)
            importlib.invalidate_caches()
            empty_runtime = importlib.import_module("_staticpython_runtime")
            empty_runtime.install()
            with self.assertRaises(FileNotFoundError):
                (fresh_root / "Lib" / "missing.dat").read_text(encoding="utf-8")
            empty_runtime.uninstall()
        finally:
            sys.path[:] = old_path
            for name in list(sys.modules):
                if name.startswith("_staticpython_runtime"):
                    sys.modules.pop(name, None)
            shutil.rmtree(fresh_root)
            self.runtime.install()

    def test_generated_resources_are_sharded_and_deduplicate_identical_payloads(self) -> None:
        self.runtime.uninstall()
        old_limit = __import__("build").RUNTIME_RESOURCE_SHARD_TEXT_BYTES
        fresh_root = Path(tempfile.mkdtemp())
        old_path = list(sys.path)
        try:
            build_module = __import__("build")
            build_module.RUNTIME_RESOURCE_SHARD_TEXT_BYTES = 8
            _write(fresh_root / "Lib" / "pkg" / "one.dat", b"alpha")
            _write(fresh_root / "Lib" / "pkg" / "two.dat", b"beta")
            _write(fresh_root / "Lib" / "pkg" / "copy.dat", b"alpha")
            write_runtime_resource_module(fresh_root, [SimpleNamespace(materialized_paths=["Lib/pkg"])])
            sys.path.insert(0, str(fresh_root / "Lib"))
            for name in list(sys.modules):
                if name.startswith("_staticpython_runtime_resources"):
                    sys.modules.pop(name, None)
            resources = importlib.import_module("_staticpython_runtime_resources")
            self.assertGreaterEqual(len(resources.RESOURCE_SHARDS), 2)
            payloads = dict(resources.iter_resource_payloads())
            self.assertEqual(payloads["Lib/pkg/one.dat"], payloads["Lib/pkg/copy.dat"])
            one_module, one_blob = resources.RESOURCE_TARGETS["Lib/pkg/one.dat"]
            copy_module, copy_blob = resources.RESOURCE_TARGETS["Lib/pkg/copy.dat"]
            self.assertEqual((one_module, one_blob), (copy_module, copy_blob))
        finally:
            __import__("build").RUNTIME_RESOURCE_SHARD_TEXT_BYTES = old_limit
            sys.path[:] = old_path
            for name in list(sys.modules):
                if name.startswith("_staticpython_runtime_resources"):
                    sys.modules.pop(name, None)
            shutil.rmtree(fresh_root)
            self.runtime.install()

    def test_freeze_verifier_reports_missing_runtime_resource_frozen_modules(self) -> None:
        self.runtime.uninstall()
        fresh_root = Path(tempfile.mkdtemp())
        try:
            _write(fresh_root / "Lib" / "_staticpython_runtime_resources.py", "# generated\n")
            _write(fresh_root / "Lib" / "_staticpython_runtime_resources_shard_000.py", "# shard\n")
            _write(
                fresh_root / "Python" / "frozen.c",
                '{"_staticpython_runtime", NULL},\n',
            )
            with self.assertRaisesRegex(RuntimeError, "missing frozen headers"):
                verify_runtime_resource_modules_frozen(fresh_root)

            _write(fresh_root / "Python" / "frozen_modules" / "_staticpython_runtime.h", b"header")
            _write(fresh_root / "Python" / "frozen_modules" / "_staticpython_runtime_resources.h", b"header")
            _write(fresh_root / "Python" / "frozen_modules" / "_staticpython_runtime_resources_shard_000.h", b"header")
            with self.assertRaisesRegex(RuntimeError, "missing frozen registry entries"):
                verify_runtime_resource_modules_frozen(fresh_root)

            _write(
                fresh_root / "Python" / "frozen.c",
                "\n".join(
                    [
                        '{"_staticpython_runtime", NULL},',
                        '{"_staticpython_runtime_resources", NULL},',
                        '{"_staticpython_runtime_resources_shard_000", NULL},',
                    ]
                ),
            )
            verify_runtime_resource_modules_frozen(fresh_root)
        finally:
            shutil.rmtree(fresh_root)
            self.runtime.install()


if __name__ == "__main__":
    unittest.main(verbosity=2)
