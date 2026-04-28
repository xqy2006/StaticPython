from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="executing",
    overlay_entries=["Lib/executing"],
    verification_steps=[
        inline_verification_step(
            "executing-smoke",
            """
import sys
from executing import Source

source = Source.for_frame(sys._getframe())
assert source is not None
assert hasattr(source, "executing")
""",
        )
    ],
)
