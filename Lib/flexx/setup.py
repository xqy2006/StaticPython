from __future__ import annotations

import json
import os
import subprocess
import sys

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


def _run_flexx_js_generator(context, script: str, label: str) -> dict:
    env = os.environ.copy()
    lib_path = str(source_path(context, "Lib"))
    env["PYTHONPATH"] = lib_path + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
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
        updated = replace_regex_once(
            text,
            r"(?ms)^# Generate the code\nmc = MetaCollector\(\)\nJS_FUNCS = .*?^assert JS_LOOP\.count\('\._scheduled_call_to_iter'\) > 2  # prevent error after refactor\n",
            static_block,
            label="flexx pre-generated event JS",
        )
    elif "HasEventsJS.JSCODE = get_HasEvents_js()" in text:
        jscode = _try_generate_static_hasevents_js(context)
        if jscode is None:
            return
        updated = replace_regex_once(
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


def patch_flexx_sources(context) -> None:
    transform_source_text(context, "Lib/flexx/event/_loop.py", _patch_flexx_event_loop, allow_missing=True)
    _patch_flexx_static_event_js(context)


LIBRARY_INTEGRATION = pypi_library(
    name="flexx",
    source_mapping={
        "flexx": "Lib/flexx",
    },
    python_packages=["flexx"],
    post_patch_hooks=[patch_flexx_sources],
)
