from __future__ import annotations

import ast
import unittest

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
        self.assertNotIn("__path__ = [__name__]", transformed)
        self.assertEqual(ensure_package_markers(transformed, "example"), transformed)

    def test_preserves_bom_when_adding_missing_path_marker(self) -> None:
        source = "\ufeff__package__ = 'example'\nVALUE = 1\n"

        transformed = ensure_package_markers(source, "example")

        self.assertTrue(transformed.startswith("\ufeff"))
        self.assertIn("__path__ = [_staticpython_os.path.dirname(__file__)]", transformed)
        self.assertEqual(ensure_package_markers(transformed, "example"), transformed)


if __name__ == "__main__":
    unittest.main()
