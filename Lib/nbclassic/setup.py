from __future__ import annotations

import base64
import hashlib
import json
import shutil
import tarfile
import zlib
from pathlib import Path, PurePosixPath

from libs import _download_file, pypi_library, source_path, write_source_text


def _compressed_resource_payload(data: bytes) -> str:
    return base64.b85encode(zlib.compress(data, level=9)).decode("ascii")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def materialize_nbclassic_vendor_licenses(context) -> None:
    integration = LIBRARY_INTEGRATION
    source = integration.dependency_resolution.get("source")
    if not isinstance(source, dict) or source.get("packagetype") != "bdist_wheel":
        return
    license_source = integration.dependency_resolution.get("license_source")
    if not isinstance(license_source, dict):
        raise RuntimeError("nbclassic pure-wheel source has no locked sdist license companion")

    filename = license_source.get("filename")
    url = license_source.get("url")
    expected_sha256 = str(license_source.get("sha256") or "").casefold()
    if (
        not isinstance(filename, str)
        or Path(filename).name != filename
        or not isinstance(url, str)
        or not url.startswith("https://")
        or len(expected_sha256) != 64
        or any(character not in "0123456789abcdef" for character in expected_sha256)
    ):
        raise RuntimeError("nbclassic locked sdist license companion is invalid")

    archive_path = (
        context.download_cache_root
        / "pypi"
        / "nbclassic"
        / str(integration.release_version)
        / filename
    )
    if not archive_path.exists():
        context.log(f"downloading nbclassic license companion from {url}")
        _download_file(url, archive_path)
    observed_sha256 = _sha256_file(archive_path)
    if observed_sha256 != expected_sha256:
        raise RuntimeError(
            "nbclassic sdist license companion hash mismatch: "
            f"expected {expected_sha256}, observed {observed_sha256}"
        )

    license_prefixes = ("license", "copying", "notice", "copyright", "authors")
    records: dict[tuple[str, str], tuple[str, bytes]] = {}
    root_license_records: set[tuple[str, str]] = set()
    vendored_license_records: set[tuple[str, str]] = set()
    has_vendored_static_payload = False
    with tarfile.open(archive_path, "r:*") as archive:
        for member in archive:
            if not member.isfile():
                continue
            normalized = PurePosixPath(member.name.replace("\\", "/"))
            if normalized.is_absolute() or ".." in normalized.parts:
                raise RuntimeError("nbclassic license companion contains an unsafe path")
            parts = tuple(part.casefold() for part in normalized.parts)
            is_vendored_static_path = "nbclassic" in parts and "static" in parts
            if is_vendored_static_path:
                has_vendored_static_payload = True
            basename = normalized.name
            if not basename.casefold().startswith(license_prefixes):
                continue
            is_root_license = len(parts) == 2
            is_vendored_license = is_vendored_static_path
            if not is_root_license and not is_vendored_license:
                continue
            if member.size <= 0 or member.size > 2 * 1024 * 1024:
                raise RuntimeError(
                    "nbclassic license companion contains an invalid license file size"
                )
            stream = archive.extractfile(member)
            if stream is None:
                raise RuntimeError("nbclassic license companion license file is unreadable")
            data = stream.read()
            if not data.strip():
                raise RuntimeError("nbclassic license companion contains an empty license file")
            digest = hashlib.sha256(data).hexdigest()
            record_key = (basename.casefold(), digest)
            records.setdefault(record_key, (basename, data))
            if is_root_license:
                root_license_records.add(record_key)
            if is_vendored_license:
                vendored_license_records.add(record_key)

    if not root_license_records:
        raise RuntimeError(
            "nbclassic sdist license companion did not contain a root license"
        )
    if has_vendored_static_payload and not vendored_license_records:
        raise RuntimeError(
            "nbclassic sdist license companion did not contain vendored static notices"
        )
    target_root = context.source_root / "licenses" / "nbclassic"
    if target_root.exists():
        shutil.rmtree(target_root)
    target_root.mkdir(parents=True)
    integration.license_files.clear()
    used_names: set[str] = set()
    for (_basename_key, digest), (basename, data) in sorted(records.items()):
        target_name = basename
        if target_name.casefold() in used_names:
            target_name = f"{digest[:12]}-{basename}"
        used_names.add(target_name.casefold())
        target = target_root / target_name
        target.write_bytes(data)
        integration.license_files.append(
            target.relative_to(context.source_root).as_posix()
        )
    context.log(
        f"materialized {len(integration.license_files)} nbclassic license/notice files "
        "from the locked sdist companion"
    )


