from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="pytz",
    overlay_entries=["Lib/pytz"],
    verification_steps=[
        inline_verification_step(
            "pytz-smoke",
            """
from datetime import datetime

import pytz

utc = pytz.timezone("UTC")
value = utc.localize(datetime(2026, 1, 1, 0, 0, 0))
assert value.utcoffset().total_seconds() == 0
assert pytz.utc.zone == "UTC"
""",
        )
    ],
)
