from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='rich',
    overlay_entries=['Lib/rich'],
    verification_steps=[
        inline_verification_step(
            "rich-smoke",
            """
import io
from rich.console import Console
from rich.table import Table

buffer = io.StringIO()
console = Console(file=buffer, force_terminal=False, color_system=None, width=80)
table = Table("name", "value")
table.add_row("codex", "42")
console.print(table)
output = buffer.getvalue()
assert "codex" in output and "42" in output
""",
        )
    ],
)
