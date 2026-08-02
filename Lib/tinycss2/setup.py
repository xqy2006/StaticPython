from libs import replace_text_all, simple_library, transform_source_text


def patch_tinycss2_sources(context):
    def patch_color4(text: str) -> str:
        updated = replace_text_all(text, "_κ", "_KAPPA")
        updated = replace_text_all(updated, "_ε", "_EPSILON")
        if "_κ" in updated or "_ε" in updated:
            raise RuntimeError("tinycss2 non-ASCII identifier anchor not patched")
        return updated

    transform_source_text(context, "Lib/tinycss2/color4.py", patch_color4, allow_missing=True)


LIBRARY_INTEGRATION = simple_library(
    name="tinycss2",
    release_version="1.5.1",
    overlay_entries=["Lib/tinycss2"],
    post_patch_hooks=[patch_tinycss2_sources],
)
