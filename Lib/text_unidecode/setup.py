from libs import replace_text_once, simple_library, source_path, transform_source_text


def _bytes_chunks_literal(data: bytes, *, chunk_size: int = 8192) -> str:
    chunks = [data[index : index + chunk_size] for index in range(0, len(data), chunk_size)]
    if not chunks:
        return "b''"
    lines = ["("]
    lines.extend(f"    {chunk!r}" for chunk in chunks)
    lines.append(")")
    return "\n".join(lines)


def patch_text_unidecode_sources(context) -> None:
    data_bin = source_path(context, "Lib/text_unidecode/data.bin").read_bytes()

    def patch_init(text: str) -> str:
        text = replace_text_once(
            text,
            "import pkgutil\n\n",
            (
                "import pkgutil\n\n"
                "_STATICPYTHON_TEXT_UNIDECODE_DATA = "
                + _bytes_chunks_literal(data_bin)
                + "\n\n"
            ),
            label="text_unidecode embedded data resource",
        )
        return replace_text_once(
            text,
            "_replaces = pkgutil.get_data(__name__, 'data.bin').decode('utf8').split('\\x00')\n",
            "_replaces = _STATICPYTHON_TEXT_UNIDECODE_DATA.decode('utf8').split('\\x00')\n",
            label="text_unidecode data.bin loader",
        )

    transform_source_text(context, "Lib/text_unidecode/__init__.py", patch_init)


LIBRARY_INTEGRATION = simple_library(
    name="text_unidecode",
    project_name="text-unidecode",
    overlay_entries=["Lib/text_unidecode"],
    post_patch_hooks=[patch_text_unidecode_sources],
)
