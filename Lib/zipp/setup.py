from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="zipp",
    overlay_entries=["Lib/zipp"],
    verification_steps=[
        inline_verification_step(
            "zipp-smoke",
            """
import io
import zipfile

from zipp import CompleteDirs, Path

assert list(CompleteDirs._implied_dirs(["demo/pkg/module.py"])) == ["demo/pkg/", "demo/"]
buffer = io.BytesIO()
with zipfile.ZipFile(buffer, "w") as archive:
    archive.writestr("pkg/data.txt", "ok")
with zipfile.ZipFile(buffer) as archive:
    root = Path(archive)
    assert (root / "pkg" / "data.txt").read_text() == "ok"
""",
        )
    ],
)
