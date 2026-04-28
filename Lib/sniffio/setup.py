from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='sniffio',
    overlay_entries=['Lib/sniffio'],
    verification_steps=[
        inline_verification_step(
            "sniffio-smoke",
            """
import anyio
import sniffio

async def probe():
    return sniffio.current_async_library()

assert anyio.run(probe) == "asyncio"
try:
    sniffio.current_async_library()
except sniffio.AsyncLibraryNotFoundError:
    pass
else:
    raise AssertionError("sniffio detected an async library outside async context")
""",
        )
    ],
)
