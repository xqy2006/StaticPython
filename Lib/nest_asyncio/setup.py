from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="nest_asyncio",
    project_name="nest-asyncio",
    source_mapping={
        "nest_asyncio.py": "Lib/nest_asyncio.py",
    },
    python_packages=["nest_asyncio"],
    verification_steps=[
        inline_verification_step(
            "nest-asyncio-smoke",
            """
import asyncio

import nest_asyncio


async def inner():
    return "ok"


async def outer():
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(inner())


nest_asyncio.apply()
assert asyncio.get_event_loop().run_until_complete(outer()) == "ok"
""",
        )
    ],
)
