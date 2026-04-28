from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="pytokens",
    overlay_entries=["Lib/pytokens"],
    verification_steps=[
        inline_verification_step(
            "pytokens-smoke",
            """
from pytokens import TokenType, tokenize

tokens = list(tokenize("value = 42\\n"))
assert tokens[0].type is TokenType.identifier
assert tokens[0].start_index == 0
assert any(token.type is TokenType.number for token in tokens)
""",
        )
    ],
)
