from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="outcome",
    overlay_entries=["Lib/outcome"],
    verification_steps=[
        inline_verification_step(
            "outcome-smoke",
            """
import outcome

value = outcome.capture(lambda: 42)
assert isinstance(value, outcome.Value)
assert value.unwrap() == 42

error = outcome.capture(lambda: 1 / 0)
assert isinstance(error, outcome.Error)
try:
    error.unwrap()
except ZeroDivisionError:
    pass
else:
    raise AssertionError("outcome did not re-raise captured error")
""",
        )
    ],
)
