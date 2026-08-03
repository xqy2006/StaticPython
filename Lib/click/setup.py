import re

from libs import replace_regex_once, replace_text_once, simple_library, transform_source_text


def _patch_click_compat(text: str) -> str:
    if '_get_windows_console_stream' not in text:
        if "._winconsole" in text or "_winconsole" in text:
            raise RuntimeError("click._compat Windows console import anchor not found")
        return text
    modern_import_guard = (
        '    try:\n'
        '        from ._winconsole import _get_windows_console_stream\n'
        '    except Exception:\n'
        '        _get_windows_console_stream = lambda *x: None\n'
    )
    if modern_import_guard in text:
        return text
    if "if sys.platform.startswith(\"win\") and WIN:" in text:
        return replace_regex_once(
            text,
            r'(?m)^([ \t]*)from \._winconsole import _get_windows_console_stream\s*$',
            r'\1try:\n\1    from ._winconsole import _get_windows_console_stream\n\1except Exception:\n\1    _get_windows_console_stream = lambda *x: None',
            label="click._compat modern windows import",
        )
    if "if WIN:" in text:
        return replace_regex_once(
            text,
            r'(?ms)^if WIN:\n.*?^\s*def _get_argv_encoding\(\):\n',
            'if WIN:\n'
            '    # Windows has a smaller terminal\n'
            '    DEFAULT_COLUMNS = 79\n\n'
            '    try:\n'
            '        from ._winconsole import _get_windows_console_stream\n'
            '    except Exception:\n'
            '        _get_windows_console_stream = lambda *x: None\n\n'
            '    def _get_argv_encoding():\n',
            label="click._compat legacy windows block",
        )
    raise RuntimeError("click._compat Windows console import anchor not found")


