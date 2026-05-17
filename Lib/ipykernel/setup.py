from __future__ import annotations

import base64
import re

from libs import simple_library, source_path, transform_source_text, write_source_text


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
                r"(from jupyter_client\.kernelspec import KernelSpecManager\n)",
                (
                    "import importlib.util\n"
                    "\\1"
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
            r'"metadata": \{"debugger": [^}]+\},',
            '"metadata": {"debugger": importlib.util.find_spec("debugpy") is not None},',
            text,
            count=1,
        )
        if count != 1 and 'importlib.util.find_spec("debugpy") is not None' not in text:
            raise RuntimeError("failed to patch ipykernel debugger metadata")

        text, count = re.subn(
            r"    # stage resources\n    shutil\.copytree\(RESOURCES, path\)\n",
            "    # stage resources\n"
            "    if os.path.isdir(RESOURCES):\n"
            "        shutil.copytree(RESOURCES, path)\n"
            "    else:\n"
            "        os.makedirs(path, exist_ok=True)\n"
            "        for resource_name in sorted(_STATICPYTHON_RESOURCES):\n"
            "            with open(pjoin(path, resource_name), \"wb\") as handle:\n"
            "                handle.write(_staticpython_resource_bytes(resource_name))\n",
            text,
            count=1,
        )
        if count != 1 and "_staticpython_resource_bytes(resource_name)" not in text:
            raise RuntimeError("failed to patch ipykernel resource staging")
        return text

    transform_source_text(context, "Lib/ipykernel/kernelspec.py", patch_kernelspec)


LIBRARY_INTEGRATION = simple_library(
    name="ipykernel",
    overlay_entries=["Lib/ipykernel", "Lib/ipykernel_launcher.py"],
    materialized_paths=[
        "Lib/ipykernel/resources/logo-32x32.png",
        "Lib/ipykernel/resources/logo-64x64.png",
        "Lib/ipykernel/resources/logo-svg.svg",
        "Lib/ipykernel/_static_resources.py",
    ],
    post_patch_hooks=[embed_ipykernel_resources],
)
