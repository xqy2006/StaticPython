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
encoder = Encoder()
encoded = encoder.encode(headers)
decoder = Decoder()
assert decoder.decode(encoded) == [(":method", "GET"), (":path", "/")]
encoded_response = encoder.encode([(":status", "200"), ("content-type", "text/plain")])
assert decoder.decode(encoded_response) == [(":status", "200"), ("content-type", "text/plain")]
""",
        )
    ],
)
