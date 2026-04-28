from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='tomlkit',
    overlay_entries=['Lib/tomlkit'],
    verification_steps=[
        inline_verification_step(
            "tomlkit-smoke",
            """
import tomlkit

doc = tomlkit.parse("[tool.demo]\\nanswer = 42\\n")
assert doc["tool"]["demo"]["answer"] == 42
doc["tool"]["demo"]["name"] = "codex"
rendered = tomlkit.dumps(doc)
assert 'name = "codex"' in rendered
""",
        )
    ],
)
