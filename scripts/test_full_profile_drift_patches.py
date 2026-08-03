from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import libs


def load_setup(name: str):
    path = REPO_ROOT / "Lib" / name / "setup.py"
    spec = importlib.util.spec_from_file_location(f"_test_{name}_setup", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PLOTLY_690_DATA_SOURCE = '''from importlib import import_module
import os

AVAILABLE_BACKENDS = ["pandas", "polars", "pyarrow", "modin", "cudf"]


def _get_dataset(d, return_type):
    filepath = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "package_data",
        "datasets",
        d + ".csv.gz",
    )
    if return_type not in AVAILABLE_BACKENDS:
        raise NotImplementedError(return_type)
    backend = import_module(return_type)
    try:
        return backend.read_csv(filepath)
    except Exception as e:
        raise Exception(str(e)).with_traceback(e.__traceback__)


def iris(return_type="pandas"):
    return _get_dataset("iris", return_type=return_type)


def election_geojson():
    path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "package_data",
        "datasets",
        "election.geojson.gz",
    )
    with gzip.GzipFile(path, "r") as f:
        return json.loads(f.read().decode("utf-8"))


def carshare(return_type="pandas"):
    return _get_dataset("carshare", return_type=return_type)
'''


class FullProfileDriftPatchTests(unittest.TestCase):
    def test_plotly_690_dataset_loader_uses_embedded_bytes(self) -> None:
        module = load_setup("plotly")
        patched = module.patch_plotly_data_source(PLOTLY_690_DATA_SOURCE)

        self.assertIn("def _get_dataset(d, return_type):", patched)
        self.assertIn(
            "dataset_bytes = _STATICPYTHON_DATASETS.get(dataset_name)",
            patched,
        )
        self.assertIn(
            "dataset_source = io.BytesIO(gzip.decompress(dataset_bytes))",
            patched,
        )
        self.assertIn("return backend.read_csv(dataset_source)", patched)
        self.assertIn(
            "geojson_bytes = _STATICPYTHON_DATASETS.get(geojson_name)",
            patched,
        )
        self.assertEqual(module.patch_plotly_data_source(patched), patched)
        compile(patched, "<patched-plotly-data>", "exec")

    def test_plotly_unknown_dataset_signature_fails_strictly(self) -> None:
        module = load_setup("plotly")
        source = "def _get_dataset(d, return_type, options):\n    return None\n"
        with self.assertRaisesRegex(RuntimeError, "unsupported plotly"):
            module.patch_plotly_data_source(source)

    def test_jedi_020_patch_recovers_equivalent_virtual_cache_path(self) -> None:
        module = load_setup("jedi")
        namespace = {"parser_cache": {"grammar": {}}}
        exec(module.JEDI_PARSER_CACHE_NEW, namespace)
        cached_path = Path(
            "staticpython-resource:/Lib/jedi/third_party/typeshed/stdlib/math.pyi"
        )
        lookup_path = Path(
            "D:/workspace/staticpython-resource:/Lib/jedi/third_party/typeshed/stdlib/math.pyi"
        )
        expected = SimpleNamespace(lines=["def sqrt(): ...\n"])
        namespace["parser_cache"]["grammar"][cached_path] = expected
        grammar = SimpleNamespace(_hashed="grammar")

        self.assertIs(namespace["get_parso_cache_node"](grammar, lookup_path), expected)
        with self.assertRaises(KeyError):
            namespace["get_parso_cache_node"](grammar, Path("D:/native/math.pyi"))

    def test_jedi_patch_rule_is_versioned_strict_and_idempotent(self) -> None:
        module = load_setup("jedi")
        integration = module.LIBRARY_INTEGRATION
        integration.release_version = "0.20.0"
        self.assertEqual(integration.dependencies, ["parso"])

        with tempfile.TemporaryDirectory() as temp_dir:
            source_root = Path(temp_dir)
            target = source_root / "Lib" / "jedi" / "parser_utils.py"
            target.parent.mkdir(parents=True)
            target.write_text(module.JEDI_PARSER_CACHE_OLD, encoding="utf-8")
            context = libs.LibraryHookContext(
                repo_root=REPO_ROOT,
                source_root=source_root,
                version_info=(3, 11, 15),
                version_mm="3.11",
                version_full="3.11.15",
                download_cache_root=source_root / "downloads",
                work_cache_root=source_root / "work",
                asset_overlay_root=REPO_ROOT / "assets" / "overlay",
                log=lambda _message: None,
            )
            libs.run_pre_patch_hooks([integration], context)
            libs.run_pre_patch_hooks([integration], context)
            self.assertEqual(
                target.read_text(encoding="utf-8"),
                module.JEDI_PARSER_CACHE_NEW,
            )
            target.write_text("def get_parso_cache_node():\n    pass\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "anchor mismatch"):
                libs.run_pre_patch_hooks([integration], context)


if __name__ == "__main__":
    unittest.main(verbosity=2)
