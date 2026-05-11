import re

from libs import simple_library, transform_first_existing_source_text


def patch_isort_sources(context):
    def patch_version(text: str) -> str:
        if "metadata.PackageNotFoundError" in text:
            return text
        updated, count = re.subn(
            r'(?m)^__version__\s*=\s*metadata\.version\("isort"\)\s*$',
            (
                "try:\n"
                '    __version__ = metadata.version("isort")\n'
                "except metadata.PackageNotFoundError:\n"
                '    __version__ = "0+staticpython"'
            ),
            text,
            count=1,
        )
        if count == 1:
            return updated
        return text

    transform_first_existing_source_text(
        context,
        ["Lib/isort/_version.py", "Lib/isort/__init__.py"],
        patch_version,
        allow_all_missing=True,
    )


LIBRARY_INTEGRATION = simple_library(
    name="isort",
    overlay_entries=["Lib/isort"],
    post_patch_hooks=[patch_isort_sources],
)
