from __future__ import annotations

import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import libs  # noqa: E402


def load_integration(name: str):
    path = REPO_ROOT / "Lib" / name / "setup.py"
    spec = importlib.util.spec_from_file_location(
        f"staticpython_history_compatibility_{name}",
        path,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def hook_context(source_root: Path) -> libs.LibraryHookContext:
    return libs.LibraryHookContext(
        repo_root=REPO_ROOT,
        source_root=source_root,
        version_info=(3, 12, 0),
        version_mm="3.12",
        version_full="3.12.0",
        download_cache_root=source_root / "downloads",
        work_cache_root=source_root / "work",
        asset_overlay_root=REPO_ROOT / "assets" / "overlay",
        log=lambda _message: None,
    )


class HistoryCompatibilityPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.notebook = load_integration("notebook")
        cls.referencing = load_integration("referencing")
        cls.specifications = load_integration("jsonschema_specifications")
        cls.rpds = load_integration("rpds")

    def test_notebook_legacy_distutils_patch_is_strict_and_self_describing(
        self,
    ) -> None:
        legacy = (
            "from distutils.version import LooseVersion\n\n"
            "def check_version(v, check):\n"
            "    try:\n"
            "        return LooseVersion(v) >= LooseVersion(check)\n"
            "    except TypeError:\n"
            "        return True\n\n\n"
            "def _check_pid_win32(pid):\n"
            "    return bool(pid)\n"
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = root / "Lib" / "notebook" / "utils.py"
            path.parent.mkdir(parents=True)
            path.write_text(legacy, encoding="utf-8")
            self.notebook.patch_legacy_distutils_version(hook_context(root))
            patched = path.read_text(encoding="utf-8")
            self.assertNotIn("distutils", patched)
            self.assertNotIn("LooseVersion", patched)
            self.assertIn(
                "from packaging.version import InvalidVersion, Version", patched
            )
            self.assertIn("return Version(v) >= Version(check)", patched)
            compile(patched, str(path), "exec")

            path.write_text(
                legacy.replace("def check_version", "def version_is_new_enough"),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(RuntimeError, "expected function not found"):
                self.notebook.patch_legacy_distutils_version(hook_context(root))

        integration = self.notebook.LIBRARY_INTEGRATION
        self.assertIn("packaging", integration.dependencies)
        self.assertEqual(
            integration.post_patch_hooks[0],
            self.notebook.patch_legacy_distutils_version,
        )

    def test_notebook_7_without_legacy_utils_is_an_explicit_noop(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            self.notebook.patch_legacy_distutils_version(hook_context(root))
            self.assertFalse((root / "Lib" / "notebook" / "utils.py").exists())

    def test_jsonschema_specification_resources_are_embedded(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            package = root / "Lib" / "jsonschema_specifications"
            schemas = package / "schemas" / "draft202012"
            schemas.mkdir(parents=True)
            (schemas / "metaschema.json").write_text(
                json.dumps(
                    {
                        "$schema": "https://json-schema.org/draft/2020-12/schema",
                        "$id": "https://json-schema.org/draft/2020-12/schema",
                    }
                ),
                encoding="utf-8",
            )
            (package / "_core.py").write_text(
                "import json\n"
                "from importlib.resources import files\n"
                "from referencing import Resource\n\n"
                "def _schemas():\n"
                "    for path in files(__package__).joinpath('schemas').iterdir():\n"
                "        yield Resource.from_contents(json.loads(path.read_text()))\n",
                encoding="utf-8",
            )
            self.specifications.embed_jsonschema_specifications(hook_context(root))
            embedded = (package / "_static_schemas.py").read_text(encoding="utf-8")
            core = (package / "_core.py").read_text(encoding="utf-8")
            self.assertIn("draft202012/metaschema.json", embedded)
            self.assertIn("_STATICPYTHON_SCHEMAS", core)
            self.assertNotIn("files(__package__).joinpath", core)
            compile(embedded, str(package / "_static_schemas.py"), "exec")
            compile(core, str(package / "_core.py"), "exec")

    def test_dependency_pack_contracts_close_jsonschema_418_plus(self) -> None:
        referencing = self.referencing.LIBRARY_INTEGRATION
        specifications = self.specifications.LIBRARY_INTEGRATION
        rpds = self.rpds.LIBRARY_INTEGRATION
        self.assertEqual(referencing.release_version, "0.37.0")
        self.assertEqual(specifications.project_name, "jsonschema-specifications")
        self.assertEqual(rpds.project_name, "rpds-py")
        self.assertEqual(
            rpds.builtin_module_registrations,
            [{"name": "rpds", "pyinit": "PyInit_rpds", "library": "rpds.lib"}],
        )
        self.assertIn("rpds.lib", rpds.python_link_dependencies_release_x64)
        self.assertEqual(
            rpds.patch_rules[0]["replacements"][0]["new"], 'crate-type = ["staticlib"]'
        )
        self.assertEqual(
            rpds.source_archive_sha256_by_version["2026.6.3"],
            "1cebd1337c242e4ec2293e541f712b2da849b29f48f0c293684b71c0632625d4",
        )

        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        historical = config["profiles"]["full"]["historical_library_contract_libraries"]
        self.assertTrue(
            {"jsonschema_specifications", "referencing", "rpds"} <= set(historical)
        )

    def test_rpds_pyo3_config_and_history_workflow_are_pinned(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            path = self.rpds._write_pyo3_config(hook_context(root))
            self.assertEqual(
                path.read_text(encoding="utf-8").splitlines(),
                [
                    "implementation=CPython",
                    "version=3.12",
                    "shared=false",
                    "abi3=false",
                    "pointer_width=64",
                    "build_flags=",
                    "lib_dir=C:/staticpython/no-python-import-library",
                    "suppress_build_script_link_lines=true",
                ],
            )
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "library-history-shard.yml"
        ).read_text(encoding="utf-8")
        self.assertIn('RUST_TOOLCHAIN: "1.88.0"', workflow)
        self.assertIn(
            "rustup toolchain install $env:RUST_TOOLCHAIN --profile minimal --target $env:RUST_TARGET",
            workflow,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
