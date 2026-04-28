from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="requests_toolbelt",
    project_name="requests-toolbelt",
    overlay_entries=["Lib/requests_toolbelt"],
    verification_steps=[
        inline_verification_step(
            "requests-toolbelt-smoke",
            """
import requests
from requests_toolbelt import MultipartEncoder
from requests_toolbelt.sessions import BaseUrlSession

encoder = MultipartEncoder(
    fields={
        "field": "value",
        "file": ("demo.txt", b"payload", "text/plain"),
    }
)
body = encoder.to_string()
assert encoder.content_type.startswith("multipart/form-data; boundary=")
assert b'name="field"' in body
assert b'filename="demo.txt"' in body
assert b"payload" in body

session = BaseUrlSession(base_url="https://example.com/api/")
request = requests.Request("GET", "users", params={"q": "codex"})
prepared = session.prepare_request(request)
assert prepared.url == "https://example.com/api/users?q=codex"
""",
        )
    ],
)
