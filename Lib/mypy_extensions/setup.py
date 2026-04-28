from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="mypy_extensions",
    project_name="mypy-extensions",
    overlay_entries=["Lib/mypy_extensions.py"],
    verification_steps=[
        inline_verification_step(
            "mypy-extensions-smoke",
            """
from mypy_extensions import (
    Arg,
    DefaultArg,
    DefaultNamedArg,
    FlexibleAlias,
    KwArg,
    NamedArg,
    TypedDict,
    VarArg,
    i16,
    i32,
    i64,
    mypyc_attr,
    trait,
    u8,
)

class Demo(TypedDict):
    value: int

FunctionalDemo = TypedDict("FunctionalDemo", {"name": str, "count": int}, total=False)

assert Demo(value=42)["value"] == 42
assert FunctionalDemo(name="codex") == {"name": "codex"}
assert Demo.__annotations__ == {"value": int}
assert FunctionalDemo.__total__ is False
assert Arg(int) is int
assert DefaultArg(str) is str
assert NamedArg(float) is float
assert DefaultNamedArg(bytes) is bytes
assert VarArg(tuple) is tuple
assert KwArg(dict) is dict
assert FlexibleAlias[int, str][float, bytes] is str
assert i64("42") == 42 and i32(7) == 7 and i16(8) == 8 and u8(9) == 9
assert isinstance(1, i64) and isinstance(1, i32) and isinstance(1, i16) and isinstance(1, u8)
assert trait(lambda: "ok")() == "ok"
assert mypyc_attr("allow_interpreted_subclasses")(lambda: "ok")() == "ok"
""",
        )
    ],
)
