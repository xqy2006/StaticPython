from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="py",
    overlay_entries=["Lib/py"],
    verification_steps=[
        inline_verification_step(
            "py-smoke",
            """
import py

path = py.path.local(".")
assert path.basename
""",
        )
    ],
)
