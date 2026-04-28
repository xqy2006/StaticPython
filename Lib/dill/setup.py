from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="dill",
    overlay_entries=["Lib/dill"],
    verification_steps=[
        inline_verification_step(
            "dill-smoke",
            """
import dill

state = {"base": 40}

def add_from_state(value):
    return state["base"] + value

func = dill.loads(dill.dumps(lambda value: value * 3))
stateful = dill.loads(dill.dumps(add_from_state))
assert func(14) == 42
assert stateful(2) == 42
""",
        )
    ],
)
