from __future__ import annotations

from libs import inline_verification_step, pypi_library, replace_text_once, script_verification_step, transform_source_text


def patch_jupyterlab_for_frozen_runtime(context) -> None:
    def patch_extensions_init(text: str) -> str:
        manager_wrapper = """

class _StaticPythonEntryPoint:
    def __init__(self, factory):
        self._factory = factory

    def load(self):
        return self._factory
"""
        if "_StaticPythonEntryPoint" not in text:
            anchor = 'for entry in entry_points(group="jupyterlab.extension_manager_v1"):\n    MANAGERS[entry.name] = entry\n'
            text = replace_text_once(
                text,
                anchor,
                anchor + manager_wrapper,
                label="jupyterlab.extensions builtin manager wrapper",
            )

        registration = (
            '\nMANAGERS.setdefault("readonly", _StaticPythonEntryPoint(get_readonly_manager))\n'
            'MANAGERS.setdefault("pypi", _StaticPythonEntryPoint(get_pypi_manager))\n'
        )
        if 'MANAGERS.setdefault("readonly", _StaticPythonEntryPoint(get_readonly_manager))' not in text:
            anchor = (
                "def get_pypi_manager(\n"
                "    app_options: Optional[dict] = None,\n"
                "    ext_options: Optional[dict] = None,\n"
                "    parent: Optional[Configurable] = None,\n"
                ") -> ExtensionManager:\n"
                '    """PyPi Extension Manager factory"""\n'
                "    return PyPIExtensionManager(app_options, ext_options, parent)\n"
            )
            text = replace_text_once(
                text,
                anchor,
                anchor + registration,
                label="jupyterlab.extensions builtin manager registration",
            )
        return text

    def patch_labapp(text: str) -> str:
        old = (
            "            if entry_point is None:\n"
            '                self.log.error(f"Extension Manager: No manager defined for provider \'{provider}\'.")\n'
            "                raise NotImplementedError()\n"
            "            else:\n"
            '                self.log.info(f"Extension Manager is \'{provider}\'.")\n'
            "            manager_factory = entry_point.load()\n"
        )
        new = (
            "            if entry_point is None:\n"
            '                self.log.warning(\n'
            '                    f"Extension Manager provider \'{provider}\' is unavailable in this environment; "\n'
            '                    "falling back to read-only manager."\n'
            "                )\n"
            '                provider = "readonly"\n'
            "                manager_factory = ReadOnlyExtensionManager\n"
            "            else:\n"
            '                self.log.info(f"Extension Manager is \'{provider}\'.")\n'
            "                manager_factory = entry_point.load()\n"
        )
        return replace_text_once(text, old, new, label="jupyterlab.labapp extension manager fallback")

    transform_source_text(context, "Lib/jupyterlab/extensions/__init__.py", patch_extensions_init)
    transform_source_text(context, "Lib/jupyterlab/labapp.py", patch_labapp)


