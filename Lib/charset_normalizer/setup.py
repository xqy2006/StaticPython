from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='charset_normalizer',
    overlay_entries=['Lib/charset_normalizer'],
    verification_steps=[
        inline_verification_step(
            "charset-normalizer-smoke",
            """
from charset_normalizer import from_bytes

result = from_bytes(b"caf\\xc3\\xa9").best()
assert result is not None
assert "utf" in result.encoding.lower()
assert str(result) == "cafe" or str(result) == "caf\u00e9"
""",
        )
    ],
)
