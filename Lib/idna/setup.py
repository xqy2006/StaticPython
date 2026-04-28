from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='idna',
    overlay_entries=['Lib/idna'],
    verification_steps=[
        inline_verification_step(
            "idna-smoke",
            """
import idna

unicode_domain = "\u4f8b\u5b50.\u6d4b\u8bd5"
punycode = idna.encode(unicode_domain).decode("ascii")
assert punycode == "xn--fsqu00a.xn--0zwm56d"
assert idna.decode(punycode) == unicode_domain
assert idna.encode("example.com").decode("ascii") == "example.com"
""",
        )
    ],
)
