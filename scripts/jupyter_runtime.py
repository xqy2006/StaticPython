from __future__ import annotations

import argparse
import html
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path


BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": "StaticPython-Verify/1.0",
}
ASSET_HEADERS = {
    "Accept": "text/css,*/*;q=0.1",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "User-Agent": "StaticPython-Verify/1.0",
}
CONFIG_DATA_PATTERN = re.compile(
    r'<script[^>]+id="jupyter-config-data"[^>]*>(?P<body>.*?)</script>',
    re.IGNORECASE | re.DOTALL,
)
ASSET_PATTERN = re.compile(
    r"""(?:src|href)=["'](?P<path>[^"']+\.(?:js|css)(?:\?[^"']*)?)["']""",
    re.IGNORECASE,
)
KERNEL_SENTINEL = "__STATICPYTHON_KERNEL__"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Runtime smoke tests for StaticPython Jupyter integrations.")
    parser.add_argument("--target", choices=("server", "notebook", "lab"), required=True)
    parser.add_argument("--timeout", type=float, default=90.0)
    return parser.parse_args()


def reserve_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    try:
        return sock.getsockname()[1]
    finally:
        sock.close()


def make_env(temp_root: Path) -> dict[str, str]:
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
    return env


def request_url(
    url: str,
    *,
    expect_json: bool,
    deadline: float,
    process: subprocess.Popen[str],
    method: str = "GET",
    data: bytes | None = None,
    headers: dict[str, str] | None = None,
    allowed_statuses: set[int] | None = None,
) -> tuple[int, object]:
    last_error: Exception | None = None
    while time.time() < deadline:
        if process.poll() is not None:
            break
        try:
            request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
            with urllib.request.urlopen(request, timeout=5) as response:
                body_text = response.read().decode("utf-8", errors="replace")
                payload: object = json.loads(body_text) if expect_json else body_text
                return response.status, payload
        except urllib.error.HTTPError as exc:
            if allowed_statuses and exc.code in allowed_statuses:
                body_text = exc.read().decode("utf-8", errors="replace")
                payload = json.loads(body_text) if expect_json else body_text
                return exc.code, payload
            last_error = exc
            time.sleep(0.5)
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"failed to fetch {url!r} before timeout: {last_error!r}")


def fetch_html_page(
    url: str,
    *,
    expected_title: str | None,
    expected_app_name: str | None,
    require_config_data: bool = True,
    deadline: float,
    process: subprocess.Popen[str],
) -> tuple[str, dict[str, object]]:
    status_code, page_text = request_url(
        url,
        expect_json=False,
        deadline=deadline,
        process=process,
        headers=BROWSER_HEADERS,
    )
    assert status_code == 200
    assert isinstance(page_text, str)
    if expected_title is not None:
        assert expected_title in page_text
    page_config = extract_page_config(page_text) if require_config_data else {}
    if expected_app_name is not None:
        assert page_config.get("appName") == expected_app_name
    return page_text, page_config


def extract_page_config(page_text: str) -> dict[str, object]:
    match = CONFIG_DATA_PATTERN.search(page_text)
    if match is None:
        raise AssertionError("jupyter-config-data script tag not found in page output")
    return json.loads(html.unescape(match.group("body")))


def verify_static_assets(
    page_text: str,
    *,
    page_url: str,
    deadline: float,
    process: subprocess.Popen[str],
    require_js: bool = False,
    require_css: bool = False,
) -> None:
    asset_urls: list[str] = []
    seen: set[str] = set()
    js_count = 0
    css_count = 0
    for match in ASSET_PATTERN.finditer(page_text):
        full_url = urllib.parse.urljoin(page_url, match.group("path"))
        if full_url in seen:
            continue
        seen.add(full_url)
        asset_urls.append(full_url)
        parsed_path = urllib.parse.urlsplit(full_url).path.lower()
        if parsed_path.endswith(".js"):
            js_count += 1
        elif parsed_path.endswith(".css"):
            css_count += 1

    if not asset_urls:
        raise AssertionError(f"no static asset links were found in {page_url}")
    if require_js and js_count == 0:
        raise AssertionError(f"no JavaScript assets were found in {page_url}")
    if require_css and css_count == 0:
        raise AssertionError(f"no CSS assets were found in {page_url}")

    for asset_url in asset_urls:
        status_code, asset_body = request_url(
            asset_url,
            expect_json=False,
            deadline=deadline,
            process=process,
            headers=ASSET_HEADERS,
        )
        assert status_code == 200
        assert isinstance(asset_body, str)
        assert len(asset_body) > 32
        assert "Traceback (most recent call last):" not in asset_body


