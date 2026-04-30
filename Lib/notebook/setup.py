from libs import inline_verification_step, pypi_library, script_verification_step


LIBRARY_INTEGRATION = pypi_library(
    name="notebook",
    release_version="7.0.8",
    source_mapping={
        "notebook": "Lib/notebook",
        "notebook/labextension": "share/jupyter/labextensions/@jupyter-notebook/lab-extension",
        "jupyter-config/jupyter_server_config.d/notebook.json": "etc/jupyter/jupyter_server_config.d/notebook.json",
    },
    cleanup_paths=[
        "etc/jupyter/jupyter_server_config.d/notebook",
    ],
    materialized_paths=[
        "Lib/notebook/templates/error.html",
        "Lib/notebook/templates/consoles.html",
        "Lib/notebook/templates/edit.html",
        "Lib/notebook/templates/notebooks.html",
        "Lib/notebook/templates/terminals.html",
        "Lib/notebook/templates/tree.html",
        "Lib/notebook/static/bundle.js",
        "share/jupyter/labextensions/@jupyter-notebook/lab-extension/package.json",
        "etc/jupyter/jupyter_server_config.d/notebook.json",
    ],
    python_packages=["notebook"],
    verification_steps=[
        inline_verification_step(
            "notebook-smoke",
            """
import json
from pathlib import Path

from notebook import _jupyter_labextension_paths
from notebook.app import JupyterNotebookApp
from jupyterlab_server.config import get_page_config

paths = _jupyter_labextension_paths()
assert paths == [{"src": "labextension", "dest": "@jupyter-notebook/lab-extension"}]

app = JupyterNotebookApp()
assert app.default_url == "/tree"
assert Path(app.static_dir).name == "static"
assert Path(app.templates_dir).name == "templates"
assert Path(app.schemas_dir).name == "schemas"
assert Path(app.app_dir).name == "lab"
assert Path(app.static_dir).exists()
assert Path(app.templates_dir).exists()
assert Path(app.schemas_dir).exists()
assert Path(app.app_dir).exists()
assert (Path(app.static_dir) / "bundle.js").exists()
assert (Path(app.templates_dir) / "consoles.html").exists()
assert (Path(app.templates_dir) / "error.html").exists()
assert (Path(app.templates_dir) / "tree.html").exists()
assert (Path(app.templates_dir) / "notebooks.html").exists()
assert (Path(app.templates_dir) / "edit.html").exists()
assert (Path(app.templates_dir) / "terminals.html").exists()
labextension_dir = Path(app.app_dir).parent / "labextensions" / "@jupyter-notebook" / "lab-extension"
assert labextension_dir.exists()
assert (labextension_dir / "package.json").exists()
assert (labextension_dir / "static").exists()
assert (labextension_dir / "schemas").exists()
page_config = get_page_config(app.extra_labextensions_path + app.labextensions_path, logger=app.log)
extension_names = {entry["name"] for entry in page_config["federated_extensions"]}
assert "@jupyter-notebook/lab-extension" in extension_names
entry = next(entry for entry in page_config["federated_extensions"] if entry["name"] == "@jupyter-notebook/lab-extension")
assert page_config["disabledExtensions"] == []
assert entry["load"].startswith("static/")
assert entry["style"] == "./style"
server_config = Path(app.app_dir).parents[2] / "etc" / "jupyter" / "jupyter_server_config.d" / "notebook.json"
assert server_config.exists()
assert json.loads(server_config.read_text(encoding="utf-8"))["ServerApp"]["jpserver_extensions"]["notebook"] is True
""",
            timeout=300,
        ),
        script_verification_step(
            "notebook-runtime",
            "scripts/jupyter_runtime.py",
            args=["--target", "notebook"],
            timeout=180,
        ),
    ],
)
