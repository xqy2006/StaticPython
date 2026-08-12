from __future__ import annotations

from libs import (
    ensure_package_markers,
    pypi_library,
    replace_text_once,
    source_path,
    transform_source_text,
    write_source_text,
)


LIBUI_CORE_SHIM = """\"\"\"Expose the builtin ``_libui_core`` module as ``libui.core``.\"\"\"

import _libui_core as _core

from _libui_core import *  # noqa: F401,F403

__doc__ = _core.__doc__
__all__ = getattr(_core, "__all__", [name for name in dir(_core) if not name.startswith("_")])


def __getattr__(name):
    return getattr(_core, name)


def __dir__():
    return sorted(set(globals()) | set(dir(_core)))
"""


LIBUI_COMMON_CONTROLS_MANIFEST_PRAGMA = r'''#pragma comment(linker, "/manifestdependency:\"type='win32' name='Microsoft.Windows.Common-Controls' version='6.0.0.0' processorArchitecture='*' publicKeyToken='6595b64144ccf1df' language='*'\"")
'''


def _patch_libui_init(text: str) -> str:
    text = ensure_package_markers(text, "libui")
    return replace_text_once(
        text,
        "    def insert_at(self, *args, **kwargs):\n"
        "        core.queue_main(lambda: self._core.insert_at(*args, **kwargs))\n",
        "    def insert_at(self, *args, **kwargs):\n"
        "        args = list(args)\n"
        "        if args and hasattr(args[0], \"_core\"):\n"
        "            args[0] = args[0]._core\n"
        "        if len(args) > 1 and hasattr(args[1], \"_core\"):\n"
        "            args[1] = args[1]._core\n"
        "        core.queue_main(lambda: self._core.insert_at(*args, **kwargs))\n",
        label="libui.__init__",
    )


def _patch_libui_declarative_init(text: str) -> str:
    return ensure_package_markers(text, "libui.declarative")


def _patch_libui_declarative_app(text: str) -> str:
    old = (
        "                    unsub = state.subscribe(\n"
        "                        lambda it=item, st=state: setattr(it, \"checked\", st.value)\n"
        "                    )\n"
    )
    old_single_line = (
        "                    unsub = state.subscribe(lambda it=item, st=state: setattr(it, \"checked\", st.value))\n"
    )
    new = (
        "                    unsub = state.subscribe(\n"
        "                        lambda it=item, st=state: core.queue_main(\n"
        "                            lambda it=it, st=st: setattr(it, \"checked\", st.value)\n"
        "                        )\n"
        "                    )\n"
    )
    if old in text:
        return replace_text_once(text, old, new, label="libui.declarative.app")
    if old_single_line in text:
        return replace_text_once(text, old_single_line, new, label="libui.declarative.app")
    if "state.subscribe" in text and 'setattr(it, "checked", st.value)' in text:
        raise RuntimeError("libui declarative checked-state subscription anchor not found")
    return text


def _patch_libui_native_module_text(text: str) -> str:
    text = replace_text_once(
        text,
        "PyInit_core",
        "PyInit__libui_core",
        label="libui native module initializer",
    )
    text = replace_text_once(
        text,
        '#include "module.h"\n',
        '#include "module.h"\n\n' + LIBUI_COMMON_CONTROLS_MANIFEST_PRAGMA,
        label="libui static Common Controls manifest",
    )
    return text.replace('"core"', '"_libui_core"')


def _patch_libui_native_module(context) -> None:
    py_module_root = source_path(context, "libui_builtin/py_module")
    if not py_module_root.exists():
        raise RuntimeError("libui native py_module source is missing")

    found_initializer = False
    for path in py_module_root.glob("*.[ch]"):
        if path.name == "builtin_alias.c":
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        if (
            "PyInit_core" not in text
            and "PyInit__libui_core" not in text
            and '"core"' not in text
        ):
            continue
        if "PyInit_core" in text or "PyInit__libui_core" in text:
            found_initializer = True
            updated = _patch_libui_native_module_text(text)
        else:
            updated = text.replace('"core"', '"_libui_core"')
        if updated != text:
            path.write_text(updated, encoding="utf-8", newline="\n")
            context.log(f"updated {path.relative_to(context.source_root)}")

    if not found_initializer:
        raise RuntimeError("libui native module initializer PyInit_core was not found")

    # The original module is now emitted with the final builtin name.  Keep the
    # overlay translation unit harmless so it cannot collide with imgui.core.
    write_source_text(
        context,
        "libui_builtin/py_module/builtin_alias.c",
        "/* StaticPython: libui's core module is renamed in-place. */\n",
    )


def patch_libui_sources(context) -> None:
    _patch_libui_native_module(context)
    transform_source_text(context, "Lib/libui/__init__.py", _patch_libui_init)
    write_source_text(context, "Lib/libui/core.py", LIBUI_CORE_SHIM)
    transform_source_text(
        context,
        "Lib/libui/declarative/__init__.py",
        _patch_libui_declarative_init,
    )
    transform_source_text(
        context,
        "Lib/libui/declarative/app.py",
        _patch_libui_declarative_app,
    )


LIBRARY_INTEGRATION = pypi_library(
    name="libui",
    source_mapping={
        "libui": "Lib/libui",
        "src/libui-ng": "libui_builtin/libui-ng",
        "src/py_module || src/libui": "libui_builtin/py_module",
    },
    overlay_entries=[
        "Lib/test/test_libui.py",
        "Lib/test/test_libui_gui.py",
        "PCbuild/_libui_core.vcxproj",
        "libui_builtin/py_module/builtin_alias.c",
        "libui_smoke_test.py",
    ],
    python_packages=["libui"],
    static_library_projects_release_x64=[
        "_libui_core.vcxproj",
    ],
    native_static_projects=[
        {
            "project": "_libui_core.vcxproj",
            "guid": "{2C4C0574-FDB9-48D3-B725-EB4F6A412C18}",
        }
    ],
    builtin_module_registrations=[
        {
            "name": "_libui_core",
            "pyinit": "PyInit__libui_core",
        }
    ],
    python_link_dependencies_release_x64=[
        "oleaut32.lib",
        "ole32.lib",
        "comctl32.lib",
        "uxtheme.lib",
        "msimg32.lib",
        "comdlg32.lib",
        "d2d1.lib",
        "dwrite.lib",
        "oleacc.lib",
        "uuid.lib",
        "windowscodecs.lib",
        "gdi32.lib",
        "_libui_core.lib",
    ],
    post_patch_hooks=[patch_libui_sources],
)
