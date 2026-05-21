from packaging.version import Version

from libs import (
    LibraryIntegration,
    _candidate_source_roots,
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


def _prepare_markdown_source(context) -> None:
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

    markdown_src = _resolve_source_entry(extracted_root, "markdown")
    markdown_dst = context.source_root / "Lib" / "markdown"
    if markdown_src.is_dir():
        _copy_entry(markdown_src, markdown_dst)
    else:
        _copy_entry(markdown_src, markdown_dst / "__init__.py")
        for root in _candidate_source_roots(extracted_root):
            for extension_path in sorted(root.glob("mdx_*.py")):
                _copy_entry(extension_path, context.source_root / "Lib" / extension_path.name)


def patch_markdown_sources(context) -> None:
    def patch_core(text: str) -> str:
        if "module_name = ext_name if '.' in ext_name else f'markdown.extensions.{ext_name}'" in text:
            return text
        if "extension_module_name = \"mdx_\" + ext" in text:
            return text
        import_anchor = "            module = importlib.import_module(ext_name)\n"
        if import_anchor not in text:
            if "importlib.import_module(ext_name)" in text:
                raise RuntimeError("markdown short extension import anchor not found")
            return text
        text = replace_text_once(
            text,
            import_anchor,
            "            module_name = ext_name if '.' in ext_name else f'markdown.extensions.{ext_name}'\n"
            "            module = importlib.import_module(module_name)\n",
            label="markdown short extension fallback import",
        )
        if "'Successfully imported extension module \"%s\".' % ext_name" in text:
            text = replace_text_once(
                text,
                "'Successfully imported extension module \"%s\".' % ext_name",
                "'Successfully imported extension module \"%s\".' % module_name",
                label="markdown short extension fallback logger",
            )
        if "'Successfuly imported extension module \"%s\".' % ext_name" in text:
            text = replace_text_once(
                text,
                "'Successfuly imported extension module \"%s\".' % ext_name",
                "'Successfuly imported extension module \"%s\".' % module_name",
                label="markdown short extension fallback legacy logger",
            )
        return text

    transform_source_text(context, "Lib/markdown/core.py", patch_core, allow_missing=True)
    transform_source_text(context, "Lib/markdown/__init__.py", patch_core, allow_missing=True)


LIBRARY_INTEGRATION = LibraryIntegration(
    name="markdown",
    source_provider="pypi",
    project_name="Markdown",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/markdown",
    ],
    cleanup_paths=[],
    python_packages=[
        "markdown",
    ],
    static_library_projects_release_x64=[],
    native_static_projects=[],
    builtin_module_registrations=[],
    staged_static_libraries_release_x64=[],
    python_link_dependencies_release_x64=[],
    python_link_wholearchive_release_x64=[],
    prepare_source_hooks=[_prepare_markdown_source],
    pre_patch_hooks=[],
    post_patch_hooks=[patch_markdown_sources],
    pre_build_hooks=[],
)
