from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='colorama',
    overlay_entries=['Lib/colorama'],
    verification_steps=[
        inline_verification_step(
            "colorama-smoke",
            """
from colorama import Fore, Style, ansi, just_fix_windows_console

just_fix_windows_console()
assert Fore.RED.startswith("[")
assert Style.RESET_ALL.endswith("m")
assert ansi.clear_screen() == "[2J"
""",
        )
    ],
)
