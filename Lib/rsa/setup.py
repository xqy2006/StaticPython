from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="rsa",
    overlay_entries=["Lib/rsa"],
    verification_steps=[
        inline_verification_step(
            "rsa-smoke",
            """
import rsa

public_key, private_key = rsa.newkeys(512)
message = b"staticpython"
signature = rsa.sign(message, private_key, "SHA-256")
rsa.verify(message, signature, public_key)
encrypted = rsa.encrypt(message, public_key)
assert rsa.decrypt(encrypted, private_key) == message
""",
        )
    ],
)
