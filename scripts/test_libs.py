from __future__ import annotations

import ast
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from libs import ensure_package_markers


class EnsurePackageMarkersTests(unittest.TestCase):
    def test_preserves_docstring_and_future_imports(self) -> None:
        source = (
            '"""package documentation"""\n'
            "from __future__ import annotations\n"
            "VALUE: list[str] = []\n"
        )

        transformed = ensure_package_markers(source, "example")

        tree = ast.parse(transformed)
        self.assertEqual(ast.get_docstring(tree), "package documentation")
        self.assertIsInstance(tree.body[1], ast.ImportFrom)
        self.assertEqual(tree.body[1].module, "__future__")
        self.assertLess(
            transformed.index("from __future__ import annotations"),
            transformed.index("__package__ = 'example'"),
        )
        compile(transformed, "<package>", "exec")

    def test_preserves_bom_shebang_and_coding_cookie(self) -> None:
        source = "\ufeff#!/usr/bin/env python\n# coding: utf-8\nVALUE = 1\n"

        transformed = ensure_package_markers(source, "example")

        self.assertTrue(transformed.startswith("\ufeff#!/usr/bin/env python\n# coding: utf-8\n"))
        self.assertGreater(
            transformed.index("__package__ = 'example'"),
            transformed.index("# coding: utf-8"),
        )
        compile(transformed.lstrip("\ufeff"), "<package>", "exec")

    def test_is_idempotent(self) -> None:
        source = '"""docs"""\nVALUE = 1\n'
        transformed = ensure_package_markers(source, "example")

        self.assertEqual(ensure_package_markers(transformed, "example"), transformed)

    def test_crlf_output_is_idempotent(self) -> None:
        source = '"""docs"""\r\nfrom __future__ import annotations\r\nVALUE = 1\r\n'
        transformed = ensure_package_markers(source, "example")

        self.assertIn("__package__ = 'example'\r\n", transformed)
        self.assertEqual(ensure_package_markers(transformed, "example"), transformed)

    def test_preserves_bom_when_upgrading_legacy_markers(self) -> None:
        source = "\ufeff__package__ = 'example'\n__path__ = [__name__]\n"

        transformed = ensure_package_markers(source, "example")

        self.assertTrue(transformed.startswith("\ufeff"))
        self.assertNotIn("\n__path__ = [__name__]\n", transformed)
        self.assertIn("globals().get('__file__')", transformed)
        self.assertEqual(ensure_package_markers(transformed, "example"), transformed)

    def test_preserves_bom_when_adding_missing_path_marker(self) -> None:
        source = "\ufeff__package__ = 'example'\nVALUE = 1\n"

        transformed = ensure_package_markers(source, "example")

        self.assertTrue(transformed.startswith("\ufeff"))
        self.assertIn(
            "__path__ = [_staticpython_os.path.dirname(_staticpython_file)]",
            transformed,
        )
        self.assertEqual(ensure_package_markers(transformed, "example"), transformed)

    def test_frozen_package_without_file_uses_module_name_path(self) -> None:
        transformed = ensure_package_markers("VALUE = 1\n", "encodings")
        namespace = {
            "__name__": "encodings",
            "__spec__": SimpleNamespace(submodule_search_locations=[]),
        }

        exec(compile(transformed, "<frozen encodings>", "exec"), namespace)

        self.assertEqual(namespace["__path__"], ["encodings"])

    def test_package_with_virtual_file_uses_virtual_directory(self) -> None:
        transformed = ensure_package_markers("VALUE = 1\n", "wx")
        namespace = {
            "__file__": "staticpython-resource:///Lib/wx/__init__.py",
            "__name__": "wx",
            "__spec__": SimpleNamespace(submodule_search_locations=[]),
        }

        exec(compile(transformed, "<frozen wx>", "exec"), namespace)

        self.assertEqual(namespace["__path__"], ["staticpython-resource:///Lib/wx"])

    def test_upgrades_unsafe_file_fallback(self) -> None:
        source = (
            "__package__ = 'encodings'\n\n"
            "try:\n"
            "    __path__ = list(getattr(__spec__, 'submodule_search_locations', ()) or ())\n"
            "except Exception:\n"
            "    __path__ = []\n"
            "if not __path__:\n"
            "    import os as _staticpython_os\n"
            "    __path__ = [_staticpython_os.path.dirname(__file__)]\n\n"
            "VALUE = 1\n"
        )

        transformed = ensure_package_markers(source, "encodings")
        namespace = {
            "__name__": "encodings",
            "__spec__": SimpleNamespace(submodule_search_locations=[]),
        }
        exec(compile(transformed, "<frozen encodings>", "exec"), namespace)

        self.assertNotIn("dirname(__file__)", transformed)
        self.assertEqual(namespace["__path__"], ["encodings"])
        self.assertEqual(ensure_package_markers(transformed, "encodings"), transformed)


if __name__ == "__main__":
    unittest.main()
