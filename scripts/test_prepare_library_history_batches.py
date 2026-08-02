from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SPEC = importlib.util.spec_from_file_location(
    "staticpython_prepare_library_history_batches",
    REPO_ROOT / "scripts" / "prepare_library_history_batches.py",
)
assert SPEC is not None and SPEC.loader is not None
history = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(history)


def source(version: str) -> dict:
    return {
        "filename": f"demo-{version}.tar.gz",
        "url": f"https://files.pythonhosted.org/demo-{version}.tar.gz",
        "sha256": (version.replace(".", "") + "a" * 64)[:64],
    }


def contract() -> dict:
    return {
        "contract_sha256": "f" * 64,
        "libraries": {
            "pure": {
                "source_provider": "pypi",
                "project_name": "pure-project",
                "versions": {
                    version: {
                        "targets": {
                            python: {"status": "candidate", "source": source(version)}
                            for python in ("3.12.13", "3.13.14")
                        }
                    }
                    for version in ("1.0", "1.1", "2.0")
                },
            },
            "native": {
                "source_provider": "pypi",
                "project_name": "native-project",
                "versions": {
                    "1.0": {
                        "targets": {
                            "3.13.14": {"status": "candidate", "source": source("1.0")},
                            "3.15.0b4": {"status": "unbuildable", "reason": "no source"},
                        }
                    }
                },
            },
            "github-only": {
                "source_provider": "github",
                "project_name": "owner/repo",
                "versions": {
                    "v1": {
                        "targets": {
                            "3.13.14": {"status": "configured", "source": {"resolver": "github"}}
                        }
                    }
                },
            },
        },
    }


class PrepareLibraryHistoryBatchesTests(unittest.TestCase):
    def test_batches_cover_every_candidate_exactly_once(self) -> None:
        result = history.prepare_history_batches(
            contract(),
            {"pure": "pure-python", "native": "native"},
            pure_batch_size=2,
            native_batch_size=1,
            max_jobs_per_run=2,
        )
        self.assertEqual(result["combination_count"], 7)
        self.assertEqual(result["build_kind_counts"], {"pure-python": 6, "native": 1})
        self.assertEqual(result["batch_count"], 5)
        self.assertEqual(result["run_shard_count"], 3)
        self.assertEqual(
            [batch["run_shard_index"] for batch in result["batches"]],
            [0, 1, 2, 0, 1],
        )
        identities = [
            (batch["library"], batch["python_version"], version)
            for batch in result["batches"]
            for version in batch["versions"]
        ]
        self.assertEqual(len(identities), len(set(identities)))

    def test_manifest_is_deterministic(self) -> None:
        first = history.prepare_history_batches(
            contract(),
            {"pure": "pure-python", "native": "native"},
        )
        second = history.prepare_history_batches(
            contract(),
            {"native": "native", "pure": "pure-python"},
        )
        self.assertEqual(first, second)

    def test_missing_build_kind_is_rejected(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "build-kind"):
            history.prepare_history_batches(contract(), {"pure": "pure-python"})

    def test_invalid_job_limit_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "between 1 and 256"):
            history.prepare_history_batches(
                contract(),
                {"pure": "pure-python", "native": "native"},
                max_jobs_per_run=257,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
