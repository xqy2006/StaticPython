from __future__ import annotations

from libs import pypi_library, replace_regex_once, source_path, transform_source_text, write_source_text


def _patch_bokeh_init(text: str) -> str:
    if "0+staticpython" in text and "PackageNotFoundError" in text:
        return text
    if ".version(\"bokeh\")" not in text:
        return text
    return replace_regex_once(
        text,
        r'(?m)^__version__ = (?P<metadata>importlib(?:\.metadata|_metadata))\.version\("bokeh"\)\s*$',
        "try:\n"
        '    __version__ = \\g<metadata>.version("bokeh")\n'
        "except \\g<metadata>.PackageNotFoundError:\n"
        '    __version__ = "0+staticpython"',
        label="bokeh version metadata fallback",
    )


def patch_bokeh_sources(context) -> None:
    transform_source_text(context, "Lib/bokeh/__init__.py", _patch_bokeh_init)
    common_properties = source_path(context, "Lib/bokeh/models/common/properties.py")
    common_init = source_path(context, "Lib/bokeh/models/common/__init__.py")
    if common_properties.exists() and not common_init.exists():
        write_source_text(
            context,
            "Lib/bokeh/models/common/__init__.py",
            '"""Compatibility package for frozen Bokeh common models."""\n',
        )


LIBRARY_INTEGRATION = pypi_library(
    name="bokeh",
    source_mapping={
        "src/bokeh||bokeh": "Lib/bokeh",
    },
    python_packages=["bokeh"],
    source_ignore_patterns=["tests"],
    post_patch_hooks=[patch_bokeh_sources],
)
