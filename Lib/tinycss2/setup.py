from libs import replace_text_all, simple_library, transform_source_text


def patch_tinycss2_sources(context):
    def patch_color4(text: str) -> str:
        updated = replace_text_all(text, "_κ", "_KAPPA")
        updated = replace_text_all(updated, "_ε", "_EPSILON")
        return updated

    transform_source_text(context, "Lib/tinycss2/color4.py", patch_color4, allow_missing=True)


LIBRARY_INTEGRATION = simple_library(
    name="tinycss2",
    overlay_entries=["Lib/tinycss2"],
    post_patch_hooks=[patch_tinycss2_sources],
)
