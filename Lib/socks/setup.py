from packaging.version import Version

from libs import (
    LibraryIntegration,
    _copy_entry,
    _download_file,
    _extract_archive,
    _find_cached_pypi_archives,
    _iter_pypi_distribution_candidates,
    _normalized_project_name,
    _resolve_source_entry,
)


def _prepare_socks_source(context) -> None:
    integration = LIBRARY_INTEGRATION
    project_name = integration.project_name or integration.name
    normalized = _normalized_project_name(project_name)
    release_version = integration.release_version
    target_version = Version(".".join(str(part) for part in context.version_info))

    candidate_archives: list[tuple[str, object, str | None, bool]] = []
    if release_version is not None:
        cached_archive_paths = _find_cached_pypi_archives(
            context.download_cache_root,
            normalized,
            release_version,
            target_version,
        )
        if cached_archive_paths:
            candidate_archives.extend((release_version, path, None, True) for path in cached_archive_paths)
        else:
            for resolved_release_version, file_info in _iter_pypi_distribution_candidates(
                project_name,
                target_version,
                release_version,
            ):
                archive_path = (
                    context.download_cache_root
                    / "pypi"
                    / normalized
                    / resolved_release_version
                    / file_info["filename"]
                )
                candidate_archives.append((resolved_release_version, archive_path, file_info["url"], False))

    failures: list[str] = []
    for resolved_release_version, archive_path, url, cached in candidate_archives:
        extract_root = (
            context.work_cache_root
            / "pypi"
            / normalized
            / resolved_release_version
            / "extracted"
            / archive_path.name
        )
        if not archive_path.exists():
            context.log(f"downloading {project_name} {resolved_release_version} from PyPI")
            assert url is not None
            _download_file(url, archive_path)
        elif cached:
            context.log(f"reusing cached {project_name} {resolved_release_version} archive without refreshing PyPI metadata")
        else:
            context.log(f"reusing cached {project_name} {resolved_release_version} archive")

        try:
            extracted_root = _extract_archive(archive_path, extract_root, context.log)
            context.log(f"using {project_name} {resolved_release_version} source from {extracted_root}")
            _copy_entry(_resolve_source_entry(extracted_root, "socks.py"), context.source_root / "Lib" / "socks.py")
            try:
                sockshandler_src = _resolve_source_entry(extracted_root, "sockshandler.py||sockshandler")
            except RuntimeError:
                sockshandler_src = None
            if sockshandler_src is not None:
                _copy_entry(sockshandler_src, context.source_root / "Lib" / "sockshandler.py")
            return
        except RuntimeError as exc:
            failures.append(f"{archive_path.name}: {exc}")
            context.log(f"distribution candidate failed for {project_name} {resolved_release_version}: {archive_path.name}: {exc}")

    raise RuntimeError(
        f"all compatible PyPI distribution artifacts failed for {project_name!r} release {release_version!r}: "
        + "; ".join(failures)
    )


LIBRARY_INTEGRATION = LibraryIntegration(
    name="socks",
    source_provider="pypi",
    project_name="PySocks",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/socks.py",
    ],
    cleanup_paths=[],
    python_packages=[
        "socks",
        "sockshandler",
    ],
    static_library_projects_release_x64=[],
    native_static_projects=[],
    builtin_module_registrations=[],
    staged_static_libraries_release_x64=[],
    python_link_dependencies_release_x64=[],
    python_link_wholearchive_release_x64=[],
    prepare_source_hooks=[_prepare_socks_source],
    pre_patch_hooks=[],
    post_patch_hooks=[],
    pre_build_hooks=[],
)
