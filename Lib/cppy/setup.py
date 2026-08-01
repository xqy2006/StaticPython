from __future__ import annotations

from libs import pypi_library, replace_text_once, transform_source_text


def _patch_cppy_setuptools_import(text: str) -> str:
    replacement = '''try:
    from setuptools.command.build_ext import build_ext
except ModuleNotFoundError as exc:
    if exc.name != "setuptools":
        raise
    _STATICPYTHON_SETUPTOOLS_ERROR = exc

    class build_ext:
        """Unavailable build command placeholder for frozen runtime use."""

        def __init__(self, *args, **kwargs):
            raise RuntimeError(
                "CppyBuildExt is a source-build helper and requires setuptools"
            ) from _STATICPYTHON_SETUPTOOLS_ERROR
'''
    return replace_text_once(
        text,
        "from setuptools.command.build_ext import build_ext\n",
        replacement,
        label="cppy optional setuptools build command",
    )


def patch_cppy_sources(context) -> None:
    transform_source_text(context, "Lib/cppy/__init__.py", _patch_cppy_setuptools_import)


LIBRARY_INTEGRATION = pypi_library(
    name="cppy",
    release_version="1.3.1",
    source_mapping={"cppy": "Lib/cppy"},
    python_packages=["cppy"],
    post_patch_hooks=[patch_cppy_sources],
    smoke_tests=[
        {
            "name": "runtime-api-without-setuptools",
            "kind": "inline",
            "code": (
                "import cppy; "
                "assert cppy.__version__; "
                "assert callable(cppy.get_include); "
                "assert isinstance(cppy.CppyBuildExt, type)"
            ),
        }
    ],
)
