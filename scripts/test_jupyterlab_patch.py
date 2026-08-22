from __future__ import annotations

import importlib.util
import sys
import unittest
import warnings
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SPEC = importlib.util.spec_from_file_location(
    "staticpython_jupyterlab_patch",
    REPO_ROOT / "Lib" / "jupyterlab" / "setup.py",
)
assert SPEC is not None and SPEC.loader is not None
jupyterlab = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(jupyterlab)


def labapp_source(*, call_not_implemented: bool) -> str:
    not_implemented = "NotImplementedError()" if call_not_implemented else "NotImplementedError"
    return (
        "class LabApp:\n"
        "    def initialize(self):\n"
        "            if entry_point is None:\n"
        "                self.log.error(f\"Extension Manager: No manager defined for provider '{provider}'.\")\n"
        f"                raise {not_implemented}\n"
        "            else:\n"
        "                self.log.info(f\"Extension Manager is '{provider}'.\")\n"
        "            manager_factory = entry_point.load()\n"
    )


class JupyterLabPatchTests(unittest.TestCase):
    def test_early_sdist_license_fallbacks_are_immutable(self) -> None:
        integration = jupyterlab.LIBRARY_INTEGRATION

        self.assertEqual(integration.license_expression, "BSD-3-Clause")
        self.assertEqual(
            [record["filename"] for record in integration.license_sources],
            ["LICENSE-2015.txt", "LICENSE-2015-2016.txt"],
        )
        self.assertEqual(
            [record["sha256"] for record in integration.license_sources],
            [
                "e73aa83e9684316187c171eeefbb03ae52a5d6c5469a5c3c222c8487a3a43df4",
                "eb713dd6d648da8f74b389761faa8c310f186f365d3055ec2c788f1800bcd94f",
            ],
        )
        for record in integration.license_sources:
            self.assertRegex(record["url"], r"/[0-9a-f]{40}/LICENSE$")

    def test_extension_manager_fallback_supports_old_and_new_raise_forms(self) -> None:
        for call_not_implemented in (True, False):
            with self.subTest(call_not_implemented=call_not_implemented):
                transformed = jupyterlab._patch_labapp_extension_manager_fallback(
                    labapp_source(call_not_implemented=call_not_implemented)
                )

                self.assertIn('provider = "readonly"', transformed)
                self.assertIn("manager_factory = ReadOnlyExtensionManager", transformed)
                self.assertIn("manager_factory = entry_point.load()", transformed)
                self.assertNotIn("raise NotImplementedError", transformed)

    def test_extension_manager_fallback_rejects_unknown_anchor_shape(self) -> None:
        source = labapp_source(call_not_implemented=False).replace(
            "self.log.error",
            "self.log.critical",
        )

        with self.assertRaisesRegex(RuntimeError, "anchor not found"):
            jupyterlab._patch_labapp_extension_manager_fallback(source)

    def test_legacy_distutils_version_patch_is_strict(self) -> None:
        source = (
            "from distutils.version import LooseVersion\n\n"
            "def versions_match(built, current):\n"
            "    return LooseVersion(built) == LooseVersion(current)\n"
        )
        patched = jupyterlab._patch_legacy_distutils_version(source)

        self.assertIn("from packaging.version import InvalidVersion, Version", patched)
        self.assertNotIn("distutils", patched)
        self.assertNotIn("LooseVersion", patched)
        self.assertEqual(patched.count("_staticpython_version_key("), 3)
        namespace: dict[str, object] = {}
        exec(compile(patched, "<jupyterlab-legacy-commands>", "exec"), namespace)
        versions_match = namespace["versions_match"]
        self.assertTrue(versions_match("1.0", "1.0.0"))
        self.assertFalse(versions_match("", "1.0"))

        with self.assertRaisesRegex(RuntimeError, "anchor not found"):
            jupyterlab._patch_legacy_distutils_version(
                source.replace(
                    "from distutils.version import LooseVersion",
                    "import distutils.version",
                )
            )

        integration = jupyterlab.LIBRARY_INTEGRATION
        self.assertIn("packaging", integration.dependencies)
        self.assertEqual(
            integration.post_patch_hooks[0],
            jupyterlab.patch_legacy_distutils_version,
        )

    def test_legacy_semver_patch_preserves_regex_behavior_without_warnings(self) -> None:
        source = """import re
SEMVER_SPEC_VERSION = '2.0.0'
NUMERIC = re.compile("^\\d+$")
def normalize(value):
    value = " ".join(re.split("\\s+", value))
    value = " ".join(re.split("\\s+", value))
    value = " ".join(re.split("\\s+", value))
    value = " ".join(re.split("\\s+", value))
    return " ".join(re.split("\\s+", value))
"""
        patched = jupyterlab._patch_legacy_semver_invalid_escapes(source)
        self.assertIn('re.compile(r"^\\d+$")', patched)
        self.assertEqual(patched.count('r"\\s+"'), 5)
        namespace: dict[str, object] = {}
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            warnings.simplefilter("error", DeprecationWarning)
            exec(compile(patched, "<jupyterlab-semver>", "exec"), namespace)
        self.assertTrue(namespace["NUMERIC"].fullmatch("123"))
        self.assertEqual(namespace["normalize"]("a   b"), "a b")

    def test_legacy_semver_patch_accepts_line_wrapped_fifth_split(self) -> None:
        source = """import re
SEMVER_SPEC_VERSION = '2.0.0'
NUMERIC = re.compile("^\\d+$")
def normalize(value):
    value = " ".join(re.split("\\s+", value))
    value = " ".join(re.split("\\s+", value))
    value = " ".join(re.split("\\s+", value))
    value = " ".join(re.split("\\s+", value))
    return re.split(
        "\\s+", value
    )
"""
        patched = jupyterlab._patch_legacy_semver_invalid_escapes(source)
        self.assertIn('re.compile(r"^\\d+$")', patched)
        self.assertEqual(patched.count('r"\\s+"'), 5)
        namespace: dict[str, object] = {}
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            warnings.simplefilter("error", DeprecationWarning)
            exec(compile(patched, "<jupyterlab-semver-four-split>", "exec"), namespace)
        self.assertTrue(namespace["NUMERIC"].fullmatch("123"))
        self.assertEqual(namespace["normalize"]("a   b"), ["a", "b"])

    def test_legacy_semver_patch_preserves_already_raw_jupyterlab_4_layout(self) -> None:
        source = r"""import re
SEMVER_SPEC_VERSION = '2.0.0'
NUMERIC = re.compile(r"^\d+$")
def normalize(value):
    value = " ".join(re.split(r"\s+", value))
    value = " ".join(re.split(r"\s+", value))
    value = " ".join(re.split(r"\s+", value))
    value = " ".join(re.split(r"\s+", value))
    return re.split(
        r"\s+", value
    )
"""
        patched = jupyterlab._patch_legacy_semver_invalid_escapes(source)
        self.assertEqual(patched, source)
        namespace: dict[str, object] = {}
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            warnings.simplefilter("error", DeprecationWarning)
            exec(compile(patched, "<jupyterlab-4-semver>", "exec"), namespace)
        self.assertTrue(namespace["NUMERIC"].fullmatch("123"))
        self.assertEqual(namespace["normalize"]("a   b"), ["a", "b"])

    def test_legacy_semver_patch_rejects_partial_anchor_drift(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "anchors changed"):
            jupyterlab._patch_legacy_semver_invalid_escapes(
                "SEMVER_SPEC_VERSION = '2.0.0'\n"
                'NUMERIC = re.compile("^\\d+$")\n'
                'value = re.split("\\s+", value)\n'
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
