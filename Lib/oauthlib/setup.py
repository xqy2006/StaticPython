from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="oauthlib",
    overlay_entries=["Lib/oauthlib"],
    verification_steps=[
        inline_verification_step(
            "oauthlib-smoke",
            """
from oauthlib.oauth2 import WebApplicationClient

client = WebApplicationClient("client-id")
url = client.prepare_request_uri(
    "https://example.com/authorize",
    redirect_uri="https://client.example/callback",
    scope=["profile", "email"],
    state="state",
)
assert "client_id=client-id" in url
assert "response_type=code" in url
assert "scope=profile+email" in url
""",
        )
    ],
)