def assert_log_health(log_output: str, target: str) -> None:
    forbidden_markers = [
        "No manager defined for provider",
        "TemplateNotFound",
        "extension failed loading with message",
        "Uncaught exception GET /lab",
        "Traceback (most recent call last):",
        "[E ",
    ]
    for marker in forbidden_markers:
        if marker in log_output:
            raise AssertionError(f"unexpected startup error marker {marker!r} in {target} log output")

    required_by_target = {
        "server": ["Jupyter Server", "jupyterlab | extension was successfully loaded."],
        "notebook": ["notebook | extension was successfully loaded."],
        "lab": ["jupyterlab | extension was successfully loaded.", "Extension Manager is 'pypi'."],
    }
    for marker in required_by_target[target]:
        if marker not in log_output:
            raise AssertionError(f"expected log marker {marker!r} missing from {target} startup output")


def write_demo_notebook(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "cells": [],
                "metadata": {},
                "nbformat": 4,
                "nbformat_minor": 5,
            }
        ),
        encoding="utf-8",
    )


def kernel_expectations() -> dict[str, bool]:
    return {
        "websocket": importlib.util.find_spec("websocket") is not None,
        "numpy": importlib.util.find_spec("numpy") is not None,
        "pandas": importlib.util.find_spec("pandas") is not None,
    }


def kernel_probe_code() -> str:
    return f"""
import importlib.util
import json

result = {{"python_ok": True}}

if importlib.util.find_spec("numpy") is not None:
    import numpy as np

    matrix = np.arange(12, dtype=np.int64).reshape(3, 4)
    gram = matrix @ matrix.T
    result["numpy"] = {{
        "sum": int(matrix.sum()),
        "gram_shape": list(gram.shape),
        "max": int(matrix.max()),
    }}

if importlib.util.find_spec("pandas") is not None:
    import pandas as pd

    frame = pd.DataFrame(
        {{
            "kind": ["a", "a", "b"],
            "value": [1, 2, 3],
            "when": pd.to_datetime(
                ["2024-01-01T00:00:00Z", "2024-01-01T01:00:00Z", "2024-01-02T00:00:00Z"],
                utc=True,
            ),
        }}
    )
    grouped = frame.groupby("kind")["value"].sum().to_dict()
    result["pandas"] = {{
        "grouped_a": int(grouped["a"]),
        "day_count": int(frame["when"].dt.day.nunique()),
        "total": int(frame["value"].sum()),
    }}

print("{KERNEL_SENTINEL}" + json.dumps(result, sort_keys=True))
""".strip()


def _read_kernel_message(ws, *, deadline: float) -> str:
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            payload = ws.recv()
        except Exception as exc:
            last_error = exc
            time.sleep(0.2)
            continue
        if isinstance(payload, bytes):
            return payload.decode("utf-8", errors="replace")
        return payload
    raise AssertionError(f"timed out waiting for kernel websocket traffic: {last_error!r}")


