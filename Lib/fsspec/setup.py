from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="fsspec",
    overlay_entries=["Lib/fsspec"],
    verification_steps=[
        inline_verification_step(
            "fsspec-smoke",
            """
from fsspec.core import url_to_fs
from fsspec.implementations.memory import MemoryFileSystem

fs = MemoryFileSystem()
with fs.open("/demo.txt", "wb") as handle:
    handle.write(b"staticpython")
with fs.open("/demo.txt", "rb") as handle:
    assert handle.read() == b"staticpython"

local_fs, path = url_to_fs("file:///tmp/staticpython.txt")
assert path.endswith("staticpython.txt")
assert local_fs.protocol in ("file", ("file", "local"))
""",
        )
    ],
)
