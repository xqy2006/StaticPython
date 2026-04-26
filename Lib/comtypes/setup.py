from libs import replace_text_once, simple_library, transform_source_text


def _patch_instancemethod(text: str) -> str:
    old = (
        "pythonapi.PyInstanceMethod_New.argtypes = [py_object]\n"
        "pythonapi.PyInstanceMethod_New.restype = py_object\n"
        "PyInstanceMethod_Type = type(pythonapi.PyInstanceMethod_New(id))\n"
        "\n"
        "\n"
        "def instancemethod(func, inst, cls):\n"
        "    mth = PyInstanceMethod_Type(func)\n"
        "    if inst is None:\n"
        "        return mth\n"
        "    return mth.__get__(inst)\n"
    )
    new = (
        "try:\n"
        "    pythonapi.PyInstanceMethod_New.argtypes = [py_object]\n"
        "    pythonapi.PyInstanceMethod_New.restype = py_object\n"
        "except AttributeError:\n"
        "    PyInstanceMethod_Type = None\n"
        "else:\n"
        "    PyInstanceMethod_Type = type(pythonapi.PyInstanceMethod_New(id))\n"
        "\n"
        "\n"
        "class _FallbackInstanceMethod:\n"
        "    def __init__(self, func, inst=None):\n"
        "        self._func = func\n"
        "        self._inst = inst\n"
        "        self.__name__ = getattr(func, \"__name__\", type(func).__name__)\n"
        "        self.__doc__ = getattr(func, \"__doc__\", None)\n"
        "\n"
        "    def __call__(self, *args, **kwargs):\n"
        "        if self._inst is None:\n"
        "            return self._func(*args, **kwargs)\n"
        "        return self._func(self._inst, *args, **kwargs)\n"
        "\n"
        "    def __get__(self, inst, cls=None):\n"
        "        if inst is None:\n"
        "            return self\n"
        "        return type(self)(self._func, inst)\n"
        "\n"
        "\n"
        "def instancemethod(func, inst, cls):\n"
        "    if PyInstanceMethod_Type is not None:\n"
        "        mth = PyInstanceMethod_Type(func)\n"
        "        if inst is None:\n"
        "            return mth\n"
        "        return mth.__get__(inst)\n"
        "    mth = _FallbackInstanceMethod(func)\n"
        "    if inst is None:\n"
        "        return mth\n"
        "    return mth.__get__(inst, cls)\n"
    )
    return replace_text_once(text, old, new, label="comtypes._post_coinit.instancemethod")


def patch_comtypes_sources(context) -> None:
    transform_source_text(
        context,
        "Lib/comtypes/_post_coinit/instancemethod.py",
        _patch_instancemethod,
    )


LIBRARY_INTEGRATION = simple_library(
    name='comtypes',
    overlay_entries=['Lib/comtypes'],
    post_patch_hooks=[patch_comtypes_sources],
)
