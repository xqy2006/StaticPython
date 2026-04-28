from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='blinker',
    overlay_entries=['Lib/blinker'],
    verification_steps=[
        inline_verification_step(
            "blinker-smoke",
            """
from blinker import Namespace, signal

seen = []
signal("global-demo").connect(lambda sender, **kw: seen.append((sender, kw)), weak=False)
signal("global-demo").send("sender", value=7)
assert seen == [("sender", {"value": 7})]
local = Namespace().signal("local")
assert local.name == "local"
""",
        )
    ],
)
