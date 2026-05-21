from packaging.version import Version

from libs import (
    LibraryIntegration,
    _copy_entry,
    _candidate_source_roots,
    _download_file,
    _extract_archive,
    _find_cached_pypi_archive,
    _normalized_project_name,
    _resolve_source_entry,
    _select_pypi_file,
    write_source_text,
)


def _find_direct_source_entry(extracted_root, selector):
    normalized = selector.replace("\\", "/").strip("/")
    for root in _candidate_source_roots(extracted_root):
        direct = root / normalized
        if direct.exists():
            return direct
        file_candidate = root / f"{normalized}.py"
        if file_candidate.exists():
            return file_candidate
    return None


def _write_python_multipart_shims(context) -> None:
    shims = {
        "Lib/python_multipart/__init__.py": (
            '"""Compatibility shim for older python-multipart releases."""\n\n'
            "from multipart import *\n"
            "from multipart import __all__, __version__\n"
        ),
        "Lib/python_multipart/decoders.py": "from multipart.decoders import *\n",
        "Lib/python_multipart/exceptions.py": "from multipart.exceptions import *\n",
        "Lib/python_multipart/multipart.py": "from multipart.multipart import *\n",
        "Lib/python_multipart/py.typed": "",
    }
    for relative, text in shims.items():
        write_source_text(context, relative, text)


def _prepare_python_multipart_source(context) -> None:
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

    multipart_src = _resolve_source_entry(extracted_root, "multipart")
    python_multipart_src = _find_direct_source_entry(extracted_root, "python_multipart")

    _copy_entry(multipart_src, context.source_root / "Lib" / "multipart")
    if python_multipart_src is not None:
        _copy_entry(python_multipart_src, context.source_root / "Lib" / "python_multipart")
    else:
        _write_python_multipart_shims(context)


LIBRARY_INTEGRATION = LibraryIntegration(
    name="python_multipart",
    source_provider="pypi",
    project_name="python-multipart",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/python_multipart",
        "Lib/multipart",
    ],
    cleanup_paths=[],
    python_packages=[
        "python_multipart",
        "multipart",
    ],
    static_library_projects_release_x64=[],
    native_static_projects=[],
    builtin_module_registrations=[],
    staged_static_libraries_release_x64=[],
    python_link_dependencies_release_x64=[],
    python_link_wholearchive_release_x64=[],
    prepare_source_hooks=[_prepare_python_multipart_source],
    pre_patch_hooks=[],
    post_patch_hooks=[],
    pre_build_hooks=[],
)
