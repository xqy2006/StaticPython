from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="yaml",
    project_name="PyYAML",
    source_mapping={"lib/yaml": "Lib/yaml"},
    verification_steps=[
        inline_verification_step(
            "yaml-smoke",
            """
import yaml

data = yaml.safe_load("items:\\n  - 1\\n  - 2\\nname: codex\\n")
assert data == {"items": [1, 2], "name": "codex"}
rendered = yaml.safe_dump(data, sort_keys=True)
assert "items:" in rendered and "name: codex" in rendered
""",
        )
    ],
)
