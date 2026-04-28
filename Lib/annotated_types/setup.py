from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="annotated_types",
    project_name="annotated-types",
    overlay_entries=["Lib/annotated_types"],
    verification_steps=[
        inline_verification_step(
            "annotated-types-smoke",
            """
from typing import Annotated

from annotated_types import Ge, Len

field = Annotated[str, Len(min_length=2), Ge("aa")]
metadata = field.__metadata__
assert isinstance(metadata[0], Len)
assert metadata[0].min_length == 2
assert metadata[1].ge == "aa"
""",
        )
    ],
)
