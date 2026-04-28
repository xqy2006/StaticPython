from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="dill",
    overlay_entries=["Lib/dill"],
    verification_steps=[
        inline_verification_step(
            "dill-smoke",
            """
import dill

func = dill.loads(dill.dumps(lambda value: value * 3))
assert func(14) == 42
""",
        )
    ],
)
