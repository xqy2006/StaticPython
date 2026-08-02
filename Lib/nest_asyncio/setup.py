from packaging.version import Version

from libs import (
    LibraryIntegration,
    _copy_entry,
    _download_file,
    _extract_archive,
    _find_cached_pypi_archive,
    _normalized_project_name,
    _resolve_source_entry,
    _select_pypi_file,
    replace_text_once,
    transform_source_text,
)


STRICT_PATCH_MIN_VERSION = Version("1.6.0")


def _replace_strictly_once(text: str, old: str, new: str, *, label: str) -> str:
    old_count = text.count(old)
    new_count = text.count(new)
    if new_count == 1 and old_count == new.count(old):
        return text
    if new_count:
        raise RuntimeError(
            f"{label} patched snippet mismatch: expected 1, found {new_count}"
        )
    if old_count != 1:
        raise RuntimeError(f"{label} anchor mismatch: expected 1, found {old_count}")
    return text.replace(old, new, 1)


def _prepare_nest_asyncio_source(context) -> None:
    integration = LIBRARY_INTEGRATION
    project_name = integration.project_name or integration.name
    normalized = _normalized_project_name(project_name)
    release_version = integration.release_version
    target_version = Version(".".join(str(part) for part in context.version_info))
    cached_archive_path = None

    if release_version is not None:
        cached_archive_path = _find_cached_pypi_archive(
            context.download_cache_root,
            normalized,
            release_version,
            target_version,
        )
        if cached_archive_path is not None:
            context.log(
                f"reusing cached {project_name} {release_version} archive without refreshing PyPI metadata"
            )
            resolved_release_version = release_version
            archive_path = cached_archive_path
        else:
            resolved_release_version, file_info = _select_pypi_file(
                project_name, target_version, release_version
            )
            archive_path = (
                context.download_cache_root
                / "pypi"
                / normalized
                / resolved_release_version
                / file_info["filename"]
            )
            url = file_info["url"]
    else:
        resolved_release_version, file_info = _select_pypi_file(
            project_name, target_version, release_version
        )
        archive_path = (
            context.download_cache_root
            / "pypi"
            / normalized
            / resolved_release_version
            / file_info["filename"]
        )
        url = file_info["url"]

    extract_root = (
        context.work_cache_root
        / "pypi"
        / normalized
        / resolved_release_version
        / "extracted"
    )

    if not archive_path.exists():
        context.log(f"downloading {project_name} {resolved_release_version} from PyPI")
        _download_file(url, archive_path)
    elif cached_archive_path is None:
        context.log(f"reusing cached {project_name} {resolved_release_version} archive")

    extracted_root = _extract_archive(archive_path, extract_root, context.log)
    context.log(
        f"using {project_name} {resolved_release_version} source from {extracted_root}"
    )
    integration.release_version = resolved_release_version

    package_src = _resolve_source_entry(extracted_root, "nest_asyncio||nest_asyncio.py")
    package_dst = context.source_root / "Lib" / "nest_asyncio"
    if package_src.is_dir():
        _copy_entry(package_src, package_dst)
    else:
        _copy_entry(package_src, package_dst / "__init__.py")


def _patch_nest_asyncio_runtime(text: str, release_version: str | None) -> str:
    if release_version is None:
        raise RuntimeError(
            "nest_asyncio patch routing requires a resolved release version"
        )
    strict = Version(release_version) >= STRICT_PATCH_MIN_VERSION

    task_alias_anchor = (
        "    if sys.version_info >= (3, 6, 0):\n"
        "        asyncio.Task = asyncio.tasks._CTask = asyncio.tasks.Task = \\\n"
        "            asyncio.tasks._PyTask\n"
        "        asyncio.Future = asyncio.futures._CFuture = asyncio.futures.Future = \\\n"
        "            asyncio.futures._PyFuture\n"
    )
    task_alias_patched = (
        task_alias_anchor
        + "    if sys.version_info >= (3, 14, 0) and hasattr(asyncio.tasks, '_c_register_task'):\n"
        + "        asyncio.tasks._py_register_task = asyncio.tasks._c_register_task\n"
        + "        asyncio.tasks._py_register_eager_task = asyncio.tasks._c_register_eager_task\n"
        + "        asyncio.tasks._py_unregister_task = asyncio.tasks._c_unregister_task\n"
        + "        asyncio.tasks._py_unregister_eager_task = asyncio.tasks._c_unregister_eager_task\n"
        + "        asyncio.tasks._py_enter_task = asyncio.tasks._c_enter_task\n"
        + "        asyncio.tasks._py_leave_task = asyncio.tasks._c_leave_task\n"
        + "        asyncio.tasks._py_swap_current_task = asyncio.tasks._c_swap_current_task\n"
        + "        asyncio.tasks._py_current_task = asyncio.tasks._c_current_task\n"
        + "        if hasattr(asyncio.tasks, '_c_all_tasks'):\n"
        + "            asyncio.tasks._py_all_tasks = asyncio.tasks._c_all_tasks\n"
    )

    task_helper_anchor = (
        "    curr_tasks = asyncio.tasks._current_tasks \\\n"
        "        if sys.version_info >= (3, 7, 0) else asyncio.Task._current_tasks\n"
        "    cls._nest_patched = True\n"
    )
    task_helper_patched = (
        "    task_current = getattr(asyncio.tasks, '_py_current_task', None)\n"
        "    task_swap = getattr(asyncio.tasks, '_py_swap_current_task', None)\n"
        + task_helper_anchor
    )

    current_task_anchor = (
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
    current_task_patched = (
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
        "                            curr_tasks[self] = curr_task\n"
    )

    replacements = [
        (
            task_alias_anchor,
            task_alias_patched,
            "nest_asyncio asyncio 3.14+ task bookkeeping aliases",
        ),
        (task_helper_anchor, task_helper_patched, "nest_asyncio task helper capture"),
        (
            current_task_anchor,
            current_task_patched,
            "nest_asyncio current task preemption",
        ),
    ]
    if strict:
        for old, new, label in replacements:
            text = _replace_strictly_once(text, old, new, label=label)
        return text

    for old, new, label in replacements:
        if old in text:
            text = replace_text_once(text, old, new, label=label)
    if "curr_tasks.pop(self, None)" in text and "task_swap(self, None)" not in text:
        raise RuntimeError("nest_asyncio current task preemption anchor not found")
    if "_c_register_task" in text and "_py_swap_current_task" not in text:
        raise RuntimeError("nest_asyncio asyncio 3.14 task alias anchor not found")
    return text


def patch_nest_asyncio_sources(context) -> None:
    integration = LIBRARY_INTEGRATION

    transform_source_text(
        context,
        "Lib/nest_asyncio/__init__.py",
        lambda text: _patch_nest_asyncio_runtime(text, integration.release_version),
    )


LIBRARY_INTEGRATION = LibraryIntegration(
    name="nest_asyncio",
    source_provider="pypi",
    project_name="nest-asyncio",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/nest_asyncio",
    ],
    cleanup_paths=[
        "Lib/nest_asyncio.py",
    ],
    python_packages=[
        "nest_asyncio",
    ],
    static_library_projects_release_x64=[],
    native_static_projects=[],
    builtin_module_registrations=[],
    staged_static_libraries_release_x64=[],
    python_link_dependencies_release_x64=[],
    python_link_wholearchive_release_x64=[],
    prepare_source_hooks=[_prepare_nest_asyncio_source],
    pre_patch_hooks=[],
    post_patch_hooks=[patch_nest_asyncio_sources],
    pre_build_hooks=[],
)
