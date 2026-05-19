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
    if "version(" in text and "prompt_toolkit" in text:
        raise RuntimeError("prompt_toolkit version metadata anchor not found")
    return text


def _patch_prompt_toolkit_application(text: str) -> str:
    if "except AttributeError:\n                have_ctypes_signal = False\n" in text:
        return text

    helper_old = (
        "        # GraalPy has the functions, but they don't work\n"
        '        have_ctypes_signal = sys.implementation.name != "graalpy"\n'
    )
    helper_new = (
        "        # GraalPy has the functions, but they don't work\n"
        '        have_ctypes_signal = sys.implementation.name != "graalpy"\n'
        "        if have_ctypes_signal:\n"
        "            try:\n"
        "                pythonapi.PyOS_getsig\n"
        "                pythonapi.PyOS_setsig\n"
        "            except AttributeError:\n"
        "                have_ctypes_signal = False\n"
    )
    if helper_old in text:
        return replace_text_once(
            text,
            helper_old,
            helper_new,
            label="prompt_toolkit ctypes signal helper",
        )

    top_level_import_old = "from ctypes import c_int, c_void_p, pythonapi\n"
    top_level_import_new = (
        "try:\n"
        "    from ctypes import c_int, c_void_p, pythonapi\n"
        "except ImportError:\n"
        "    c_int = c_void_p = pythonapi = None\n"
        "    have_ctypes_signal = False\n"
        "else:\n"
        "    have_ctypes_signal = sys.implementation.name != \"graalpy\"\n"
    )
    top_level_setup_old = (
        "# PyOS_sighandler_t PyOS_getsig(int i)\n"
        "pythonapi.PyOS_getsig.restype = c_void_p\n"
        "pythonapi.PyOS_getsig.argtypes = (c_int,)\n"
        "\n"
        "# PyOS_sighandler_t PyOS_setsig(int i, PyOS_sighandler_t h)\n"
        "pythonapi.PyOS_setsig.restype = c_void_p\n"
        "pythonapi.PyOS_setsig.argtypes = (\n"
        "    c_int,\n"
        "    c_void_p,\n"
        ")\n"
    )
    top_level_setup_new = (
        "if have_ctypes_signal:\n"
        "    try:\n"
        "        # PyOS_sighandler_t PyOS_getsig(int i)\n"
        "        pythonapi.PyOS_getsig.restype = c_void_p\n"
        "        pythonapi.PyOS_getsig.argtypes = (c_int,)\n"
        "\n"
        "        # PyOS_sighandler_t PyOS_setsig(int i, PyOS_sighandler_t h)\n"
        "        pythonapi.PyOS_setsig.restype = c_void_p\n"
        "        pythonapi.PyOS_setsig.argtypes = (\n"
        "            c_int,\n"
        "            c_void_p,\n"
        "        )\n"
        "    except AttributeError:\n"
        "        have_ctypes_signal = False\n"
    )
    if top_level_import_old in text and top_level_setup_old in text:
        text = replace_text_once(
            text,
            top_level_import_old,
            top_level_import_new,
            label="prompt_toolkit top-level ctypes import",
        )
        text = replace_text_once(
            text,
            top_level_setup_old,
            top_level_setup_new,
            label="prompt_toolkit top-level ctypes signal setup",
        )
        text = replace_text_once(
            text,
            "                sigint_os = pythonapi.PyOS_getsig(signal.SIGINT)\n",
            "                sigint_os = pythonapi.PyOS_getsig(signal.SIGINT) if have_ctypes_signal else None\n",
            label="prompt_toolkit top-level ctypes getsig guard",
        )
        text = replace_text_once(
            text,
            "                    pythonapi.PyOS_setsig(signal.SIGINT, sigint_os)\n",
            "                    if have_ctypes_signal:\n"
            "                        pythonapi.PyOS_setsig(signal.SIGINT, sigint_os)\n",
            label="prompt_toolkit top-level ctypes setsig guard",
        )
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
    if "from ctypes import c_int, c_void_p, pythonapi" in text:
        raise RuntimeError("prompt_toolkit ctypes signal anchor not found")
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
