from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="starlette",
    overlay_entries=["Lib/starlette"],
    verification_steps=[
        inline_verification_step(
            "starlette-smoke",
            """
import anyio
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route
from starlette.testclient import TestClient


async def homepage(request):
    return PlainTextResponse("staticpython")


app = Starlette(routes=[Route("/", homepage)])
with TestClient(app) as client:
    response = client.get("/")
    assert response.status_code == 200
    assert response.text == "staticpython"

async def run_task():
    return "ok"

assert anyio.run(run_task) == "ok"
""",
        )
    ],
)
