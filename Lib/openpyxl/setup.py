from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='openpyxl',
    overlay_entries=['Lib/openpyxl'],
    verification_steps=[
        inline_verification_step(
            "openpyxl-smoke",
            """
import io
import openpyxl

workbook = openpyxl.Workbook()
sheet = workbook.active
sheet.title = "Data"
sheet.append(["name", "value"])
sheet.append(["codex", 42])
buffer = io.BytesIO()
workbook.save(buffer)
buffer.seek(0)
loaded = openpyxl.load_workbook(buffer, data_only=True)
assert loaded["Data"]["A2"].value == "codex"
assert loaded["Data"]["B2"].value == 42
""",
        )
    ],
)
