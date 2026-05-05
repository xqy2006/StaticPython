from __future__ import annotations

import asyncio

import anyio
import nest_asyncio
import sniffio
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


async def inner() -> str:
    return "ok"


async def outer() -> str:
    loop = asyncio.get_event_loop()
    return loop.run_until_complete(inner())


async def probe() -> str:
    return sniffio.current_async_library()


async def homepage(request):
    return PlainTextResponse("staticpython")


def main() -> int:
    if anyio.run(probe) != "asyncio":
        raise AssertionError("anyio did not report asyncio before nest_asyncio.apply()")
    nest_asyncio.apply()
    if asyncio.get_event_loop().run_until_complete(outer()) != "ok":
        raise AssertionError("nested event loop execution failed")
    if anyio.run(probe) != "asyncio":
        raise AssertionError("anyio/sniffio no longer works after nest_asyncio.apply()")
    app = Starlette(routes=[Route("/", homepage)])
    with TestClient(app) as client:
        response = client.get("/")
    if response.status_code != 200 or response.text != "staticpython":
        raise AssertionError(f"unexpected starlette response: {response.status_code} {response.text!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
