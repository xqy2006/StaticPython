from packaging.version import Version

from libs import (
    LibraryIntegration,
    _candidate_pypi_archives,
    _copy_entry,
    _download_file,
    _extract_archive,
    _normalized_project_name,
    _resolve_source_entry,
)


def _candidate_archives(
    context,
    project_name: str,
    release_version: str | None,
) -> list[tuple[str, object, str | None, bool]]:
    target_version = Version(".".join(str(part) for part in context.version_info))
    return _candidate_pypi_archives(
        context.download_cache_root,
        project_name,
        target_version,
        release_version,
    )


def _prepare_html5lib_source(context) -> None:
    integration = LIBRARY_INTEGRATION
    project_name = integration.project_name or integration.name
    normalized = _normalized_project_name(project_name)
    release_version = integration.release_version
    candidates = _candidate_archives(context, project_name, release_version)

    failures: list[str] = []
    for resolved_release_version, archive_path, url, cached in candidates:
        extract_root = (
            context.work_cache_root
            / "pypi"
            / normalized
            / resolved_release_version
            / "extracted"
            / archive_path.name
        )
        if not archive_path.exists():
            assert url is not None
            context.log(f"downloading {project_name} {resolved_release_version} from PyPI")
            _download_file(url, archive_path)
        elif cached:
            context.log(f"reusing cached {project_name} {resolved_release_version} archive without refreshing PyPI metadata")
        else:
            context.log(f"reusing cached {project_name} {resolved_release_version} archive")

        try:
            extracted_root = _extract_archive(archive_path, extract_root, context.log)
            context.log(f"using {project_name} {resolved_release_version} source from {extracted_root}")
            package_src = _resolve_source_entry(extracted_root, "html5lib||src/html5lib")
            _copy_entry(package_src, context.source_root / "Lib" / "html5lib")
            return
        except RuntimeError as exc:
            failures.append(f"{archive_path.name}: {exc}")
            context.log(f"distribution candidate failed for {project_name} {resolved_release_version}: {archive_path.name}: {exc}")

    target_description = f"release {release_version!r}" if release_version is not None else "all releases"
    raise RuntimeError(
        f"all compatible PyPI distribution artifacts failed for {project_name!r} {target_description}: "
        + "; ".join(failures)
    )


LIBRARY_INTEGRATION = LibraryIntegration(
    name="html5lib",
    source_provider="pypi",
    project_name="html5lib",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/html5lib",
    ],
    cleanup_paths=[],
    python_packages=[
        "html5lib",
    ],
    static_library_projects_release_x64=[],
    native_static_projects=[],
    builtin_module_registrations=[],
    staged_static_libraries_release_x64=[],
    python_link_dependencies_release_x64=[],
    python_link_wholearchive_release_x64=[],
    prepare_source_hooks=[_prepare_html5lib_source],
    pre_patch_hooks=[],
    post_patch_hooks=[],
    pre_build_hooks=[],
)
