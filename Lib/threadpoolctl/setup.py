from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="threadpoolctl",
    overlay_entries=["Lib/threadpoolctl.py"],
    verification_steps=[
        inline_verification_step(
            "threadpoolctl-smoke",
            """
from threadpoolctl import ThreadpoolController, threadpool_info, threadpool_limits

assert isinstance(threadpool_info(), list)
controller = ThreadpoolController()
assert isinstance(controller.info(), list)
with threadpool_limits(limits=1):
    assert isinstance(threadpool_info(), list)
""",
        )
    ],
)
