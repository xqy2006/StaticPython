from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="hypothesis",
    source_mapping={
        "_hypothesis_globals.py": "Lib/_hypothesis_globals.py",
        "hypothesis": "Lib/hypothesis",
    },
    verification_steps=[
        inline_verification_step(
            "hypothesis-smoke",
            """
from hypothesis import given, settings
from hypothesis import strategies as st

seen = []

@settings(max_examples=5, derandomize=True)
@given(st.integers(min_value=0, max_value=10))
def check(value):
    seen.append(value)
    assert value >= 0

check()
assert seen
""",
        )
    ],
)
