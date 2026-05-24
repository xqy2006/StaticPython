from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from libs import pypi_library, replace_regex_once, source_path, transform_source_text


def _patch_flexx_event_loop(text: str) -> str:
    if not text or "asyncio.get_event_loop()" not in text:
        return text
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


def _static_js_meta_literal(meta: dict) -> str:
    lines = ["{"]
    for key in ("vars_unknown", "vars_global", "std_functions", "std_methods"):
        values = sorted(str(value) for value in meta.get(key, []))
        lines.append(f"    {key!r}: set({values!r}),")
    # Keep build paths out of the frozen asset metadata.
    lines.append("    'filename': None,")
    lines.append(f"    'linenr': {meta.get('linenr', 1_000_000_000)!r},")
    lines.append("}")
    return "\n".join(lines)


def _render_static_js_block(payload: dict) -> str:
    return (
        "# Generate the code\n"
        "# StaticPython pre-generates this block because frozen modules do not expose\n"
        "# inspectable Python source code for PScript's import-time transpilation.\n"
        f"JS_EVENT = JSString({payload['source']!r})\n"
        f"JS_EVENT.meta = {_static_js_meta_literal(payload['meta'])}\n"
        "JS_FUNCS = JS_LOOP = JS_COMPONENT = JS_PROP = JS_EVENT\n"
        "assert JS_LOOP.count('._scheduled_call_to_iter') > 2  # prevent error after refactor\n"
    )


def _render_static_component_js_block(
    component_payload: dict,
    module_payload: dict,
    bsdf_extension_payload: dict,
) -> str:
    return (
        "# StaticPython pre-generates base app component JS because frozen\n"
        "# modules do not expose inspectable Python source code for PScript.\n"
        f"_STATICPYTHON_COMPONENT_JS = {component_payload!r}\n"
        f"_STATICPYTHON_MODULE_JS = {module_payload!r}\n"
        f"_STATICPYTHON_BSDF_EXTENSION_JS = {bsdf_extension_payload!r}\n"
    )


def _render_static_pscript_js_block(payload: dict) -> str:
    return (
        "# StaticPython pre-generates this PScript module because frozen modules\n"
        "# do not expose inspectable Python source code at runtime.\n"
        f"_STATICPYTHON_PSCRIPT_JS = {payload!r}\n"
    )


def _replace_regex_once_literal(text: str, pattern: str, replacement: str, *, label: str) -> str:
    if replacement in text:
        return text
    updated, count = re.subn(pattern, lambda _match: replacement, text, count=1)
    if count != 1:
        raise RuntimeError(f"expected regex not found in {label}: {pattern}")
    return updated


def _build_flexx_generator_import_root(context):
    base = context.work_cache_root.resolve()
    root = (context.work_cache_root / "flexx-jsgen-import" / context.version_full / context.source_root.name).resolve()
    if root != base and base not in root.parents:
        raise RuntimeError(f"refusing to prepare flexx generator import root outside work cache: {root}")
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    for package in ("flexx", "pscript"):
        source = source_path(context, f"Lib/{package}")
        if source.exists():
            shutil.copytree(
                source,
                root / package,
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
            )
    if not (root / "flexx").exists():
        raise RuntimeError("flexx package is missing from the materialized source tree")
    return root


def _run_flexx_js_generator(context, script: str, label: str) -> dict:
    env = os.environ.copy()
    import_root = str(_build_flexx_generator_import_root(context))
    existing_pythonpath = [
        path
        for path in env.get("PYTHONPATH", "").split(os.pathsep)
        if path and Path(path).resolve() != source_path(context, "Lib").resolve()
    ]
    env["PYTHONPATH"] = os.pathsep.join([import_root, *existing_pythonpath])
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(context.source_root),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"failed to pre-generate flexx {label} JS:\n"
            f"stdout:\n{completed.stdout}\n"
            f"stderr:\n{completed.stderr}"
        )
    output_lines = [line for line in completed.stdout.splitlines() if line.strip()]
    if not output_lines:
        raise RuntimeError(f"failed to pre-generate flexx {label} JS: generator produced no JSON output")
    return json.loads(output_lines[-1])


