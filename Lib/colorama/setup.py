from packaging.version import Version

from libs import (
    LibraryIntegration,
    _candidate_pypi_archives,
    _copy_entry,
    _download_file,
    _extract_archive,
    _resolve_source_entry,
    read_text_file,
    write_source_text,
)


def _candidate_archives(context, project_name: str, release_version: str | None) -> list[tuple[str, object, str | None, bool]]:
    target_version = Version(".".join(str(part) for part in context.version_info))
    return _candidate_pypi_archives(
        context.download_cache_root,
        project_name,
        target_version,
        release_version,
    )


def _copy_colorama_package(context, extracted_root, target_release_version: str) -> None:
    destination = context.source_root / "Lib" / "colorama"
    _copy_entry(_resolve_source_entry(extracted_root, "colorama"), destination)
    init_path = destination / "__init__.py"
    text = read_text_file(init_path)
    text = text.replace("__version__ = '0.1.16'", f"__version__ = '{target_release_version}'")
    text = text.replace('__version__ = "0.1.16"', f'__version__ = "{target_release_version}"')
    init_path.write_text(text, encoding="utf-8", newline="\n")


def _prepare_colorama_source(context) -> None:
    integration = LIBRARY_INTEGRATION
    release_version = integration.release_version

    candidates = _candidate_archives(context, "colorama", release_version)
    # Early colorama sdists on PyPI are truncated; 0.1.16 is the nearest complete same-series source.
    if release_version is not None and Version(release_version) <= Version("0.1.15"):
        candidates.extend(_candidate_archives(context, "colorama", "0.1.16"))
    elif release_version is None:
        candidates.extend(_candidate_archives(context, "colorama", "0.1.16"))

    failures: list[str] = []
    for resolved_release_version, archive_path, url, cached in candidates:
        extract_root = (
            context.work_cache_root
            / "pypi"
            / "colorama"
            / resolved_release_version
            / "extracted"
            / archive_path.name
        )
        if not archive_path.exists():
            assert url is not None
            context.log(f"downloading colorama {resolved_release_version} from PyPI")
            _download_file(url, archive_path)
        elif cached:
            context.log(f"reusing cached colorama {resolved_release_version} archive without refreshing PyPI metadata")
        else:
            context.log(f"reusing cached colorama {resolved_release_version} archive")

        try:
            extracted_root = _extract_archive(archive_path, extract_root, context.log)
            context.log(f"using colorama {resolved_release_version} source from {extracted_root}")
            _copy_colorama_package(context, extracted_root, release_version or resolved_release_version)
            return
        except RuntimeError as exc:
            failures.append(f"{archive_path.name}: {exc}")
            context.log(f"distribution candidate failed for colorama {resolved_release_version}: {archive_path.name}: {exc}")

    target_description = f"release {release_version!r}" if release_version is not None else "all releases"
    raise RuntimeError(
        f"all compatible PyPI distribution artifacts failed for 'colorama' {target_description}: "
        + "; ".join(failures)
    )


LIBRARY_INTEGRATION = LibraryIntegration(
    name="colorama",
    source_provider="pypi",
    project_name="colorama",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/colorama",
    ],
    cleanup_paths=[],
    python_packages=[
        "colorama",
    ],
    static_library_projects_release_x64=[],
    native_static_projects=[],
    builtin_module_registrations=[],
    staged_static_libraries_release_x64=[],
    python_link_dependencies_release_x64=[],
    python_link_wholearchive_release_x64=[],
    prepare_source_hooks=[_prepare_colorama_source],
    pre_patch_hooks=[],
    post_patch_hooks=[],
    pre_build_hooks=[],
)
