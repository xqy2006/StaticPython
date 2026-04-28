from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='dotenv',
    overlay_entries=['Lib/dotenv'],
    verification_steps=[
        inline_verification_step(
            "dotenv-smoke",
            """
import io
from dotenv import dotenv_values

values = dotenv_values(stream=io.StringIO("A=1\\nQUOTED='two words'\\n"))
assert values["A"] == "1"
assert values["QUOTED"] == "two words"
""",
        )
    ],
)
