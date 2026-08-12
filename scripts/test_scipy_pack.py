from __future__ import annotations

import ast
import importlib.util
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from packaging.version import Version


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import build
import libs


EXPECTED_VERSIONS = {
    "numpy": "2.4.4",
    "pybind11": "3.0.4",
    "scipy": "1.17.1",
}

EXPECTED_SOURCE_HASHES = {
    "numpy": "2d390634c5182175533585cc89f3608a4682ccb173cc9bb940b2881c8d6f8fa0",
    "pybind11": "3286b59c8a774b9ee650169302dd5a4eedc30a8617905a0560dd8ee44775130c",
    "scipy": "95d8e012d8cb8816c226aef832200b1d45109ed4464303e997c5b13122b297c0",
}


class SciPyPackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(
            (REPO_ROOT / "config.json").read_text(encoding="utf-8")
        )
        cls.definitions = {
            integration.name: integration
            for integration in libs.load_integration_definitions(REPO_ROOT / "Lib")
        }
        setup_path = REPO_ROOT / "Lib" / "scipy" / "setup.py"
        spec = importlib.util.spec_from_file_location(
            "staticpython_scipy_setup_test",
            setup_path,
        )
        assert spec is not None and spec.loader is not None
        cls.scipy_setup = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.scipy_setup)

    def test_experimental_profile_locks_exact_dependency_closure(self) -> None:
        _name, profile = build.resolve_profile(self.config, "scipy-experimental")
        self.assertEqual(profile["third_party_libraries"], ["scipy"])
        self.assertEqual(
            profile["third_party_library_version_overrides"],
            EXPECTED_VERSIONS,
        )
        catalog = build.profile_library_catalog(
            self.config,
            profile,
            "third_party_library_catalog",
        )
        selected = libs.load_integrations(
            build.LIB_PATCH_ROOT,
            ["scipy"],
            target_version=Version("3.13.15"),
            version_overrides=profile["third_party_library_version_overrides"],
            library_catalog=catalog,
        )
        self.assertEqual(
            [integration.name for integration in selected],
            ["numpy", "pybind11", "scipy"],
        )
        self.assertNotIn(
            "scipy",
            self.config["profiles"]["full"]["third_party_libraries"],
        )

    def test_every_closure_source_archive_has_an_exact_hash_pin(self) -> None:
        for name, version in EXPECTED_VERSIONS.items():
            with self.subTest(name=name):
                integration = self.definitions[name]
                self.assertEqual(integration.release_version, version)
                self.assertEqual(
                    integration.source_archive_sha256_by_version,
                    {version: EXPECTED_SOURCE_HASHES[name]},
                )

    def test_cython_codegen_toolchain_is_exact_and_hash_pinned(self) -> None:
        self.assertEqual(self.scipy_setup.SCIPY_CYTHON_VERSION, "3.2.9")
        self.assertEqual(
            self.scipy_setup.SCIPY_CYTHON_REQUIREMENT,
            "Cython==3.2.9",
        )
        self.assertEqual(
            self.scipy_setup.SCIPY_CYTHON_WHEEL_FILENAME,
            "cython-3.2.9-py3-none-any.whl",
        )
        self.assertEqual(
            self.scipy_setup.SCIPY_CYTHON_WHEEL_SHA256,
            "a2b0e87f6b80790c929308ca0831d686f7a180feab684fe8cd4a4380bd96aaca",
        )
        self.assertTrue(
            self.scipy_setup.SCIPY_CYTHON_WHEEL_URL.endswith(
                "/cython-3.2.9-py3-none-any.whl"
            )
        )

        context = SimpleNamespace(download_cache_root=Path("C:/cache"))
        cache_dir = self.scipy_setup.scipy_cython_cache_dir(context).as_posix()
        self.assertIn("/scipy-cython/3.2.9/", cache_dir)

    def test_scipy_contract_declares_native_subset_and_extended_smoke(self) -> None:
        integration = self.definitions["scipy"]
        self.assertEqual(integration.dependencies, ["numpy", "pybind11"])
        self.assertEqual(
            integration.python_link_dependencies_release_x64,
            [
                "scipy._lib._ccallback_c.lib",
                "scipy._lib._uarray._uarray.lib",
                "scipy.fft._pocketfft.pypocketfft.lib",
            ],
        )
        self.assertEqual(len(integration.smoke_tests), 2)
        self.assertEqual(
            integration.smoke_tests[1],
            {
                "name": "phase-1-extended-api-behavior",
                "kind": "script",
                "script": "scripts/scipy_profile_verify.py",
                "timeout": 120,
            },
        )

    def test_extended_smoke_covers_each_supported_phase_one_area(self) -> None:
        smoke_path = REPO_ROOT / "scripts" / "scipy_profile_verify.py"
        source = smoke_path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(smoke_path))
        expected_tests = {
            "test_scipy_import",
            "test_scipy_fft",
            "test_scipy_constants",
            "test_scipy_fftpack",
            "test_scipy_io_wavfile",
            "test_scipy_io_arff",
            "test_scipy_integrate",
            "test_scipy_special",
            "test_scipy_linalg",
            "test_scipy_signal",
            "test_scipy_optimize",
            "test_scipy_interpolate",
            "test_scipy_stats",
            "test_scipy_sparse",
            "test_scipy_sparse_linalg",
            "test_scipy_spatial",
        }
        defined_functions = {
            node.name
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        registered_tests = {
            (node.elts[0].value, node.elts[1].id)
            for node in ast.walk(tree)
            if isinstance(node, ast.Tuple)
            and len(node.elts) == 2
            and isinstance(node.elts[0], ast.Constant)
            and isinstance(node.elts[0].value, str)
            and isinstance(node.elts[1], ast.Name)
        }
        for function in expected_tests:
            with self.subTest(function=function):
                self.assertIn(function, defined_functions)
                label = function.removeprefix("test_").replace("_", "-")
                self.assertIn((label, function), registered_tests)

    def test_workflow_covers_all_target_cpython_series(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "scipy-static.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("push:\n    branches: [master]", workflow)
        self.assertIn("pull_request:\n    paths:", workflow)
        targets = {
            "3.11.15": "cp311",
            "3.12.13": "cp312",
            "3.13.15": "cp313",
            "3.14.7": "cp314",
            "3.15.0rc1": "cp315",
        }
        for version, tag in targets.items():
            with self.subTest(version=version):
                self.assertEqual(workflow.count(f'cpython_version: "{version}"'), 2)
                self.assertEqual(workflow.count(f"python_tag: {tag}"), 2)
        self.assertEqual(
            workflow.count("VERIFY_CPYTHON_VERSION: ${{ matrix.cpython_version }}"),
            2,
        )
        self.assertIn("scipy-runtime-sdk-${{ matrix.python_tag }}", workflow)
        self.assertIn("scipy-static-1.17.1-${{ matrix.python_tag }}", workflow)
        self.assertNotIn("scipy-static-1.17.1-cp313", workflow)

    def test_workflow_requires_no_extraction_and_independent_pe_evidence(self) -> None:
        workflow = (
            REPO_ROOT / ".github" / "workflows" / "scipy-static.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("--profile scipy-experimental", workflow)
        self.assertIn("Expected three dependency-complete SciPy packs", workflow)
        self.assertIn("$smoke.PSObject.Properties['released_files']", workflow)
        self.assertIn("SciPy verification released runtime files", workflow)
        self.assertIn("phase-1-extended-api-behavior", workflow)
        self.assertIn("$report.pe_audit.status -ne 'passed'", workflow)
        self.assertIn("dumpbin /NOLOGO /DEPENDENTS", workflow)
        self.assertIn("forbidden_entry_symbols", workflow)
        self.assertIn("main_object_records", workflow)
        self.assertIn("$scipy.toolchain.cython.version -ne '3.2.9'", workflow)
        self.assertIn("cython-3.2.9-py3-none-any.whl", workflow)
        self.assertIn(self.scipy_setup.SCIPY_CYTHON_WHEEL_SHA256, workflow)


if __name__ == "__main__":
    unittest.main(verbosity=2)
