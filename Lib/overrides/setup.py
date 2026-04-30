from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="overrides",
    overlay_entries=["Lib/overrides"],
    verification_steps=[
        inline_verification_step(
            "overrides-smoke",
            """
from overrides import override


class Base:
    def value(self):
        return "base"


class Child(Base):
    @override
    def value(self):
        return "child"


assert Child().value() == "child"
assert Base().value() == "base"
""",
        )
    ],
)
