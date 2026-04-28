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
assert jmespath.search("items[?value>`1`].name | [0]", data) == "beta"
""",
        )
    ],
)
