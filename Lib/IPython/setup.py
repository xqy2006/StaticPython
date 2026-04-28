from libs import inline_verification_step, replace_text_once, simple_library, transform_source_text


def patch_ipython_sources(context):
    def patch_skipdoctest_import(text: str) -> str:
        return replace_text_once(
            text,
            "from IPython.testing.skipdoctest import skip_doctest\n",
            "def skip_doctest(function):\n    return function\n",
            label="IPython skip_doctest fallback",
        )

    ipython_root = context.source_root / "Lib" / "IPython"
    for path in sorted(ipython_root.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if "from IPython.testing.skipdoctest import skip_doctest" not in text:
            continue
        relative = path.relative_to(context.source_root).as_posix()
        transform_source_text(context, relative, patch_skipdoctest_import)


LIBRARY_INTEGRATION = simple_library(
    name="IPython",
    project_name="ipython",
    overlay_entries=["Lib/IPython"],
    post_patch_hooks=[patch_ipython_sources],
    verification_steps=[
        inline_verification_step(
            "ipython-smoke",
            """
from IPython.core.interactiveshell import InteractiveShell

shell = InteractiveShell.instance()
result = shell.run_cell("answer = 40 + 2", store_history=False)
assert result.success
assert shell.user_ns["answer"] == 42
""",
        )
    ],
)
