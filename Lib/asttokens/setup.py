from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="asttokens",
    overlay_entries=["Lib/asttokens"],
    verification_steps=[
        inline_verification_step(
            "asttokens-smoke",
            """
import asttokens

tokens = asttokens.ASTTokens("x = 1 + 2", parse=True)
assign = tokens.tree.body[0]
assert tokens.get_text(assign.value) == "1 + 2"
""",
        )
    ],
)
