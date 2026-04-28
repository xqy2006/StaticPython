from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='mdurl',
    overlay_entries=['Lib/mdurl'],
    verification_steps=[
        inline_verification_step(
            "mdurl-smoke",
            """
from mdurl import decode, encode, parse

assert encode("a b") == "a%20b"
assert decode("a%20b") == "a b"
parsed = parse("https://user:pass@example.com:443/a?b=1#frag")
assert parsed.protocol == "https:"
assert parsed.hostname == "example.com"
assert parsed.pathname == "/a"
""",
        )
    ],
)
