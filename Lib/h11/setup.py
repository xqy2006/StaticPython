from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='h11',
    overlay_entries=['Lib/h11'],
    verification_steps=[
        inline_verification_step(
            "h11-smoke",
            """
import h11

conn = h11.Connection(h11.CLIENT)
data = conn.send(h11.Request(method="GET", target="/", headers=[("host", "example.com")]))
assert b"GET / HTTP/1.1" in data
assert conn.our_state is h11.SEND_BODY
conn.send(h11.EndOfMessage())
assert conn.our_state is h11.DONE
""",
        )
    ],
)
