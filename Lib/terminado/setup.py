from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="terminado",
    overlay_entries=["Lib/terminado"],
    verification_steps=[
        inline_verification_step(
            "terminado-smoke",
            """
from terminado.management import _update_removing
from terminado.websocket import TermSocket

data = {"keep": 1, "drop": 2}
_update_removing(data, {"drop": None, "add": 3})

assert data == {"keep": 1, "add": 3}
assert callable(TermSocket.send_json_message)
assert callable(TermSocket.origin_check)
""",
        )
    ],
)
