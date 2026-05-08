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
)


def _copy_flat_package_root(src_root, dst_root) -> None:
    dst_root.mkdir(parents=True, exist_ok=True)
    for child in sorted(src_root.iterdir(), key=lambda path: path.name.casefold()):
        if child.name == "__pycache__":
            continue
        if child.name.endswith((".egg-info", ".dist-info")):
            continue
        _copy_entry(child, dst_root / child.name)


def _prepare_pythonjsonlogger_source(context) -> None:
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
            context.log(f"reusing cached {project_name} {release_version} archive without refreshing PyPI metadata")
            resolved_release_version = release_version
            archive_path = cached_archive_path
        else:
            resolved_release_version, file_info = _select_pypi_file(project_name, target_version, release_version)
            archive_path = (
                context.download_cache_root
                / "pypi"
                / normalized
                / resolved_release_version
                / file_info["filename"]
            )
            url = file_info["url"]
    else:
        resolved_release_version, file_info = _select_pypi_file(project_name, target_version, release_version)
        archive_path = (
            context.download_cache_root
            / "pypi"
            / normalized
            / resolved_release_version
            / file_info["filename"]
        )
        url = file_info["url"]

    extract_root = context.work_cache_root / "pypi" / normalized / resolved_release_version / "extracted"

    if not archive_path.exists():
        context.log(f"downloading {project_name} {resolved_release_version} from PyPI")
        _download_file(url, archive_path)
    elif cached_archive_path is None:
        context.log(f"reusing cached {project_name} {resolved_release_version} archive")

    extracted_root = _extract_archive(archive_path, extract_root, context.log)
    context.log(f"using {project_name} {resolved_release_version} source from {extracted_root}")

    destination = context.source_root / "Lib" / "pythonjsonlogger"
    try:
        package_src = _resolve_source_entry(extracted_root, "src/pythonjsonlogger||pythonjsonlogger")
    except RuntimeError:
        package_src = None

    if package_src is not None:
        _copy_entry(package_src, destination)
        return

    flat_root = _resolve_source_entry(extracted_root, "src")
    _copy_flat_package_root(flat_root, destination)


LIBRARY_INTEGRATION = LibraryIntegration(
    name="pythonjsonlogger",
    source_provider="pypi",
    project_name="python-json-logger",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/pythonjsonlogger",
    ],
    cleanup_paths=[],
    python_packages=[
        "pythonjsonlogger",
    ],
    static_library_projects_release_x64=[],
    native_static_projects=[],
    builtin_module_registrations=[],
    staged_static_libraries_release_x64=[],
    python_link_dependencies_release_x64=[],
    python_link_wholearchive_release_x64=[],
    prepare_source_hooks=[_prepare_pythonjsonlogger_source],
    pre_patch_hooks=[],
    post_patch_hooks=[],
    pre_build_hooks=[],
)
