from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="cloudpickle",
    overlay_entries=["Lib/cloudpickle"],
    verification_steps=[
        inline_verification_step(
            "cloudpickle-smoke",
            """
import cloudpickle

func = cloudpickle.loads(cloudpickle.dumps(lambda value: value + 41))
assert func(1) == 42
""",
        )
    ],
)
