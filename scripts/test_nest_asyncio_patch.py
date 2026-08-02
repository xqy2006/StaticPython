from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


def load_setup_module():
    path = REPO_ROOT / "Lib" / "nest_asyncio" / "setup.py"
    spec = importlib.util.spec_from_file_location(
        "_staticpython_test_nest_asyncio_setup", path
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


TASK_ALIAS_ANCHOR = (
    "    if sys.version_info >= (3, 6, 0):\n"
    "        asyncio.Task = asyncio.tasks._CTask = asyncio.tasks.Task = \\\n"
    "            asyncio.tasks._PyTask\n"
    "        asyncio.Future = asyncio.futures._CFuture = asyncio.futures.Future = \\\n"
    "            asyncio.futures._PyFuture\n"
)
TASK_HELPER_ANCHOR = (
    "    curr_tasks = asyncio.tasks._current_tasks \\\n"
    "        if sys.version_info >= (3, 7, 0) else asyncio.Task._current_tasks\n"
    "    cls._nest_patched = True\n"
)
CURRENT_TASK_ANCHOR = (
    "            if not handle._cancelled:\n"
    "                # preempt the current task so that that checks in\n"
    "                # Task.__step do not raise\n"
    "                curr_task = curr_tasks.pop(self, None)\n"
    "\n"
    "                try:\n"
    "                    handle._run()\n"
    "                finally:\n"
    "                    # restore the current task\n"
    "                    if curr_task is not None:\n"
    "                        curr_tasks[self] = curr_task\n"
)
CANONICAL_SOURCE = "\n".join(
    [TASK_ALIAS_ANCHOR, CURRENT_TASK_ANCHOR, TASK_HELPER_ANCHOR]
)


def expect_runtime_error(label: str, action) -> None:
    try:
        action()
    except RuntimeError:
        return
    raise AssertionError(f"{label} did not fail closed")


def main() -> int:
    module = load_setup_module()

    patched = module._patch_nest_asyncio_runtime(CANONICAL_SOURCE, "1.6.0")
    required = (
        "asyncio.tasks._py_register_task = asyncio.tasks._c_register_task",
        "task_current = getattr(asyncio.tasks, '_py_current_task', None)",
        "task_swap(self, None)",
        "task_swap(self, curr_task)",
    )
    for snippet in required:
        if snippet not in patched:
            raise AssertionError(f"patched source is missing {snippet!r}")
    if module._patch_nest_asyncio_runtime(patched, "1.6.0") != patched:
        raise AssertionError("strict nest_asyncio patch is not idempotent")

    drifted_sources = {
        "task alias": CANONICAL_SOURCE.replace(
            "asyncio.futures._PyFuture", "asyncio.futures._FutureDrift", 1
        ),
        "task helper": CANONICAL_SOURCE.replace(
            "cls._nest_patched = True", "cls._nest_patched = bool(1)", 1
        ),
        "current task": CANONICAL_SOURCE.replace("that checks in", "the checks in", 1),
        "duplicate anchors": CANONICAL_SOURCE + CANONICAL_SOURCE,
    }
    for label, source in drifted_sources.items():
        expect_runtime_error(
            label,
            lambda source=source: module._patch_nest_asyncio_runtime(source, "1.6.0"),
        )

    expect_runtime_error(
        "unresolved version",
        lambda: module._patch_nest_asyncio_runtime(CANONICAL_SOURCE, None),
    )

    legacy = module._patch_nest_asyncio_runtime(TASK_ALIAS_ANCHOR, "1.5.9")
    if "asyncio.tasks._py_register_task" not in legacy:
        raise AssertionError(
            "legacy-compatible nest_asyncio alias patch was not applied"
        )

    print("nest_asyncio strict patch tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
