from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="pure_eval",
    project_name="pure-eval",
    overlay_entries=["Lib/pure_eval"],
    verification_steps=[
        inline_verification_step(
            "pure-eval-smoke",
            """
import pure_eval

assert hasattr(pure_eval, "Evaluator")
assert hasattr(pure_eval, "CannotEval")
""",
        )
    ],
)
