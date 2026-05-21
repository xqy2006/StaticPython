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
    read_text_file,
    write_source_text,
)


def _prepare_decorator_source(context) -> None:
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
                project_name,
                target_version,
                release_version,
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
            project_name,
            target_version,
            release_version,
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
        context.work_cache_root / "pypi" / normalized / resolved_release_version / "extracted"
    )

    if not archive_path.exists():
        context.log(f"downloading {project_name} {resolved_release_version} from PyPI")
        _download_file(url, archive_path)
    elif cached_archive_path is None:
        context.log(f"reusing cached {project_name} {resolved_release_version} archive")

    extracted_root = _extract_archive(archive_path, extract_root, context.log)
    context.log(f"using {project_name} {resolved_release_version} source from {extracted_root}")

    decorator_src = _resolve_source_entry(
        extracted_root,
        "src/decorator.py||decorator.py||src/decorator||decorator",
    )
    destination = context.source_root / "Lib" / "decorator"

    if decorator_src.is_file():
        write_source_text(context, "Lib/decorator/__init__.py", read_text_file(decorator_src))
        return

    _copy_entry(decorator_src, destination)
    nested_module = destination / "decorator.py"
    package_init = destination / "__init__.py"
    if not package_init.exists() and nested_module.exists():
        write_source_text(context, "Lib/decorator/__init__.py", read_text_file(nested_module))


LIBRARY_INTEGRATION = LibraryIntegration(
    name="decorator",
    source_provider="pypi",
    project_name="decorator",
    release_version="5.2.1",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/decorator",
    ],
    cleanup_paths=[],
    python_packages=[
        "decorator",
    ],
    static_library_projects_release_x64=[],
    native_static_projects=[],
    builtin_module_registrations=[],
    staged_static_libraries_release_x64=[],
    python_link_dependencies_release_x64=[],
    python_link_wholearchive_release_x64=[],
    prepare_source_hooks=[_prepare_decorator_source],
    pre_patch_hooks=[],
    post_patch_hooks=[],
    pre_build_hooks=[],
)
