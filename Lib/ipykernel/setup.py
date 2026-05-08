from __future__ import annotations

import base64
import re

from libs import replace_regex_once, simple_library, source_path, transform_source_text, write_source_text


def embed_ipykernel_resources(context) -> None:
    write_source_text(
        context,
        "Lib/ipykernel_launcher.py",
        '"""Entry point for launching an IPython kernel."""\n\n'
        "import sys\n\n"
        'if __name__ == "__main__":\n'
        "    if sys.path and sys.path[0] == \"\":\n"
        "        del sys.path[0]\n"
        "\n"
        "    from ipykernel import kernelapp as app\n"
        "\n"
        "    app.launch_new_instance()\n",
    )
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
                text, count = re.subn(
                    r"(import tempfile\n)",
                    (
                        "\\1"
                        "import importlib.util\n"
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
        if count != 1:
            text, count = re.subn(
                r'"metadata": \{"debugger": _is_debugpy_available\},',
                '"metadata": {"debugger": importlib.util.find_spec("debugpy") is not None},',
                text,
                count=1,
            )
        if count != 1:
            text, count = re.subn(
                r"'metadata': \{\s*'debugger': _is_debugpy_available\s*\}",
                '\'metadata\': {\'debugger\': importlib.util.find_spec("debugpy") is not None}',
                text,
                count=1,
            )
        if (
            count != 1
            and 'importlib.util.find_spec("debugpy") is not None' not in text
            and '"metadata":' in text
        ):
            raise RuntimeError("failed to patch ipykernel debugger metadata")

        if "Path(path)" in text and "_staticpython_resource_bytes" in text:
            return text
        text, count = re.subn(
            r"(?ms)^(\s*# stage resources\n)\s*shutil\.copytree\(RESOURCES, path\)\n",
            "\\1"
            "    path_text = str(path)\n"
            "    if os.path.isdir(RESOURCES):\n"
            "        shutil.copytree(RESOURCES, path_text)\n"
            "    else:\n"
            "        os.makedirs(path_text, exist_ok=True)\n"
            "        for resource_name in sorted(_STATICPYTHON_RESOURCES):\n"
            "            with open(os.path.join(path_text, resource_name), 'wb') as resource_file:\n"
            "                resource_file.write(_staticpython_resource_bytes(resource_name))\n",
            text,
            count=1,
        )
        if count != 1:
            raise RuntimeError("failed to patch ipykernel resource staging")
        return text

    transform_source_text(context, "Lib/ipykernel/kernelspec.py", patch_kernelspec)


LIBRARY_INTEGRATION = simple_library(
    name="ipykernel",
    source_mapping={
        "ipykernel": "Lib/ipykernel",
    },
    materialized_paths=[
        "Lib/ipykernel_launcher.py",
        "Lib/ipykernel/resources/logo-32x32.png",
        "Lib/ipykernel/resources/logo-64x64.png",
        "Lib/ipykernel/_static_resources.py",
    ],
    post_patch_hooks=[embed_ipykernel_resources],
)
