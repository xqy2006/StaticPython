from libs import (
    replace_function_block_once,
    replace_regex_once,
    replace_text_once,
    simple_library,
    source_path,
    transform_source_text,
)


def patch_lark_sources(context) -> None:
    grammar_root = source_path(context, "Lib/lark/grammars")
    if not grammar_root.exists():
        return
    embedded_grammars = {
        grammar_path.name: grammar_path.read_text(encoding="utf-8")
        for grammar_path in sorted(grammar_root.glob("*.lark"))
    }
    if not embedded_grammars:
        return

    def patch_load_grammar(text: str) -> str:
        if "_STATICPYTHON_EMBEDDED_GRAMMARS" not in text:
            anchor = "EXT = '.lark'\n"
            if anchor not in text:
                anchor = 'EXT = ".lark"\n'
            if anchor not in text:
                raise RuntimeError("expected lark IMPORT_PATHS/EXT block")
            text = text.replace(
                anchor,
                f"_STATICPYTHON_EMBEDDED_GRAMMARS = {embedded_grammars!r}\n\n{anchor}",
                1,
            )

        if "pkgutil.get_data" in text:
            replacement = """def __call__(self, base_path, grammar_path):
        if base_path is None:
            to_try = self.search_paths
        else:
            # Check whether or not the importing grammar was loaded by this module.
            if not isinstance(base_path, PackageResource) or base_path.pkg_name != self.pkg_name:
                # Technically false, but FileNotFound doesn't exist in python2.7, and this message should never reach the end user anyway
                raise IOError()
            to_try = [base_path.path]
        for path in to_try:
            full_path = os.path.join(path, grammar_path)
            embedded_key = full_path.replace('\\\\', '/')
            embedded_name = os.path.basename(embedded_key)
            embedded_text = _STATICPYTHON_EMBEDDED_GRAMMARS.get(embedded_key)
            if embedded_text is None:
                embedded_text = _STATICPYTHON_EMBEDDED_GRAMMARS.get(embedded_name)
            if embedded_text is not None:
                return PackageResource(self.pkg_name, full_path), embedded_text
            try:
                text = pkgutil.get_data(self.pkg_name, full_path)
            except IOError:
                continue
            else:
                return PackageResource(self.pkg_name, full_path), text.decode()
        raise IOError()
"""
            return replace_function_block_once(
                text,
                "__call__",
                replacement,
                label="lark package-resource loader block",
            )

        if "def import_grammar(" in text and "embedded_key = joined_path.replace('\\\\', '/')" not in text:
            return replace_function_block_once(
                text,
                "import_grammar",
                """def import_grammar(self, grammar_path, base_paths=[]):
        if grammar_path not in _imported_grammars:
            import_paths = base_paths + IMPORT_PATHS
            for import_path in import_paths:
                with suppress(IOError):
                    joined_path = os.path.join(import_path, grammar_path)
                    embedded_key = joined_path.replace('\\\\', '/')
                    embedded_name = os.path.basename(embedded_key)
                    text = _STATICPYTHON_EMBEDDED_GRAMMARS.get(embedded_key)
                    if text is None:
                        text = _STATICPYTHON_EMBEDDED_GRAMMARS.get(embedded_name)
                    if text is None:
                        with open(joined_path, encoding='utf8') as f:
                            text = f.read()
                    grammar = self.load_grammar(text, joined_path)
                    _imported_grammars[grammar_path] = grammar
                    break
            else:
                open(grammar_path, encoding='utf8') # Force a file not found error
                assert False

        return _imported_grammars[grammar_path]

""",
                label="lark filesystem grammar loader block",
                next_name="load_grammar",
            )

        return replace_regex_once(
            text,
            r"(?ms)^        for import_path in import_paths:\n(?:            .*\n)+?                break\n",
            """        for import_path in import_paths:
            with suppress(IOError):
                joined_path = os.path.join(import_path, grammar_path)
                embedded_key = joined_path.replace('\\\\', '/')
                embedded_name = os.path.basename(embedded_key)
                text = _STATICPYTHON_EMBEDDED_GRAMMARS.get(embedded_key)
                if text is None:
                    text = _STATICPYTHON_EMBEDDED_GRAMMARS.get(embedded_name)
                if text is None:
                    with open(joined_path, encoding='utf8') as f:
                        text = f.read()
                grammar = self.load_grammar(text, joined_path)
                _imported_grammars[grammar_path] = grammar
                break
""",
            label="lark filesystem grammar loader block",
        )

    transform_source_text(context, "Lib/lark/load_grammar.py", patch_load_grammar)


LIBRARY_INTEGRATION = simple_library(
    name="lark",
    overlay_entries=["Lib/lark"],
    post_patch_hooks=[patch_lark_sources],
)
