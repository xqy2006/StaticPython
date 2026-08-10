import re

from libs import (
    replace_text_once,
    simple_library,
    source_path,
    transform_source_text,
)


def _bytes_chunks_literal(data: bytes, *, chunk_size: int = 8192) -> str:
    chunks = [data[index : index + chunk_size] for index in range(0, len(data), chunk_size)]
    if not chunks:
        return "b''"
    lines = ["("]
    lines.extend(f"    {chunk!r}" for chunk in chunks)
    lines.append(")")
    return "\n".join(lines)


def _insert_embedded_model_resources(
    text: str,
    resources: list[tuple[str, bytes]],
) -> str:
    markers = [f"{name} = " for name, _data in resources]
    present = [marker in text for marker in markers]
    if any(present):
        if not all(present):
            raise RuntimeError("partially patched chardet embedded model resources")
        return text

    constants = "".join(
        f"{name} = {_bytes_chunks_literal(data)}\n\n" for name, data in resources
    )
    anchors = (
        r'(?m)^_V2_MAGIC = b"CMD2"\n',
        r"(?m)^NON_ASCII_BIGRAM_WEIGHT[^\n]*\n(?:#[^\n]*\n)*",
    )
    for pattern in anchors:
        matches = list(re.finditer(pattern, text))
        if len(matches) > 1:
            raise RuntimeError(
                "expected exactly one anchor in chardet embedded model resources; "
                f"found {len(matches)} for {pattern}"
            )
        if len(matches) == 1:
            match = matches[0]
            return text[: match.end()] + constants + text[match.end() :]
    raise RuntimeError("expected anchor not found in chardet embedded model resources")


def _replace_resource_loader(
    text: str,
    *,
    package: str,
    filename: str,
    target: str,
    constant: str,
    label: str,
) -> str:
    original_pattern = (
        rf'(?m)^(?P<indent>[ \t]*)ref = importlib\.resources\.files\("{re.escape(package)}"\)'
        rf'\.joinpath\("{re.escape(filename)}"\)\n'
        rf'(?P=indent){re.escape(target)} = ref\.read_bytes\(\)\n'
    )
    patched_pattern = rf"(?m)^[ \t]*{re.escape(target)} = {re.escape(constant)}\n"
    original_matches = list(re.finditer(original_pattern, text))
    patched_matches = list(re.finditer(patched_pattern, text))
    if len(patched_matches) == 1 and not original_matches:
        return text
    if len(original_matches) != 1 or patched_matches:
        raise RuntimeError(
            f"expected exactly one {label}; found "
            f"{len(original_matches)} original and {len(patched_matches)} patched"
        )
    match = original_matches[0]
    indent = match.group("indent")
    return text[: match.start()] + f"{indent}{target} = {constant}\n" + text[match.end() :]


def _replace_rowmax_loader(text: str) -> str:
    original = (
        '    files = importlib.resources.files("chardet.models")\n'
        "    try:\n"
        '        data = files.joinpath("rowmax.bin").read_bytes()\n'
        "        models_digest = hashlib.sha256(\n"
        '            files.joinpath("models.bin").read_bytes()\n'
        "        ).digest()\n"
    )
    patched = (
        "    try:\n"
        "        data = _STATICPYTHON_ROWMAX_BIN\n"
        "        models_digest = hashlib.sha256(_STATICPYTHON_MODELS_BIN).digest()\n"
    )
    patched_count = text.count(patched)
    original_count = text.count(original)
    if patched_count == 1 and original_count == 0:
        return text
    if original_count != 1 or patched_count:
        raise RuntimeError(
            "expected exactly one chardet rowmax.bin loader; found "
            f"{original_count} original and {patched_count} patched"
        )
    return text.replace(original, patched, 1)


def patch_chardet_sources(context) -> None:
    models_path = source_path(context, "Lib/chardet/models/models.bin")
    idf_path = source_path(context, "Lib/chardet/models/idf.bin")
    rowmax_path = source_path(context, "Lib/chardet/models/rowmax.bin")
    confusion_path = source_path(context, "Lib/chardet/models/confusion.bin")

    if not models_path.exists():
        return

    models_bin = models_path.read_bytes()
    idf_bin = idf_path.read_bytes() if idf_path.exists() else None
    rowmax_bin = rowmax_path.read_bytes() if rowmax_path.exists() else None
    confusion_bin = confusion_path.read_bytes() if confusion_path.exists() else None

    def patch_models(text: str) -> str:
        resources = [("_STATICPYTHON_MODELS_BIN", models_bin)]
        if idf_bin is not None:
            resources.append(("_STATICPYTHON_IDF_BIN", idf_bin))
        if rowmax_bin is not None:
            resources.append(("_STATICPYTHON_ROWMAX_BIN", rowmax_bin))
        text = _insert_embedded_model_resources(text, resources)
        text = _replace_resource_loader(
            text,
            package="chardet.models",
            filename="models.bin",
            target="data",
            constant="_STATICPYTHON_MODELS_BIN",
            label="chardet models.bin loader",
        )
        if idf_bin is not None:
            text = _replace_resource_loader(
                text,
                package="chardet.models",
                filename="idf.bin",
                target="data",
                constant="_STATICPYTHON_IDF_BIN",
                label="chardet idf.bin loader",
            )
        if rowmax_bin is not None:
            text = _replace_rowmax_loader(text)
        elif 'joinpath("rowmax.bin")' in text:
            raise RuntimeError("chardet rowmax.bin loader has no matching source resource")
        return text

    def patch_confusion(text: str) -> str:
        if confusion_bin is None:
            return text
        text = replace_text_once(
            text,
            "DistinguishingMaps = dict[\n",
            (
                "_STATICPYTHON_CONFUSION_BIN = "
                + _bytes_chunks_literal(confusion_bin)
                + "\n\nDistinguishingMaps = dict[\n"
            ),
            label="chardet embedded confusion resource",
        )
        return _replace_resource_loader(
            text,
            package="chardet.models",
            filename="confusion.bin",
            target="raw",
            constant="_STATICPYTHON_CONFUSION_BIN",
            label="chardet confusion.bin loader",
        )

    transform_source_text(context, "Lib/chardet/models/__init__.py", patch_models)
    if confusion_bin is not None:
        transform_source_text(context, "Lib/chardet/pipeline/confusion.py", patch_confusion, allow_missing=True)


LIBRARY_INTEGRATION = simple_library(
    name="chardet",
    overlay_entries=["Lib/chardet"],
    post_patch_hooks=[patch_chardet_sources],
)
