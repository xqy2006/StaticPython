from __future__ import annotations

import importlib.util
import json
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
    def test_historical_only_integrations_have_build_kinds(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))

        kinds = history.integration_build_kinds(config)

        self.assertEqual(kinds["attr"], "pure-python")
        self.assertEqual(kinds["cattr"], "pure-python")

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
            [shard["batch_count"] for shard in result["run_shards"]],
            [2, 2, 1],
        )
        self.assertEqual(
            sum(shard["combination_count"] for shard in result["run_shards"]),
            result["combination_count"],
        )
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

    def test_pull_request_smoke_selects_one_latest_candidate(self) -> None:
        result = history.prepare_history_batches(
            contract(),
            {"pure": "pure-python", "native": "native"},
            smoke_library="pure",
            smoke_python_series="3.13",
        )
        self.assertEqual(result["selection"]["mode"], "smoke")
        self.assertEqual(result["combination_count"], 1)
        self.assertEqual(result["batches"][0]["versions"], ["2.0"])
        self.assertEqual(result["batches"][0]["python_version"], "3.13.14")

    def test_targeted_selection_covers_every_candidate_for_requested_libraries(
        self,
    ) -> None:
        result = history.prepare_history_batches(
            contract(),
            {"pure": "pure-python", "native": "native"},
            pure_batch_size=2,
            selected_libraries=["PURE"],
        )
        self.assertEqual(result["selection"]["mode"], "targeted")
        self.assertEqual(result["selection"]["libraries"], ["pure"])
        self.assertEqual(result["combination_count"], 6)
        self.assertEqual({batch["library"] for batch in result["batches"]}, {"pure"})
        self.assertEqual(
            {
                (batch["python_version"], version)
                for batch in result["batches"]
                for version in batch["versions"]
            },
            {
                (python_version, version)
                for python_version in ("3.12.13", "3.13.14")
                for version in ("1.0", "1.1", "2.0")
            },
        )

    def test_targeted_selection_rejects_missing_duplicate_and_smoke_filters(
        self,
    ) -> None:
        build_kinds = {"pure": "pure-python", "native": "native"}
        with self.assertRaisesRegex(RuntimeError, "missing from contract"):
            history.prepare_history_batches(
                contract(), build_kinds, selected_libraries=["absent"]
            )
        with self.assertRaisesRegex(RuntimeError, "repeated"):
            history.prepare_history_batches(
                contract(), build_kinds, selected_libraries=["pure", "PURE"]
            )
        with self.assertRaisesRegex(RuntimeError, "mutually exclusive"):
            history.prepare_history_batches(
                contract(),
                build_kinds,
                selected_libraries=["pure"],
                smoke_library="pure",
                smoke_python_series="3.13",
            )

    def test_excess_run_shards_are_rejected_without_dropping_batches(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "needs 7 run shards"):
            history.prepare_history_batches(
                contract(),
                {"pure": "pure-python", "native": "native"},
                pure_batch_size=1,
                native_batch_size=1,
                max_jobs_per_run=1,
                max_run_shards=6,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
