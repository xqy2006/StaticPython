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


LEGACY_WIDE_ALIAS_ANCHOR = (
    "    if sys.version_info[:2] == (3, 6):\n"
    "        # use pure python tasks and futures\n"
    "        asyncio.Task = asyncio.tasks._CTask = asyncio.tasks.Task = \\\n"
    "                asyncio.tasks._PyTask\n"
    "        asyncio.Future = asyncio.futures._CFuture = asyncio.futures.Future = \\\n"
    "                asyncio.futures._PyFuture\n"
)
LEGACY_COMPACT_ALIAS_ANCHOR = (
    "    if sys.version_info[:2] == (3, 6):\n"
    "        # use pure python tasks and futures\n"
    "        asyncio.Task = asyncio.tasks._CTask = asyncio.tasks.Task = \\\n"
    "            asyncio.tasks._PyTask\n"
    "        asyncio.Future = asyncio.futures._CFuture = asyncio.futures.Future = \\\n"
    "            asyncio.futures._PyFuture\n"
)
MODERN_ALIAS_ANCHOR = (
    "    if sys.version_info >= (3, 6, 0):\n"
    "        asyncio.Task = asyncio.tasks._CTask = asyncio.tasks.Task = \\\n"
    "            asyncio.tasks._PyTask\n"
    "        asyncio.Future = asyncio.futures._CFuture = asyncio.futures.Future = \\\n"
    "            asyncio.futures._PyFuture\n"
)
ALL_TASKS_ANCHOR = "    if future in asyncio.Task.all_tasks(self):\n"
LOOP_CHECK_ANCHOR = (
    "    cls = loop.__class__\n"
    "    cls._run_forever_orig = cls.run_forever\n"
    "    cls.run_forever = run_forever\n"
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
    [MODERN_ALIAS_ANCHOR, CURRENT_TASK_ANCHOR, TASK_HELPER_ANCHOR]
)


def expect_runtime_error(label: str, action) -> None:
    try:
        action()
    except RuntimeError:
        return
    raise AssertionError(f"{label} did not fail closed")


def assert_version_rule(module, source: str, version: str, *, task_swap: bool) -> str:
    patched = module._patch_nest_asyncio_runtime(source, version)
    required = [
        "    if sys.version_info >= (3, 6, 0):",
        "asyncio.tasks._py_register_task = asyncio.tasks._c_register_task",
    ]
    if task_swap:
        required.extend(
            [
                "task_current = getattr(asyncio.tasks, '_py_current_task', None)",
                "task_swap(self, None)",
                "task_swap(self, curr_task)",
            ]
        )
    for snippet in required:
        if snippet not in patched:
            raise AssertionError(
                f"nest_asyncio {version} patched source is missing {snippet!r}"
            )
    if not task_swap and "task_swap(self, None)" in patched:
        raise AssertionError(f"nest_asyncio {version} used the 1.6.0+ task-swap rule")
    if module._patch_nest_asyncio_runtime(patched, version) != patched:
        raise AssertionError(f"nest_asyncio {version} patch is not idempotent")
    return patched


