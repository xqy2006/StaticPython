from pathlib import Path

from packaging.version import Version

from libs import (
    LibraryIntegration,
    _copy_entry,
    _download_file,
    _extract_archive,
    _find_cached_pypi_archive,
    _materialize_distribution_licenses,
    _normalized_project_name,
    _resolve_source_entry,
    _select_pypi_file,
    configure_python_module_ownership,
    read_source_text,
    read_text_file,
    write_source_text,
)


_COMPATIBILITY_ROOT = Path(__file__).with_name("compat")
_NATIVE_FLOATS_COMPAT = read_text_file(_COMPATIBILITY_ROOT / "floats.py")
_NATIVE_CATHETUS_COMPAT = read_text_file(_COMPATIBILITY_ROOT / "cathetus.py")


def _configure_hypothesis_globals_module(enabled: bool) -> None:
    """Keep optional top-level module metadata aligned with the selected sdist."""
    configure_python_module_ownership(
        LIBRARY_INTEGRATION,
        module_name="_hypothesis_globals",
        materialized_path="Lib/_hypothesis_globals.py",
        enabled=enabled,
        expose_top_level=True,
    )


def _prepare_hypothesis_source(context) -> None:
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

    _copy_entry(_resolve_source_entry(extracted_root, "hypothesis"), context.source_root / "Lib" / "hypothesis")
    try:
        globals_src = _resolve_source_entry(extracted_root, "_hypothesis_globals.py")
    except RuntimeError:
        globals_src = None
    if globals_src is not None:
        _copy_entry(globals_src, context.source_root / "Lib" / "_hypothesis_globals.py")
    _configure_hypothesis_globals_module(globals_src is not None)
    _materialize_distribution_licenses(context, integration, extracted_root)


def _install_hypothesis_native_compatibility(context) -> None:
    """Freeze an API-compatible implementation when upstream requires its Rust module."""
    release_version = LIBRARY_INTEGRATION.release_version
    if not release_version:
        raise RuntimeError("Hypothesis native compatibility requires a resolved release version")
    release = Version(release_version)

    # 6.156.3 introduced the Rust module for version/cathetus, while 6.157.2
    # moved the remaining float helpers. Earlier source releases are entirely
    # Python and must not be forced through either newer source layout.
    native_start = Version("6.156.3")
    floats_start = Version("6.157.2")
    if release < native_start:
        return

    version_source = read_source_text(context, "Lib/hypothesis/version.py")
    core_source = read_source_text(
        context,
        "Lib/hypothesis/strategies/_internal/core.py",
    )
    version_anchor = "from hypothesis._native import __version__ as __version__"
    cathetus_anchor = "from hypothesis._native.internal.cathetus import cathetus"
    if version_anchor not in version_source or cathetus_anchor not in core_source:
        raise RuntimeError("Hypothesis native-module anchors changed; compatibility layer was not applied")

    floats_source = read_source_text(context, "Lib/hypothesis/internal/floats.py")
    floats_anchor = "from hypothesis._native.internal.floats import ("
    has_native_floats = floats_anchor in floats_source
    if has_native_floats != (release >= floats_start):
        raise RuntimeError("Hypothesis native-float version boundary changed; compatibility layer was not applied")

    write_source_text(
        context,
        "Lib/hypothesis/_native/__init__.py",
        "# Generated by StaticPython for the frozen runtime.\n"
        f"__version__ = {release_version!r}\n",
    )
    write_source_text(
        context,
        "Lib/hypothesis/_native/internal/__init__.py",
        "# Generated by StaticPython for the frozen runtime.\n",
    )
    write_source_text(
        context,
        "Lib/hypothesis/_native/internal/cathetus.py",
        _NATIVE_CATHETUS_COMPAT,
    )
    if has_native_floats:
        write_source_text(
            context,
            "Lib/hypothesis/_native/internal/floats.py",
            _NATIVE_FLOATS_COMPAT,
        )


LIBRARY_INTEGRATION = LibraryIntegration(
    name="hypothesis",
    source_provider="pypi",
    project_name="hypothesis",
    release_version="6.164.0",
    dependencies=[],
    auto_resolve_dependencies=True,
    overlay_entries=[],
    materialized_paths=[
        "Lib/_hypothesis_globals.py",
        "Lib/hypothesis",
    ],
    cleanup_paths=[
        "Lib/_hypothesis_globals.py",
    ],
    python_packages=[
        "_hypothesis_globals",
        "hypothesis",
    ],
    top_level_import_names=[
        "_hypothesis_globals",
        "hypothesis",
    ],
    static_library_projects_release_x64=[],
    native_static_projects=[],
    builtin_module_registrations=[],
    staged_static_libraries_release_x64=[],
    python_link_dependencies_release_x64=[],
    python_link_wholearchive_release_x64=[],
    license_expression="MPL-2.0",
    prepare_source_hooks=[_prepare_hypothesis_source],
    pre_patch_hooks=[],
    post_patch_hooks=[_install_hypothesis_native_compatibility],
    pre_build_hooks=[],
    smoke_tests=[
        {
            "name": "native-float-and-strategy-behavior",
            "kind": "inline",
            "code": (
                "import math; "
                "from hypothesis import given, settings, strategies as st; "
                "from hypothesis._native.internal.cathetus import cathetus; "
                "from hypothesis._native.internal.floats import int_to_float, float_to_int, next_up; "
                "assert cathetus(5.0, 4.0) == 3.0; "
                "assert int_to_float(float_to_int(-0.0, 64), 64) == 0.0; "
                "assert math.copysign(1.0, int_to_float(float_to_int(-0.0, 64), 64)) < 0; "
                "assert next_up(0.0, 64) > 0.0; "
                "exec('@settings(max_examples=5, database=None)\\n@given(st.integers())\\ndef check(value):\\n    assert value == int(value)\\ncheck()')"
            ),
        }
    ],
)
