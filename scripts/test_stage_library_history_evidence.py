from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import stage_library_history_evidence as stage


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


class StageLibraryHistoryEvidenceTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, dict]:
        evidence_root = root / "source"
        combination = evidence_root / "combinations" / "demo"
        combination.mkdir(parents=True)
        files = {
            "combinations/demo/config.json": b'{"demo": true}\n',
            "combinations/demo/combination-evidence.v1.json": b'{"status": "passed"}\n',
        }
        for relative, payload in files.items():
            (evidence_root / relative).write_bytes(payload)
        (combination / "packs").mkdir()
        (combination / "packs" / "do-not-upload.zip").write_bytes(b"pack")
        batch = {
            "schema_version": 1,
            "kind": "staticpython-library-history-batch-evidence",
            "batch_id": "demo-batch",
            "evidence_sha256": "a" * 64,
            "files": [
                {"path": relative, "sha256": _sha256(payload)}
                for relative, payload in files.items()
            ],
        }
        (evidence_root / stage.BATCH_EVIDENCE_NAME).write_text(
            json.dumps(batch), encoding="utf-8"
        )
        return evidence_root, batch

    def test_stages_only_exact_manifest_files(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_root, batch = self._fixture(root)
            result = stage.stage_evidence(evidence_root, root / "staged")
            self.assertEqual(result["batch_id"], "demo-batch")
            self.assertEqual(result["file_count"], 1 + len(batch["files"]))
            staged = sorted(
                path.relative_to(root / "staged").as_posix()
                for path in (root / "staged").rglob("*")
                if path.is_file()
            )
            self.assertEqual(
                staged,
                [
                    "combinations/demo/combination-evidence.v1.json",
                    "combinations/demo/config.json",
                    stage.BATCH_EVIDENCE_NAME,
                ],
            )

    def test_rejects_source_hash_drift(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_root, _batch = self._fixture(root)
            (evidence_root / "combinations/demo/config.json").write_bytes(b"changed")
            with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
                stage.stage_evidence(evidence_root, root / "staged")

    def test_rejects_path_traversal(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_root, batch = self._fixture(root)
            batch["files"][0]["path"] = "../outside.json"
            (evidence_root / stage.BATCH_EVIDENCE_NAME).write_text(
                json.dumps(batch), encoding="utf-8"
            )
            with self.assertRaisesRegex(RuntimeError, "unsafe history evidence path"):
                stage.stage_evidence(evidence_root, root / "staged")

    def test_rejects_case_insensitive_duplicate_paths(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            evidence_root, batch = self._fixture(root)
            duplicate = dict(batch["files"][0])
            duplicate["path"] = duplicate["path"].upper()
            batch["files"].append(duplicate)
            (evidence_root / stage.BATCH_EVIDENCE_NAME).write_text(
                json.dumps(batch), encoding="utf-8"
            )
            with self.assertRaisesRegex(
                RuntimeError, "duplicate history evidence path"
            ):
                stage.stage_evidence(evidence_root, root / "staged")


if __name__ == "__main__":
    unittest.main()
