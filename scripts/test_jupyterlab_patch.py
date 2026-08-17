from __future__ import annotations

import importlib.util
import sys
import unittest
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


if __name__ == "__main__":
    unittest.main(verbosity=2)
