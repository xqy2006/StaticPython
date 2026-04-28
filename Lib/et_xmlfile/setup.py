from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='et_xmlfile',
    overlay_entries=['Lib/et_xmlfile'],
    verification_steps=[
        inline_verification_step(
            "et-xmlfile-smoke",
            """
import io
from et_xmlfile import xmlfile

buffer = io.BytesIO()
with xmlfile(buffer) as xf:
    with xf.element("root", {"kind": "demo"}):
        with xf.element("child"):
            xf.write("demo")
xml = buffer.getvalue()
assert b'<root kind="demo">' in xml
assert b"<child>demo</child>" in xml
""",
        )
    ],
)
