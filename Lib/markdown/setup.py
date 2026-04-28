from libs import inline_verification_step, replace_text_once, simple_library, transform_source_text


def patch_markdown_sources(context) -> None:
    def patch_core(text: str) -> str:
        return replace_text_once(
            text,
            (
                "        try:\n"
                "            module = importlib.import_module(ext_name)\n"
                "            logger.debug(\n"
                "                'Successfully imported extension module \"%s\".' % ext_name\n"
                "            )\n"
            ),
            (
                "        module_name = ext_name if '.' in ext_name else f'markdown.extensions.{ext_name}'\n"
                "        try:\n"
                "            module = importlib.import_module(module_name)\n"
                "            logger.debug(\n"
                "                'Successfully imported extension module \"%s\".' % module_name\n"
                "            )\n"
            ),
            label="markdown short extension fallback",
        )

    transform_source_text(context, "Lib/markdown/core.py", patch_core)


LIBRARY_INTEGRATION = simple_library(
    name='markdown',
    overlay_entries=['Lib/markdown'],
    post_patch_hooks=[patch_markdown_sources],
    verification_steps=[
        inline_verification_step(
            "markdown-smoke",
            """
import markdown

html = markdown.markdown("# Title\\n\\n- a\\n- b", extensions=["extra"])
assert "<h1>Title</h1>" in html
assert "<li>a</li>" in html
""",
        )
    ],
)