def _generate_static_js_event(context) -> dict:
    script = r"""
import json
from flexx.event import _js

meta = {}
for key, value in getattr(_js.JS_EVENT, "meta", {}).items():
    if isinstance(value, set):
        meta[key] = sorted(value)
    else:
        meta[key] = value
print(json.dumps({"source": str(_js.JS_EVENT), "meta": meta}, ensure_ascii=False))
"""
    return _run_flexx_js_generator(context, script, "event")


def _generate_static_component_js(context) -> dict:
    script = r"""
import importlib.util
import json
import logging
import sys
import types
from pathlib import Path

import flexx

app_dir = Path(flexx.__file__).parent / "app"
app_pkg = types.ModuleType("flexx.app")
app_pkg.__path__ = [str(app_dir)]
app_pkg.logger = logging.getLogger("flexx.app")
sys.modules["flexx.app"] = app_pkg

spec = importlib.util.spec_from_file_location("flexx.app._component2", app_dir / "_component2.py")
_component2 = importlib.util.module_from_spec(spec)
sys.modules["flexx.app._component2"] = _component2
spec.loader.exec_module(_component2)


def make_jsonable(value):
    if isinstance(value, set):
        return sorted(make_jsonable(item) for item in value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)):
        return [make_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {make_jsonable(key): make_jsonable(item) for key, item in value.items()}
    return value


payload = {}
for cls in (_component2.JsComponent, _component2.PyComponent):
    code = cls.JS.CODE
    meta = {key: make_jsonable(value) for key, value in getattr(code, "meta", {}).items()}
    payload[cls.__name__] = {"source": str(code), "meta": meta}
print(json.dumps(payload, ensure_ascii=False))
"""
    return _run_flexx_js_generator(context, script, "app component")


def _generate_static_module_js(context) -> dict:
    script = r"""
import importlib.util
import json
import logging
import sys
import types
from pathlib import Path

import flexx
from pscript import py2js

app_dir = Path(flexx.__file__).parent / "app"
app_pkg = types.ModuleType("flexx.app")
app_pkg.__path__ = [str(app_dir)]
app_pkg.logger = logging.getLogger("flexx.app")
sys.modules["flexx.app"] = app_pkg

spec = importlib.util.spec_from_file_location("flexx.app._component2", app_dir / "_component2.py")
_component2 = importlib.util.module_from_spec(spec)
sys.modules["flexx.app._component2"] = _component2
spec.loader.exec_module(_component2)


def make_jsonable(value):
    if isinstance(value, set):
        return sorted(make_jsonable(item) for item in value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)):
        return [make_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {make_jsonable(key): make_jsonable(item) for key, item in value.items()}
    return value


payload = {}
for name in ("LocalProperty",):
    code = py2js(getattr(_component2, name), inline_stdlib=False, docstrings=False)
    meta = {key: make_jsonable(value) for key, value in getattr(code, "meta", {}).items()}
    payload[name] = {"source": str(code), "meta": meta}
print(json.dumps(payload, ensure_ascii=False))
"""
    return _run_flexx_js_generator(context, script, "app module")


