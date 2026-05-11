import re

from libs import simple_library, transform_source_text


def patch_ipython_sources(context):
    def patch_skipdoctest_import(text: str) -> str:
        if "def skip_doctest(function):\n    return function\n" in text:
            return text
        updated, count = re.subn(
            r"(?m)^from IPython\.testing\.skipdoctest import skip_doctest\s*$",
            "def skip_doctest(function):\n    return function",
            text,
            count=1,
        )
        if count == 1:
            return updated
        return text

    ipython_root = context.source_root / "Lib" / "IPython"
    for path in sorted(ipython_root.rglob("*.py")):
        text = path.read_text(encoding="latin-1")
        if "from IPython.testing.skipdoctest import skip_doctest" not in text:
            continue
        relative = path.relative_to(context.source_root).as_posix()
        transform_source_text(context, relative, patch_skipdoctest_import)


LIBRARY_INTEGRATION = simple_library(
    name="IPython",
    project_name="ipython",
    overlay_entries=["Lib/IPython"],
    post_patch_hooks=[patch_ipython_sources],
)
