from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="wsproto",
    overlay_entries=["Lib/wsproto"],
    verification_steps=[
        inline_verification_step(
            "wsproto-smoke",
            """
from wsproto.frame_protocol import CloseReason, Opcode
from wsproto.utilities import generate_accept_token

token = generate_accept_token(b"dGhlIHNhbXBsZSBub25jZQ==")
assert token == b"s3pPLMBiTxaQ9kYGzzhZRbK+xOo="
assert CloseReason.NORMAL_CLOSURE == 1000
assert Opcode.TEXT == 0x1
""",
        )
    ],
)
