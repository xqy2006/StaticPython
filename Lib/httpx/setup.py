from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='httpx',
    overlay_entries=['Lib/httpx'],
    verification_steps=[
        inline_verification_step(
            "httpx-smoke",
            """
import httpx

transport = httpx.MockTransport(lambda request: httpx.Response(200, json={"path": request.url.path}))
with httpx.Client(transport=transport, base_url="https://example.com") as client:
    response = client.get("/demo")
assert response.status_code == 200
assert response.json() == {"path": "/demo"}
""",
        )
    ],
)
