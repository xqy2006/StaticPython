from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="docutils",
    overlay_entries=["Lib/docutils"],
    runtime_resource_paths=[
        "Lib/docutils/writers/html5_polyglot",
    ],
    verification_steps=[
        inline_verification_step(
            "docutils-smoke",
            """
from docutils.core import publish_parts

source = "Title\\n=====\\n\\n* item one\\n* item two\\n"
parts = publish_parts(
    source,
    writer_name="html5",
    settings_overrides={
        "embed_stylesheet": False,
        "stylesheet_path": "",
        "stylesheet": "",
        "template": str((__import__("docutils").__file__ and (__import__("pathlib").Path(__import__("docutils").__file__).resolve().parent / "writers" / "html5_polyglot" / "template.txt"))),
    },
)
html = parts["html_body"]
assert "<h1" in html and "Title" in html
assert "item one" in html and "item two" in html
""",
        )
    ],
)
