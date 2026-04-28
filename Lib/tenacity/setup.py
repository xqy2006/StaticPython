from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='tenacity',
    overlay_entries=['Lib/tenacity'],
    verification_steps=[
        inline_verification_step(
            "tenacity-smoke",
            """
from tenacity import retry, retry_if_exception_type, stop_after_attempt

calls = []
@retry(stop=stop_after_attempt(3), retry=retry_if_exception_type(ValueError), reraise=True)
def flaky():
    calls.append(1)
    if len(calls) < 2:
        raise ValueError("try again")
    return "ok"

assert flaky() == "ok"
assert len(calls) == 2
""",
        )
    ],
)
