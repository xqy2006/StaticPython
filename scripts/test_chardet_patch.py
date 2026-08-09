from __future__ import annotations

import hashlib
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_chardet_setup():
    spec = importlib.util.spec_from_file_location(
        "staticpython_chardet_setup_test",
        REPO_ROOT / "Lib" / "chardet" / "setup.py",
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ChardetPatchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.models = self.root / "Lib" / "chardet" / "models"
        self.models.mkdir(parents=True)
        (self.models / "models.bin").write_bytes(b"models-7.5.1")
        (self.models / "idf.bin").write_bytes(b"idf-7.5.1")
        self.context = SimpleNamespace(source_root=self.root, log=lambda _message: None)
        self.module = load_chardet_setup()

    def tearDown(self) -> None:
        self.temp.cleanup()

    @staticmethod
    def modern_source() -> str:
        return '''import hashlib
import importlib.resources

_V2_MAGIC = b"CMD2"
#: rowmax.bin format changed in chardet 7.5.1.
_ROWMAX_MAGIC = b"CRM1"

def _load_models_data():
    ref = importlib.resources.files("chardet.models").joinpath("models.bin")
    data = ref.read_bytes()
    return data

def get_idf_weights():
    ref = importlib.resources.files("chardet.models").joinpath("idf.bin")
    data = ref.read_bytes()
    return data

def load_models():
    return {"test": b"model"}

def get_rowmax():
    models = load_models()
    files = importlib.resources.files("chardet.models")
    try:
        data = files.joinpath("rowmax.bin").read_bytes()
        models_digest = hashlib.sha256(
            files.joinpath("models.bin").read_bytes()
        ).digest()
    except (FileNotFoundError, OSError):
        return b"fallback", b"fallback"
    return data, models_digest
'''

    @staticmethod
    def legacy_source() -> str:
        return '''import importlib.resources

_V2_MAGIC = b"CMD2"

def _load_models_data():
    ref = importlib.resources.files("chardet.models").joinpath("models.bin")
    data = ref.read_bytes()
    return data

def get_idf_weights():
    ref = importlib.resources.files("chardet.models").joinpath("idf.bin")
    data = ref.read_bytes()
    return data
'''

    def write_source(self, source: str) -> Path:
        target = self.models / "__init__.py"
        target.write_text(source, encoding="utf-8", newline="\n")
        return target

    def test_751_embeds_models_idf_and_rowmax_without_resource_reads(self) -> None:
        rowmax = b"rowmax-7.5.1"
        (self.models / "rowmax.bin").write_bytes(rowmax)
        target = self.write_source(self.modern_source())

        self.module.patch_chardet_sources(self.context)
        patched = target.read_text(encoding="utf-8")
        compile(patched, str(target), "exec")
        self.assertIn("_STATICPYTHON_MODELS_BIN = ", patched)
        self.assertIn("_STATICPYTHON_IDF_BIN = ", patched)
        self.assertIn("_STATICPYTHON_ROWMAX_BIN = ", patched)
        for filename in ("models.bin", "idf.bin", "rowmax.bin"):
            self.assertNotIn(f'joinpath("{filename}")', patched)

        namespace: dict[str, object] = {}
        exec(compile(patched, str(target), "exec"), namespace)
        with mock.patch("importlib.resources.files", side_effect=AssertionError("disk lookup")):
            self.assertEqual(namespace["_load_models_data"](), b"models-7.5.1")
            self.assertEqual(namespace["get_idf_weights"](), b"idf-7.5.1")
            embedded_rowmax, models_digest = namespace["get_rowmax"]()
        self.assertEqual(embedded_rowmax, rowmax)
        self.assertEqual(models_digest, hashlib.sha256(b"models-7.5.1").digest())

        self.module.patch_chardet_sources(self.context)
        self.assertEqual(target.read_text(encoding="utf-8"), patched)

    def test_legacy_layout_remains_supported_and_idempotent(self) -> None:
        target = self.write_source(self.legacy_source())
        self.module.patch_chardet_sources(self.context)
        patched = target.read_text(encoding="utf-8")
        compile(patched, str(target), "exec")
        self.assertIn("_STATICPYTHON_MODELS_BIN = ", patched)
        self.assertIn("_STATICPYTHON_IDF_BIN = ", patched)
        self.assertNotIn("_STATICPYTHON_ROWMAX_BIN", patched)
        self.module.patch_chardet_sources(self.context)
        self.assertEqual(target.read_text(encoding="utf-8"), patched)

    def test_rowmax_loader_drift_fails_without_partial_write(self) -> None:
        (self.models / "rowmax.bin").write_bytes(b"rowmax")
        original = self.modern_source().replace(
            'files.joinpath("rowmax.bin").read_bytes()',
            'files.joinpath("rowmax-v2.bin").read_bytes()',
        )
        target = self.write_source(original)
        with self.assertRaisesRegex(RuntimeError, "exactly one chardet rowmax.bin loader"):
            self.module.patch_chardet_sources(self.context)
        self.assertEqual(target.read_text(encoding="utf-8"), original)

    def test_duplicate_model_anchor_fails_closed(self) -> None:
        source = self.legacy_source().replace(
            '_V2_MAGIC = b"CMD2"\n',
            '_V2_MAGIC = b"CMD2"\n_V2_MAGIC = b"CMD2"\n',
            1,
        )
        target = self.write_source(source)
        with self.assertRaisesRegex(RuntimeError, "expected exactly one anchor"):
            self.module.patch_chardet_sources(self.context)
        self.assertEqual(target.read_text(encoding="utf-8"), source)


if __name__ == "__main__":
    unittest.main()
