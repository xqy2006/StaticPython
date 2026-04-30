from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="rfc3986_validator",
    project_name="rfc3986-validator",
    source_mapping={
        "rfc3986_validator.py": "Lib/rfc3986_validator.py",
    },
    python_packages=["rfc3986_validator"],
    verification_steps=[
        inline_verification_step(
            "rfc3986-validator-smoke",
            """
from rfc3986_validator import validate_rfc3986

assert validate_rfc3986("https://example.com/staticpython")
assert validate_rfc3986("mailto:test@example.com", rule="URI")
assert not validate_rfc3986("not a uri")
""",
        )
    ],
)
