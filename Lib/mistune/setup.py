from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='mistune',
    overlay_entries=['Lib/mistune'],
    verification_steps=[
        inline_verification_step(
            "mistune-smoke",
            """
import mistune

html = mistune.html("# Title\\n\\n**bold**")
assert "<h1>Title</h1>" in html
assert "<strong>bold</strong>" in html
renderer = mistune.create_markdown()
assert "<p>demo</p>" in renderer("demo")
""",
        )
    ],
)
