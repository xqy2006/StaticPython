from libs import inline_verification_step, pypi_library


LIBRARY_INTEGRATION = pypi_library(
    name="jupyterlab_server",
    project_name="jupyterlab-server",
    release_version="2.24.0",
    source_mapping={
        "jupyterlab_server": "Lib/jupyterlab_server",
    },
    materialized_paths=[
        "Lib/jupyterlab_server/templates/index.html",
        "Lib/jupyterlab_server/templates/error.html",
        "Lib/jupyterlab_server/templates/403.html",
    ],
    python_packages=["jupyterlab_server"],
    verification_steps=[
        inline_verification_step(
            "jupyterlab-server-smoke",
            """
from pathlib import Path

from jupyterlab_server import LabServerApp
from jupyterlab_server.config import get_page_config
from jupyterlab_server.settings_utils import _get_user_settings
from jupyterlab_server.workspaces_handler import slugify
import jupyterlab_server

app = LabServerApp()
assert app.default_url == "/lab"
assert app.settings_url == "/lab/api/settings/"
assert app.translations_api_url == "/lab/api/translations/"
assert app.workspaces_api_url == "/lab/api/workspaces/"
assert app.themes_url == "/lab/api/themes/"
assert app.licenses_url == "/lab/api/licenses/"
assert app.templates_dir == ""
assert app.schemas_dir == ""
templates_dir = Path(jupyterlab_server.__file__).parent / "templates"
assert (templates_dir / "index.html").exists()
assert (templates_dir / "error.html").exists()
assert (templates_dir / "403.html").exists()
assert (Path(jupyterlab_server.__file__).parent / "rest-api.yml").exists()

settings = _get_user_settings(str(Path.cwd()), "@jupyterlab/apputils-extension:themes", {"type": "object"})
assert settings["raw"] == "{}" or settings["raw"] == {}
assert settings["settings"] == {}

page_config = get_page_config([], logger=app.log)
assert isinstance(page_config, dict)
assert page_config.get("federated_extensions") == []
assert slugify("/StaticPython Workspace") != ""
""",
        )
    ],
)
