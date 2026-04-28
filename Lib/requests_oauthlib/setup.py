from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="requests_oauthlib",
    project_name="requests-oauthlib",
    overlay_entries=["Lib/requests_oauthlib"],
    verification_steps=[
        inline_verification_step(
            "requests-oauthlib-smoke",
            """
from requests_oauthlib import OAuth1

auth = OAuth1("client-key", client_secret="client-secret")
assert auth.client.client_key == "client-key"
assert auth.client.client_secret == "client-secret"
""",
        )
    ],
)
