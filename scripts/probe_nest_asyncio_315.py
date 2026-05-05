from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path

import anyio
import sniffio
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


def _prepend_patch_root() -> None:
    patch_file = os.environ.get("STATICPYTHON_NEST_ASYNCIO_PATCH")
    if not patch_file:
        return
    patch_path = Path(patch_file).resolve()
    spec = importlib.util.spec_from_file_location("nest_asyncio", patch_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"failed to load patched nest_asyncio from {patch_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules["nest_asyncio"] = module
    spec.loader.exec_module(module)


_prepend_patch_root()

import nest_asyncio


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
    print("nest_asyncio_file", nest_asyncio.__file__)
    print("phase", "before_apply_anyio", anyio.run(probe))
    nest_asyncio.apply()
    print("phase", "nested_loop", asyncio.get_event_loop().run_until_complete(outer()))
    print("phase", "after_apply_anyio", anyio.run(probe))
    app = Starlette(routes=[Route("/", homepage)])
    with TestClient(app) as client:
        response = client.get("/")
        print("phase", "starlette", response.status_code, response.text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
