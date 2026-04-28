from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="typing_inspect",
    project_name="typing-inspect",
    overlay_entries=["Lib/typing_inspect.py"],
    verification_steps=[
        inline_verification_step(
            "typing-inspect-smoke",
            """
from typing import List, Optional, Union

from typing_inspect import get_args, get_origin, is_optional_type, is_union_type

assert get_origin(List[int]) is list
assert get_args(List[int]) == (int,)
assert is_optional_type(Optional[int])
assert is_union_type(Union[int, str])
""",
        )
    ],
)
