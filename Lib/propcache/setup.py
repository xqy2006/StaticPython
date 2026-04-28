from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="propcache",
    overlay_entries=["Lib/propcache"],
    verification_steps=[
        inline_verification_step(
            "propcache-smoke",
            """
from propcache import cached_property, under_cached_property

class Demo:
    def __init__(self):
        self.calls = 0
        self._cache = {}

    @cached_property
    def value(self):
        self.calls += 1
        return self.calls

    @under_cached_property
    def under_value(self):
        self.calls += 10
        return self.calls

obj = Demo()
assert obj.value == 1
assert obj.value == 1
assert obj.under_value == 11
assert obj.under_value == 11
""",
        )
    ],
)
