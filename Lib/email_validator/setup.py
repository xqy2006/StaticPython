from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="email_validator",
    project_name="email-validator",
    overlay_entries=["Lib/email_validator"],
    verification_steps=[
        inline_verification_step(
            "email-validator-smoke",
            """
from email_validator import EmailNotValidError, validate_email

result = validate_email("User.Name+tag@example.com", check_deliverability=False)
assert result.normalized == "User.Name+tag@example.com"

try:
    validate_email("not an address", check_deliverability=False)
except EmailNotValidError:
    pass
else:
    raise AssertionError("invalid email was accepted")
""",
        )
    ],
)
