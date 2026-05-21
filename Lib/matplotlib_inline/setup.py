from libs import replace_text_once, simple_library, transform_source_text


def patch_matplotlib_inline_sources(context):
    def patch_init(text: str) -> str:
        if text == "":
            return 'from . import config  # noqa\n'
        if "from . import config  # noqa\n" in text and "backend_inline" not in text:
            return text
        return replace_text_once(
            text,
            "from . import backend_inline, config  # noqa\n",
            "from . import config  # noqa\n",
            label="matplotlib_inline optional backend import",
        )

    transform_source_text(context, "Lib/matplotlib_inline/__init__.py", patch_init)


LIBRARY_INTEGRATION = simple_library(
    name="matplotlib_inline",
    project_name="matplotlib-inline",
    overlay_entries=["Lib/matplotlib_inline"],
    post_patch_hooks=[patch_matplotlib_inline_sources],
)