def main() -> int:
    module = load_setup_module()

    for version in ("0.9.0", "0.9.1"):
        patched = assert_version_rule(
            module, LEGACY_WIDE_ALIAS_ANCHOR, version, task_swap=False
        )
        if "sys.version_info[:2] == (3, 6)" in patched:
            raise AssertionError(f"nest_asyncio {version} retained its Python 3.6-only guard")
    compact_source = "\n".join([LEGACY_COMPACT_ALIAS_ANCHOR, ALL_TASKS_ANCHOR])
    compact_patched = assert_version_rule(
        module, compact_source, "0.9.2", task_swap=False
    )
    if "if future in asyncio.all_tasks(self):" not in compact_patched:
        raise AssertionError("nest_asyncio 0.9.2 retained the removed Task.all_tasks API")
    for version in ("0.9.3", "1.0.0", "1.5.9"):
        assert_version_rule(module, MODERN_ALIAS_ANCHOR, version, task_swap=False)
    loop_check_source = "\n".join([MODERN_ALIAS_ANCHOR, LOOP_CHECK_ANCHOR])
    for version in ("1.1.0", "1.2.3"):
        loop_patched = assert_version_rule(
            module, loop_check_source, version, task_swap=False
        )
        if "cls._check_running = _check_running" not in loop_patched:
            raise AssertionError(
                f"nest_asyncio {version} did not disable the nested-loop guard"
            )
    assert_version_rule(module, CANONICAL_SOURCE, "1.6.0", task_swap=True)

    drifted_sources = {
        "legacy wide task alias": LEGACY_WIDE_ALIAS_ANCHOR.replace(
            "asyncio.futures._PyFuture", "asyncio.futures._FutureDrift", 1
        ),
        "legacy compact task alias": LEGACY_COMPACT_ALIAS_ANCHOR.replace(
            "asyncio.futures._PyFuture", "asyncio.futures._FutureDrift", 1
        ),
        "modern task alias": MODERN_ALIAS_ANCHOR.replace(
            "asyncio.futures._PyFuture", "asyncio.futures._FutureDrift", 1
        ),
        "removed all_tasks API": compact_source.replace(
            "Task.all_tasks", "Task.all_tasks_drift", 1
        ),
        "nested loop guard": loop_check_source.replace(
            "cls.run_forever = run_forever", "cls.run_forever = run_forever_drift", 1
        ),
        "task helper": CANONICAL_SOURCE.replace(
            "cls._nest_patched = True", "cls._nest_patched = bool(1)", 1
        ),
        "current task": CANONICAL_SOURCE.replace("that checks in", "the checks in", 1),
    }
    drift_versions = {
        "legacy wide task alias": "0.9.0",
        "legacy compact task alias": "0.9.2",
        "modern task alias": "1.5.9",
        "removed all_tasks API": "0.9.2",
        "nested loop guard": "1.2.3",
        "task helper": "1.6.0",
        "current task": "1.6.0",
    }
    for label, source in drifted_sources.items():
        expect_runtime_error(
            label,
            lambda source=source, version=drift_versions[label]: (
                module._patch_nest_asyncio_runtime(source, version)
            ),
        )

    partial_sources = {
        "legacy task alias partial patch": (
            LEGACY_WIDE_ALIAS_ANCHOR
            + "    asyncio.tasks._py_register_task = asyncio.tasks._c_register_task\n",
            "0.9.1",
        ),
        "modern task alias partial patch": (
            MODERN_ALIAS_ANCHOR
            + "    asyncio.tasks._py_register_task = asyncio.tasks._c_register_task\n",
            "1.5.9",
        ),
        "all_tasks partial patch": (
            compact_source + "    if future in asyncio.all_tasks(self):\n",
            "0.9.2",
        ),
        "nested loop guard partial patch": (
            loop_check_source + "    cls._check_running = _check_running\n",
            "1.2.3",
        ),
        "task helper partial patch": (
            CANONICAL_SOURCE
            + "    task_current = getattr(asyncio.tasks, '_py_current_task', None)\n",
            "1.6.0",
        ),
        "current task partial patch": (
            CANONICAL_SOURCE + "                task_swap(self, None)\n",
            "1.6.0",
        ),
    }
    for label, (source, version) in partial_sources.items():
        expect_runtime_error(
            label,
            lambda source=source, version=version: (
                module._patch_nest_asyncio_runtime(source, version)
            ),
        )

    duplicate_sources = (
        ("legacy wide duplicate", LEGACY_WIDE_ALIAS_ANCHOR * 2, "0.9.1"),
        (
            "legacy compact duplicate",
            "\n".join([LEGACY_COMPACT_ALIAS_ANCHOR * 2, ALL_TASKS_ANCHOR]),
            "0.9.2",
        ),
        (
            "all_tasks duplicate",
            "\n".join([LEGACY_COMPACT_ALIAS_ANCHOR, ALL_TASKS_ANCHOR * 2]),
            "0.9.2",
        ),
        ("modern duplicate", MODERN_ALIAS_ANCHOR * 2, "1.5.9"),
        (
            "nested loop guard duplicate",
            "\n".join([MODERN_ALIAS_ANCHOR, LOOP_CHECK_ANCHOR * 2]),
            "1.1.0",
        ),
        ("1.6.0 duplicate", CANONICAL_SOURCE + CANONICAL_SOURCE, "1.6.0"),
    )
    for label, source, version in duplicate_sources:
        expect_runtime_error(
            label,
            lambda source=source, version=version: (
                module._patch_nest_asyncio_runtime(source, version)
            ),
        )

    expect_runtime_error(
        "version/source routing mismatch",
        lambda: module._patch_nest_asyncio_runtime(
            LEGACY_COMPACT_ALIAS_ANCHOR, "0.9.3"
        ),
    )
    expect_runtime_error(
        "unsupported historical version",
        lambda: module._patch_nest_asyncio_runtime(LEGACY_WIDE_ALIAS_ANCHOR, "0.8.9"),
    )

    expect_runtime_error(
        "unresolved version",
        lambda: module._patch_nest_asyncio_runtime(CANONICAL_SOURCE, None),
    )

    print("nest_asyncio version-routed strict patch tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
