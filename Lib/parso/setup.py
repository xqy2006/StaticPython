from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="parso",
    overlay_entries=["Lib/parso"],
    runtime_resource_paths=[
        "Lib/parso/python",
    ],
    materialized_paths=[
        "Lib/parso/python/grammar313.txt",
        "Lib/parso/python/grammar314.txt",
    ],
    verification_steps=[
        inline_verification_step(
            "parso-smoke",
            """
import parso
import sys
from pathlib import Path

module = parso.parse("def func(value):\\n    return value + 1\\n")
function = module.children[0]
grammar_dir = Path(parso.__file__).parent / "python"
current_grammar = grammar_dir / f"grammar{sys.version_info.major}{sys.version_info.minor}.txt"
assert function.name.value == "func"
assert function.get_code().startswith("def func")
assert "return value + 1" in function.get_code()
assert grammar_dir.exists()
assert current_grammar.exists()
""",
        )
    ],
)
