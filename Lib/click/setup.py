from libs import replace_text_once, simple_library, transform_source_text


def _patch_click_compat(text: str) -> str:
    old = (
        'if sys.platform.startswith("win") and WIN:\n'
        "    from ._winconsole import _get_windows_console_stream\n"
    )
    new = (
        'if sys.platform.startswith("win") and WIN:\n'
        "    try:\n"
        "        from ._winconsole import _get_windows_console_stream\n"
        "    except Exception:\n"
        "        def _get_windows_console_stream(\n"
        "            f: t.TextIO, encoding: str | None, errors: str | None\n"
        "        ) -> t.TextIO | None:\n"
        "            return None\n"
    )
    return replace_text_once(text, old, new, label="click._compat")


def _patch_click_winconsole(text: str) -> str:
    old = (
        "    PyObject_GetBuffer = pythonapi.PyObject_GetBuffer\n"
        "    PyBuffer_Release = pythonapi.PyBuffer_Release\n"
        "\n"
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
    new = (
        "    try:\n"
        "        PyObject_GetBuffer = pythonapi.PyObject_GetBuffer\n"
        "        PyBuffer_Release = pythonapi.PyBuffer_Release\n"
        "    except AttributeError:\n"
        "        get_buffer = None\n"
        "    else:\n"
        "\n"
        "        def get_buffer(obj: Buffer, writable: bool = False) -> Array[c_char]:\n"
        "            buf = Py_buffer()\n"
        "            flags: int = PyBUF_WRITABLE if writable else PyBUF_SIMPLE\n"
        "            PyObject_GetBuffer(py_object(obj), byref(buf), flags)\n"
        "\n"
        "            try:\n"
        "                buffer_type = c_char * buf.len\n"
        "                out: Array[c_char] = buffer_type.from_address(buf.buf)\n"
        "                return out\n"
        "            finally:\n"
        "                PyBuffer_Release(byref(buf))\n"
    )
    return replace_text_once(text, old, new, label="click._winconsole")


def patch_click_sources(context) -> None:
    transform_source_text(context, "Lib/click/_compat.py", _patch_click_compat)
    transform_source_text(context, "Lib/click/_winconsole.py", _patch_click_winconsole)


LIBRARY_INTEGRATION = simple_library(
    name='click',
    overlay_entries=['Lib/click'],
    post_patch_hooks=[patch_click_sources],
)
