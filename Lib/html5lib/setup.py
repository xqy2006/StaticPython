from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="html5lib",
    overlay_entries=["Lib/html5lib"],
    verification_steps=[
        inline_verification_step(
            "html5lib-smoke",
            """
import html5lib

document = html5lib.parse("<!doctype html><title>StaticPython</title><p>ok</p>")
html = document.find("{http://www.w3.org/1999/xhtml}head")
title = html.find("{http://www.w3.org/1999/xhtml}title")
assert title.text == "StaticPython"
""",
        )
    ],
)
