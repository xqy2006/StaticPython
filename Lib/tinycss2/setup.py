from libs import inline_verification_step, replace_text_all, simple_library, transform_source_text


def patch_tinycss2_sources(context):
    def patch_color4(text: str) -> str:
        updated = replace_text_all(text, "_κ", "_KAPPA")
        updated = replace_text_all(updated, "_ε", "_EPSILON")
        return updated

    transform_source_text(context, "Lib/tinycss2/color4.py", patch_color4)


LIBRARY_INTEGRATION = simple_library(
    name="tinycss2",
    overlay_entries=["Lib/tinycss2"],
    post_patch_hooks=[patch_tinycss2_sources],
    verification_steps=[
        inline_verification_step(
            "tinycss2-smoke",
            """
from tinycss2 import parse_stylesheet, serialize

rules = parse_stylesheet("h1 { color: red; margin: 0 }", skip_whitespace=True)
assert rules and rules[0].type == "qualified-rule"
assert "color" in serialize(rules[0].content)
""",
        )
    ],
)