def _generate_static_bsdf_extension_js(context) -> dict:
    script = r"""
import importlib.util
import json
import logging
import sys
import types
from pathlib import Path

import flexx
from pscript import py2js

app_dir = Path(flexx.__file__).parent / "app"
app_pkg = types.ModuleType("flexx.app")
app_pkg.__path__ = [str(app_dir)]
app_pkg.logger = logging.getLogger("flexx.app")
sys.modules["flexx.app"] = app_pkg

spec = importlib.util.spec_from_file_location("flexx.app._component2", app_dir / "_component2.py")
_component2 = importlib.util.module_from_spec(spec)
sys.modules["flexx.app._component2"] = _component2
spec.loader.exec_module(_component2)


def make_jsonable(value):
    if isinstance(value, set):
        return sorted(make_jsonable(item) for item in value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)):
        return [make_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {make_jsonable(key): make_jsonable(item) for key, item in value.items()}
    return value


payload = {}
for cls_name in ("BsdfComponentExtension",):
    if not hasattr(_component2, cls_name):
        continue
    cls = getattr(_component2, cls_name)
    payload[cls_name] = {}
    for method_name in ("match", "encode", "decode"):
        code = py2js(getattr(cls, method_name + "_js"), indent=1, inline_stdlib=False, docstrings=False)
        meta = {key: make_jsonable(value) for key, value in getattr(code, "meta", {}).items()}
        payload[cls_name][method_name] = {"source": str(code), "meta": meta}
print(json.dumps(payload, ensure_ascii=False))
"""
    return _run_flexx_js_generator(context, script, "BSDF extension")


def _generate_static_pscript_module_js(context, module_name: str, module_file: str) -> dict:
    script = rf"""
import importlib.util
import json
import logging
import sys
import types
from pathlib import Path

import flexx
from pscript import py2js

app_dir = Path(flexx.__file__).parent / "app"
app_pkg = types.ModuleType("flexx.app")
app_pkg.__path__ = [str(app_dir)]
app_pkg.logger = logging.getLogger("flexx.app")
sys.modules["flexx.app"] = app_pkg

spec = importlib.util.spec_from_file_location({module_name!r}, app_dir / {module_file!r})
module = importlib.util.module_from_spec(spec)
sys.modules[{module_name!r}] = module
spec.loader.exec_module(module)


def make_jsonable(value):
    if isinstance(value, set):
        return sorted(make_jsonable(item) for item in value)
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")
    if isinstance(value, (list, tuple)):
        return [make_jsonable(item) for item in value]
    if isinstance(value, dict):
        return {{make_jsonable(key): make_jsonable(item) for key, item in value.items()}}
    return value


code = py2js(module, inline_stdlib=False, docstrings=False)
meta = {{key: make_jsonable(value) for key, value in getattr(code, "meta", {{}}).items()}}
print(json.dumps({{"source": str(code), "meta": meta}}, ensure_ascii=False))
"""
    return _run_flexx_js_generator(context, script, f"{module_name} PScript module")


def _try_generate_static_hasevents_js(context) -> str | None:
    script = r"""
import json
from flexx.event import _js

print(json.dumps({"source": str(_js.HasEventsJS.JSCODE)}, ensure_ascii=False))
"""
    try:
        return _run_flexx_js_generator(context, script, "HasEvents")["source"]
    except RuntimeError as exc:
        reason = next((line for line in reversed(str(exc).splitlines()) if line.strip()), type(exc).__name__)
        context.log(f"skip legacy flexx HasEvents JS pre-generation because the bundled transpiler failed: {reason}")
        return None


def _patch_flexx_static_event_js(context) -> None:
    path = source_path(context, "Lib/flexx/event/_js.py")
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if "JS_EVENT = JS_FUNCS + JS_LOGGER + JS_LOOP + JS_COMPONENT + JS_PROP" in text:
        payload = _generate_static_js_event(context)
        static_block = _render_static_js_block(payload)
        updated = _replace_regex_once_literal(
            text,
            r"(?ms)^# Generate the code\nmc = MetaCollector\(\)\nJS_FUNCS = .*?^assert JS_LOOP\.count\('\._scheduled_call_to_iter'\) > 2  # prevent error after refactor\n",
            static_block,
            label="flexx pre-generated event JS",
        )
    elif "HasEventsJS.JSCODE = get_HasEvents_js()" in text:
        jscode = _try_generate_static_hasevents_js(context)
        if jscode is None:
            return
        updated = _replace_regex_once_literal(
            text,
            r"(?m)^HasEventsJS\.JSCODE = get_HasEvents_js\(\)\s*$",
            f"# StaticPython pre-generates this because frozen modules do not expose\n"
            f"# inspectable Python source code for PScript's import-time transpilation.\n"
            f"HasEventsJS.JSCODE = {jscode!r}",
            label="flexx pre-generated HasEvents JS",
        )
    else:
        return
    if updated != text:
        path.write_text(updated, encoding="utf-8", newline="\n")
        context.log(f"updated {path.relative_to(context.source_root)}")


