from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="importlib_metadata",
    project_name="importlib-metadata",
    overlay_entries=["Lib/importlib_metadata"],
    verification_steps=[
        inline_verification_step(
            "importlib-metadata-smoke",
            """
from importlib_metadata import EntryPoint

entry = EntryPoint(name="demo", value="json:loads", group="console_scripts")
assert entry.module == "json"
assert entry.attr == "loads"
assert entry.load()("{\\"answer\\": 42}") == {"answer": 42}
""",
        )
    ],
)
