from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="humanize",
    overlay_entries=["Lib/humanize"],
    verification_steps=[
        inline_verification_step(
            "humanize-smoke",
            """
from datetime import timedelta
import humanize

assert humanize.intcomma(1234567) == "1,234,567"
assert humanize.naturalsize(1536) == "1.5 kB"
assert "hour" in humanize.naturaldelta(timedelta(hours=2, minutes=5))
""",
        )
    ],
)
