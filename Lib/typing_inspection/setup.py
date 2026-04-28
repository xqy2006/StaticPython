from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="typing_inspection",
    project_name="typing-inspection",
    overlay_entries=["Lib/typing_inspection"],
    verification_steps=[
        inline_verification_step(
            "typing-inspection-smoke",
            """
from typing import Literal, Union

from typing_inspection.introspection import get_literal_values
from typing_inspection.typing_objects import is_union

assert list(get_literal_values(Literal["a", "b"])) == ["a", "b"]
assert is_union(Union)
""",
        )
    ],
)
