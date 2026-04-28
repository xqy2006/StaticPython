from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='typing_extensions',
    overlay_entries=['Lib/typing_extensions.py'],
    verification_steps=[
        inline_verification_step(
            "typing-extensions-smoke",
            """
from typing_extensions import Annotated, Literal, TypedDict, get_args, get_origin

class Demo(TypedDict):
    value: int

assert Demo(value=1)["value"] == 1
annotated = Annotated[int, "meta"]
assert get_origin(annotated) is Annotated
assert get_args(annotated) == (int, "meta")
assert get_args(Literal["a", "b"]) == ("a", "b")
""",
        )
    ],
)
