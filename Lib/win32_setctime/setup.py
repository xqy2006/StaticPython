from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='win32_setctime',
    overlay_entries=['Lib/win32_setctime'],
    verification_steps=[
        inline_verification_step(
            "win32-setctime-smoke",
            """
import os
import tempfile
import win32_setctime

assert isinstance(win32_setctime.SUPPORTED, bool)
fd, path = tempfile.mkstemp()
os.close(fd)
try:
    if win32_setctime.SUPPORTED:
        win32_setctime.setctime(path, 1_700_000_000)
    assert os.path.exists(path)
finally:
    os.unlink(path)
""",
        )
    ],
)
