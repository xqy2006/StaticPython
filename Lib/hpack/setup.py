from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="hpack",
    overlay_entries=["Lib/hpack"],
    verification_steps=[
        inline_verification_step(
            "hpack-smoke",
            """
from hpack import Decoder, Encoder

headers = [(b":method", b"GET"), (b":path", b"/")]
encoded = Encoder().encode(headers)
assert Decoder().decode(encoded) == [(":method", "GET"), (":path", "/")]
""",
        )
    ],
)
