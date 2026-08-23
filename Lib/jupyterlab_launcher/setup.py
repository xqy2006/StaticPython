from __future__ import annotations

from libs import pypi_library, transform_source_text


def _patch_json_minify_invalid_escapes(text: str) -> str:
    """Keep legacy JSON.minify sources warning-free for _freeze_module."""

    anchor = "tokenizer = re.compile('\"|(/\\*)|(\\*/)|(//)|\\n|\\r')"
    replacement = "tokenizer = re.compile(r'\"|(/\\*)|(\\*/)|(//)|\\n|\\r')"
    count = text.count(anchor)
    if count == 0:
        if replacement in text:
            return text
        if "def json_minify(" in text and "tokenizer = re.compile(" in text:
            raise RuntimeError(
                "jupyterlab-launcher json_minify invalid-escape anchor not found"
            )
        return text
    if count != 1:
        raise RuntimeError(
            "jupyterlab-launcher json_minify invalid-escape anchor matched "
            f"{count} times"
        )
    return text.replace(anchor, replacement, 1)


def patch_json_minify_invalid_escapes(context) -> None:
    transform_source_text(
        context,
        "Lib/jupyterlab_launcher/json_minify.py",
        _patch_json_minify_invalid_escapes,
        allow_missing=True,
    )


LIBRARY_INTEGRATION = pypi_library(
    name="jupyterlab_launcher",
    project_name="jupyterlab-launcher",
    source_mapping={"jupyterlab_launcher": "Lib/jupyterlab_launcher"},
    source_ignore_patterns=["tests"],
    python_packages=["jupyterlab_launcher"],
    post_patch_hooks=[patch_json_minify_invalid_escapes],
)
