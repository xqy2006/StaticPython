from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="websocket",
    project_name="websocket-client",
    overlay_entries=["Lib/websocket"],
    verification_steps=[
        inline_verification_step(
            "websocket-client-smoke",
            """
from websocket import ABNF
from websocket._url import parse_url

frame = ABNF.create_frame("hello", ABNF.OPCODE_TEXT)
frame.validate(skip_utf8_validation=False)
assert frame.opcode == ABNF.OPCODE_TEXT
assert frame.data == b"hello"
host, port, resource, secure = parse_url("wss://example.com/chat")
assert (host, port, resource, secure) == ("example.com", 443, "/chat", True)
""",
        )
    ],
)
