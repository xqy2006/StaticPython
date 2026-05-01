from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="requests",
    overlay_entries=["Lib/requests"],
    verification_steps=[
        inline_verification_step(
            "requests-smoke",
            """
from collections import OrderedDict
import requests
from requests import Request, Session
from requests.cookies import RequestsCookieJar

request = requests.Request("POST", "https://example.com/api", params=OrderedDict([("a", "1"), ("b", "2")]), json={"ok": True})
prepared = request.prepare()
assert prepared.method == "POST"
assert prepared.url == "https://example.com/api?a=1&b=2"
assert prepared.body == b'{"ok": true}'
session = requests.Session()
assert "https://" in session.adapters

cookie_jar = RequestsCookieJar()
cookie_jar.set("token", "abc", domain="example.com", path="/")
session = Session()
session.cookies = cookie_jar
prepared_with_cookie = session.prepare_request(Request("GET", "https://example.com/demo", params={"x": "1"}))
assert prepared_with_cookie.headers["Cookie"] == "token=abc"
assert prepared_with_cookie.url == "https://example.com/demo?x=1"

response = requests.Response()
response.status_code = 200
response._content = b'{"ok": true}'
response.headers["Content-Type"] = "application/json"
assert response.json() == {"ok": True}
""",
        )
    ],
)
