from __future__ import annotations

from libs import ensure_package_markers, pypi_library, replace_regex_once, transform_source_text


def _patch_remi_init(text: str) -> str:
    text = ensure_package_markers(text, "remi")
    if "pkg_resources" not in text:
        return text
    return replace_regex_once(
        text,
        r"(?ms)^from pkg_resources import get_distribution, DistributionNotFound\s*"
        r"try:\s*"
        r"    __version__ = get_distribution\(__name__\)\.version\s*"
        r"except DistributionNotFound:\s*"
        r"    # package is not installed\s*"
        r"    pass\s*",
        "try:\n"
        "    from importlib.metadata import PackageNotFoundError, version\n"
        "except Exception:  # pragma: no cover - importlib.metadata is stdlib on supported CPython\n"
        "    PackageNotFoundError = Exception\n"
        "    version = None\n"
        "\n"
        "try:\n"
        "    __version__ = version(__name__) if version is not None else \"0+staticpython\"\n"
        "except PackageNotFoundError:\n"
        "    __version__ = \"0+staticpython\"\n",
        label="remi package metadata fallback",
    )


def patch_remi_sources(context) -> None:
    transform_source_text(context, "Lib/remi/__init__.py", _patch_remi_init)


LIBRARY_INTEGRATION = pypi_library(
    name="remi",
    source_mapping={
        "remi": "Lib/remi",
    },
    python_packages=["remi"],
    post_patch_hooks=[patch_remi_sources],
)
