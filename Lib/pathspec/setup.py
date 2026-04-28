from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="pathspec",
    overlay_entries=["Lib/pathspec"],
    verification_steps=[
        inline_verification_step(
            "pathspec-smoke",
            """
from pathspec import PathSpec

spec = PathSpec.from_lines("gitwildmatch", ["*.pyc", "build/"])
assert spec.match_file("demo.pyc")
assert spec.match_file("build/output.txt")
assert not spec.match_file("src/demo.py")
""",
        )
    ],
)
