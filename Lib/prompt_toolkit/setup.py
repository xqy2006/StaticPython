import re

from libs import (
    replace_text_once,
    simple_library,
    transform_first_existing_source_text,
    transform_source_text,
)


def _patch_prompt_toolkit_init(text: str) -> str:
    if "metadata.PackageNotFoundError" in text:
        return text
    if "importlib_metadata.PackageNotFoundError" in text:
        return text
    updated, count = re.subn(
        r'(?m)^__version__\s*=\s*(metadata|importlib_metadata)\.version\([\'"]prompt_toolkit[\'"]\)\s*$',
        (
            "try:\n"
            '    __version__ = metadata.version("prompt_toolkit")\n'
            "except metadata.PackageNotFoundError:\n"
            '    __version__ = "3.0.52"'
        ),
        text,
        count=1,
    )
    if count == 1:
        return updated
    updated, count = re.subn(
        r'(?m)^__version__\s*=\s*(?:getattr\()?metadata,?\s*[\'"]version[\'"]?\)?',
        (
            "try:\n"
            '    __version__ = metadata.version("prompt_toolkit")\n'
            "except Exception:\n"
            '    __version__ = "3.0.52"'
        ),
        text,
        count=1,
    )
    if count == 1:
        return updated
    return text


def _patch_prompt_toolkit_application(text: str) -> str:
    if "pythonapi.PyOS_getsig" in text and "have_ctypes_signal = False" in text:
        return text

    old = (
        "    try:\n"
        "        from ctypes import c_int, c_void_p, pythonapi\n"
        "    except ImportError:\n"
        "        # Any of the above imports don't exist? Don't do anything here.\n"
        "        yield\n"
        "        return\n"
    )
    new = (
        "    try:\n"
        "        from ctypes import c_int, c_void_p, pythonapi\n"
        "        pythonapi.PyOS_getsig\n"
        "        pythonapi.PyOS_setsig\n"
        "    except (ImportError, AttributeError):\n"
        "        # Any of the above imports don't exist? Don't do anything here.\n"
        "        yield\n"
        "        return\n"
    )
    if old in text:
        return text.replace(old, new, 1)

    updated, count = re.subn(
        r"(?s)    try:\n        from ctypes import c_int, c_void_p, pythonapi\n    except ImportError:\n        # Any of the above imports don't exist\? Don't do anything here\.\n        yield\n        return\n",
        new,
        text,
        count=1,
    )
    if count == 1:
        return updated
    return text


def patch_prompt_toolkit_sources(context) -> None:
    transform_source_text(context, "Lib/prompt_toolkit/__init__.py", _patch_prompt_toolkit_init)
    transform_first_existing_source_text(
        context,
        [
            "Lib/prompt_toolkit/application/application.py",
            "Lib/prompt_toolkit/interface.py",
        ],
        _patch_prompt_toolkit_application,
        allow_all_missing=True,
    )


LIBRARY_INTEGRATION = simple_library(
    name='prompt_toolkit',
    overlay_entries=['Lib/prompt_toolkit'],
    post_patch_hooks=[patch_prompt_toolkit_sources],
)
