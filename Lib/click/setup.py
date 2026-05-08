from libs import replace_regex_once, simple_library, transform_source_text


def _patch_click_compat(text: str) -> str:
    if 'from ._winconsole import _get_windows_console_stream' not in text:
        return text
    return replace_regex_once(
        text,
        r'if sys\.platform\.startswith\("win"\) and WIN:\n\s+from \._winconsole import _get_windows_console_stream\n',
        'if sys.platform.startswith("win") and WIN:\n'
        '    try:\n'
        '        from ._winconsole import _get_windows_console_stream\n'
        '    except Exception:\n'
        '        def _get_windows_console_stream(f, encoding=None, errors=None):\n'
        '            return None\n',
        label="click._compat",
    )


def _patch_click_winconsole(text: str) -> str:
    if "PyObject_GetBuffer = pythonapi.PyObject_GetBuffer" not in text:
        return text
    return replace_regex_once(
        text,
        r"(?ms)    PyObject_GetBuffer = pythonapi\.PyObject_GetBuffer\n    PyBuffer_Release = pythonapi\.PyBuffer_Release\n\n    def get_buffer\(.*?^            PyBuffer_Release\(byref\(buf\)\)\n",
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
        "                out = buffer_type.from_address(buf.buf)\n"
        "                return out\n"
        "            finally:\n"
        "                PyBuffer_Release(byref(buf))\n",
        label="click._winconsole",
    )


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
    overlay_entries=['Lib/click'],
    post_patch_hooks=[patch_click_sources],
)
