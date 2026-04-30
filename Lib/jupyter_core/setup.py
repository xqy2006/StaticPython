from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="jupyter_core",
    project_name="jupyter-core",
    overlay_entries=["Lib/jupyter_core"],
    verification_steps=[
        inline_verification_step(
            "jupyter-core-smoke",
            """
import os
import tempfile
from pathlib import Path

from jupyter_core.application import JupyterApp
from jupyter_core.paths import (
    ENV_JUPYTER_PATH,
    jupyter_config_dir,
    jupyter_data_dir,
    jupyter_path,
    jupyter_runtime_dir,
    secure_write,
)

assert isinstance(jupyter_config_dir(), str)
assert isinstance(jupyter_data_dir(), str)
assert isinstance(jupyter_runtime_dir(), str)
assert any(Path(item).name == "kernels" for item in jupyter_path("kernels"))
assert all(isinstance(item, str) for item in ENV_JUPYTER_PATH)

with tempfile.TemporaryDirectory() as temp_dir:
    path = Path(temp_dir) / "connection.json"
    with secure_write(str(path)) as handle:
        handle.write("{}")
    assert path.read_text(encoding="utf-8") == "{}"

app = JupyterApp()
assert app.name == "jupyter"
assert isinstance(app.version, str)
assert os.path.isabs(jupyter_runtime_dir())
""",
        )
    ],
)
