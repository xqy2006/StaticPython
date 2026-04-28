from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='pyperclip',
    overlay_entries=['Lib/pyperclip'],
    verification_steps=[
        inline_verification_step(
            "pyperclip-smoke",
            """
import pyperclip

assert isinstance(pyperclip.is_available(), bool)
try:
    pyperclip.determine_clipboard()
except Exception as exc:
    assert exc.__class__.__name__ in {"PyperclipException", "RuntimeError"}
""",
        )
    ],
)
