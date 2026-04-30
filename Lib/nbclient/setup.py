from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="nbclient",
    overlay_entries=["Lib/nbclient"],
    verification_steps=[
        inline_verification_step(
            "nbclient-smoke",
            """
from nbclient import NotebookClient
from nbformat import v4

notebook = v4.new_notebook()
notebook.cells.append(v4.new_markdown_cell("# StaticPython"))
notebook.cells.append(v4.new_code_cell("answer = 40 + 2\\nanswer"))

client = NotebookClient(
    notebook,
    kernel_name="python3",
    timeout=60,
)
executed = client.execute()
assert executed.cells[0].source == "# StaticPython"
assert executed.cells[1].execution_count == 1
assert executed.cells[1].outputs
output = executed.cells[1].outputs[0]
assert output["output_type"] == "execute_result"
assert output["data"]["text/plain"] == "42"
""",
            timeout=600,
        )
    ],
)
