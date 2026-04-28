from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="responses",
    overlay_entries=["Lib/responses"],
    verification_steps=[
        inline_verification_step(
            "responses-smoke",
            """
import requests
import responses


@responses.activate
def run():
    responses.add(
        responses.GET,
        "https://example.com/api",
        json={"ok": True, "items": [1, 2]},
        status=200,
    )
    response = requests.get("https://example.com/api", timeout=1)
    assert response.status_code == 200
    assert response.json() == {"ok": True, "items": [1, 2]}
    assert len(responses.calls) == 1
    assert responses.calls[0].request.url == "https://example.com/api"


run()
""",
        )
    ],
)
