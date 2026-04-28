from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="cloudpickle",
    overlay_entries=["Lib/cloudpickle"],
    verification_steps=[
        inline_verification_step(
            "cloudpickle-smoke",
            """
import cloudpickle

factor = 40

def make_adder(delta):
    return lambda value: value + delta + factor

class LocalGreeter:
    def __init__(self, prefix):
        self.prefix = prefix

    def greet(self, name):
        return f"{self.prefix} {name}"

func = cloudpickle.loads(cloudpickle.dumps(make_adder(1)))
greeter = cloudpickle.loads(cloudpickle.dumps(LocalGreeter("hi")))
assert func(1) == 42
assert greeter.greet("codex") == "hi codex"
""",
        )
    ],
)
