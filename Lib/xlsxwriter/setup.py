from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='xlsxwriter',
    overlay_entries=['Lib/xlsxwriter'],
    verification_steps=[
        inline_verification_step(
            "xlsxwriter-smoke",
            """
import io
import zipfile
import xlsxwriter

buffer = io.BytesIO()
workbook = xlsxwriter.Workbook(buffer, {"in_memory": True})
sheet = workbook.add_worksheet("Data")
sheet.write(0, 0, "codex")
sheet.write_formula(0, 1, "=SUM(1,2)")
workbook.close()
buffer.seek(0)
with zipfile.ZipFile(buffer) as archive:
    names = archive.namelist()
assert "xl/workbook.xml" in names
assert any(name.startswith("xl/worksheets/") for name in names)
""",
        )
    ],
)
