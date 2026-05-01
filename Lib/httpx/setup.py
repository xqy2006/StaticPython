from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="httpx",
    overlay_entries=["Lib/httpx"],
    verification_steps=[
        inline_verification_step(
            "httpx-smoke",
            """
import asyncio
import httpx

transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"path": request.url.path}))
with httpx.Client(transport=transport, base_url="https://example.com") as client:
    response = client.get("/demo")
assert response.status_code == 200
assert response.json() == {"path": "/demo"}

async def main():
    async def handler(request):
        assert request.url.params["q"] == "x"
        return httpx.Response(201, headers={"X-Test": "ok"}, json={"path": request.url.path})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://example.com") as client:
        response = await client.get("/items", params={"q": "x"})
        assert response.status_code == 201
        assert response.headers["X-Test"] == "ok"
        assert response.json() == {"path": "/items"}

asyncio.run(main())
""",
        )
    ],
)
