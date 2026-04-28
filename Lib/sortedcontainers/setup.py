from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="sortedcontainers",
    overlay_entries=["Lib/sortedcontainers"],
    verification_steps=[
        inline_verification_step(
            "sortedcontainers-smoke",
            """
from sortedcontainers import SortedDict, SortedList

values = SortedList([3, 1, 2])
assert list(values) == [1, 2, 3]
mapping = SortedDict({"b": 2, "a": 1})
assert list(mapping.items()) == [("a", 1), ("b", 2)]
""",
        )
    ],
)
