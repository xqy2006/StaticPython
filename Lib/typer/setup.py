from packaging.version import Version

from libs import (
    LibraryIntegration,
    _candidate_pypi_archives,
    _copy_entry,
    _download_file,
    _extract_archive,
    _effective_pypi_release_version,
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


def _prepare_typer_source(context) -> None:
    integration = LIBRARY_INTEGRATION
    release_version = integration.release_version
    target_version = Version(".".join(str(part) for part in context.version_info))
    effective_release_version = _effective_pypi_release_version("typer", target_version, release_version)
    if effective_release_version is None:
        raise RuntimeError(f"could not find a compatible PyPI distribution artifact for 'typer' and target Python {target_version}")

    candidates = _candidate_archives(context, "typer", release_version)
    # typer 0.12.x split the real library into typer-slim.
    if Version(effective_release_version) >= Version("0.12.dev1") and Version(effective_release_version) < Version("0.13"):
        candidates.extend(_candidate_archives(context, "typer-slim", effective_release_version))

    failures: list[str] = []
    for resolved_release_version, archive_path, url, cached in candidates:
        normalized = _normalized_project_name(archive_path.parent.parent.name)
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
            context.log(f"downloading {normalized} {resolved_release_version} from PyPI")
            _download_file(url, archive_path)
        elif cached:
            context.log(f"reusing cached {normalized} {resolved_release_version} archive without refreshing PyPI metadata")
        else:
            context.log(f"reusing cached {normalized} {resolved_release_version} archive")

        try:
            extracted_root = _extract_archive(archive_path, extract_root, context.log)
            context.log(f"using {normalized} {resolved_release_version} source from {extracted_root}")
            _copy_entry(_resolve_source_entry(extracted_root, "typer"), context.source_root / "Lib" / "typer")
            return
        except RuntimeError as exc:
            failures.append(f"{archive_path.name}: {exc}")
            context.log(f"distribution candidate failed for typer {resolved_release_version}: {archive_path.name}: {exc}")

    target_description = f"release {release_version!r}" if release_version is not None else "all releases"
    raise RuntimeError(
        f"all compatible PyPI distribution artifacts failed for 'typer' {target_description}: " + "; ".join(failures)
    )


LIBRARY_INTEGRATION = LibraryIntegration(
    name="typer",
    source_provider="pypi",
    project_name="typer",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/typer",
    ],
    cleanup_paths=[],
    python_packages=[
        "typer",
    ],
    static_library_projects_release_x64=[],
    native_static_projects=[],
    builtin_module_registrations=[],
    staged_static_libraries_release_x64=[],
    python_link_dependencies_release_x64=[],
    python_link_wholearchive_release_x64=[],
    prepare_source_hooks=[_prepare_typer_source],
    pre_patch_hooks=[],
    post_patch_hooks=[],
    pre_build_hooks=[],
)
