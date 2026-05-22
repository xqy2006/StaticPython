from __future__ import annotations

from libs import pypi_library, transform_source_text


def _patch_pystray_source(text: str) -> str:
    return text.replace("Moses Palmér", "Moses Palmer")


def patch_pystray_sources(context) -> None:
    for relative in (
        "__init__.py",
        "_appindicator.py",
        "_base.py",
        "_darwin.py",
        "_dummy.py",
        "_gtk.py",
        "_info.py",
        "_util/__init__.py",
        "_util/gtk.py",
        "_util/notify_dbus.py",
        "_util/win32.py",
        "_win32.py",
        "_xorg.py",
    ):
        transform_source_text(context, f"Lib/pystray/{relative}", _patch_pystray_source, allow_missing=True)


LIBRARY_INTEGRATION = pypi_library(
    name="pystray",
    source_mapping={
        "pystray": "Lib/pystray",
    },
    python_packages=["pystray"],
    post_patch_hooks=[patch_pystray_sources],
)
