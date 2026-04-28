from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='httpcore',
    overlay_entries=['Lib/httpcore'],
    verification_steps=[
        inline_verification_step(
            "httpcore-smoke",
            """
import httpcore

origin = httpcore.Origin(b"https", b"example.com", 443)
assert origin.scheme == b"https"
assert origin.host == b"example.com"
assert origin.port == 443
assert issubclass(httpcore.ConnectError, httpcore.NetworkError)
""",
        )
    ],
)
