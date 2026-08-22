from __future__ import annotations

import base64
import json

from libs import (
    ensure_text_before,
    pypi_library,
    replace_function_block_once,
    replace_text_once,
    replace_regex_once,
    source_path,
    transform_first_existing_source_text,
    transform_source_text,
    write_source_text,
)


def _read_optional_text(path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


def _supports_notebook_config(package_root) -> bool:
    init_text = _read_optional_text(package_root / "__init__.py")
    if "_jupyter_server_extension_paths" in init_text or "load_jupyter_server_extension" in init_text:
        return True
    return (package_root / "extension.py").exists()


def _supports_server_config(package_root) -> bool:
    init_text = _read_optional_text(package_root / "__init__.py")
    if "_jupyter_server_extension_points" in init_text:
        return True
    return (package_root / "serverextension.py").exists()


def _patch_labapp_extension_manager_fallback(text: str) -> str:
    if not text or "entry_point is None" not in text or "manager_factory = entry_point.load()" not in text:
        if "Extension Manager" in text and "manager_factory" in text:
            raise RuntimeError("jupyterlab.labapp extension manager fallback anchor not found")
        return text

    prefix = (
        "            if entry_point is None:\n"
        '                self.log.error(f"Extension Manager: No manager defined for provider \'{provider}\'.")\n'
    )
    suffix = (
        "            else:\n"
        '                self.log.info(f"Extension Manager is \'{provider}\'.")\n'
        "            manager_factory = entry_point.load()\n"
    )
    old_variants = (
        prefix + "                raise NotImplementedError()\n" + suffix,
        prefix + "                raise NotImplementedError\n" + suffix,
    )
    matches = [candidate for candidate in old_variants if candidate in text]
    if len(matches) != 1:
        raise RuntimeError("jupyterlab.labapp extension manager fallback anchor not found")

    new = (
        "            if entry_point is None:\n"
        '                self.log.warning(\n'
        '                    f"Extension Manager provider \'{provider}\' is unavailable in this environment; "\n'
        '                    "falling back to read-only manager."\n'
        "                )\n"
        '                provider = "readonly"\n'
        "                manager_factory = ReadOnlyExtensionManager\n"
        "            else:\n"
        '                self.log.info(f"Extension Manager is \'{provider}\'.")\n'
        "                manager_factory = entry_point.load()\n"
    )
    return replace_text_once(
        text,
        matches[0],
        new,
        label="jupyterlab.labapp extension manager fallback",
    )


def _patch_legacy_distutils_version(text: str) -> str:
    """Keep early JupyterLab commands importable without stdlib distutils."""

    legacy_import = "from distutils.version import LooseVersion\n"
    if legacy_import not in text:
        if "LooseVersion(" in text or "distutils.version" in text:
            raise RuntimeError("JupyterLab legacy version comparison anchor not found")
        return text

    text = replace_text_once(
        text,
        legacy_import,
        "from packaging.version import InvalidVersion, Version\n\n"
        "def _staticpython_version_key(value):\n"
        "    try:\n"
        "        return (0, Version(value))\n"
        "    except (InvalidVersion, TypeError):\n"
        "        return (1, str(value))\n\n",
        label="JupyterLab distutils version import",
    )
    comparisons = text.count("LooseVersion(")
    if comparisons == 0:
        raise RuntimeError("JupyterLab legacy version comparison anchor not found")
    text = text.replace("LooseVersion(", "_staticpython_version_key(")
    if "LooseVersion" in text or "distutils.version" in text:
        raise RuntimeError("JupyterLab legacy version comparison was only partially patched")
    return text


def patch_legacy_distutils_version(context) -> None:
    transform_source_text(
        context,
        "Lib/jupyterlab/commands.py",
        _patch_legacy_distutils_version,
        allow_missing=True,
    )


def _patch_legacy_semver_invalid_escapes(text: str) -> str:
    """Keep the legacy vendored semver module warning-free for _freeze_module."""

    numeric_anchor = 'NUMERIC = re.compile("^\\d+$")'
    split_anchor = 're.split("\\s+",'
    numeric_count = text.count(numeric_anchor)
    split_count = text.count(split_anchor)
    if numeric_count == 0 and split_count == 0:
        if 'NUMERIC = re.compile(r"^\\d+$")' in text and 're.split(r"\\s+",' in text:
            return text
        if "SEMVER_SPEC_VERSION" in text:
            raise RuntimeError("JupyterLab legacy semver invalid-escape anchors not found")
        return text
    if numeric_count != 1 or split_count != 5:
        raise RuntimeError(
            "JupyterLab legacy semver invalid-escape anchors changed: "
            f"numeric={numeric_count}, split={split_count}"
        )
    return text.replace(numeric_anchor, 'NUMERIC = re.compile(r"^\\d+$")').replace(
        split_anchor,
        're.split(r"\\s+",',
    )


def patch_legacy_semver_invalid_escapes(context) -> None:
    transform_source_text(
        context,
        "Lib/jupyterlab/semver.py",
        _patch_legacy_semver_invalid_escapes,
        allow_missing=True,
    )


def patch_jupyterlab_for_frozen_runtime(context) -> None:
    package_root = source_path(context, "Lib/jupyterlab")
    legacy_static_root = package_root / "build"
    if not (package_root / "static").exists() and legacy_static_root.exists():
        if not (package_root / "static").exists():
            (package_root / "static").mkdir(parents=True, exist_ok=True)
            for path in sorted(legacy_static_root.rglob("*")):
                if not path.is_file():
                    continue
                target = package_root / "static" / path.relative_to(legacy_static_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(path.read_bytes())
        staging_package = legacy_static_root / "package.json"
        if staging_package.exists() and not (package_root / "staging" / "package.json").exists():
            staging_dir = package_root / "staging"
            staging_dir.mkdir(parents=True, exist_ok=True)
            (staging_dir / "package.json").write_bytes(staging_package.read_bytes())
    if not (package_root / "static").exists():
        return
    byte_resources = {
        path.relative_to(package_root).as_posix(): base64.b64encode(path.read_bytes()).decode("ascii")
        for root_name in ("static", "themes")
        for path in sorted((package_root / root_name).rglob("*"))
        if (package_root / root_name).exists() and path.is_file()
    }
    templates = {
        path.name: path.read_text(encoding="utf-8")
        for path in sorted((package_root / "static").glob("*.html"))
    }
    static_package_path = package_root / "static" / "package.json"
    staging_package_path = package_root / "staging" / "package.json"
    source_package = package_root / "package.json"
    fallback_package_text = source_package.read_text(encoding="utf-8") if source_package.exists() else "{}"
    for package_path in (static_package_path, staging_package_path):
        if not package_path.exists():
            package_path.parent.mkdir(parents=True, exist_ok=True)
            package_path.write_text(fallback_package_text, encoding="utf-8", newline="\n")
    static_package_data = json.loads(static_package_path.read_text(encoding="utf-8"))
    core_package_data = json.loads(staging_package_path.read_text(encoding="utf-8"))
    schemas: dict[str, dict] = {}
    for schema_path in sorted((package_root / "schemas").rglob("*.json")):
        if schema_path.name == "package.json.orig":
            continue
        rel_path = schema_path.relative_to(package_root / "schemas")
        package_dir = rel_path.parent.as_posix()
        plugin = schema_path.stem
        schema_name = f"{package_dir}:{plugin}"
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
        version = "N/A"
        package_json = schema_path.parent / "package.json.orig"
        if package_json.exists():
            version = json.loads(package_json.read_text(encoding="utf-8")).get("version", "N/A")
        schemas[schema_name] = {"schema": schema, "version": version}

    has_static_js = any(
        key.startswith("static/") and key.endswith(".js")
        for key in byte_resources
    )
    legacy_layout = legacy_static_root.exists() or ("index.html" not in templates and has_static_js)

    if legacy_layout:
        if "index.html" not in templates:
            lab_html = package_root / "lab.html"
            if lab_html.exists():
                (package_root / "static" / "index.html").write_text(lab_html.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
                templates["index.html"] = lab_html.read_text(encoding="utf-8")
            else:
                templates["index.html"] = "<!doctype html><title>JupyterLab</title>\n"
    else:
        if "index.html" not in templates or not has_static_js:
            raise RuntimeError("expected JupyterLab static resources were not materialized")
        if "@jupyterlab/apputils-extension:themes" not in schemas:
            raise RuntimeError("expected JupyterLab theme settings schema was not materialized")

    if legacy_layout and "@jupyterlab/apputils-extension:themes" not in schemas:
        schemas["@jupyterlab/apputils-extension:themes"] = {"schema": {}, "version": "N/A"}
    if legacy_layout:
        for relative, content in {
            "schemas/@jupyterlab/apputils-extension/themes.json": "{}\n",
            "themes/@jupyterlab/theme-light-extension/index.css": "/* StaticPython legacy placeholder */\n",
            "themes/@jupyterlab/theme-dark-extension/index.css": "/* StaticPython legacy placeholder */\n",
        }.items():
            target = package_root / relative
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="\n")
        for relative, content in {
            "share/jupyter/lab/schemas/@jupyterlab/apputils-extension/themes.json": "{}\n",
            "share/jupyter/lab/themes/@jupyterlab/theme-light-extension/index.css": "/* StaticPython legacy placeholder */\n",
            "share/jupyter/lab/themes/@jupyterlab/theme-dark-extension/index.css": "/* StaticPython legacy placeholder */\n",
            "share/jupyter/lab/staging/package.json": staging_package_path.read_text(encoding="utf-8"),
            "share/jupyter/lab/static/package.json": static_package_path.read_text(encoding="utf-8"),
            "share/jupyter/lab/static/index.html": (package_root / "lab.html").read_text(encoding="utf-8") if (package_root / "lab.html").exists() else "",
        }.items():
            target = context.source_root / relative
            if not target.exists():
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding="utf-8", newline="\n")

    write_source_text(
        context,
        "Lib/jupyterlab/_staticpython_resources.py",
        "# Generated by StaticPython; keeps JupyterLab package resources available after freezing.\n"
        "import base64\n\n"
        f"TEMPLATES = {templates!r}\n"
        f"BYTE_RESOURCES = {byte_resources!r}\n"
        f"STATIC_PACKAGE_DATA = {static_package_data!r}\n"
        f"CORE_PACKAGE_DATA = {core_package_data!r}\n"
        f"SCHEMAS = {schemas!r}\n\n"
        "def resource_bytes(path: str) -> bytes | None:\n"
        "    data = BYTE_RESOURCES.get(path.replace('\\\\', '/'))\n"
        "    return None if data is None else base64.b64decode(data)\n",
    )
    if _supports_notebook_config(package_root):
        write_source_text(
            context,
            "etc/jupyter/jupyter_notebook_config.d/jupyterlab.json",
            json.dumps(
                {
                    "NotebookApp": {
                        "nbserver_extensions": {
                            "jupyterlab": True,
                        }
                    }
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )
    if _supports_server_config(package_root):
        write_source_text(
            context,
            "etc/jupyter/jupyter_server_config.d/jupyterlab.json",
            json.dumps(
                {
                    "ServerApp": {
                        "jpserver_extensions": {
                            "jupyterlab": True,
                        }
                    }
                },
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
        )

    def patch_coreconfig(text: str) -> str:
        if not text:
            return text
        if "def _get_default_core_data():" not in text:
            if '"staging", "package.json"' in text:
                raise RuntimeError("jupyterlab coreconfig package data anchor not found")
            return text
        text = ensure_text_before(
            text,
            "def _get_default_core_data():\n",
            "from ._staticpython_resources import CORE_PACKAGE_DATA as _STATICPYTHON_CORE_PACKAGE_DATA\n",
            label="jupyterlab coreconfig package data import",
        )
        return replace_function_block_once(
            text,
            "_get_default_core_data",
            'def _get_default_core_data():\n'
            '    """Get the data for the app template."""\n'
            '    if _STATICPYTHON_CORE_PACKAGE_DATA:\n'
            '        return json.loads(json.dumps(_STATICPYTHON_CORE_PACKAGE_DATA))\n'
            '    with open(pjoin(HERE, "staging", "package.json")) as fid:\n'
            '        return json.load(fid)\n\n',
            label="jupyterlab coreconfig embedded package data",
            next_name="_is_lab_package",
        )

    def patch_commands(text: str) -> str:
        if not text:
            return text
        if "def ensure_app(app_dir):" not in text:
            if "def _get_static_data(" in text:
                text = ensure_text_before(
                    text,
                    "def _get_static_data(app_dir):\n",
                    "from jupyterlab._staticpython_resources import STATIC_PACKAGE_DATA as _STATICPYTHON_STATIC_PACKAGE_DATA\n",
                    label="jupyterlab commands static package data import",
                )
                return replace_function_block_once(
                    text,
                    "_get_static_data",
                    'def _get_static_data(app_dir):\n'
                    '    """Get the data for the app static dir."""\n'
                    '    target = pjoin(app_dir, "static", "package.json")\n'
                    '    if _STATICPYTHON_STATIC_PACKAGE_DATA:\n'
                    '        return json.loads(json.dumps(_STATICPYTHON_STATIC_PACKAGE_DATA))\n'
                    '    if osp.exists(target):\n'
                    '        with open(target) as fid:\n'
                    '            return json.load(fid)\n'
                    '    else:\n'
                    '        return None\n\n',
                    label="jupyterlab static package data fallback",
                    next_name="_validate_compatibility",
                )
            if "JupyterLab application assets not found" in text:
                raise RuntimeError("jupyterlab ensure_app embedded assets anchor not found")
            return text
        text = ensure_text_before(
            text,
            "def ensure_app(app_dir):\n",
            "from jupyterlab._staticpython_resources import STATIC_PACKAGE_DATA as _STATICPYTHON_STATIC_PACKAGE_DATA\n",
            label="jupyterlab commands static package data import",
        )
        text = replace_function_block_once(
            text,
            "ensure_app",
            'def ensure_app(app_dir):\n'
            '    """Ensure that an application directory is available.\n\n'
            '    If it does not exist, return a list of messages to prompt the user.\n'
            '    """\n'
            '    if _STATICPYTHON_STATIC_PACKAGE_DATA or osp.exists(pjoin(app_dir, "static", "index.html")):\n'
            '        return\n\n'
            '    msgs = [\n'
            '        \'JupyterLab application assets not found in "%s"\' % app_dir,\n'
            '        "Please run `jupyter lab build` or use a different app directory",\n'
            '    ]\n'
            '    return msgs\n\n',
            label="jupyterlab ensure_app embedded assets",
            next_name="watch_packages",
        )
        return replace_function_block_once(
            text,
            "_get_static_data",
            'def _get_static_data(app_dir):\n'
            '    """Get the data for the app static dir."""\n'
            '    target = pjoin(app_dir, "static", "package.json")\n'
            '    if _STATICPYTHON_STATIC_PACKAGE_DATA:\n'
            '        return json.loads(json.dumps(_STATICPYTHON_STATIC_PACKAGE_DATA))\n'
            '    if osp.exists(target):\n'
            '        with open(target) as fid:\n'
            '            return json.load(fid)\n'
            '    else:\n'
            '        return None\n\n',
            label="jupyterlab static package data fallback",
            next_name="_validate_compatibility",
        )

    def patch_extensions_init(text: str) -> str:
        if 'for entry in entry_points(group="jupyterlab.extension_manager_v1"):' not in text:
            if "jupyterlab.extension_manager_v1" in text or "MANAGERS" in text:
                raise RuntimeError("jupyterlab.extensions builtin manager entry-point anchor not found")
            return text
        manager_wrapper = """

class _StaticPythonEntryPoint:
    def __init__(self, factory):
        self._factory = factory

    def load(self):
        return self._factory
"""
        if "_StaticPythonEntryPoint" not in text:
            anchor = 'for entry in entry_points(group="jupyterlab.extension_manager_v1"):\n    MANAGERS[entry.name] = entry\n'
            text = replace_text_once(
                text,
                anchor,
                anchor + manager_wrapper,
                label="jupyterlab.extensions builtin manager wrapper",
            )

        registration = (
            '\nMANAGERS.setdefault("readonly", _StaticPythonEntryPoint(get_readonly_manager))\n'
            'MANAGERS.setdefault("pypi", _StaticPythonEntryPoint(get_pypi_manager))\n'
        )
        if 'MANAGERS.setdefault("readonly", _StaticPythonEntryPoint(get_readonly_manager))' not in text:
            text = replace_regex_once(
                text,
                r'(?m)^(\s*return PyPIExtensionManager\(app_options, ext_options, parent\)\n)',
                r'\1' + registration,
                label="jupyterlab.extensions builtin manager registration",
            )
        return text

    transform_first_existing_source_text(
        context,
        [
            "Lib/jupyterlab/coreconfig.py",
            "Lib/jupyterlab/commands.py",
        ],
        patch_coreconfig,
        allow_all_missing=True,
    )
    transform_source_text(context, "Lib/jupyterlab/commands.py", patch_commands, allow_missing=True)
    transform_source_text(
        context,
        "Lib/jupyterlab/extensions/__init__.py",
        patch_extensions_init,
        allow_missing=True,
    )
    transform_source_text(
        context,
        "Lib/jupyterlab/labapp.py",
        _patch_labapp_extension_manager_fallback,
        allow_missing=True,
    )


LIBRARY_INTEGRATION = pypi_library(
    name="jupyterlab",
    release_version="4.0.9",
    dependencies=["packaging"],
    source_mapping={
        "jupyterlab": "Lib/jupyterlab",
        "?build": "Lib/jupyterlab/build",
        "?lab.html": "Lib/jupyterlab/lab.html",
        "?package.json": "Lib/jupyterlab/package.json",
        "jupyterlab/static||jupyterlab/build||static||build": "share/jupyter/lab/static",
        "?jupyterlab/schemas||?schemas": "share/jupyter/lab/schemas",
        "?jupyterlab/themes||?themes": "share/jupyter/lab/themes",
        "?jupyterlab/staging||?staging": "share/jupyter/lab/staging",
    },
    source_ignore_patterns=[
        "galata",
        "tests",
    ],
    cleanup_paths=[
        "etc/jupyter/jupyter_server_config.d/jupyterlab.json",
        "etc/jupyter/jupyter_notebook_config.d/jupyterlab.json",
    ],
    materialized_paths=[
        "share/jupyter/lab/static/index.html",
        "share/jupyter/lab/static/package.json",
        "Lib/jupyterlab/_staticpython_resources.py",
    ],
    python_packages=["jupyterlab"],
    license_expression="BSD-3-Clause",
    # The earliest PyPI sdists omit the repository LICENSE file.  Preserve the
    # two upstream notices used by those releases from immutable Git commits;
    # source distributions that include their own license remain preferred.
    license_sources=[
        {
            "filename": "LICENSE-2015.txt",
            "url": (
                "https://raw.githubusercontent.com/jupyterlab/jupyterlab/"
                "ef40f33f074ce921cc1405b4658f62f8876802b0/LICENSE"
            ),
            "sha256": "e73aa83e9684316187c171eeefbb03ae52a5d6c5469a5c3c222c8487a3a43df4",
        },
        {
            "filename": "LICENSE-2015-2016.txt",
            "url": (
                "https://raw.githubusercontent.com/jupyterlab/jupyterlab/"
                "5e4e335b87307012491adee2c150aaeebceba85c/LICENSE"
            ),
            "sha256": "eb713dd6d648da8f74b389761faa8c310f186f365d3055ec2c788f1800bcd94f",
        },
    ],
    post_patch_hooks=[
        patch_legacy_distutils_version,
        patch_legacy_semver_invalid_escapes,
        patch_jupyterlab_for_frozen_runtime,
    ],
)
