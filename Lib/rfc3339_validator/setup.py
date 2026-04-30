from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="rfc3339_validator",
    project_name="rfc3339-validator",
    source_mapping={
        "rfc3339_validator.py": "Lib/rfc3339_validator.py",
    },
    python_packages=["rfc3339_validator"],
    verification_steps=[
        inline_verification_step(
            "rfc3339-validator-smoke",
            """
from rfc3339_validator import validate_rfc3339

assert validate_rfc3339("2024-01-01T00:00:00Z")
assert validate_rfc3339("2024-01-01T00:00:00+08:00")
assert not validate_rfc3339("2024-13-01T00:00:00Z")
assert not validate_rfc3339("not-a-timestamp")
""",
        )
    ],
)
