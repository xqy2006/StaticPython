from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='dateutil',
    overlay_entries=['Lib/dateutil'],
    verification_steps=[
        inline_verification_step(
            "dateutil-smoke",
            """
from datetime import datetime
from dateutil import parser, tz
from dateutil.relativedelta import relativedelta

value = parser.isoparse("2024-01-02T03:04:05+00:00")
assert value.tzinfo is not None
assert datetime(2024, 1, 31) + relativedelta(months=1) == datetime(2024, 2, 29)
assert tz.gettz("UTC") is not None
""",
        )
    ],
)
