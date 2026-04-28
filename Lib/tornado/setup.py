from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="tornado",
    overlay_entries=["Lib/tornado"],
    verification_steps=[
        inline_verification_step(
            "tornado-smoke",
            """
from tornado.escape import json_decode, json_encode
from tornado.httputil import url_concat

assert json_decode(json_encode({"ok": True})) == {"ok": True}
assert url_concat("https://example.com/api", {"q": "static python"}) == "https://example.com/api?q=static+python"
""",
        )
    ],
)
