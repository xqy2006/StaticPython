from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="filelock",
    overlay_entries=["Lib/filelock"],
    verification_steps=[
        inline_verification_step(
            "filelock-smoke",
            """
import tempfile
from pathlib import Path

from filelock import FileLock, Timeout

with tempfile.TemporaryDirectory() as temp_dir:
    lock_path = Path(temp_dir) / "demo.lock"
    with FileLock(str(lock_path), timeout=1):
        assert lock_path.exists()
        try:
            FileLock(str(lock_path), timeout=0).acquire()
        except Timeout:
            pass
        else:
            raise AssertionError("filelock allowed a second exclusive lock")
""",
        )
    ],
)
