from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="frozenlist",
    overlay_entries=["Lib/frozenlist"],
    verification_steps=[
        inline_verification_step(
            "frozenlist-smoke",
            """
from frozenlist import FrozenList

items = FrozenList([1])
items.append(2)
items.freeze()
assert list(items) == [1, 2]
assert items.frozen
try:
    items.append(3)
except RuntimeError:
    pass
else:
    raise AssertionError("FrozenList allowed mutation after freeze")
""",
        )
    ],
)
