from __future__ import annotations

import importlib.util
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import libs


SPEC = importlib.util.spec_from_file_location(
    "staticpython_library_version_contract",
    REPO_ROOT / "scripts" / "library_version_contract.py",
)
assert SPEC is not None and SPEC.loader is not None
contract = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(contract)


def file_info(
    filename: str,
    *,
    packagetype: str = "sdist",
    requires_python: str | None = None,
    yanked: bool = False,
    sha256: str | None = "a" * 64,
) -> dict:
    result = {
        "filename": filename,
        "packagetype": packagetype,
        "requires_python": requires_python,
        "yanked": yanked,
        "url": f"https://files.example.invalid/{filename}",
    }
    if sha256 is not None:
        result["digests"] = {"sha256": sha256}
    return result


class LibraryVersionContractTests(unittest.TestCase):
    def test_historical_alias_is_discovered_outside_current_release_roots(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        payload = {"releases": {"1.0": [file_info("attrs-1.0.tar.gz")]}}
        result = contract.discover_contract(
            config,
            ["3.13.15"],
            selected_libraries=["attr"],
            payload_loader=lambda _name: payload,
        )
        self.assertEqual(list(result["libraries"]), ["attr"])
        self.assertNotIn("attr", config["profiles"]["full"]["third_party_libraries"])

    def test_default_discovery_includes_current_and_historical_catalogs(self) -> None:
        config = {
            "third_party_library_catalog": {
                "libraries": [
                    {
                        "name": "current",
                        "source_provider": "pypi",
                        "overlay_entries": ["Lib/current"],
                    },
                    {
                        "name": "historical",
                        "source_provider": "pypi",
                        "overlay_entries": ["Lib/historical"],
                    },
                ]
            },
            "profiles": {
                "full": {
                    "third_party_libraries": ["current"],
                    "historical_library_contract_libraries": ["historical"],
                }
            },
        }
        payload = {"releases": {"1.0": [file_info("demo-1.0.tar.gz")]}}
        result = contract.discover_contract(
            config,
            ["3.13.15"],
            payload_loader=lambda _name: payload,
        )
        self.assertEqual(list(result["libraries"]), ["current", "historical"])

    def test_contract_excludes_prerelease_dev_and_yanked_only_versions(self) -> None:
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            project_name="demo",
        )
        payload = {
            "info": {"requires_python": ">=3.15"},
            "releases": {
                "1.0": [file_info("demo-1.0.tar.gz")],
                "1.1rc1": [file_info("demo-1.1rc1.tar.gz")],
                "1.1.dev1": [file_info("demo-1.1.dev1.tar.gz")],
                "1.2": [file_info("demo-1.2.tar.gz", yanked=True)],
            },
        }
        result = contract.pypi_library_contract(
            integration,
            payload,
            [libs.Version("3.11.15"), libs.Version("3.15.0b4")],
        )
        self.assertEqual(list(result["versions"]), ["1.0"])
        self.assertEqual(result["versions"]["1.0"]["targets"]["3.11.15"]["status"], "candidate")

    def test_requires_python_is_evaluated_per_historical_file(self) -> None:
        integration = libs.LibraryIntegration(name="demo", source_provider="pypi")
        payload = {
            "releases": {
                "2.0": [file_info("demo-2.0.tar.gz", requires_python=">=3.13")],
            }
        }
        result = contract.pypi_library_contract(
            integration,
            payload,
            [libs.Version("3.11.15"), libs.Version("3.13.14")],
        )
        targets = result["versions"]["2.0"]["targets"]
        self.assertEqual(targets["3.11.15"]["status"], "not-applicable")
        self.assertEqual(targets["3.13.14"]["status"], "candidate")

    def test_native_only_release_is_evidence_backed_unbuildable(self) -> None:
        integration = libs.LibraryIntegration(name="demo", source_provider="pypi")
        payload = {
            "releases": {
                "3.0": [
                    file_info(
                        "demo-3.0-cp313-cp313-win_amd64.whl",
                        packagetype="bdist_wheel",
                    )
                ]
            }
        }
        result = contract.pypi_library_contract(
            integration,
            payload,
            [libs.Version("3.13.14")],
        )
        target = result["versions"]["3.0"]["targets"]["3.13.14"]
        self.assertEqual(target["status"], "unbuildable")
        self.assertEqual(target["artifacts"], ["demo-3.0-cp313-cp313-win_amd64.whl"])

    def test_source_without_sha256_is_unbuildable(self) -> None:
        integration = libs.LibraryIntegration(name="demo", source_provider="pypi")
        payload = {
            "releases": {
                "3.0": [file_info("demo-3.0.tar.gz", sha256=None)],
            }
        }
        result = contract.pypi_library_contract(
            integration,
            payload,
            [libs.Version("3.13.14")],
        )
        target = result["versions"]["3.0"]["targets"]["3.13.14"]
        self.assertEqual(target["status"], "unbuildable")
        self.assertIn("verifiable SHA-256", target["reason"])

    def test_explicit_universal_wheel_resolver_is_preserved_in_contract(self) -> None:
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            source_resolver="pypi-universal-wheel",
        )
        payload = {
            "releases": {
                "1.0": [
                    file_info("demo-1.0.tar.gz", sha256="a" * 64),
                    file_info(
                        "demo-1.0-py3-none-any.whl",
                        packagetype="bdist_wheel",
                        sha256="b" * 64,
                    ),
                ]
            }
        }
        result = contract.pypi_library_contract(
            integration,
            payload,
            [libs.Version("3.13.14")],
        )
        self.assertEqual(result["source_resolver"], "pypi-universal-wheel")
        source = result["versions"]["1.0"]["targets"]["3.13.14"]["source"]
        self.assertEqual(source["filename"], "demo-1.0-py3-none-any.whl")
        self.assertEqual(source["sha256"], "b" * 64)

    def test_non_pypi_source_is_recorded_but_not_scheduled_as_candidate(self) -> None:
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="github",
            source_resolver="github-source",
            release_version="v1.0.0",
        )
        result = contract.configured_library_contract(
            integration,
            [libs.Version("3.13.14")],
        )
        target = result["versions"]["v1.0.0"]["targets"]["3.13.14"]
        self.assertEqual(target["status"], "configured")
        self.assertEqual(target["source"], {"resolver": "github-source"})

    def test_contract_integrity_rejects_modified_baseline(self) -> None:
        payload = {
            "schema_version": contract.SCHEMA_VERSION,
            "target_python_versions": ["3.13.14"],
            "libraries": {},
            "status_counts": {},
        }
        payload["contract_sha256"] = contract._contract_sha256(payload)
        contract.validate_contract_integrity(payload)
        payload["target_python_versions"] = ["3.13.15"]
        with self.assertRaisesRegex(RuntimeError, "SHA-256 mismatch"):
            contract.validate_contract_integrity(payload)

    def test_minimum_release_version_is_respected(self) -> None:
        integration = libs.LibraryIntegration(
            name="demo",
            source_provider="pypi",
            minimum_release_version="2.0",
        )
        payload = {
            "releases": {
                "1.0": [file_info("demo-1.0.tar.gz")],
                "2.0": [file_info("demo-2.0.tar.gz")],
            }
        }
        result = contract.pypi_library_contract(
            integration,
            payload,
            [libs.Version("3.13.14")],
        )
        self.assertEqual(list(result["versions"]), ["2.0"])

    def test_discovery_is_deterministic_and_hashes_the_contract(self) -> None:
        config = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        payload = {"releases": {"1.0": [file_info("six-1.0.tar.gz")]}}
        with mock.patch.object(contract.libs, "load_integration_definitions") as load:
            load.return_value = [
                libs.LibraryIntegration(
                    name="six",
                    source_provider="pypi",
                    project_name="six",
                )
            ]
            first = contract.discover_contract(
                config,
                ["3.15.0b4", "3.11.15", "3.11.15"],
                selected_libraries=["six"],
                payload_loader=lambda _name: payload,
            )
            second = contract.discover_contract(
                config,
                ["3.11.15", "3.15.0b4"],
                selected_libraries=["six"],
                payload_loader=lambda _name: payload,
            )
        self.assertEqual(first, second)
        self.assertEqual(first["target_python_versions"], ["3.11.15", "3.15.0b4"])
        contract_hash = first.pop("contract_sha256")
        self.assertEqual(contract_hash, contract._contract_sha256(first))

    def test_delta_finds_new_candidates_hash_drift_and_regressions(self) -> None:
        previous = {
            "contract_sha256": "previous",
            "target_python_versions": ["3.13.14"],
            "libraries": {
                "demo": {
                    "versions": {
                        "1.0": {
                            "targets": {
                                "3.13.14": {
                                    "status": "candidate",
                                    "source": {"filename": "demo-1.0.tar.gz", "sha256": "a" * 64},
                                }
                            }
                        },
                        "0.9": {
                            "targets": {
                                "3.13.14": {
                                    "status": "candidate",
                                    "source": {"filename": "demo-0.9.tar.gz", "sha256": "b" * 64},
                                }
                            }
                        },
                        "0.8": {
                            "targets": {
                                "3.13.14": {
                                    "status": "unbuildable",
                                    "reason": "no source",
                                }
                            }
                        },
                    }
                }
            },
        }
        current = {
            "contract_sha256": "current",
            "target_python_versions": ["3.13.14"],
            "libraries": {
                "demo": {
                    "versions": {
                        "1.1": {
                            "targets": {
                                "3.13.14": {
                                    "status": "candidate",
                                    "source": {"filename": "demo-1.1.tar.gz", "sha256": "c" * 64},
                                }
                            }
                        },
                        "1.0": {
                            "targets": {
                                "3.13.14": {
                                    "status": "candidate",
                                    "source": {"filename": "demo-1.0.tar.gz", "sha256": "d" * 64},
                                }
                            }
                        },
                        "0.8": {
                            "targets": {
                                "3.13.14": {
                                    "status": "candidate",
                                    "source": {"filename": "demo-0.8.tar.gz", "sha256": "e" * 64},
                                }
                            }
                        },
                    }
                }
            },
        }
        delta = contract.contract_delta(current, previous)
        self.assertEqual(
            [(item["library"], item["version"]) for item in delta["new_candidates"]],
            [("demo", "0.8"), ("demo", "1.1")],
        )
        self.assertEqual(len(delta["drifted_candidates"]), 1)
        self.assertEqual(delta["drifted_candidates"][0]["version"], "1.0")
        self.assertEqual(len(delta["regressions"]), 1)
        self.assertEqual(delta["regressions"][0]["version"], "0.9")

    def test_candidate_regression_to_unbuildable_keeps_both_evidence_records(self) -> None:
        previous = {
            "contract_sha256": "previous",
            "target_python_versions": ["3.13.14"],
            "libraries": {
                "demo": {
                    "versions": {
                        "1.0": {
                            "targets": {
                                "3.13.14": {
                                    "status": "candidate",
                                    "source": {"filename": "demo-1.0.tar.gz", "sha256": "a" * 64},
                                }
                            }
                        }
                    }
                }
            },
        }
        current = {
            "contract_sha256": "current",
            "target_python_versions": ["3.13.14"],
            "libraries": {
                "demo": {
                    "versions": {
                        "1.0": {
                            "targets": {
                                "3.13.14": {
                                    "status": "unbuildable",
                                    "reason": "native-only release",
                                    "artifacts": ["demo-1.0-cp313-win_amd64.whl"],
                                }
                            }
                        }
                    }
                }
            },
        }
        delta = contract.contract_delta(current, previous)
        self.assertEqual(len(delta["regressions"]), 1)
        self.assertEqual(len(delta["new_unbuildable"]), 1)
        self.assertEqual(delta["new_unbuildable"][0]["reason"], "native-only release")
        self.assertNotIn("previous_status", delta["new_unbuildable"][0])

    def test_first_discovery_is_a_non_building_baseline(self) -> None:
        delta = contract.contract_delta({"contract_sha256": "current"}, None)
        self.assertTrue(delta["baseline"])
        self.assertEqual(delta["new_candidates"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
