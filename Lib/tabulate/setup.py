from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='tabulate',
    overlay_entries=['Lib/tabulate'],
    verification_steps=[
        inline_verification_step(
            "tabulate-smoke",
            """
from tabulate import tabulate

table = tabulate([["codex", 42]], headers=["name", "value"], tablefmt="github")
assert "codex" in table
assert "| name" in table
plain = tabulate([[1, 2], [3, 4]], tablefmt="plain")
assert "1" in plain and "4" in plain
""",
        )
    ],
)
