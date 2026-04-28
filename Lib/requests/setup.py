from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='requests',
    overlay_entries=['Lib/requests'],
    verification_steps=[
        inline_verification_step(
            "requests-smoke",
            """
from collections import OrderedDict
import requests

request = requests.Request("POST", "https://example.com/api", params=OrderedDict([("a", "1"), ("b", "2")]), json={"ok": True})
prepared = request.prepare()
assert prepared.method == "POST"
assert prepared.url == "https://example.com/api?a=1&b=2"
assert prepared.body == b'{"ok": true}'
session = requests.Session()
assert "https://" in session.adapters
""",
        )
    ],
)
