from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="stack_data",
    project_name="stack-data",
    overlay_entries=["Lib/stack_data"],
    verification_steps=[
        inline_verification_step(
            "stack-data-smoke",
            """
import stack_data

assert hasattr(stack_data, "FrameInfo")
assert hasattr(stack_data, "Source")
""",
        )
    ],
)