def verify_kernel_execution(
    port: int,
    token: str,
    kernel_id: str,
    session_id: str,
    deadline: float,
    process: subprocess.Popen[str],
) -> None:
    expectations = kernel_expectations()
    if not expectations["websocket"]:
        return

    from websocket import create_connection

    ws_url = (
        f"ws://127.0.0.1:{port}/api/kernels/{kernel_id}/channels"
        f"?session_id={session_id}&token={token}"
    )
    last_error: Exception | None = None
    ws = None
    while time.time() < deadline:
        if process.poll() is not None:
            break
        try:
            ws = create_connection(ws_url, timeout=5, enable_multithread=False)
            ws.settimeout(1)
            break
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    if ws is None:
        raise AssertionError(f"failed to open kernel websocket {ws_url!r}: {last_error!r}")

    try:
        client_session = uuid.uuid4().hex
        message_id = uuid.uuid4().hex
        ws.send(
            json.dumps(
                {
                    "header": {
                        "msg_id": message_id,
                        "username": "staticpython",
                        "session": client_session,
                        "msg_type": "execute_request",
                        "version": "5.3",
                    },
                    "parent_header": {},
                    "metadata": {},
                    "content": {
                        "code": kernel_probe_code(),
                        "silent": False,
                        "store_history": False,
                        "user_expressions": {},
                        "allow_stdin": False,
                        "stop_on_error": True,
                    },
                    "channel": "shell",
                }
            )
        )

        output_chunks: list[str] = []
        saw_reply = False
        saw_idle = False
        last_message = ""
        while time.time() < deadline:
            if process.poll() is not None:
                break
            raw_message = _read_kernel_message(ws, deadline=deadline)
            last_message = raw_message
            payload = json.loads(raw_message)
            parent_header = payload.get("parent_header") or {}
            if parent_header.get("msg_id") != message_id:
                continue

            header = payload.get("header") or {}
            msg_type = payload.get("msg_type") or header.get("msg_type")
            content = payload.get("content") or {}
            if msg_type == "stream":
                output_chunks.append(content.get("text", ""))
            elif msg_type == "execute_result":
                data = content.get("data") or {}
                text_plain = data.get("text/plain")
                if text_plain:
                    output_chunks.append(str(text_plain))
            elif msg_type == "error":
                traceback_text = "\n".join(content.get("traceback") or [])
                raise AssertionError(
                    "kernel execution failed\n"
                    f"ename: {content.get('ename')}\n"
                    f"evalue: {content.get('evalue')}\n"
                    f"traceback:\n{traceback_text}"
                )
            elif msg_type == "execute_reply":
                if content.get("status") != "ok":
                    raise AssertionError(f"kernel execute_reply returned {content!r}")
                saw_reply = True
            elif msg_type == "status" and content.get("execution_state") == "idle":
                saw_idle = True

            combined_output = "".join(output_chunks)
            if saw_reply and saw_idle and KERNEL_SENTINEL in combined_output:
                marker_index = combined_output.index(KERNEL_SENTINEL) + len(KERNEL_SENTINEL)
                payload_line = combined_output[marker_index:].splitlines()[0].strip()
                kernel_result = json.loads(payload_line)
                assert kernel_result["python_ok"] is True
                if expectations["numpy"]:
                    assert kernel_result["numpy"]["sum"] == 66
                    assert kernel_result["numpy"]["gram_shape"] == [3, 3]
                    assert kernel_result["numpy"]["max"] == 11
                if expectations["pandas"]:
                    assert kernel_result["pandas"]["grouped_a"] == 3
                    assert kernel_result["pandas"]["day_count"] == 2
                    assert kernel_result["pandas"]["total"] == 6
                return

        raise AssertionError(
            "kernel execution did not finish before timeout\n"
            f"last websocket message: {last_message}"
        )
    finally:
        ws.close()


