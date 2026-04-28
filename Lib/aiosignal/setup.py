from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="aiosignal",
    overlay_entries=["Lib/aiosignal"],
    verification_steps=[
        inline_verification_step(
            "aiosignal-smoke",
            """
import asyncio
from aiosignal import Signal

seen = []
signal = Signal(owner="owner")

async def receiver(*args, **kwargs):
    seen.append((args, kwargs))

signal.append(receiver)
signal.freeze()
asyncio.run(signal.send("sender", value=3))
assert seen == [(('sender',), {'value': 3})]
""",
        )
    ],
)
