from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="send2trash",
    project_name="send2trash",
    overlay_entries=["Lib/send2trash"],
    verification_steps=[
        inline_verification_step(
            "send2trash-smoke",
            """
import tempfile
from pathlib import Path

from send2trash import send2trash

with tempfile.TemporaryDirectory() as temp_dir:
    file_path = Path(temp_dir) / "staticpython-trash.txt"
    file_path.write_text("trash me", encoding="utf-8")
    send2trash(str(file_path))
    assert not file_path.exists()
""",
        )
    ],
)
