from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='markdown_it',
    overlay_entries=['Lib/markdown_it'],
    verification_steps=[
        inline_verification_step(
            "markdown-it-smoke",
            """
from markdown_it import MarkdownIt

md = MarkdownIt()
html = md.render("**bold**\\n\\n[link](https://example.com)")
assert "<strong>bold</strong>" in html
assert 'href="https://example.com"' in html
""",
        )
    ],
)
