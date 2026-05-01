from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="openpyxl",
    overlay_entries=["Lib/openpyxl"],
    verification_steps=[
        inline_verification_step(
            "openpyxl-smoke",
            """
import io
import openpyxl
from openpyxl.styles import Font

workbook = openpyxl.Workbook()
sheet = workbook.active
sheet.title = "Data"
sheet["A1"] = "name"
sheet["B1"] = "value"
sheet["A2"] = "codex"
sheet["B2"] = "=SUM(20,22)"
sheet["A1"].font = Font(bold=True)
sheet.merge_cells("C1:D1")
sheet["C1"] = "merged"
buffer = io.BytesIO()
workbook.save(buffer)
buffer.seek(0)
loaded = openpyxl.load_workbook(buffer, data_only=False)
assert loaded["Data"]["A1"].font.bold is True
assert loaded["Data"]["A2"].value == "codex"
assert loaded["Data"]["B2"].value == "=SUM(20,22)"
assert "C1:D1" in [str(item) for item in loaded["Data"].merged_cells.ranges]
""",
        )
    ],
)
