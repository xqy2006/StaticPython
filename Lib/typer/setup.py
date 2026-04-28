from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='typer',
    overlay_entries=['Lib/typer'],
    verification_steps=[
        inline_verification_step(
            "typer-smoke",
            """
import typer
from typer.testing import CliRunner

app = typer.Typer()

@app.command()
def hello(name: str):
    typer.echo(f"hello {name}")

result = CliRunner().invoke(app, ["codex"])
assert result.exit_code == 0
assert "hello codex" in result.output
""",
        )
    ],
)
