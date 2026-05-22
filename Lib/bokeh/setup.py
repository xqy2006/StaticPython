from __future__ import annotations

from libs import pypi_library, replace_regex_once, transform_source_text


def _patch_bokeh_init(text: str) -> str:
    if "0+staticpython" in text and "PackageNotFoundError" in text:
        return text
    return replace_regex_once(
        text,
        r'(?m)^__version__ = importlib_metadata\.version\("bokeh"\)\s*$',
        "try:\n"
        '    __version__ = importlib_metadata.version("bokeh")\n'
        "except importlib_metadata.PackageNotFoundError:\n"
        '    __version__ = "0+staticpython"',
        label="bokeh version metadata fallback",
    )


def patch_bokeh_sources(context) -> None:
    transform_source_text(context, "Lib/bokeh/__init__.py", _patch_bokeh_init)


LIBRARY_INTEGRATION = pypi_library(
    name="bokeh",
    source_mapping={
        "src/bokeh||bokeh": "Lib/bokeh",
    },
    python_packages=["bokeh"],
    source_ignore_patterns=["tests"],
    post_patch_hooks=[patch_bokeh_sources],
)
