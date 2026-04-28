from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='pypdf',
    overlay_entries=['Lib/pypdf'],
    verification_steps=[
        inline_verification_step(
            "pypdf-smoke",
            """
import io
from pypdf import PdfReader, PdfWriter

writer = PdfWriter()
writer.add_blank_page(width=72, height=144)
buffer = io.BytesIO()
writer.write(buffer)
buffer.seek(0)
reader = PdfReader(buffer)
assert len(reader.pages) == 1
assert float(reader.pages[0].mediabox.height) == 144.0
""",
        )
    ],
)
