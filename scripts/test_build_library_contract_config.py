from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "staticpython_build_library_contract_config",
    REPO_ROOT / "scripts" / "build_library_contract_config.py",
)
assert SPEC is not None and SPEC.loader is not None
builder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(builder)


class BuildLibraryContractConfigTests(unittest.TestCase):
    def test_contract_profile_selects_one_root_and_overrides_its_version(self) -> None:
        base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        result, canonical_name = builder.build_contract_config(base, "opengl", "3.1.9")
        profile = result["profiles"]["library-contract"]
        self.assertEqual(canonical_name, "OpenGL")
        self.assertEqual(profile["third_party_libraries"], ["OpenGL"])
        self.assertEqual(profile["third_party_library_version_overrides"]["OpenGL"], "3.1.9")
        self.assertEqual(profile["verification"], {"enabled": False})
        self.assertNotIn("library-contract", base["profiles"])

    def test_unknown_library_is_rejected(self) -> None:
        base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        with self.assertRaisesRegex(RuntimeError, "not in the current or historical"):
            builder.build_contract_config(base, "missing-library", "1.0")

    def test_historical_alias_can_build_without_becoming_a_current_release_root(self) -> None:
        base = json.loads((REPO_ROOT / "config.json").read_text(encoding="utf-8"))
        self.assertNotIn("attr", base["profiles"]["full"]["third_party_libraries"])
        result, canonical_name = builder.build_contract_config(base, "attr", "25.4.0")
        self.assertEqual(canonical_name, "attr")
        self.assertEqual(
            result["profiles"]["library-contract"]["third_party_libraries"],
            ["attr"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
