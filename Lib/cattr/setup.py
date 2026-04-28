from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='cattr',
    overlay_entries=['Lib/cattr'],
    verification_steps=[
        inline_verification_step(
            "cattr-smoke",
            """
import attr
import cattr

@attr.s(auto_attribs=True)
class Item:
    value: int

item = cattr.structure({"value": 9}, Item)
assert item.value == 9
assert cattr.unstructure(item) == {"value": 9}
""",
        )
    ],
)
