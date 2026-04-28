from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="parso",
    overlay_entries=["Lib/parso"],
    verification_steps=[
        inline_verification_step(
            "parso-smoke",
            """
import parso

module = parso.parse("value = 42\\n")
assert module.children[0].get_code().strip() == "value = 42"
""",
        )
    ],
)
