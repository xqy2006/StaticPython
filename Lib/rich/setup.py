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
from rich.text import Text

buffer = io.StringIO()
console = Console(file=buffer, force_terminal=False, color_system=None, width=80)
table = Table("name", "value")
table.add_row("codex", "42")
console.print(table)
console.print(Text("plain", style="bold"))
output = buffer.getvalue()
assert "codex" in output and "42" in output
assert "plain" in output
""",
        )
    ],
)
