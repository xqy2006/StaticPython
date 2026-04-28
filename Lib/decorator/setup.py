from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="decorator",
    overlay_entries=["Lib/decorator.py"],
    verification_steps=[
        inline_verification_step(
            "decorator-smoke",
            """
from decorator import decorator

@decorator
def traced(func, *args, **kwargs):
    return ("called", func(*args, **kwargs))

@traced
def add(a, b):
    return a + b

assert add(2, 4) == ("called", 6)
assert add.__name__ == "add"
""",
        )
    ],
)
