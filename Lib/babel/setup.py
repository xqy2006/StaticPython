from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="babel",
    project_name="Babel",
    overlay_entries=["Lib/babel"],
    runtime_resource_paths=[
        "Lib/babel/locale-data",
    ],
    materialized_paths=[
        "Lib/babel/locale-data/root.dat",
        "Lib/babel/locale-data/en.dat",
        "Lib/babel/locale-data/en_US.dat",
    ],
    verification_steps=[
        inline_verification_step(
            "babel-smoke",
            """
from datetime import datetime
from pathlib import Path

from babel import Locale
from babel.dates import format_datetime
from babel.localedata import exists
from babel.numbers import format_currency
import babel

locale = Locale.parse("en_US")
formatted_datetime = format_datetime(datetime(2024, 1, 2, 3, 4, 5), locale="en_US")
formatted_currency = format_currency(1234.5, "USD", locale="en_US")
locale_data_dir = Path(babel.__file__).parent / "locale-data"

assert locale.display_name == "English (United States)"
assert "2024" in formatted_datetime
assert "3:04:05" in formatted_datetime
assert "$1,234.50" == formatted_currency
assert locale_data_dir.exists()
assert exists("root")
assert exists("en")
assert exists("en_US")
""",
        )
    ],
)
