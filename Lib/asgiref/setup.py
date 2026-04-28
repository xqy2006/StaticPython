from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='asgiref',
    overlay_entries=['Lib/asgiref'],
    verification_steps=[
        inline_verification_step(
            "asgiref-smoke",
            """
import asyncio
from asgiref.sync import async_to_sync, sync_to_async

async def add(a, b):
    return a + b

def mul(a, b):
    return a * b

assert async_to_sync(add)(2, 3) == 5
assert asyncio.run(sync_to_async(mul)(4, 5)) == 20
""",
        )
    ],
)