def _patch_flexx_static_component_js(context) -> None:
    path = source_path(context, "Lib/flexx/app/_component2.py")
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if "_STATICPYTHON_COMPONENT_JS" in text:
        return
    if "def _get_js(cls):" not in text or "cls.JS.CODE = cls._get_js()" not in text:
        return

    component_payload = _generate_static_component_js(context)
    module_payload = _generate_static_module_js(context)
    bsdf_extension_payload = _generate_static_bsdf_extension_js(context) if "class BsdfComponentExtension" in text else {}
    static_block = _render_static_component_js_block(component_payload, module_payload, bsdf_extension_payload)
    updated = _replace_regex_once_literal(
        text,
        r"(?m)^manager = None  # Set by __init__ to prevent circular dependencies\s*$",
        "manager = None  # Set by __init__ to prevent circular dependencies\n\n" + static_block,
        label="flexx static app component JS payload",
    )
    match = re.search(r"(?m)^(?P<indent>\s*)cls_name = cls\.__name__\s*$", updated)
    if match is None:
        raise RuntimeError("expected regex not found in flexx static app component JS lookup")
    indent = match.group("indent")
    replacement = (
        f"{indent}cls_name = cls.__name__\n"
        f"{indent}staticpython_payload = _STATICPYTHON_COMPONENT_JS.get(cls_name)\n"
        f"{indent}if staticpython_payload is not None:\n"
        f"{indent}    js = JSString(staticpython_payload['source'])\n"
        f"{indent}    js.meta = {{\n"
        f"{indent}        key: set(value) if isinstance(value, list) else value\n"
        f"{indent}        for key, value in staticpython_payload.get('meta', {{}}).items()\n"
        f"{indent}    }}\n"
        f"{indent}    return js"
    )
    updated = updated[: match.start()] + replacement + updated[match.end():]
    if updated != text:
        path.write_text(updated, encoding="utf-8", newline="\n")
        context.log(f"updated {path.relative_to(context.source_root)}")


def _patch_flexx_static_pscript_module_js(context) -> None:
    path = source_path(context, "Lib/flexx/app/_clientcore.py")
    if not path.exists():
        return
    text = path.read_text(encoding="utf-8")
    if "_STATICPYTHON_PSCRIPT_JS" in text:
        return
    if "__pscript__ = True" not in text and "__pyscript__ = True" not in text:
        return

    payload = _generate_static_pscript_module_js(context, "flexx.app._clientcore", "_clientcore.py")
    static_block = _render_static_pscript_js_block(payload)
    updated = _replace_regex_once_literal(
        text,
        r"(?m)^__(?:pyscript|pscript)__ = True\s*$",
        "__pscript__ = True\n\n" + static_block,
        label="flexx static _clientcore PScript JS payload",
    )
    if updated != text:
        path.write_text(updated, encoding="utf-8", newline="\n")
        context.log(f"updated {path.relative_to(context.source_root)}")


