from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="notebook_shim",
    project_name="notebook-shim",
    source_mapping={
        "notebook_shim": "Lib/notebook_shim",
        "jupyter_server_config.d/notebook_shim.json": "etc/jupyter/jupyter_server_config.d/notebook_shim.json",
    },
    cleanup_paths=[
        "etc/jupyter/jupyter_server_config.d/notebook_shim",
    ],
    verification_steps=[
        inline_verification_step(
            "notebook-shim-smoke",
            """
import json
import sys
from pathlib import Path

from traitlets.config import Config

from jupyter_server.extension.application import ExtensionApp
from notebook_shim.shim import NotebookConfigShimMixin


class DemoApp(NotebookConfigShimMixin, ExtensionApp):
    pass


cfg = Config(
    {
        "NotebookApp": {"allow_remote_access": True},
        "ServerApp": {"port": 9999},
        "DemoApp": {"default_url": "/demo"},
    }
)

app = DemoApp()
shimmed = app.shim_config_from_notebook_to_jupyter_server(cfg)

assert shimmed["ServerApp"]["allow_remote_access"] is True
assert shimmed["ServerApp"]["port"] == 9999
assert shimmed["DemoApp"]["default_url"] == "/demo"
config_path = Path(sys.prefix) / "etc" / "jupyter" / "jupyter_server_config.d" / "notebook_shim.json"
assert config_path.exists()
assert json.loads(config_path.read_text(encoding="utf-8"))["ServerApp"]["jpserver_extensions"]["notebook_shim"] is True
""",
        )
    ],
)