LIBRARY_INTEGRATION = pypi_library(
    name="jupyterlab",
    release_version="4.0.9",
    source_mapping={
        "jupyterlab": "Lib/jupyterlab",
        "jupyterlab/static": "share/jupyter/lab/static",
        "jupyterlab/schemas": "share/jupyter/lab/schemas",
        "jupyterlab/themes": "share/jupyter/lab/themes",
        "jupyterlab/staging": "share/jupyter/lab/staging",
        "jupyter-config/jupyter_server_config.d/jupyterlab.json": "etc/jupyter/jupyter_server_config.d/jupyterlab.json",
        "jupyter-config/jupyter_notebook_config.d/jupyterlab.json": "etc/jupyter/jupyter_notebook_config.d/jupyterlab.json",
    },
    runtime_resource_paths=[
        "Lib/jupyterlab/static",
        "Lib/jupyterlab/schemas",
        "Lib/jupyterlab/staging",
        "Lib/jupyterlab/themes",
        "share/jupyter/lab",
        "etc/jupyter/jupyter_server_config.d/jupyterlab.json",
        "etc/jupyter/jupyter_notebook_config.d/jupyterlab.json",
    ],
    cleanup_paths=[
        "etc/jupyter/jupyter_server_config.d/jupyterlab",
        "etc/jupyter/jupyter_notebook_config.d/jupyterlab",
    ],
    materialized_paths=[
        "share/jupyter/lab/static/index.html",
        "share/jupyter/lab/static/package.json",
        "share/jupyter/lab/schemas/@jupyterlab/apputils-extension/themes.json",
        "share/jupyter/lab/themes/@jupyterlab/theme-light-extension/index.css",
        "share/jupyter/lab/themes/@jupyterlab/theme-dark-extension/index.css",
        "share/jupyter/lab/staging/package.json",
        "etc/jupyter/jupyter_server_config.d/jupyterlab.json",
        "etc/jupyter/jupyter_notebook_config.d/jupyterlab.json",
    ],
    python_packages=["jupyterlab"],
    post_patch_hooks=[patch_jupyterlab_for_frozen_runtime],
    verification_steps=[
        inline_verification_step(
            "jupyterlab-smoke",
            """
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

from jupyterlab.commands import get_app_dir, get_user_settings_dir, get_workspaces_dir
from jupyterlab.coreconfig import CoreConfig
from jupyterlab.extensions import MANAGERS
from jupyterlab.labapp import LabApp

assert "readonly" in MANAGERS
assert "pypi" in MANAGERS

app_dir = Path(get_app_dir())
assert app_dir.name == "lab"
assert app_dir.exists()
assert "user-settings" in get_user_settings_dir()
assert "workspaces" in get_workspaces_dir()

config = CoreConfig()
assert config.static_dir == "../static"
assert "@jupyterlab/application-extension" in config.extensions

app = LabApp()
assert app.default_url == "/lab"
assert Path(app.static_dir).name == "static"
assert Path(app.templates_dir).name == "static"
assert Path(app.schemas_dir).name == "schemas"
assert Path(app.static_dir).exists()
assert Path(app.templates_dir).exists()
assert Path(app.schemas_dir).exists()
assert Path(app.themes_dir).exists()
assert (Path(app.static_dir) / "index.html").exists()
assert (Path(app.static_dir) / "package.json").exists()
assert (Path(app.app_dir) / "staging" / "package.json").exists()
assert (Path(app.schemas_dir) / "@jupyterlab" / "apputils-extension" / "themes.json").exists()
assert (Path(app.themes_dir) / "@jupyterlab" / "theme-light-extension" / "index.css").exists()
assert (Path(app.themes_dir) / "@jupyterlab" / "theme-dark-extension" / "index.css").exists()
server_config = Path(app_dir.parents[2]) / "etc" / "jupyter" / "jupyter_server_config.d" / "jupyterlab.json"
notebook_config = Path(app_dir.parents[2]) / "etc" / "jupyter" / "jupyter_notebook_config.d" / "jupyterlab.json"
assert server_config.exists()
assert notebook_config.exists()
assert json.loads(server_config.read_text(encoding="utf-8"))["ServerApp"]["jpserver_extensions"]["jupyterlab"] is True
assert json.loads(notebook_config.read_text(encoding="utf-8"))["NotebookApp"]["nbserver_extensions"]["jupyterlab"] is True


def reserve_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    try:
        return sock.getsockname()[1]
    finally:
        sock.close()


with tempfile.TemporaryDirectory() as temp_dir:
    temp_root = Path(temp_dir)
    work_dir = temp_root / "work"
    work_dir.mkdir()
    port = reserve_port()
    token = "staticpython-jupyterlab"
    env = os.environ.copy()
    env.update(
        {
            "JUPYTER_CONFIG_DIR": str(temp_root / "config"),
            "JUPYTER_DATA_DIR": str(temp_root / "data"),
            "JUPYTER_RUNTIME_DIR": str(temp_root / "runtime"),
            "JUPYTERLAB_SETTINGS_DIR": str(temp_root / "lab" / "user-settings"),
            "JUPYTERLAB_WORKSPACES_DIR": str(temp_root / "lab" / "workspaces"),
            "PYTHONUTF8": "1",
            "PYTHONIOENCODING": "utf-8",
        }
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    command = [
        sys.executable,
        "-m",
        "jupyterlab",
        "--ServerApp.ip=127.0.0.1",
        f"--ServerApp.port={port}",
        "--ServerApp.port_retries=0",
        "--ServerApp.open_browser=False",
        f"--ServerApp.root_dir={work_dir}",
        f"--ServerApp.token={token}",
        "--ServerApp.password=",
    ]
    process = subprocess.Popen(
        command,
        cwd=str(work_dir),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        creationflags=creationflags,
    )
    output = ""
    try:
        url = f"http://127.0.0.1:{port}/lab?token={token}"
        response_text = None
        last_error = None
        deadline = time.time() + 90
        while time.time() < deadline:
            if process.poll() is not None:
                break
            try:
                with urllib.request.urlopen(url, timeout=5) as response:
                    response_text = response.read().decode("utf-8", errors="replace")
                    status_code = response.status
                break
            except Exception as exc:
                last_error = exc
                time.sleep(0.5)
        if response_text is None:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=15)
            if process.stdout is not None:
                output = process.stdout.read()
            raise AssertionError(
                f"failed to load /lab within timeout: {last_error!r}\\n"
                f"process return code: {process.returncode}\\n"
                f"jupyter output:\\n{output[-8000:]}"
            )
        assert status_code == 200
        assert "<title>JupyterLab</title>" in response_text
        assert "jupyter-config-data" in response_text
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=15)
        if process.stdout is not None:
            output = process.stdout.read()
        if process.returncode not in (0, -15, 1):
            raise AssertionError(
                f"jupyterlab server exited unexpectedly with code {process.returncode}\\n"
                f"jupyter output:\\n{output[-8000:]}"
            )
""",
            timeout=180,
        ),
        script_verification_step(
            "jupyterlab-runtime",
            "scripts/jupyter_runtime.py",
            args=["--target", "lab"],
            timeout=180,
        ),
    ],
)
