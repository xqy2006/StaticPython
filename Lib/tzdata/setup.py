from __future__ import annotations

import base64
import io
import re
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from libs import LibraryHookContext, pypi_library


TZDATA_EMBED_MARKER_BEGIN = "# -- SINGLEFILE-TZDATA-BEGIN --"
TZDATA_EMBED_MARKER_END = "# -- SINGLEFILE-TZDATA-END --"


def _replace_once(text: str, old: str, new: str, *, path: Path) -> str:
    if new in text:
        return text
    if old not in text:
        raise RuntimeError(f"expected snippet not found in {path}: {old!r}")
    return text.replace(old, new, 1)


def _chunk_ascii(text: str, width: int = 100) -> list[str]:
    return [text[index:index + width] for index in range(0, len(text), width)]


def _render_tzdata_embedded_block(tzdata_root: Path) -> str:
    zoneinfo_root = tzdata_root / "zoneinfo"
    zones_path = tzdata_root / "zones"
    if not zoneinfo_root.exists():
        raise RuntimeError(f"tzdata zoneinfo directory missing: {zoneinfo_root}")
    if not zones_path.exists():
        raise RuntimeError(f"tzdata zones file missing: {zones_path}")

    buffer = io.BytesIO()
    with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
        archive.writestr("zones", zones_path.read_bytes())
        for path in sorted(zoneinfo_root.rglob("*")):
            if not path.is_file():
                continue
            if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:
                continue
            if path.name == "__init__.py":
                continue
            archive.writestr(path.relative_to(tzdata_root).as_posix(), path.read_bytes())

    payload = base64.b85encode(buffer.getvalue()).decode("ascii")
    payload_lines = "\n".join(f'    "{chunk}"' for chunk in _chunk_ascii(payload))
    return (
        f"{TZDATA_EMBED_MARKER_BEGIN}\n"
        "import base64 as _sf_tzdata_base64\n"
        "import io as _sf_tzdata_io\n"
        "from functools import lru_cache as _sf_tzdata_lru_cache\n"
        "from zipfile import ZipFile as _sf_tzdata_ZipFile\n"
        "\n"
        "_EMBEDDED_TZDATA_ZIP_B85 = (\n"
        f"{payload_lines}\n"
        ")\n"
        "\n"
        "@_sf_tzdata_lru_cache(maxsize=1)\n"
        "def _singlefile_tzdata_archive():\n"
        "    payload = _sf_tzdata_base64.b85decode(\"\".join(_EMBEDDED_TZDATA_ZIP_B85).encode(\"ascii\"))\n"
        "    return _sf_tzdata_ZipFile(_sf_tzdata_io.BytesIO(payload))\n"
        "\n"
        "def open_zoneinfo(key):\n"
        "    try:\n"
        "        data = _singlefile_tzdata_archive().read(f\"zoneinfo/{key}\")\n"
        "    except KeyError as exc:\n"
        "        raise FileNotFoundError(key) from exc\n"
        "    return _sf_tzdata_io.BytesIO(data)\n"
        "\n"
        "def available_timezones():\n"
        "    data = _singlefile_tzdata_archive().read(\"zones\").decode(\"utf-8\")\n"
        "    return tuple(zone.strip() for zone in data.splitlines() if zone.strip())\n"
        f"{TZDATA_EMBED_MARKER_END}\n"
    )


def _embed_tzdata_package(context: LibraryHookContext) -> None:
    path = context.source_root / "Lib" / "tzdata" / "__init__.py"
    if not path.exists():
        context.log("skip tzdata embed because Lib/tzdata/__init__.py is missing")
        return

    text = path.read_text(encoding="utf-8")
    text = re.sub(
        rf"\n?{re.escape(TZDATA_EMBED_MARKER_BEGIN)}.*?{re.escape(TZDATA_EMBED_MARKER_END)}\n?",
        "\n",
        text,
        flags=re.DOTALL,
    ).rstrip()
    text = f"{text}\n\n{_render_tzdata_embedded_block(path.parent)}"
    path.write_text(text, encoding="utf-8", newline="\n")