def _patch_flexx_static_module_js(context) -> None:
    component_path = source_path(context, "Lib/flexx/app/_component2.py")

    def patch(text: str) -> str:
        if not component_path.exists():
            return text
        if "_STATICPYTHON_MODULE_JS" not in component_path.read_text(encoding="utf-8", errors="ignore"):
            return text
        if "staticpython_payload = getattr(self._pymodule, '_STATICPYTHON_MODULE_JS', {}).get(name)" in text:
            return text
        target = (
            "                try:\n"
            "                    js = py2js(val, inline_stdlib=False, docstrings=False)\n"
            "                except Exception as err:\n"
            "                    t = 'JS in \"%s\" uses %r but cannot transpile it with PScript:\\n%s'\n"
            "                    raise ValueError(t % (self.filename, name, str(err)))"
        )
        replacement = (
            "                staticpython_payload = getattr(self._pymodule, '_STATICPYTHON_MODULE_JS', {}).get(name)\n"
            "                if staticpython_payload is not None:\n"
            "                    js = JSString(staticpython_payload['source'])\n"
            "                    js.meta = {\n"
            "                        key: set(value) if isinstance(value, list) else value\n"
            "                        for key, value in staticpython_payload.get('meta', {}).items()\n"
            "                    }\n"
            "                else:\n"
            "                    try:\n"
            "                        js = py2js(val, inline_stdlib=False, docstrings=False)\n"
            "                    except Exception as err:\n"
            "                        t = 'JS in \"%s\" uses %r but cannot transpile it with PScript:\\n%s'\n"
            "                        raise ValueError(t % (self.filename, name, str(err)))"
        )
        return _replace_regex_once_literal(
            text,
            re.escape(target),
            replacement,
            label="flexx pre-generated app module JS lookup",
        )

    transform_source_text(context, "Lib/flexx/app/_modules.py", patch, allow_missing=True)


def _patch_flexx_static_bsdf_extension_js(context) -> None:
    component_path = source_path(context, "Lib/flexx/app/_component2.py")

    def patch(text: str) -> str:
        if not component_path.exists():
            return text
        component_text = component_path.read_text(encoding="utf-8", errors="ignore")
        if "_STATICPYTHON_BSDF_EXTENSION_JS" not in component_text:
            return text
        if "staticpython_extension_payload = getattr(self._pymodule, '_STATICPYTHON_BSDF_EXTENSION_JS', {}).get(name)" in text:
            return text
        target = (
            "        elif isinstance(val, type) and issubclass(val, bsdf.Extension):\n"
            "            # A bit hacky mechanism to define BSDF extensions that also work in JS.\n"
            "            # todo: can we make this better? See also app/_component2.py (issue #429)\n"
            "            js = 'var %s = {name: \"%s\"' % (name, val.name)\n"
            "            for mname in ('match', 'encode', 'decode'):\n"
            "                func = getattr(val, mname + '_js')\n"
            "                funccode = py2js(func, indent=1, inline_stdlib=False, docstrings=False)\n"
            "                js += ',\\n    ' + mname + ':' + funccode.split('=', 1)[1].rstrip(' \\n;')\n"
            "                self._collect_dependencies(funccode, _dep_stack)\n"
            "            js += '};\\n'\n"
            "            js += 'serializer.add_extension(%s);\\n' % name\n"
            "            js = JSString(js)\n"
            "            js.meta = funccode.meta\n"
            "            self._pscript_code[name] = js\n"
            "            self._deps.setdefault('flexx.app._clientcore',\n"
            "                                 ['flexx.app._clientcore']).append('serializer')"
        )
        replacement = (
            "        elif isinstance(val, type) and issubclass(val, bsdf.Extension):\n"
            "            # A bit hacky mechanism to define BSDF extensions that also work in JS.\n"
            "            # todo: can we make this better? See also app/_component2.py (issue #429)\n"
            "            staticpython_extension_payload = getattr(self._pymodule, '_STATICPYTHON_BSDF_EXTENSION_JS', {}).get(name)\n"
            "            js = 'var %s = {name: \"%s\"' % (name, val.name)\n"
            "            for mname in ('match', 'encode', 'decode'):\n"
            "                if staticpython_extension_payload is not None:\n"
            "                    staticpython_func_payload = staticpython_extension_payload[mname]\n"
            "                    funccode = JSString(staticpython_func_payload['source'])\n"
            "                    funccode.meta = {\n"
            "                        key: set(value) if isinstance(value, list) else value\n"
            "                        for key, value in staticpython_func_payload.get('meta', {}).items()\n"
            "                    }\n"
            "                else:\n"
            "                    func = getattr(val, mname + '_js')\n"
            "                    funccode = py2js(func, indent=1, inline_stdlib=False, docstrings=False)\n"
            "                js += ',\\n    ' + mname + ':' + funccode.split('=', 1)[1].rstrip(' \\n;')\n"
            "                self._collect_dependencies(funccode, _dep_stack)\n"
            "            js += '};\\n'\n"
            "            js += 'serializer.add_extension(%s);\\n' % name\n"
            "            js = JSString(js)\n"
            "            js.meta = funccode.meta\n"
            "            self._pscript_code[name] = js\n"
            "            self._deps.setdefault('flexx.app._clientcore',\n"
            "                                 ['flexx.app._clientcore']).append('serializer')"
        )
        return _replace_regex_once_literal(
            text,
            re.escape(target),
            replacement,
            label="flexx pre-generated BSDF extension JS lookup",
        )

    transform_source_text(context, "Lib/flexx/app/_modules.py", patch, allow_missing=True)


