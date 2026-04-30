from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='attrs',
    overlay_entries=['Lib/attrs', 'Lib/attr'],
    python_packages=['attrs', 'attr'],
    verification_steps=[
        inline_verification_step(
            "attrs-smoke",
            """
import attrs

@attrs.define(frozen=True)
class Point:
    x: int = attrs.field(validator=attrs.validators.ge(0))
    y: int = 0

point = Point(1, 2)
assert attrs.asdict(point) == {"x": 1, "y": 2}
assert attrs.evolve(point, y=3).y == 3
""",
        )
    ],
)
