from __future__ import annotations

import re

from packaging.version import Version

from libs import pypi_library, read_source_text, write_source_text


def _render_frozen_version_module(source: str, release_version: str) -> str:
    marker = "# This file will be replaced in the wheel with a hard-coded version."
    if f"__version__ = {release_version!r}  # StaticPython frozen version" in source:
        return source
    required = (
        marker,
        'input_file = DIR.parent / "include/pybind11/detail/common.h"',
        "match = regex.search(input_file.read_text(encoding=\"utf-8\"))",
    )
    missing = [anchor for anchor in required if anchor not in source]
    if missing:
        raise RuntimeError(f"pybind11 source-version anchors changed: {missing!r}")
    version = Version(release_version)
    version_parts = tuple(version.release)
    return (
        "from __future__ import annotations\n\n"
        f"__version__ = {release_version!r}  # StaticPython frozen version\n"
        f"version_info = {version_parts!r}\n"
    )


def patch_pybind11_sources(context) -> None:
    release_version = LIBRARY_INTEGRATION.release_version
    if not release_version:
        raise RuntimeError("pybind11 frozen version patch requires a resolved release version")

    common = read_source_text(
        context,
        "pybind11_builtin/include/pybind11/detail/common.h",
    )
    macros = {}
    for part in ("MAJOR", "MINOR", "PATCH"):
        match = re.search(rf"(?m)^#define PYBIND11_VERSION_{part} +(\d+)\s*$", common)
        if match is None:
            raise RuntimeError(f"pybind11 {part.lower()} version macro was not found")
        macros[part] = int(match.group(1))
    source_version = (macros["MAJOR"], macros["MINOR"], macros["PATCH"])
    release = Version(release_version)
    if tuple(release.release[:3]) != source_version:
        raise RuntimeError(
            f"pybind11 source version {source_version!r} does not match resolved {release_version}"
        )

    relative = "Lib/pybind11/_version.py"
    source = read_source_text(context, relative)
    write_source_text(context, relative, _render_frozen_version_module(source, release_version))


LIBRARY_INTEGRATION = pypi_library(
    name="pybind11",
    release_version="3.0.4",
    source_mapping={
        "pybind11/include/pybind11||include/pybind11": "pybind11_builtin/include/pybind11",
        "pybind11": "Lib/pybind11",
    },
    python_packages=["pybind11"],
    post_patch_hooks=[patch_pybind11_sources],
    smoke_tests=[
        {
            "name": "frozen-version-api",
            "kind": "inline",
            "code": (
                "import pybind11; "
                "assert pybind11.__version__; "
                "assert tuple(pybind11.version_info)[:2] >= (2, 0); "
                "assert callable(pybind11.get_include)"
            ),
        }
    ],
)
