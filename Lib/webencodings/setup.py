from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="webencodings",
    overlay_entries=["Lib/webencodings"],
    verification_steps=[
        inline_verification_step(
            "webencodings-smoke",
            """
from webencodings import ascii_lower, lookup

assert ascii_lower("UTF-8") == "utf-8"
assert lookup("utf-8").name == "utf-8"
""",
        )
    ],
)
