from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="docutils",
    overlay_entries=["Lib/docutils"],
    verification_steps=[
        inline_verification_step(
            "docutils-smoke",
            """
from docutils.core import publish_parts

source = "Title\\n=====\\n\\n* item one\\n* item two\\n"
parts = publish_parts(source, writer_name="html5")
html = parts["html_body"]
assert "<h1" in html and "Title" in html
assert "item one" in html and "item two" in html
""",
        )
    ],
)
