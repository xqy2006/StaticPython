from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="jedi",
    overlay_entries=["Lib/jedi"],
    verification_steps=[
        inline_verification_step(
            "jedi-smoke",
            """
import jedi

script = jedi.Script("import math\\nmath.sq")
completions = script.complete(2, 7)
assert any(item.name == "sqrt" for item in completions)
""",
        )
    ],
)
