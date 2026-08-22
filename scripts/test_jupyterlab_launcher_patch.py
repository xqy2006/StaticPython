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
    "staticpython_jupyterlab_launcher_patch",
    REPO_ROOT / "Lib" / "jupyterlab_launcher" / "setup.py",
)
assert SPEC is not None and SPEC.loader is not None
jupyterlab_launcher = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(jupyterlab_launcher)


class JupyterLabLauncherPatchTests(unittest.TestCase):
    def test_invalid_escape_patch_preserves_json_minifier_regex(self) -> None:
        source = """import re
def json_minify(string, strip_space=True):
    tokenizer = re.compile('"|(/\\*)|(\\*/)|(//)|\\n|\\r')
    return [match.group() for match in re.finditer(tokenizer, string)]
"""
        patched = jupyterlab_launcher._patch_json_minify_invalid_escapes(source)
        self.assertIn("tokenizer = re.compile(r'", patched)
        namespace: dict[str, object] = {}
        with warnings.catch_warnings():
            warnings.simplefilter("error", SyntaxWarning)
            warnings.simplefilter("error", DeprecationWarning)
            exec(
                compile(patched, "<jupyterlab-launcher-json-minify>", "exec"), namespace
            )
        self.assertEqual(
            namespace["json_minify"]("/*x*/\n//y\r"),
            ["/*", "*/", "\n", "//", "\r"],
        )

    def test_invalid_escape_patch_rejects_drift(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "anchor not found"):
            jupyterlab_launcher._patch_json_minify_invalid_escapes(
                "import re\ndef json_minify(value):\n"
                "    tokenizer = re.compile('changed')\n"
            )

    def test_integration_replaces_catalog_entry_with_strict_hook(self) -> None:
        integration = jupyterlab_launcher.LIBRARY_INTEGRATION
        self.assertEqual(integration.project_name, "jupyterlab-launcher")
        self.assertIn("Lib/jupyterlab_launcher", integration.materialized_paths)
        self.assertEqual(integration.source_ignore_patterns, ["tests"])
        self.assertIn(
            jupyterlab_launcher.patch_json_minify_invalid_escapes,
            integration.post_patch_hooks,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