def verify_contents_crud(
    base: str,
    token: str,
    deadline: float,
    process: subprocess.Popen[str],
) -> None:
    json_headers = {"Content-Type": "application/json"}

    status_code, created_payload = request_url(
        f"{base}/api/contents?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
        method="POST",
        data=json.dumps({"type": "file", "ext": ".txt"}).encode("utf-8"),
        headers=json_headers,
    )
    assert status_code == 201
    assert created_payload["type"] == "file"
    created_path = created_payload["path"]
    quoted_created_path = urllib.parse.quote(created_path, safe="")

    status_code, saved_payload = request_url(
        f"{base}/api/contents/{quoted_created_path}?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
        method="PUT",
        data=json.dumps({"type": "file", "format": "text", "content": "alpha"}).encode("utf-8"),
        headers=json_headers,
    )
    assert status_code in {200, 201}
    assert saved_payload["path"] == created_path

    status_code, contents_payload = request_url(
        f"{base}/api/contents/{quoted_created_path}?content=1&token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert contents_payload["type"] == "file"
    assert contents_payload["format"] == "text"
    assert contents_payload["content"] == "alpha"

    status_code, checkpoint_payload = request_url(
        f"{base}/api/contents/{quoted_created_path}/checkpoints?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
        method="POST",
    )
    assert status_code == 201
    checkpoint_id = checkpoint_payload["id"]
    quoted_checkpoint_id = urllib.parse.quote(checkpoint_id, safe="")

    status_code, checkpoints_payload = request_url(
        f"{base}/api/contents/{quoted_created_path}/checkpoints?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert any(checkpoint["id"] == checkpoint_id for checkpoint in checkpoints_payload)

    status_code, _ = request_url(
        f"{base}/api/contents/{quoted_created_path}?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
        method="PUT",
        data=json.dumps({"type": "file", "format": "text", "content": "beta"}).encode("utf-8"),
        headers=json_headers,
    )
    assert status_code in {200, 201}

    status_code, updated_payload = request_url(
        f"{base}/api/contents/{quoted_created_path}?content=1&token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert updated_payload["content"] == "beta"

    status_code, _ = request_url(
        f"{base}/api/contents/{quoted_created_path}/checkpoints/{quoted_checkpoint_id}?token={token}",
        expect_json=False,
        deadline=deadline,
        process=process,
        method="POST",
    )
    assert status_code == 204

    status_code, restored_payload = request_url(
        f"{base}/api/contents/{quoted_created_path}?content=1&token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert restored_payload["content"] == "alpha"

    status_code, _ = request_url(
        f"{base}/api/contents/{quoted_created_path}/checkpoints/{quoted_checkpoint_id}?token={token}",
        expect_json=False,
        deadline=deadline,
        process=process,
        method="DELETE",
    )
    assert status_code == 204

    renamed_path = "renamed-staticpython.txt"
    quoted_renamed_path = urllib.parse.quote(renamed_path, safe="")
    status_code, renamed_payload = request_url(
        f"{base}/api/contents/{quoted_created_path}?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
        method="PATCH",
        data=json.dumps({"path": renamed_path}).encode("utf-8"),
        headers=json_headers,
    )
    assert status_code == 200
    assert renamed_payload["path"] == renamed_path

    status_code, copied_payload = request_url(
        f"{base}/api/contents?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
        method="POST",
        data=json.dumps({"copy_from": renamed_path}).encode("utf-8"),
        headers=json_headers,
    )
    assert status_code == 201
    copied_path = copied_payload["path"]
    assert copied_path != renamed_path
    quoted_copied_path = urllib.parse.quote(copied_path, safe="")

    status_code, copied_contents = request_url(
        f"{base}/api/contents/{quoted_copied_path}?content=1&token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert copied_contents["content"] == "alpha"

    status_code, _ = request_url(
        f"{base}/api/contents/{quoted_copied_path}?token={token}",
        expect_json=False,
        deadline=deadline,
        process=process,
        method="DELETE",
    )
    assert status_code == 204

    status_code, _ = request_url(
        f"{base}/api/contents/{quoted_renamed_path}?token={token}",
        expect_json=False,
        deadline=deadline,
        process=process,
        method="DELETE",
    )
    assert status_code == 204


def verify_session_runtime(
    port: int,
    token: str,
    deadline: float,
    process: subprocess.Popen[str],
    *,
    work_dir: Path,
) -> None:
    base = f"http://127.0.0.1:{port}"
    notebook_path = work_dir / "demo.ipynb"
    write_demo_notebook(notebook_path)

    status_code, session_payload = request_url(
        f"{base}/api/sessions?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
        method="POST",
        data=json.dumps(
            {
                "path": notebook_path.name,
                "type": "notebook",
                "name": "",
                "kernel": {"name": "python3"},
            }
        ).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert status_code == 201
    assert session_payload["kernel"]["name"] == "python3"
    assert session_payload["path"] == notebook_path.name

    kernel_id = session_payload["kernel"]["id"]
    session_id = session_payload["id"]
    status_code, kernel_payload = request_url(
        f"{base}/api/kernels/{kernel_id}?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert kernel_payload["execution_state"] in {"starting", "idle", "busy"}
    verify_kernel_execution(port, token, kernel_id, session_id, deadline, process)

    status_code, _ = request_url(
        f"{base}/api/sessions/{session_id}?token={token}",
        expect_json=False,
        deadline=deadline,
        process=process,
        method="DELETE",
    )
    assert status_code == 204


def verify_server_runtime(
    port: int,
    token: str,
    deadline: float,
    process: subprocess.Popen[str],
    *,
    work_dir: Path,
) -> None:
    base = f"http://127.0.0.1:{port}"
    script_path = work_dir / "demo.py"
    script_path.write_text("print('staticpython')\n", encoding="utf-8")

    root_page, root_config = fetch_html_page(
        f"{base}/?token={token}",
        expected_title="<title>Jupyter Server</title>",
        expected_app_name=None,
        require_config_data=False,
        deadline=deadline,
        process=process,
    )
    verify_static_assets(
        root_page,
        page_url=f"{base}/?token={token}",
        deadline=deadline,
        process=process,
        require_css=True,
    )

    view_page, _ = fetch_html_page(
        f"{base}/view/{urllib.parse.quote(script_path.name)}?token={token}",
        expected_title=None,
        expected_app_name=None,
        require_config_data=False,
        deadline=deadline,
        process=process,
    )
    assert "<title>demo.py</title>" in view_page
    assert '<iframe id="iframe"' in view_page
    assert 'src="/files/demo.py"' in view_page

    status_code, file_payload = request_url(
        f"{base}/files/{urllib.parse.quote(script_path.name)}?token={token}",
        expect_json=False,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert isinstance(file_payload, str)
    assert file_payload.strip() == "print('staticpython')"

    status_code, status_payload = request_url(
        f"{base}/api/status?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert isinstance(status_payload, dict)
    assert "started" in status_payload and "last_activity" in status_payload

    status_code, kernelspecs_payload = request_url(
        f"{base}/api/kernelspecs?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert kernelspecs_payload["default"] == "python3"
    assert "python3" in kernelspecs_payload["kernelspecs"]
    status_code, error_page = request_url(
        f"{base}/definitely-not-here?token={token}",
        expect_json=False,
        deadline=deadline,
        process=process,
        headers=BROWSER_HEADERS,
        allowed_statuses={404},
    )
    assert status_code == 404
    assert isinstance(error_page, str)
    assert "404" in error_page and "Not Found" in error_page
    verify_contents_crud(base, token, deadline, process)
    verify_session_runtime(port, token, deadline, process, work_dir=work_dir)


def verify_notebook_runtime(
    port: int,
    token: str,
    deadline: float,
    process: subprocess.Popen[str],
    *,
    work_dir: Path,
) -> None:
    base = f"http://127.0.0.1:{port}"
    notebook_path = work_dir / "demo.ipynb"
    write_demo_notebook(notebook_path)
    script_path = work_dir / "demo.py"
    script_path.write_text("print('staticpython')\n", encoding="utf-8")

    tree_page, tree_config = fetch_html_page(
        f"{base}/tree?token={token}",
        expected_title="<title>Home</title>",
        expected_app_name="Jupyter Notebook",
        deadline=deadline,
        process=process,
    )
    assert tree_config.get("fullStaticUrl") == "/static/notebook"
    verify_static_assets(
        tree_page,
        page_url=f"{base}/tree?token={token}",
        deadline=deadline,
        process=process,
        require_js=True,
    )

    notebook_page, notebook_config = fetch_html_page(
        f"{base}/notebooks/{urllib.parse.quote(notebook_path.name)}?token={token}",
        expected_title="<title>Jupyter Notebook - Notebook</title>",
        expected_app_name="Jupyter Notebook",
        deadline=deadline,
        process=process,
    )
    assert notebook_config.get("fullStaticUrl") == "/static/notebook"
    verify_static_assets(
        notebook_page,
        page_url=f"{base}/notebooks/{urllib.parse.quote(notebook_path.name)}?token={token}",
        deadline=deadline,
        process=process,
        require_js=True,
    )

    edit_page, edit_config = fetch_html_page(
        f"{base}/edit/{urllib.parse.quote(script_path.name)}?token={token}",
        expected_title="<title>Jupyter Notebook - Edit</title>",
        expected_app_name="Jupyter Notebook",
        deadline=deadline,
        process=process,
    )
    assert edit_config.get("fullStaticUrl") == "/static/notebook"
    verify_static_assets(
        edit_page,
        page_url=f"{base}/edit/{urllib.parse.quote(script_path.name)}?token={token}",
        deadline=deadline,
        process=process,
        require_js=True,
    )

    consoles_page, consoles_config = fetch_html_page(
        f"{base}/consoles/{urllib.parse.quote(notebook_path.stem)}?token={token}",
        expected_title="<title>Jupyter Notebook - Console</title>",
        expected_app_name="Jupyter Notebook",
        deadline=deadline,
        process=process,
    )
    assert consoles_config.get("fullStaticUrl") == "/static/notebook"
    verify_static_assets(
        consoles_page,
        page_url=f"{base}/consoles/{urllib.parse.quote(notebook_path.stem)}?token={token}",
        deadline=deadline,
        process=process,
        require_js=True,
    )

    terminals_page, terminals_config = fetch_html_page(
        f"{base}/terminals/{urllib.parse.quote(notebook_path.stem)}?token={token}",
        expected_title="<title>Jupyter Notebook - Terminal</title>",
        expected_app_name="Jupyter Notebook",
        deadline=deadline,
        process=process,
    )
    assert terminals_config.get("fullStaticUrl") == "/static/notebook"
    verify_static_assets(
        terminals_page,
        page_url=f"{base}/terminals/{urllib.parse.quote(notebook_path.stem)}?token={token}",
        deadline=deadline,
        process=process,
        require_js=True,
    )

    status_code, file_payload = request_url(
        f"{base}/files/{urllib.parse.quote(script_path.name)}?token={token}",
        expect_json=False,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert isinstance(file_payload, str)
    assert file_payload.strip() == "print('staticpython')"

    status_code, status_payload = request_url(
        f"{base}/api/status?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert isinstance(status_payload, dict)
    assert "started" in status_payload

    status_code, notebook_payload = request_url(
        f"{base}/api/contents/{urllib.parse.quote(notebook_path.name)}?content=1&token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert notebook_payload["type"] == "notebook"
    assert notebook_payload["path"] == notebook_path.name

    status_code, contents_payload = request_url(
        f"{base}/api/contents?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert contents_payload["type"] == "directory"
    assert contents_payload["path"] == ""

    status_code, kernelspecs_payload = request_url(
        f"{base}/api/kernelspecs?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert kernelspecs_payload["default"] == "python3"
    assert kernelspecs_payload["kernelspecs"]["python3"]["spec"]["argv"][1:3] == ["-m", "ipykernel_launcher"]
    verify_contents_crud(base, token, deadline, process)
    verify_session_runtime(port, token, deadline, process, work_dir=work_dir)


def verify_lab_runtime(
    port: int,
    token: str,
    deadline: float,
    process: subprocess.Popen[str],
    *,
    work_dir: Path,
) -> None:
    base = f"http://127.0.0.1:{port}"
    notebook_path = work_dir / "demo.ipynb"
    write_demo_notebook(notebook_path)

    lab_page, lab_config = fetch_html_page(
        f"{base}/lab?token={token}",
        expected_title="<title>JupyterLab</title>",
        expected_app_name="JupyterLab",
        deadline=deadline,
        process=process,
    )
    assert lab_config.get("appUrl") == "/lab"
    assert lab_config.get("extensionManager", {}).get("name") == "PyPI"
    verify_static_assets(
        lab_page,
        page_url=f"{base}/lab?token={token}",
        deadline=deadline,
        process=process,
        require_js=True,
    )

    tree_page, tree_config = fetch_html_page(
        f"{base}/lab/tree/{urllib.parse.quote(notebook_path.name)}?token={token}",
        expected_title="<title>JupyterLab</title>",
        expected_app_name="JupyterLab",
        deadline=deadline,
        process=process,
    )
    assert tree_config.get("appUrl") == "/lab"
    assert tree_config.get("extensionManager", {}).get("name") == "PyPI"
    verify_static_assets(
        tree_page,
        page_url=f"{base}/lab/tree/{urllib.parse.quote(notebook_path.name)}?token={token}",
        deadline=deadline,
        process=process,
        require_js=True,
    )

    status_code, status_payload = request_url(
        f"{base}/api/status?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert isinstance(status_payload, dict)
    assert "started" in status_payload

    status_code, kernelspecs_payload = request_url(
        f"{base}/api/kernelspecs?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert kernelspecs_payload["default"] == "python3"
    assert "python3" in kernelspecs_payload["kernelspecs"]

    status_code, settings_payload = request_url(
        f"{base}/lab/api/settings/@jupyterlab/apputils-extension:themes?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert settings_payload["id"] == "@jupyterlab/apputils-extension:themes"
    assert settings_payload["schema"]["title"] == "Theme"

    status_code, _ = request_url(
        f"{base}/lab/api/settings/@jupyterlab/apputils-extension:themes?token={token}",
        expect_json=False,
        deadline=deadline,
        process=process,
        method="PUT",
        data=json.dumps({"raw": '{"theme":"JupyterLab Dark"}'}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert status_code == 204

    status_code, updated_settings = request_url(
        f"{base}/lab/api/settings/@jupyterlab/apputils-extension:themes?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert updated_settings["settings"]["theme"] == "JupyterLab Dark"
    raw_settings = updated_settings["raw"]
    if isinstance(raw_settings, str):
        raw_settings = json.loads(raw_settings or "{}")
    assert raw_settings["theme"] == "JupyterLab Dark"

    status_code, translations_payload = request_url(
        f"{base}/lab/api/translations?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert isinstance(translations_payload["data"], dict)
    assert isinstance(translations_payload["message"], str)

    status_code, default_translation_payload = request_url(
        f"{base}/lab/api/translations/default?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert isinstance(default_translation_payload["data"], dict)
    assert isinstance(default_translation_payload["message"], str)

    status_code, theme_css = request_url(
        f"{base}/lab/api/themes/@jupyterlab/theme-light-extension/index.css?token={token}",
        expect_json=False,
        deadline=deadline,
        process=process,
        headers=ASSET_HEADERS,
    )
    assert status_code == 200
    assert isinstance(theme_css, str)
    assert "--jp-layout-color0" in theme_css

    status_code, workspace_payload = request_url(
        f"{base}/lab/api/workspaces/lab?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert workspace_payload["metadata"]["id"] == "/lab"

    workspace_name = "staticpython-test"
    workspace_document = {
        "data": {
            "layout-restorer:data": {
                "main": {
                    "current": "launcher",
                }
            }
        },
        "metadata": {"id": f"/{workspace_name}"},
    }
    status_code, _ = request_url(
        f"{base}/lab/api/workspaces/{workspace_name}?token={token}",
        expect_json=False,
        deadline=deadline,
        process=process,
        method="PUT",
        data=json.dumps(workspace_document).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    assert status_code == 204

    status_code, created_workspace = request_url(
        f"{base}/lab/api/workspaces/{workspace_name}?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert created_workspace["metadata"]["id"] == f"/{workspace_name}"
    assert created_workspace["data"]["layout-restorer:data"]["main"]["current"] == "launcher"

    status_code, workspace_list = request_url(
        f"{base}/lab/api/workspaces?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert f"/{workspace_name}" in workspace_list["workspaces"]["ids"]

    status_code, _ = request_url(
        f"{base}/lab/api/workspaces/{workspace_name}?token={token}",
        expect_json=False,
        deadline=deadline,
        process=process,
        method="DELETE",
    )
    assert status_code == 204

    status_code, deleted_workspace = request_url(
        f"{base}/lab/api/workspaces/{workspace_name}?token={token}",
        expect_json=True,
        deadline=deadline,
        process=process,
    )
    assert status_code == 200
    assert deleted_workspace["metadata"]["id"] == f"/{workspace_name}"
    assert deleted_workspace["data"] == {}

    verify_contents_crud(base, token, deadline, process)
    verify_session_runtime(port, token, deadline, process, work_dir=work_dir)


def main() -> int:
    args = parse_args()
    module_name = {
        "server": "jupyter_server",
        "notebook": "notebook",
        "lab": "jupyterlab",
    }[args.target]
    page_path = {
        "server": "/",
        "notebook": "/tree",
        "lab": "/lab",
    }[args.target]

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        work_dir = temp_root / "work"
        work_dir.mkdir()
        token = f"staticpython-{args.target}"
        port = reserve_port()
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                module_name,
                "--ServerApp.ip=127.0.0.1",
                f"--ServerApp.port={port}",
                "--ServerApp.port_retries=0",
                "--ServerApp.open_browser=False",
                f"--ServerApp.root_dir={work_dir}",
                f"--ServerApp.token={token}",
                "--ServerApp.password=",
            ],
            cwd=str(work_dir),
            env=make_env(temp_root),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        log_output = ""
        verification_succeeded = False
        try:
            deadline = time.time() + args.timeout
            if args.target == "server":
                verify_server_runtime(port, token, deadline, process, work_dir=work_dir)
            elif args.target == "notebook":
                verify_notebook_runtime(port, token, deadline, process, work_dir=work_dir)
            else:
                verify_lab_runtime(port, token, deadline, process, work_dir=work_dir)
            verification_succeeded = True
            return 0
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=15)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=15)
            if process.stdout is not None:
                log_output = process.stdout.read()
            if verification_succeeded:
                assert_log_health(log_output, args.target)
            if verification_succeeded and process.returncode not in (0, -15, 1):
                raise AssertionError(
                    f"{args.target} runtime exited unexpectedly with code {process.returncode}\n"
                    f"startup page: {page_path}\n"
                    f"log tail:\n{log_output[-8000:]}"
                )


if __name__ == "__main__":
    raise SystemExit(main())
