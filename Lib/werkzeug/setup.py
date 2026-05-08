import re

from libs import simple_library, transform_source_text


def _patch_werkzeug_init(text: str) -> str:
    if "PackageNotFoundError" in text:
        return text
    updated, count = re.subn(
        r'(?m)^__version__ = (?:importlib\.metadata\.)?version\("werkzeug"\)\n',
        (
            "try:\n"
            '    __version__ = importlib.metadata.version("werkzeug")\n'
            "except importlib.metadata.PackageNotFoundError:\n"
            '    __version__ = "0+staticpython"\n'
        ),
        text,
        count=1,
    )
    if count == 1:
        if "import importlib.metadata" not in updated and "from importlib import metadata" not in updated:
            if updated.startswith("from "):
                return "import importlib.metadata\n" + updated
            return "import importlib.metadata\n\n" + updated
        return updated
    return text


def patch_werkzeug_sources(context) -> None:
    transform_source_text(context, "Lib/werkzeug/__init__.py", _patch_werkzeug_init)


LIBRARY_INTEGRATION = simple_library(
    name='werkzeug',
    overlay_entries=['Lib/werkzeug'],
    post_patch_hooks=[patch_werkzeug_sources],
)
