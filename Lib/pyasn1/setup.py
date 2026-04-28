from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="pyasn1",
    overlay_entries=["Lib/pyasn1"],
    verification_steps=[
        inline_verification_step(
            "pyasn1-smoke",
            """
from pyasn1.codec.der.decoder import decode
from pyasn1.codec.der.encoder import encode
from pyasn1.type.univ import Integer

encoded = encode(Integer(42))
decoded, rest = decode(encoded, asn1Spec=Integer())
assert int(decoded) == 42
assert rest == b""
""",
        )
    ],
)
