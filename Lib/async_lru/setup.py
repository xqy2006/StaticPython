from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="async_lru",
    project_name="async-lru",
    overlay_entries=["Lib/async_lru"],
    verification_steps=[
        inline_verification_step(
            "async-lru-smoke",
            """
import asyncio

from async_lru import alru_cache


calls = {"count": 0}


@alru_cache(maxsize=4)
async def cached(value):
    calls["count"] += 1
    await asyncio.sleep(0)
    return value * 2


async def main():
    first = await cached(21)
    second = await cached(21)
    info = cached.cache_info()
    assert first == 42
    assert second == 42
    assert calls["count"] == 1
    assert info.hits >= 1
    assert cached.cache_contains(21)
    assert cached.cache_invalidate(21)
    assert not cached.cache_contains(21)
    await cached.cache_close()


asyncio.run(main())
""",
        )
    ],
)
