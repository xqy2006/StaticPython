from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="more_itertools",
    project_name="more-itertools",
    overlay_entries=["Lib/more_itertools"],
    verification_steps=[
        inline_verification_step(
            "more-itertools-smoke",
            """
from more_itertools import chunked, flatten, pairwise

assert list(chunked([1, 2, 3, 4], 2)) == [[1, 2], [3, 4]]
assert list(flatten([[1, 2], [3]])) == [1, 2, 3]
assert list(pairwise([1, 2, 3])) == [(1, 2), (2, 3)]
""",
        )
    ],
)
