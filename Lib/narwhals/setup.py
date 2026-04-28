from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="narwhals",
    overlay_entries=["Lib/narwhals"],
    verification_steps=[
        inline_verification_step(
            "narwhals-smoke",
            """
import narwhals
from narwhals.dependencies import is_into_dataframe

assert callable(narwhals.from_native)
assert narwhals.Int64.__name__ == "Int64"
assert is_into_dataframe({"a": [1, 2]}) is False
""",
        )
    ],
)
