from __future__ import annotations

from libs import pypi_library, replace_regex_once, transform_source_text


def _patch_flexx_event_loop(text: str) -> str:
    if "asyncio.new_event_loop()" in text:
        return text
    return replace_regex_once(
        text,
        r"(?m)^(?P<indent>\s*)loop = asyncio\.get_event_loop\(\)\s*$",
        "\\g<indent>try:\n"
        "\\g<indent>    loop = asyncio.get_event_loop()\n"
        "\\g<indent>except RuntimeError:\n"
        "\\g<indent>    loop = asyncio.new_event_loop()\n"
        "\\g<indent>    asyncio.set_event_loop(loop)",
        label="flexx asyncio default event loop fallback",
    )


def patch_flexx_sources(context) -> None:
    transform_source_text(context, "Lib/flexx/event/_loop.py", _patch_flexx_event_loop)


LIBRARY_INTEGRATION = pypi_library(
    name="flexx",
    source_mapping={
        "flexx": "Lib/flexx",
    },
    python_packages=["flexx"],
    post_patch_hooks=[patch_flexx_sources],
)
