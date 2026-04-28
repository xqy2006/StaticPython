from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='wcwidth',
    overlay_entries=['Lib/wcwidth'],
    verification_steps=[
        inline_verification_step(
            "wcwidth-smoke",
            """
from wcwidth import wcwidth, wcswidth

assert wcwidth("a") == 1
assert wcwidth("́") == 0
assert wcswidth("abc") == 3
assert wcswidth("中文") == 4
""",
        )
    ],
)
