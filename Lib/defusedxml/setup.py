from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="defusedxml",
    overlay_entries=["Lib/defusedxml"],
    verification_steps=[
        inline_verification_step(
            "defusedxml-smoke",
            """
from defusedxml import ElementTree

root = ElementTree.fromstring("<root><child value='1'/></root>")
assert root.tag == "root"
assert root[0].attrib["value"] == "1"
""",
        )
    ],
)
