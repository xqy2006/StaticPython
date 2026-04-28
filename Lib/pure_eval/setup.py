from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="pure_eval",
    project_name="pure-eval",
    overlay_entries=["Lib/pure_eval"],
    verification_steps=[
        inline_verification_step(
            "pure-eval-smoke",
            """
import ast
from pure_eval import CannotEval, Evaluator, group_expressions, is_expression_interesting

items = [1, 2, 3]
evaluator = Evaluator({"value": 10, "items": items, "len": len})
expr = ast.parse("value + len(items) + items[0]", mode="eval").body
assert evaluator[expr] == 14

try:
    evaluator[ast.parse("setattr(items, 'x', 1)", mode="eval").body]
except CannotEval:
    pass
else:
    raise AssertionError("unsafe call unexpectedly evaluated")

first = ast.parse("items[0]", mode="eval").body
second = ast.parse("items[0]", mode="eval").body
groups = group_expressions([(first, 1), (second, 1)])
assert len(groups) == 1
assert len(groups[0][0]) == 2
assert not is_expression_interesting(ast.parse("123", mode="eval").body, 123)
""",
        )
    ],
)
