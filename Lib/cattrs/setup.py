from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='cattrs',
    overlay_entries=['Lib/cattrs'],
    verification_steps=[
        inline_verification_step(
            "cattrs-smoke",
            """
import attrs
import cattrs

@attrs.define
class Item:
    value: int

converter = cattrs.Converter()
item = converter.structure({"value": 11}, Item)
assert item.value == 11
assert converter.unstructure(item) == {"value": 11}
""",
        )
    ],
)