def _patch_click_winconsole(text: str) -> str:
    if "PyObject_GetBuffer" not in text:
        if "Py_buffer" in text or "pythonapi" in text:
            raise RuntimeError("click._winconsole PyObject_GetBuffer anchor not found")
        return text
    if "except (AttributeError, ImportError):\n    pythonapi = None\n" in text:
        return text
    if "except ImportError:\n    pythonapi = None\n" in text:
        return replace_text_once(
            text,
            "except ImportError:\n    pythonapi = None\n",
            "except (AttributeError, ImportError):\n    pythonapi = None\n",
            label="click._winconsole pythonapi import guard",
        )
    if "except AttributeError:\n        get_buffer = None\n    else:\n\n        def get_buffer" in text:
        return text
    updated, count = re.subn(
        r"(?ms)^    PyObject_GetBuffer = pythonapi\.PyObject_GetBuffer\n"
        r"    PyBuffer_Release = pythonapi\.PyBuffer_Release\n\n"
        r"(?P<func>    def get_buffer\(.*?^            PyBuffer_Release\(byref\(buf\)\)\n)",
        lambda match: (
            "    try:\n"
            "        PyObject_GetBuffer = pythonapi.PyObject_GetBuffer\n"
            "        PyBuffer_Release = pythonapi.PyBuffer_Release\n"
            "    except AttributeError:\n"
            "        get_buffer = None\n"
            "    else:\n\n"
            + "".join("    " + line if line.strip() else line for line in match.group("func").splitlines(keepends=True))
        ),
        text,
        count=1,
    )
    if count:
        return updated
    top_level_assignments = (
        "PyObject_GetBuffer = pythonapi.PyObject_GetBuffer\n"
        "PyBuffer_Release = pythonapi.PyBuffer_Release\n"
    )
    if top_level_assignments in text:
        text = replace_text_once(
            text,
            top_level_assignments,
            "try:\n"
            "    PyObject_GetBuffer = pythonapi.PyObject_GetBuffer\n"
            "    PyBuffer_Release = pythonapi.PyBuffer_Release\n"
            "except AttributeError:\n"
            "    PyObject_GetBuffer = None\n"
            "    PyBuffer_Release = None\n",
            label="click._winconsole top-level pythonapi import guard",
        )
        updated, count = re.subn(
            r"(?ms)^(?P<func>def get_buffer\(.*?^        PyBuffer_Release\(byref\(buf\)\)\n)",
            lambda match: (
                "if PyObject_GetBuffer is None:\n"
                "    get_buffer = None\n"
                "else:\n\n"
                + "".join("    " + line if line.strip() else line for line in match.group("func").splitlines(keepends=True))
            ),
            text,
            count=1,
        )
        if count == 0:
            raise RuntimeError("click._winconsole top-level get_buffer anchor not found")
        return updated
    old_legacy = (
        "    PyObject_GetBuffer = pythonapi.PyObject_GetBuffer\n"
        "    PyBuffer_Release = pythonapi.PyBuffer_Release\n\n"
        "    def get_buffer(obj, writable=False):\n"
        "        buf = Py_buffer()\n"
        "        flags = PyBUF_WRITABLE if writable else PyBUF_SIMPLE\n"
        "        PyObject_GetBuffer(py_object(obj), byref(buf), flags)\n"
        "        try:\n"
        "            buffer_type = c_char * buf.len\n"
        "            return buffer_type.from_address(buf.buf)\n"
        "        finally:\n"
        "            PyBuffer_Release(byref(buf))\n"
    )
    new_legacy = (
        "    try:\n"
        "        PyObject_GetBuffer = pythonapi.PyObject_GetBuffer\n"
        "        PyBuffer_Release = pythonapi.PyBuffer_Release\n"
        "    except AttributeError:\n"
        "        get_buffer = None\n"
        "    else:\n"
        "\n"
        "        def get_buffer(obj, writable=False):\n"
        "            buf = Py_buffer()\n"
        "            flags = PyBUF_WRITABLE if writable else PyBUF_SIMPLE\n"
        "            PyObject_GetBuffer(py_object(obj), byref(buf), flags)\n"
        "\n"
        "            try:\n"
        "                buffer_type = c_char * buf.len\n"
        "                return buffer_type.from_address(buf.buf)\n"
        "            finally:\n"
        "                PyBuffer_Release(byref(buf))\n"
    )
    if old_legacy in text:
        return replace_text_once(
            text,
            old_legacy,
            new_legacy,
            label="click._winconsole",
        )
    old_modern = (
        "    PyObject_GetBuffer = pythonapi.PyObject_GetBuffer\n"
        "    PyBuffer_Release = pythonapi.PyBuffer_Release\n\n"
        "    def get_buffer(obj: Buffer, writable: bool = False) -> Array[c_char]:\n"
        "        buf = Py_buffer()\n"
        "        flags: int = PyBUF_WRITABLE if writable else PyBUF_SIMPLE\n"
        "        PyObject_GetBuffer(py_object(obj), byref(buf), flags)\n"
        "\n"
        "        try:\n"
        "            buffer_type = c_char * buf.len\n"
        "            out: Array[c_char] = buffer_type.from_address(buf.buf)\n"
        "            return out\n"
        "        finally:\n"
        "            PyBuffer_Release(byref(buf))\n"
    )
    if old_modern in text:
        return replace_text_once(
            text,
            old_modern,
            new_legacy,
            label="click._winconsole",
        )
    raise RuntimeError("click._winconsole PyObject_GetBuffer anchor not found")


def patch_click_sources(context) -> None:
    transform_source_text(context, "Lib/click/_compat.py", _patch_click_compat)
    transform_source_text(
        context,
        "Lib/click/_winconsole.py",
        _patch_click_winconsole,
        allow_missing=True,
    )


LIBRARY_INTEGRATION = simple_library(
    name='click',
    dependencies=['colorama'],
    overlay_entries=['Lib/click'],
    release_version='8.4.2',
    source_archive_sha256_by_version={
        '8.4.2': '9a6cea6e60b17ebe0a44c5cc636d94f09bd66142c1cd7d8b4cd731c4917a15f6',
    },
    post_patch_hooks=[patch_click_sources],
)
