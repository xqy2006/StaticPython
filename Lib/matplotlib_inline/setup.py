from libs import inline_verification_step, replace_text_once, simple_library, transform_source_text


def patch_matplotlib_inline_sources(context):
    def patch_init(text: str) -> str:
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
    verification_steps=[
        inline_verification_step(
            "matplotlib-inline-smoke",
            """
from matplotlib_inline.config import InlineBackend

backend = InlineBackend.instance()
assert backend.figure_formats == {"png"}
backend.figure_format = "svg"
assert backend.figure_formats == {"svg"}
assert backend.print_figure_kwargs["bbox_inches"] == "tight"
""",
        )
    ],
)
