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
    async with send, receive:
        await send.send("ok")
        value = await receive.receive()

    seen = []

    async def child():
        seen.append(anyio.get_current_task().name is not None)

    async with anyio.create_task_group() as group:
        group.start_soon(child)

    return value, seen

assert anyio.run(worker) == ("ok", [True])
""",
        )
    ],
)
