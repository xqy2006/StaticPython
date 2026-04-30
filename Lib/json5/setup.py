from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="json5",
    overlay_entries=["Lib/json5"],
    verification_steps=[
        inline_verification_step(
            "json5-smoke",
            """
import io

import json5

payload = json5.loads("{unquoted: 'value', trailing: [1,2,], flag: true}")
assert payload == {"unquoted": "value", "trailing": [1, 2], "flag": True}

buffer = io.StringIO("{answer: 42}\\n")
assert json5.load(buffer) == {"answer": 42}

rendered = json5.dumps({"answer": 42}, quote_keys=True)
assert '"answer"' in rendered
assert json5.loads(rendered)["answer"] == 42
""",
        )
    ],
)
