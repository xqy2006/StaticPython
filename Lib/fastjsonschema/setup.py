from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="fastjsonschema",
    overlay_entries=["Lib/fastjsonschema"],
    verification_steps=[
        inline_verification_step(
            "fastjsonschema-smoke",
            """
import fastjsonschema

validate = fastjsonschema.compile({
    "type": "object",
    "properties": {"answer": {"type": "integer"}},
    "required": ["answer"],
})
assert validate({"answer": 42}) == {"answer": 42}
""",
        )
    ],
)