def embed_nbclassic_resources(context) -> None:
    package_root = source_path(context, "Lib/nbclassic")
    static_root = package_root / "static"
    templates_root = package_root / "templates"
    if not static_root.exists() or not templates_root.exists():
        raise RuntimeError("expected nbclassic static resources and templates were not materialized")

    templates: dict[str, str] = {}
    for path in sorted(templates_root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(templates_root).as_posix()
        text = path.read_text(encoding="utf-8")
        templates[relative] = text
        templates[f"templates/{relative}"] = text

    resource_payloads = {
        path.relative_to(package_root).as_posix(): _compressed_resource_payload(path.read_bytes())
        for path in sorted(static_root.rglob("*"))
        if path.is_file()
    }
    if "tree.html" not in templates:
        raise RuntimeError("expected nbclassic tree template was not materialized")
    if not any(name.startswith("static/") and name.endswith(".js") for name in resource_payloads):
        raise RuntimeError("expected nbclassic JavaScript resources were not materialized")

    write_source_text(
        context,
        "Lib/nbclassic/_staticpython_resources.py",
        "# Generated by StaticPython; keeps nbclassic resources available after freezing.\n"
        "import base64\n"
        "import zlib\n\n"
        f"TEMPLATES = {templates!r}\n"
        f"RESOURCE_PAYLOADS = {resource_payloads!r}\n\n"
        "def resource_bytes(path: str) -> bytes | None:\n"
        "    payload = RESOURCE_PAYLOADS.get(path.replace('\\\\', '/').lstrip('/'))\n"
        "    if payload is None:\n"
        "        return None\n"
        "    return zlib.decompress(base64.b85decode(payload.encode('ascii')))\n",
    )
    write_source_text(
        context,
        "etc/jupyter/jupyter_server_config.d/nbclassic.json",
        json.dumps(
            {"ServerApp": {"jpserver_extensions": {"nbclassic": True}}},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
    )


LIBRARY_INTEGRATION = pypi_library(
    name="nbclassic",
    release_version="1.3.3",
    source_mapping={
        "nbclassic": "Lib/nbclassic",
    },
    source_ignore_patterns=["tests"],
    cleanup_paths=[
        "etc/jupyter/jupyter_server_config.d/nbclassic.json",
    ],
    materialized_paths=[
        "Lib/nbclassic/_staticpython_resources.py",
        "etc/jupyter/jupyter_server_config.d/nbclassic.json",
    ],
    python_packages=["nbclassic"],
    # PyPI's 1.3.3 sdist contains a full development node_modules tree and is
    # over five times larger than the immutable pure-Python wheel. The wheel
    # is a permitted source input here and still has an exact lock digest.
    source_resolver="pypi-universal-wheel",
    resource_rules=[
        {"action": "include", "path": "Lib/nbclassic/i18n"},
        {
            "action": "include",
            "path": "etc/jupyter/jupyter_server_config.d/nbclassic.json",
        },
    ],
    license_expression="BSD-3-Clause",
    smoke_tests=[
        {
            "name": "embedded-classic-ui-resources",
            "kind": "inline",
            "code": (
                "import nbclassic; "
                "from nbclassic._staticpython_resources import TEMPLATES, resource_bytes; "
                "from jupyter_server._staticpython_resources import "
                "resolve_resource_from_roots, resource_bytes_for_path; "
                "assert 'tree.html' in TEMPLATES; "
                "assert resource_bytes('static/favicon.ico'); "
                "path = resolve_resource_from_roots([nbclassic.DEFAULT_STATIC_FILES_PATH], "
                "'favicon.ico'); "
                "assert path == 'staticpython-resource://nbclassic/static/favicon.ico'; "
                "assert resource_bytes_for_path(path) == resource_bytes('static/favicon.ico')"
            ),
        }
    ],
    prepare_source_hooks=[materialize_nbclassic_vendor_licenses],
    post_patch_hooks=[embed_nbclassic_resources],
)
