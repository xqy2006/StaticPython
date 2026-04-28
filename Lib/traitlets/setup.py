from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="traitlets",
    overlay_entries=["Lib/traitlets"],
    verification_steps=[
        inline_verification_step(
            "traitlets-smoke",
            """
from traitlets import HasTraits, Int, TraitError

class Counter(HasTraits):
    value = Int(0)

seen = []
counter = Counter()
counter.observe(lambda change: seen.append(change["new"]), names="value")
counter.value = 5
assert seen == [5]
try:
    counter.value = "bad"
except TraitError:
    pass
else:
    raise AssertionError("traitlets accepted a non-integer value")
""",
        )
    ],
)
