from __future__ import annotations

import base64
import re

from libs import inline_verification_step, simple_library, source_path, transform_source_text, write_source_text


def embed_ipykernel_resources(context) -> None:
    resources_root = source_path(context, "Lib/ipykernel/resources")
    encoded_resources = {
        path.name: base64.b64encode(path.read_bytes()).decode("ascii")
        for path in sorted(resources_root.iterdir())
        if path.is_file()
    }
    write_source_text(
        context,
        "Lib/ipykernel/_static_resources.py",
        "import base64\n\n"
        + "RESOURCES = "
        + repr(encoded_resources)
        + "\n\n\n"
        + "def resource_bytes(name: str) -> bytes:\n"
        + "    return base64.b64decode(RESOURCES[name])\n",
    )

    def patch_kernelspec(text: str) -> str:
        if "from ._static_resources import" not in text:
            text, count = re.subn(
                r"(import tempfile\nfrom pathlib import Path\nfrom typing import Any\n)",
                (
                    "\\1"
                    "\nimport importlib.util\n"
                    "from ._static_resources import (\n"
                    "    RESOURCES as _STATICPYTHON_RESOURCES,\n"
                    "    resource_bytes as _staticpython_resource_bytes,\n"
                    ")\n"
                ),
                text,
                count=1,
            )
            if count != 1:
                raise RuntimeError("failed to patch ipykernel kernelspec imports")

        text, count = re.subn(
            r'"metadata": \{"debugger": True\},',
            '"metadata": {"debugger": importlib.util.find_spec("debugpy") is not None},',
            text,
            count=1,
        )
        if count != 1 and 'importlib.util.find_spec("debugpy") is not None' not in text:
            raise RuntimeError("failed to patch ipykernel debugger metadata")

        old = "    # stage resources\\n    shutil.copytree(RESOURCES, path)\\n"
        new = (
            "    # stage resources\\n"
            "    path = Path(path)\\n"
            "    if os.path.isdir(RESOURCES):\\n"
            "        shutil.copytree(RESOURCES, path)\\n"
            "    else:\\n"
            "        path.mkdir(parents=True, exist_ok=True)\\n"
            "        for resource_name in sorted(_STATICPYTHON_RESOURCES):\\n"
            "            (path / resource_name).write_bytes(_staticpython_resource_bytes(resource_name))\\n"
        )
        if old in text:
            text = text.replace(old, new, 1)
        elif "_STATICPYTHON_RESOURCES" not in text:
            raise RuntimeError("failed to patch ipykernel resource staging")
        return text

    transform_source_text(context, "Lib/ipykernel/kernelspec.py", patch_kernelspec)


LIBRARY_INTEGRATION = simple_library(
    name="ipykernel",
    overlay_entries=["Lib/ipykernel", "Lib/ipykernel_launcher.py"],
    verification_imports=["ipykernel_launcher"],
    materialized_paths=[
        "Lib/ipykernel/resources/logo-32x32.png",
        "Lib/ipykernel/resources/logo-64x64.png",
        "Lib/ipykernel/resources/logo-svg.svg",
        "Lib/ipykernel/_static_resources.py",
    ],
    verification_materialized_paths=[
        "Lib/ipykernel/resources/logo-32x32.png",
        "Lib/ipykernel/resources/logo-64x64.png",
        "Lib/ipykernel/resources/logo-svg.svg",
    ],
    post_patch_hooks=[embed_ipykernel_resources],
    verification_steps=[
        inline_verification_step(
            "ipykernel-smoke",
            """
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

import ipykernel
from ipykernel.kernelspec import write_kernel_spec
from jupyter_client import KernelManager
from jupyter_client.kernelspec import KernelSpecManager

with tempfile.TemporaryDirectory() as temp_dir:
    spec_dir = Path(temp_dir) / "kernels" / "python3"
    written_dir = Path(write_kernel_spec(spec_dir))
    assert written_dir == spec_dir

    kernel_json = json.loads((spec_dir / "kernel.json").read_text(encoding="utf-8"))
    has_debugpy = importlib.util.find_spec("debugpy") is not None
    assert kernel_json["argv"][0] == sys.executable
    assert kernel_json["argv"][1:4] == ["-m", "ipykernel_launcher", "-f"]
    assert kernel_json["metadata"]["debugger"] is has_debugpy
    assert (spec_dir / "logo-32x32.png").read_bytes().startswith(b"\\x89PNG")
    assert (spec_dir / "logo-64x64.png").read_bytes().startswith(b"\\x89PNG")
    assert "<svg" in (spec_dir / "logo-svg.svg").read_text(encoding="utf-8")

    prefix = Path(temp_dir) / "prefix"
    kernels_dir = prefix / "share" / "jupyter" / "kernels"
    kernel_spec_manager = KernelSpecManager(
        kernel_dirs=[str(kernels_dir)],
        ensure_native_kernel=False,
    )
    installed_path = Path(
        kernel_spec_manager.install_kernel_spec(
            str(spec_dir),
            kernel_name="python3",
            prefix=str(prefix),
        )
    )
    assert installed_path == kernels_dir / "python3"
    assert (installed_path / "kernel.json").exists()

    manager = KernelManager(
        kernel_name="python3",
        kernel_spec_manager=kernel_spec_manager,
    )
    manager.connection_file = str((Path(temp_dir) / "connection.json").resolve())
    manager.start_kernel()
    client = manager.client()
    client.start_channels()
    try:
        client.wait_for_ready(timeout=60)

        execute_id = client.execute("answer = 40 + 2\\nanswer")
        while True:
            reply = client.get_shell_msg(timeout=60)
            if reply.get("parent_header", {}).get("msg_id") == execute_id:
                break
        assert reply["content"]["status"] == "ok"

        execute_result = None
        while True:
            message = client.get_iopub_msg(timeout=60)
            if message.get("parent_header", {}).get("msg_id") != execute_id:
                continue
            msg_type = message["header"]["msg_type"]
            if msg_type == "execute_result":
                execute_result = message["content"]["data"]["text/plain"]
            if msg_type == "status" and message["content"]["execution_state"] == "idle":
                break
        assert execute_result == "42"

        complete_id = client.complete("ans", 3)
        while True:
            completion = client.get_shell_msg(timeout=60)
            if completion.get("parent_header", {}).get("msg_id") == complete_id:
                break
        assert "answer" in completion["content"]["matches"]
    finally:
        client.stop_channels()
        manager.shutdown_kernel(now=True)
""",
            timeout=600,
        )
    ],
)
