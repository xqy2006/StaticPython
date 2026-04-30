from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="bleach",
    overlay_entries=["Lib/bleach"],
    verification_steps=[
        inline_verification_step(
            "bleach-smoke",
            """
import bleach
from bleach.css_sanitizer import CSSSanitizer

cleaned = bleach.clean(
    '<p style="color:red;position:absolute"><script>x</script>Hello <b>world</b></p>',
    tags={"p", "b"},
    attributes={"p": ["style"]},
    css_sanitizer=CSSSanitizer(allowed_css_properties=["color"]),
    strip=True,
)
assert "<script>" not in cleaned
assert "position:absolute" not in cleaned
assert "color:red" in cleaned
assert "<b>world</b>" in cleaned
""",
        )
    ],
)
