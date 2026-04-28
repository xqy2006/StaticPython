from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="joblib",
    overlay_entries=["Lib/joblib"],
    verification_steps=[
        inline_verification_step(
            "joblib-smoke",
            """
from joblib import Parallel, delayed, hash
from joblib.memory import Memory

assert Parallel(n_jobs=1)(delayed(lambda value: value * value)(item) for item in range(4)) == [0, 1, 4, 9]
assert hash({"static": "python"})
memory = Memory(location=None, verbose=0)

@memory.cache
def add(a, b):
    return a + b

assert add(2, 5) == 7
""",
        )
    ],
)
