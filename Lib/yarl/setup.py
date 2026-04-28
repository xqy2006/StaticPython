from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="yarl",
    overlay_entries=["Lib/yarl"],
    verification_steps=[
        inline_verification_step(
            "yarl-smoke",
            """
from yarl import URL

url = URL("https://example.com") / "api" % {"q": "static python"}
assert str(url) == "https://example.com/api?q=static+python"
assert url.with_scheme("http").scheme == "http"
assert URL("/a/b").parts == ("/", "a", "b")
""",
        )
    ],
)
