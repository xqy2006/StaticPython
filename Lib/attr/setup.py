from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='attr',
    overlay_entries=['Lib/attr'],
    verification_steps=[
        inline_verification_step(
            "attr-smoke",
            """
import attr

@attr.s(auto_attribs=True, slots=True)
class Item:
    value: int = attr.ib(validator=attr.validators.instance_of(int))

item = Item(5)
assert attr.asdict(item) == {"value": 5}
assert attr.evolve(item, value=6).value == 6
""",
        )
    ],
)
