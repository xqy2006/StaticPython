from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="parso",
    overlay_entries=["Lib/parso"],
    verification_steps=[
        inline_verification_step(
            "parso-smoke",
            """
import parso

module = parso.parse("def func(value):\\n    return value + 1\\n")
function = module.children[0]
assert function.name.value == "func"
assert function.get_code().startswith("def func")
assert "return value + 1" in function.get_code()
""",
        )
    ],
)
