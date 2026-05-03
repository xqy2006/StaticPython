from libs import replace_text_once, simple_library, transform_source_text


def patch_isort_sources(context):
    def patch_version(text: str) -> str:
        return replace_text_once(
            text,
            'from importlib import metadata\n\n__version__ = metadata.version("isort")\n',
            (
                "from importlib import metadata\n\n"
                "try:\n"
                '    __version__ = metadata.version("isort")\n'
                "except metadata.PackageNotFoundError:\n"
                '    __version__ = "0+staticpython"\n'
            ),
            label="isort metadata-free version fallback",
        )

    transform_source_text(context, "Lib/isort/_version.py", patch_version)


LIBRARY_INTEGRATION = simple_library(
    name="isort",
    overlay_entries=["Lib/isort"],
    post_patch_hooks=[patch_isort_sources],
)