def _patch_zoneinfo_common(context: LibraryHookContext) -> None:
    path = context.source_root / "Lib" / "zoneinfo" / "_common.py"
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n")
    if "return tzdata.open_zoneinfo(key)" in normalized:
        return

    pattern = re.compile(
        r"    except \((?:ImportError, FileNotFoundError, UnicodeEncodeError(?:, IsADirectoryError)?)\):\n"
        r"        # There are (?:three|four) types of exception that can be raised that all amount\n"
        r"        # to \"we cannot find this key\":\n"
        r"        #\n"
        r"        # ImportError: If package_name doesn't exist \(e\.g\. if tzdata is not\n"
        r"        #   installed, or if there's an error in the folder name like\n"
        r"        #   Amrica/New_York\)\n"
        r"        # FileNotFoundError: If resource_name doesn't exist in the package\n"
        r"        #   \(e\.g\. Europe/Krasnoy\)\n"
        r"        # UnicodeEncodeError: If package_name or resource_name are not UTF-8,\n"
        r"        #   such as keys containing a surrogate character\.\n"
        r"(?:        # IsADirectoryError: If package_name without a resource_name specified\.\n)?"
        r"        raise ZoneInfoNotFoundError\(f\"No time zone found with key \{key\}\"\)\n",
        flags=re.DOTALL,
    )
    replacement = (
        "    except (ImportError, FileNotFoundError, UnicodeEncodeError, IsADirectoryError):\n"
        "        # There are four types of exception that can be raised that all amount\n"
        "        # to \"we cannot find this key\":\n"
        "        #\n"
        "        # ImportError: If package_name doesn't exist (e.g. if tzdata is not\n"
        "        #   installed, or if there's an error in the folder name like\n"
        "        #   Amrica/New_York)\n"
        "        # FileNotFoundError: If resource_name doesn't exist in the package\n"
        "        #   (e.g. Europe/Krasnoy)\n"
        "        # UnicodeEncodeError: If package_name or resource_name are not UTF-8,\n"
        "        #   such as keys containing a surrogate character.\n"
        "        # IsADirectoryError: If package_name without a resource_name specified.\n"
        "        try:\n"
        "            import tzdata\n"
        "            return tzdata.open_zoneinfo(key)\n"
        "        except (ImportError, FileNotFoundError, KeyError, AttributeError):\n"
        "            raise ZoneInfoNotFoundError(f\"No time zone found with key {key}\")\n"
    )
    normalized, count = pattern.subn(replacement, normalized, count=1)
    if count != 1:
        raise RuntimeError(f"failed to patch zoneinfo common fallback in {path}")
    path.write_text(normalized, encoding="utf-8", newline="\n")


def _patch_zoneinfo_tzpath(context: LibraryHookContext) -> None:
    path = context.source_root / "Lib" / "zoneinfo" / "_tzpath.py"
    if not path.exists():
        return

    text = path.read_text(encoding="utf-8")
    normalized = text.replace("\r\n", "\n")
    if "valid_zones.update(tzdata.available_timezones())" in normalized:
        return

    replacement = (
        "    try:\n"
        "        with resources.files(\"tzdata\").joinpath(\"zones\").open(\"r\", encoding=\"utf-8\") as f:\n"
        "            for zone in f:\n"
        "                zone = zone.strip()\n"
        "                if zone:\n"
        "                    valid_zones.add(zone)\n"
        "    except (ImportError, FileNotFoundError):\n"
        "        try:\n"
        "            import tzdata\n"
        "            valid_zones.update(tzdata.available_timezones())\n"
        "        except (ImportError, AttributeError, FileNotFoundError, KeyError):\n"
        "            pass\n"
    )
    old_variants = [
        (
            "    try:\n"
            "        zones_file = resources.files(\"tzdata\").joinpath(\"zones\")\n"
            "        with zones_file.open(\"r\", encoding=\"utf-8\") as f:\n"
            "            for zone in f:\n"
            "                zone = zone.strip()\n"
            "                if zone:\n"
            "                    valid_zones.add(zone)\n"
            "    except (ImportError, FileNotFoundError):\n"
            "        pass\n"
        ),
        (
            "    try:\n"
            "        with resources.files(\"tzdata\").joinpath(\"zones\").open(\"r\") as f:\n"
            "            for zone in f:\n"
            "                zone = zone.strip()\n"
            "                if zone:\n"
            "                    valid_zones.add(zone)\n"
            "    except (ImportError, FileNotFoundError):\n"
            "        pass\n"
        ),
        (
            "    try:\n"
            "        zones_file = resources.files(\"tzdata\").joinpath(\"zones\")\n"
            "        with zones_file.open(\"r\") as f:\n"
            "            for zone in f:\n"
            "                zone = zone.strip()\n"
            "                if zone:\n"
            "                    valid_zones.add(zone)\n"
            "    except (ImportError, FileNotFoundError):\n"
            "        pass\n"
        ),
        (
            "    try:\n"
            "        with resources.files(\"tzdata\").joinpath(\"zones\").open(\"r\", encoding=\"utf-8\") as f:\n"
            "            for zone in f:\n"
            "                zone = zone.strip()\n"
            "                if zone:\n"
            "                    valid_zones.add(zone)\n"
            "    except (ImportError, FileNotFoundError):\n"
            "        pass\n"
        ),
    ]
    for old in old_variants:
        if old in normalized:
            normalized = normalized.replace(old, replacement, 1)
            break
    else:
        raise RuntimeError(f"failed to patch zoneinfo tzpath fallback in {path}")
    path.write_text(normalized, encoding="utf-8", newline="\n")


def apply_tzdata_singlefile_support(context: LibraryHookContext) -> None:
    _embed_tzdata_package(context)
    _patch_zoneinfo_common(context)
    _patch_zoneinfo_tzpath(context)


LIBRARY_INTEGRATION = pypi_library(
    name="tzdata",
    source_entries=["tzdata"],
    python_packages=[
        "tzdata",
    ],
    post_patch_hooks=[
        apply_tzdata_singlefile_support,
    ],
)
