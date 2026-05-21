import re

from libs import (
    replace_regex_once,
    simple_library,
    source_path,
    transform_first_existing_source_text,
    transform_source_text,
    write_source_text,
)


def _patch_flask_testing(text: str) -> str:
    if 'werkzeug.__version__' in text:
        updated = text
        replacements = [
            (
                'f"werkzeug/{werkzeug.__version__}"',
                'f"werkzeug/{getattr(werkzeug, \'__version__\', \'3.1.8\')}"',
            ),
            (
                '"werkzeug/" + werkzeug.__version__',
                '"werkzeug/" + getattr(werkzeug, "__version__", "3.1.8")',
            ),
        ]
        for old, new in replacements:
            if old in updated:
                updated = updated.replace(old, new, 1)
                break
        if "werkzeug.__version__" in updated:
            raise RuntimeError("flask.testing werkzeug.__version__ anchor not found")
        return updated
    if 'importlib.metadata.version("werkzeug")' not in text:
        if "werkzeug/" in text or "_werkzeug_version" in text:
            raise RuntimeError("flask.testing werkzeug version anchor not found")
        return text
    return replace_regex_once(
        text,
        r"(?ms)(\s+if not _werkzeug_version:\n)(\s+)_werkzeug_version = importlib\.metadata\.version\(\"werkzeug\"\)\n",
        r'\1'
        r'\2try:'
        r'\n\2    _werkzeug_version = importlib.metadata.version("werkzeug")'
        r'\n\2except importlib.metadata.PackageNotFoundError:'
        r'\n\2    _werkzeug_version = "3.1.8"'
        r'\n',
        label="flask.testing",
    )


def _patch_flask_cli(text: str) -> str:
    if "werkzeug.__version__" not in text:
        version_block_match = re.search(r"(?ms)^def get_version\(.*?^version_option\s*=", text)
        version_block = version_block_match.group(0) if version_block_match else ""
        if version_block_match and (
            ("Werkzeug" in version_block or "werkzeug" in version_block)
            and 'version("werkzeug")' not in version_block
            and "version('werkzeug')" not in version_block
        ):
            raise RuntimeError("flask.cli werkzeug version anchor not found")
        return text
    updated = text
    replacements = [
        (
            '"werkzeug": werkzeug.__version__,',
            '"werkzeug": getattr(werkzeug, "__version__", "3.1.8"),',
        ),
        (
            "'werkzeug': werkzeug.__version__,",
            "'werkzeug': getattr(werkzeug, \"__version__\", \"3.1.8\"),",
        ),
        (
            'f"Werkzeug {werkzeug.__version__}"',
            'f"Werkzeug {getattr(werkzeug, \'__version__\', \'3.1.8\')}"',
        ),
    ]
    for old, new in replacements:
        if old in updated:
            updated = updated.replace(old, new, 1)
            break
    if "werkzeug.__version__" in updated:
        raise RuntimeError("flask.cli werkzeug.__version__ anchor not found")
    return updated


def patch_flask_sources(context) -> None:
    transform_first_existing_source_text(
        context,
        [
            "Lib/flask/testing.py",
            "Lib/flask/test.py",
        ],
        _patch_flask_testing,
        allow_all_missing=True,
    )
    transform_source_text(context, "Lib/flask/cli.py", _patch_flask_cli, allow_missing=True)
    package_root = source_path(context, "Lib/flask")
    sansio_root = package_root / "sansio"
    if not package_root.is_dir() or not sansio_root.exists():
        return
    write_source_text(
        context,
        "Lib/flask/sansio/__init__.py",
        (
            "from .app import App as App\n"
            "from .blueprints import Blueprint as Blueprint\n"
            "from .blueprints import BlueprintSetupState as BlueprintSetupState\n"
            "from .scaffold import Scaffold as Scaffold\n"
            "from .scaffold import _sentinel as _sentinel\n"
        ),
    )


LIBRARY_INTEGRATION = simple_library(
    name="flask",
    overlay_entries=["Lib/flask"],
    post_patch_hooks=[patch_flask_sources],
)
