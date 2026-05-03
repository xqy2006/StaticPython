from libs import replace_text_once, simple_library, source_path, transform_source_text


def patch_lark_sources(context) -> None:
    grammar_root = source_path(context, "Lib/lark/grammars")
    embedded_grammars = {
        f"grammars/{grammar_path.name}": grammar_path.read_text(encoding="utf-8")
        for grammar_path in sorted(grammar_root.glob("*.lark"))
    }

    def patch_load_grammar(text: str) -> str:
        text = replace_text_once(
            text,
            "IMPORT_PATHS = ['grammars']\n\nEXT = '.lark'\n",
            (
                "IMPORT_PATHS = ['grammars']\n\n"
                f"_STATICPYTHON_EMBEDDED_GRAMMARS = {embedded_grammars!r}\n\n"
                "EXT = '.lark'\n"
            ),
            label="lark embedded grammar table",
        )
        return replace_text_once(
            text,
            (
                "            full_path = os.path.join(path, grammar_path)\n"
                "            try:\n"
                "                text: Optional[bytes] = pkgutil.get_data(self.pkg_name, full_path)\n"
            ),
            (
                "            full_path = os.path.join(path, grammar_path)\n"
                "            embedded_text = _STATICPYTHON_EMBEDDED_GRAMMARS.get(full_path.replace('\\\\', '/'))\n"
                "            if embedded_text is not None:\n"
                "                return PackageResource(self.pkg_name, full_path), embedded_text\n"
                "            try:\n"
                "                text: Optional[bytes] = pkgutil.get_data(self.pkg_name, full_path)\n"
            ),
            label="lark embedded grammar loader fallback",
        )

    transform_source_text(context, "Lib/lark/load_grammar.py", patch_load_grammar)


LIBRARY_INTEGRATION = simple_library(
    name="lark",
    overlay_entries=["Lib/lark"],
    post_patch_hooks=[patch_lark_sources],
)
