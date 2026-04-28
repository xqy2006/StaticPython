from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="aiohappyeyeballs",
    overlay_entries=["Lib/aiohappyeyeballs"],
    verification_steps=[
        inline_verification_step(
            "aiohappyeyeballs-smoke",
            """
import inspect
import aiohappyeyeballs
from aiohappyeyeballs import addr_to_addr_infos

infos = addr_to_addr_infos(("127.0.0.1", 80))
assert infos and infos[0][4] == ("127.0.0.1", 80)
assert inspect.iscoroutinefunction(aiohappyeyeballs.start_connection)
""",
        )
    ],
)
