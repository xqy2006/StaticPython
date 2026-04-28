from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='annotated_doc',
    overlay_entries=['Lib/annotated_doc'],
    verification_steps=[
        inline_verification_step(
            "annotated-doc-smoke",
            """
from annotated_doc import Doc

marker = Doc("primary key")
assert marker.documentation == "primary key"
assert repr(marker) == "Doc('primary key')"
""",
        )
    ],
)
