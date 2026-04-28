from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="zipp",
    overlay_entries=["Lib/zipp"],
    verification_steps=[
        inline_verification_step(
            "zipp-smoke",
            """
from zipp import CompleteDirs

assert list(CompleteDirs._implied_dirs(["demo/pkg/module.py"])) == ["demo/pkg/", "demo/"]
""",
        )
    ],
)
