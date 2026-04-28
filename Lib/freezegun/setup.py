from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="freezegun",
    overlay_entries=["Lib/freezegun"],
    verification_steps=[
        inline_verification_step(
            "freezegun-smoke",
            """
from datetime import date, datetime, timedelta
from freezegun import freeze_time


@freeze_time("2024-01-02 03:04:05")
def run():
    assert datetime.now() == datetime(2024, 1, 2, 3, 4, 5)
    assert date.today() == date(2024, 1, 2)
    assert datetime.now() + timedelta(days=1) == datetime(2024, 1, 3, 3, 4, 5)


run()
""",
        )
    ],
)
