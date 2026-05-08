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


def _prepare_rfc3986_validator_source(context) -> None:
    integration = LIBRARY_INTEGRATION
    project_name = integration.project_name or integration.name
    normalized = _normalized_project_name(project_name)
    release_version = integration.release_version

    target_version = Version(".".join(str(part) for part in context.version_info))
    if release_version is not None:
        cached_archive_paths = _find_cached_pypi_archives(
            context.download_cache_root,
            normalized,
            release_version,
            target_version,
        )
        if cached_archive_paths:
            candidates = [(release_version, path, None, True) for path in cached_archive_paths]
        else:
            candidates = []
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
                candidates.append((resolved_release_version, archive_path, file_info["url"], False))
    else:
        candidates = []
        for resolved_release_version, file_info in _iter_pypi_distribution_candidates(
            project_name,
            target_version,
            None,
        ):
            archive_path = (
                context.download_cache_root
                / "pypi"
                / normalized
                / resolved_release_version
                / file_info["filename"]
            )
            candidates.append((resolved_release_version, archive_path, file_info["url"], False))

    # PyPI sdist for 0.1.0 is missing the real module file; fall back to the upstream tag archive.
    if release_version in {None, "0.1.0"}:
        github_archive_path = (
            context.download_cache_root
            / "github"
            / "naimetti-rfc3986-validator"
            / "tags"
            / "v0.1.0"
            / "rfc3986-validator-v0.1.0.zip"
        )
        github_url = "https://github.com/naimetti/rfc3986-validator/archive/refs/tags/v0.1.0.zip"
        candidates.append(("0.1.0", github_archive_path, github_url, github_archive_path.exists()))

    failures: list[str] = []
    for resolved_release_version, archive_path, url, cached in candidates:
        source_kind = "github" if "github" in archive_path.parts else "pypi"
        extract_root = (
            context.work_cache_root
            / source_kind
            / normalized
            / resolved_release_version
            / "extracted"
            / archive_path.name
        )
        if not archive_path.exists():
            assert url is not None
            context.log(f"downloading {project_name} {resolved_release_version} from {source_kind}")
            _download_file(url, archive_path)
        elif cached:
            context.log(
                f"reusing cached {project_name} {resolved_release_version} {source_kind} archive without refreshing metadata"
            )
        else:
            context.log(f"reusing cached {project_name} {resolved_release_version} {source_kind} archive")

        try:
            extracted_root = _extract_archive(archive_path, extract_root, context.log)
            context.log(f"using {project_name} {resolved_release_version} source from {extracted_root}")
            module_src = _resolve_source_entry(extracted_root, "rfc3986_validator.py||rfc3986_validator")
            destination = context.source_root / "Lib" / "rfc3986_validator.py"
            if module_src.is_dir():
                module_src = _resolve_source_entry(module_src, "__init__.py")
            _copy_entry(module_src, destination)
            return
        except RuntimeError as exc:
            failures.append(f"{archive_path.name}: {exc}")
            context.log(
                f"distribution candidate failed for {project_name} {resolved_release_version}: {archive_path.name}: {exc}"
            )

    raise RuntimeError(
        f"all compatible source artifacts failed for {project_name!r} release {release_version!r}: "
        + "; ".join(failures)
    )


LIBRARY_INTEGRATION = LibraryIntegration(
    name="rfc3986_validator",
    source_provider="pypi",
    project_name="rfc3986-validator",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/rfc3986_validator.py",
    ],
    cleanup_paths=[],
    python_packages=[
        "rfc3986_validator",
    ],
    static_library_projects_release_x64=[],
    native_static_projects=[],
    builtin_module_registrations=[],
    staged_static_libraries_release_x64=[],
    python_link_dependencies_release_x64=[],
    python_link_wholearchive_release_x64=[],
    prepare_source_hooks=[_prepare_rfc3986_validator_source],
    pre_patch_hooks=[],
    post_patch_hooks=[],
    pre_build_hooks=[],
)
