from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='anyio',
    overlay_entries=['Lib/anyio'],
    verification_steps=[
        inline_verification_step(
            "anyio-smoke",
            """
import anyio

async def worker():
    send, receive = anyio.create_memory_object_stream(1)
    await send.send("ok")
    return await receive.receive()

assert anyio.run(worker) == "ok"
""",
        )
    ],
)
