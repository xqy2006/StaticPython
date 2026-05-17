import re

from libs import (
    replace_regex_once,
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


def patch_chardet_sources(context) -> None:
    models_path = source_path(context, "Lib/chardet/models/models.bin")
    idf_path = source_path(context, "Lib/chardet/models/idf.bin")
    confusion_path = source_path(context, "Lib/chardet/models/confusion.bin")

    if not models_path.exists():
        return

    models_bin = models_path.read_bytes()
    idf_bin = idf_path.read_bytes() if idf_path.exists() else None
    confusion_bin = confusion_path.read_bytes() if confusion_path.exists() else None

    def patch_models(text: str) -> str:
        constants = "_STATICPYTHON_MODELS_BIN = " + _bytes_chunks_literal(models_bin) + "\n\n"
        if idf_bin is not None:
            constants += "_STATICPYTHON_IDF_BIN = " + _bytes_chunks_literal(idf_bin) + "\n\n"
        if "_STATICPYTHON_MODELS_BIN" not in text:
            if '_V2_MAGIC = b"CMD2"\n\n' in text:
                text = replace_text_once(
                    text,
                    '_V2_MAGIC = b"CMD2"\n\n',
                    '_V2_MAGIC = b"CMD2"\n\n' + constants,
                    label="chardet embedded model resources",
                )
            else:
                updated, count = re.subn(
                    r"(?m)^(?P<anchor>NON_ASCII_BIGRAM_WEIGHT[^\n]*\n(?:#.*\n)*)",
                    lambda match: match.group("anchor") + "\n" + constants,
                    text,
                    count=1,
                )
                if count != 1:
                    raise RuntimeError("expected anchor not found in chardet embedded model resources")
                text = updated
        text = replace_regex_once(
            text,
            r'(?m)^(?P<indent>[ \t]*)ref = importlib\.resources\.files\("chardet\.models"\)\.joinpath\("models\.bin"\)\n(?P=indent)data = ref\.read_bytes\(\)\n',
            "\\g<indent>data = _STATICPYTHON_MODELS_BIN\n",
            label="chardet models.bin loader",
        )
        if idf_bin is None:
            return text
        return replace_regex_once(
            text,
            r'(?m)^(?P<indent>[ \t]*)ref = importlib\.resources\.files\("chardet\.models"\)\.joinpath\("idf\.bin"\)\n(?P=indent)data = ref\.read_bytes\(\)\n',
            "\\g<indent>data = _STATICPYTHON_IDF_BIN\n",
            label="chardet idf.bin loader",
        )

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
        return replace_regex_once(
            text,
            r'(?m)^(?P<indent>[ \t]*)ref = importlib\.resources\.files\("chardet\.models"\)\.joinpath\("confusion\.bin"\)\n(?P=indent)raw = ref\.read_bytes\(\)\n',
            "\\g<indent>raw = _STATICPYTHON_CONFUSION_BIN\n",
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
