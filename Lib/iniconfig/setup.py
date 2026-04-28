from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="iniconfig",
    overlay_entries=["Lib/iniconfig"],
    verification_steps=[
        inline_verification_step(
            "iniconfig-smoke",
            """
import tempfile
from pathlib import Path

from iniconfig import IniConfig

with tempfile.TemporaryDirectory() as temp_dir:
    path = Path(temp_dir) / "demo.ini"
    path.write_text("[tool]\\nname = staticpython\\n", encoding="utf-8")
    config = IniConfig(str(path))
    assert config["tool"]["name"] == "staticpython"
    assert "tool" in config.sections
    assert list(config["tool"]) == ["name"]
""",
        )
    ],
)
