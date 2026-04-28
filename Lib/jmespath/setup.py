from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="jmespath",
    overlay_entries=["Lib/jmespath"],
    verification_steps=[
        inline_verification_step(
            "jmespath-smoke",
            """
import jmespath

data = {"items": [{"name": "alpha", "value": 1}, {"name": "beta", "value": 2}]}
expression = jmespath.compile("items[?value>`1`].name | [0]")
assert expression.search(data) == "beta"
assert jmespath.search("length(items)", data) == 2
""",
        )
    ],
)
