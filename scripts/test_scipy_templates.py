from __future__ import annotations

import ast
import math
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]


def load_template_function(path: Path, name: str, globals_: dict):
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    function = next(
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name
    )
    namespace = dict(globals_)
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    return namespace[name]


class OptimizeTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bracket = staticmethod(
            load_template_function(
                REPO_ROOT / "Lib" / "scipy" / "optimize_template.py",
                "bracket",
                {
                    "math": math,
                    "_ensure_tuple": lambda value: (
                        value if isinstance(value, tuple) else (value,)
                    ),
                },
            )
        )

    def test_bracket_reports_function_calls(self) -> None:
        calls: list[float] = []

        def objective(value: float) -> float:
            calls.append(value)
            return (value - 2.0) ** 2

        result = self.bracket(objective, xa=0.0, xb=1.0)

        self.assertEqual(len(result), 7)
        xa, xb, xc, fa, fb, fc, funcalls = result
        self.assertLess(xa, xb)
        self.assertLess(xb, xc)
        self.assertLess(fb, fa)
        self.assertLess(fb, fc)
        self.assertEqual(funcalls, len(calls))

    def test_bracket_grow_limit_is_bounded_and_fails_closed(self) -> None:
        calls: list[float] = []

        def decreasing(value: float) -> float:
            calls.append(value)
            return -value

        with self.assertRaisesRegex(RuntimeError, "grow_limit"):
            self.bracket(
                decreasing,
                xa=0.0,
                xb=1.0,
                grow_limit=3.0,
                maxiter=1000,
            )

        self.assertLess(len(calls), 10)


class SparseLinalgTemplateTests(unittest.TestCase):
    def test_cg_counts_attempted_iteration_before_breakdown(self) -> None:
        source = (
            REPO_ROOT / "Lib" / "scipy" / "sparse_linalg_template.py"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "iterations += 1\n        matvec = operator.matvec(direction)",
            source,
        )
        self.assertEqual(source.count("return x, iterations"), 3)
        self.assertNotIn("return x, -1", source)


if __name__ == "__main__":
    unittest.main()
