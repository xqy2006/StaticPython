from libs import inline_verification_step, pypi_library, script_verification_step


LIBRARY_INTEGRATION = pypi_library(
    name="jupyter_server",
    project_name="jupyter-server",
    release_version="2.7.0",
    source_mapping={
        "jupyter_server": "Lib/jupyter_server",
    },
    materialized_paths=[
        "Lib/jupyter_server/templates/404.html",
        "Lib/jupyter_server/templates/browser-open.html",
        "Lib/jupyter_server/templates/login.html",
        "Lib/jupyter_server/templates/logout.html",
        "Lib/jupyter_server/templates/page.html",
        "Lib/jupyter_server/templates/error.html",
        "Lib/jupyter_server/templates/view.html",
        "Lib/jupyter_server/templates/main.html",
        "Lib/jupyter_server/event_schemas/contents_service/v1.yaml",
    ],
    python_packages=["jupyter_server"],
    verification_imports=["jupyter_server.serverapp"],
    verification_steps=[
        inline_verification_step(
            "jupyter-server-smoke",
            """
from pathlib import Path
from types import SimpleNamespace

import jupyter_server
from jupyter_server.base.handlers import AuthenticatedHandler
from jupyter_server.extension.application import ExtensionApp
from jupyter_server.serverapp import ServerApp
from jupyter_server.utils import url_path_join

template_roots = [Path(path) for path in jupyter_server.DEFAULT_TEMPLATE_PATH_LIST]

assert Path(jupyter_server.DEFAULT_STATIC_FILES_PATH).name == "static"
assert Path(jupyter_server.DEFAULT_EVENTS_SCHEMA_PATH).name == "event_schemas"
assert any(path.name == "templates" for path in template_roots)
assert any((path / "main.html").exists() for path in template_roots)
assert any((path / "page.html").exists() for path in template_roots)
assert any((path / "error.html").exists() for path in template_roots)
assert any((path / "view.html").exists() for path in template_roots)
assert any((path / "404.html").exists() for path in template_roots)
assert any((path / "browser-open.html").exists() for path in template_roots)
assert any((path / "login.html").exists() for path in template_roots)
assert any((path / "logout.html").exists() for path in template_roots)
assert Path(jupyter_server.DEFAULT_EVENTS_SCHEMA_PATH).exists()
assert any(Path(jupyter_server.DEFAULT_EVENTS_SCHEMA_PATH).rglob("*.yaml"))
assert url_path_join("/base/", "api", "status") == "/base/api/status"

app = ServerApp()
assert app.default_url == "/"
assert app.contents_manager_class is not None
app.gateway_config = SimpleNamespace(gateway_enabled=False)
assert app.kernel_manager_class is not None
assert app.session_manager_class is not None
assert app.kernel_spec_manager_class is not None
assert app.kernel_websocket_connection_class is not None
assert any(Path(path).name == "static" for path in app.static_file_path)
assert issubclass(ExtensionApp, object)
assert callable(AuthenticatedHandler.set_default_headers)
""",
            timeout=300,
        ),
        script_verification_step(
            "jupyter-server-runtime",
            "scripts/jupyter_runtime.py",
            args=["--target", "server"],
            timeout=180,
        ),
    ],
)
