from libs import replace_text_once, simple_library, transform_source_text


def patch_nest_asyncio_sources(context) -> None:
    def patch_runtime(text: str) -> str:
        text = replace_text_once(
            text,
            "    if sys.version_info >= (3, 6, 0):\n"
            "        asyncio.Task = asyncio.tasks._CTask = asyncio.tasks.Task = \\\n"
            "            asyncio.tasks._PyTask\n"
            "        asyncio.Future = asyncio.futures._CFuture = asyncio.futures.Future = \\\n"
            "            asyncio.futures._PyFuture\n",
            "    if sys.version_info >= (3, 6, 0):\n"
            "        asyncio.Task = asyncio.tasks._CTask = asyncio.tasks.Task = \\\n"
            "            asyncio.tasks._PyTask\n"
            "        asyncio.Future = asyncio.futures._CFuture = asyncio.futures.Future = \\\n"
            "            asyncio.futures._PyFuture\n"
            "    if sys.version_info >= (3, 14, 0) and hasattr(asyncio.tasks, '_c_register_task'):\n"
            "        asyncio.tasks._py_register_task = asyncio.tasks._c_register_task\n"
            "        asyncio.tasks._py_register_eager_task = asyncio.tasks._c_register_eager_task\n"
            "        asyncio.tasks._py_unregister_task = asyncio.tasks._c_unregister_task\n"
            "        asyncio.tasks._py_unregister_eager_task = asyncio.tasks._c_unregister_eager_task\n"
            "        asyncio.tasks._py_enter_task = asyncio.tasks._c_enter_task\n"
            "        asyncio.tasks._py_leave_task = asyncio.tasks._c_leave_task\n"
            "        asyncio.tasks._py_swap_current_task = asyncio.tasks._c_swap_current_task\n"
            "        asyncio.tasks._py_current_task = asyncio.tasks._c_current_task\n"
            "        if hasattr(asyncio.tasks, '_c_all_tasks'):\n"
            "            asyncio.tasks._py_all_tasks = asyncio.tasks._c_all_tasks\n",
            label="nest_asyncio asyncio 3.14+ task bookkeeping aliases",
        )
        text = replace_text_once(
            text,
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
            "                        curr_tasks[self] = curr_task\n",
            "            if not handle._cancelled:\n"
            "                # Preempt the current task using the same bookkeeping\n"
            "                # hooks that asyncio.Task.__step() uses on this Python.\n"
            "                if task_current is not None and task_swap is not None:\n"
            "                    curr_task = task_current(self)\n"
            "                    if curr_task is not None:\n"
            "                        task_swap(self, None)\n"
            "                else:\n"
            "                    curr_task = curr_tasks.pop(self, None)\n"
            "\n"
            "                try:\n"
            "                    handle._run()\n"
            "                finally:\n"
            "                    # restore the current task\n"
            "                    if curr_task is not None:\n"
            "                        if task_swap is not None:\n"
            "                            task_swap(self, curr_task)\n"
            "                        else:\n"
            "                            curr_tasks[self] = curr_task\n",
            label="nest_asyncio current task preemption",
        )
        return replace_text_once(
            text,
            "    curr_tasks = asyncio.tasks._current_tasks \\\n"
            "        if sys.version_info >= (3, 7, 0) else asyncio.Task._current_tasks\n"
            "    cls._nest_patched = True\n",
            "    task_current = getattr(asyncio.tasks, '_py_current_task', None)\n"
            "    task_swap = getattr(asyncio.tasks, '_py_swap_current_task', None)\n"
            "    curr_tasks = asyncio.tasks._current_tasks \\\n"
            "        if sys.version_info >= (3, 7, 0) else asyncio.Task._current_tasks\n"
            "    cls._nest_patched = True\n",
            label="nest_asyncio task helper capture",
        )

    transform_source_text(context, "Lib/nest_asyncio.py", patch_runtime)


LIBRARY_INTEGRATION = simple_library(
    name="nest_asyncio",
    project_name="nest-asyncio",
    source_mapping={
        "nest_asyncio.py": "Lib/nest_asyncio.py",
    },
    python_packages=["nest_asyncio"],
    post_patch_hooks=[patch_nest_asyncio_sources],
)