def _patch_flexx_pscript_module_loader(context) -> None:
    clientcore_path = source_path(context, "Lib/flexx/app/_clientcore.py")

    def patch(text: str) -> str:
        if not clientcore_path.exists():
            return text
        if "_STATICPYTHON_PSCRIPT_JS" not in clientcore_path.read_text(encoding="utf-8", errors="ignore"):
            return text
        if "staticpython_payload = getattr(self._pymodule, '_STATICPYTHON_PSCRIPT_JS', None)" in text:
            return text
        target = (
            "        if is_pscript_module(self._pymodule):\n"
            "            # PScript module; transpile as a whole\n"
            "            js = py2js(self._pymodule, inline_stdlib=False, docstrings=False)\n"
            "            self._pscript_code['__all__'] = js\n"
            "            self._provided_names.update([n for n in js.meta['vars_defined']\n"
            "                                         if not n.startswith('_')])"
        )
        replacement = (
            "        if is_pscript_module(self._pymodule):\n"
            "            # PScript module; transpile as a whole\n"
            "            staticpython_payload = getattr(self._pymodule, '_STATICPYTHON_PSCRIPT_JS', None)\n"
            "            if staticpython_payload is not None:\n"
            "                js = JSString(staticpython_payload['source'])\n"
            "                js.meta = {\n"
            "                    key: set(value) if isinstance(value, list) else value\n"
            "                    for key, value in staticpython_payload.get('meta', {}).items()\n"
            "                }\n"
            "            else:\n"
            "                js = py2js(self._pymodule, inline_stdlib=False, docstrings=False)\n"
            "            self._pscript_code['__all__'] = js\n"
            "            self._provided_names.update([n for n in js.meta['vars_defined']\n"
            "                                         if not n.startswith('_')])"
        )
        return _replace_regex_once_literal(
            text,
            re.escape(target),
            replacement,
            label="flexx pre-generated PScript module JS loader",
        )

    transform_source_text(context, "Lib/flexx/app/_modules.py", patch, allow_missing=True)


def patch_flexx_sources(context) -> None:
    transform_source_text(context, "Lib/flexx/event/_loop.py", _patch_flexx_event_loop, allow_missing=True)
    _patch_flexx_static_event_js(context)
    _patch_flexx_static_pscript_module_js(context)
    _patch_flexx_pscript_module_loader(context)
    _patch_flexx_static_component_js(context)
    _patch_flexx_static_bsdf_extension_js(context)
    _patch_flexx_static_module_js(context)


LIBRARY_INTEGRATION = pypi_library(
    name="flexx",
    source_mapping={
        "flexx": "Lib/flexx",
    },
    python_packages=["flexx"],
    post_patch_hooks=[patch_flexx_sources],
)
