from libs import replace_text_all, simple_library, source_path, transform_first_existing_source_text


def normalize_pyparsing_source(context) -> None:
    package_root = source_path(context, "Lib/pyparsing")
    init_py = package_root / "__init__.py"
    legacy_py3 = source_path(context, "Lib/pyparsing_py3.py")

    if package_root.is_file():
        text = package_root.read_text(encoding="utf-8")
        package_root.unlink()
        package_root.mkdir(parents=True, exist_ok=True)
        init_py.write_text(text, encoding="utf-8", newline="\n")
        context.log("normalized legacy pyparsing.py module into Lib/pyparsing/__init__.py")
        return

    if package_root.is_dir():
        if not init_py.exists() and legacy_py3.exists():
            text = legacy_py3.read_text(encoding="utf-8")
            init_py.write_text(text, encoding="utf-8", newline="\n")
            context.log("restored missing Lib/pyparsing/__init__.py from legacy pyparsing_py3.py")
        return

    if legacy_py3.exists():
        package_root.mkdir(parents=True, exist_ok=True)
        text = legacy_py3.read_text(encoding="utf-8")
        init_py.write_text(text, encoding="utf-8", newline="\n")
        context.log("materialized legacy pyparsing_py3.py into Lib/pyparsing/__init__.py")


def patch_pyparsing_unicode_identifiers(context) -> None:
    def patch(text: str) -> str:
        replacements = [
            (
                "    \u0627\u0644\u0639\u0631\u0628\u064a\u0629 = Arabic\n",
                '    locals()["\\u0627\\u0644\\u0639\\u0631\\u0628\\u064a\\u0629"] = Arabic\n',
            ),
            (
                "    \u4e2d\u6587 = Chinese\n",
                '    locals()["\\u4e2d\\u6587"] = Chinese\n',
            ),
            (
                "    \u043a\u0438\u0440\u0438\u043b\u043b\u0438\u0446\u0430 = Cyrillic\n",
                '    locals()["\\u043a\\u0438\\u0440\\u0438\\u043b\\u043b\\u0438\\u0446\\u0430"] = Cyrillic\n',
            ),
            (
                "    \u0395\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac = Greek\n",
                '    locals()["\\u0395\\u03bb\\u03bb\\u03b7\\u03bd\\u03b9\\u03ba\\u03ac"] = Greek\n',
            ),
            (
                "    \u05e2\u05b4\u05d1\u05e8\u05b4\u05d9\u05ea = Hebrew\n",
                '    locals()["\\u05e2\\u05b4\\u05d1\\u05e8\\u05b4\\u05d9\\u05ea"] = Hebrew\n',
            ),
            (
                "    \u65e5\u672c\u8a9e = Japanese\n",
                '    locals()["\\u65e5\\u672c\\u8a9e"] = Japanese\n',
            ),
            (
                "    \ud55c\uad6d\uc5b4 = Korean\n",
                '    locals()["\\ud55c\\uad6d\\uc5b4"] = Korean\n',
            ),
            (
                "    \u0e44\u0e17\u0e22 = Thai\n",
                '    locals()["\\u0e44\\u0e17\\u0e22"] = Thai\n',
            ),
            (
                "    \u0926\u0947\u0935\u0928\u093e\u0917\u0930\u0940 = Devanagari\n",
                '    locals()["\\u0926\\u0947\\u0935\\u0928\\u093e\\u0917\\u0930\\u0940"] = Devanagari\n',
            ),
            (
                "        \u6f22\u5b57 = Kanji\n",
                '        locals()["\\u6f22\\u5b57"] = Kanji\n',
            ),
            (
                "        \u30ab\u30bf\u30ab\u30ca = Katakana\n",
                '        locals()["\\u30ab\\u30bf\\u30ab\\u30ca"] = Katakana\n',
            ),
            (
                "        \u3072\u3089\u304c\u306a = Hiragana\n",
                '        locals()["\\u3072\\u3089\\u304c\\u306a"] = Hiragana\n',
            ),
            (
                "pyparsing_unicode.\u0627\u0644\u0639\u0631\u0628\u064a\u0629 = pyparsing_unicode.Arabic\n",
                'setattr(pyparsing_unicode, "\\u0627\\u0644\\u0639\\u0631\\u0628\\u064a\\u0629", pyparsing_unicode.Arabic)\n',
            ),
            (
                "pyparsing_unicode.\u4e2d\u6587 = pyparsing_unicode.Chinese\n",
                'setattr(pyparsing_unicode, "\\u4e2d\\u6587", pyparsing_unicode.Chinese)\n',
            ),
            (
                "pyparsing_unicode.\u043a\u0438\u0440\u0438\u043b\u043b\u0438\u0446\u0430 = pyparsing_unicode.Cyrillic\n",
                'setattr(pyparsing_unicode, "\\u043a\\u0438\\u0440\\u0438\\u043b\\u043b\\u0438\\u0446\\u0430", pyparsing_unicode.Cyrillic)\n',
            ),
            (
                "pyparsing_unicode.\u0395\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac = pyparsing_unicode.Greek\n",
                'setattr(pyparsing_unicode, "\\u0395\\u03bb\\u03bb\\u03b7\\u03bd\\u03b9\\u03ba\\u03ac", pyparsing_unicode.Greek)\n',
            ),
            (
                "pyparsing_unicode.\u05e2\u05b4\u05d1\u05e8\u05b4\u05d9\u05ea = pyparsing_unicode.Hebrew\n",
                'setattr(pyparsing_unicode, "\\u05e2\\u05b4\\u05d1\\u05e8\\u05b4\\u05d9\\u05ea", pyparsing_unicode.Hebrew)\n',
            ),
            (
                "pyparsing_unicode.\u65e5\u672c\u8a9e = pyparsing_unicode.Japanese\n",
                'setattr(pyparsing_unicode, "\\u65e5\\u672c\\u8a9e", pyparsing_unicode.Japanese)\n',
            ),
            (
                "pyparsing_unicode.Japanese.\u6f22\u5b57 = pyparsing_unicode.Japanese.Kanji\n",
                'setattr(pyparsing_unicode.Japanese, "\\u6f22\\u5b57", pyparsing_unicode.Japanese.Kanji)\n',
            ),
            (
                "pyparsing_unicode.Japanese.\u30ab\u30bf\u30ab\u30ca = pyparsing_unicode.Japanese.Katakana\n",
                'setattr(pyparsing_unicode.Japanese, "\\u30ab\\u30bf\\u30ab\\u30ca", pyparsing_unicode.Japanese.Katakana)\n',
            ),
            (
                "pyparsing_unicode.Japanese.\u3072\u3089\u304c\u306a = pyparsing_unicode.Japanese.Hiragana\n",
                'setattr(pyparsing_unicode.Japanese, "\\u3072\\u3089\\u304c\\u306a", pyparsing_unicode.Japanese.Hiragana)\n',
            ),
            (
                "pyparsing_unicode.\ud55c\uad6d\uc5b4 = pyparsing_unicode.Korean\n",
                'setattr(pyparsing_unicode, "\\ud55c\\uad6d\\uc5b4", pyparsing_unicode.Korean)\n',
            ),
            (
                "pyparsing_unicode.\u0e44\u0e17\u0e22 = pyparsing_unicode.Thai\n",
                'setattr(pyparsing_unicode, "\\u0e44\\u0e17\\u0e22", pyparsing_unicode.Thai)\n',
            ),
            (
                "pyparsing_unicode.\u0926\u0947\u0935\u0928\u093e\u0917\u0930\u0940 = pyparsing_unicode.Devanagari\n",
                'setattr(pyparsing_unicode, "\\u0926\\u0947\\u0935\\u0928\\u093e\\u0917\\u0930\\u0940", pyparsing_unicode.Devanagari)\n',
            ),
        ]
        for old, new in replacements:
            text = replace_text_all(text, old, new)
        remaining = [old.strip() for old, _new in replacements if old in text]
        if remaining:
            raise RuntimeError("pyparsing unicode identifier anchor not patched: " + ", ".join(remaining[:3]))
        return text

    transform_first_existing_source_text(
        context,
        [
            "Lib/pyparsing/unicode.py",
            "Lib/pyparsing/__init__.py",
        ],
        patch,
        allow_all_missing=True,
    )


LIBRARY_INTEGRATION = simple_library(
    name="pyparsing",
    source_mapping={
        "?pyparsing": "Lib/pyparsing",
        "?pyparsing_py3.py": "Lib/pyparsing_py3.py",
    },
    materialized_paths=["Lib/pyparsing"],
    prepare_source_hooks=[normalize_pyparsing_source],
    post_patch_hooks=[patch_pyparsing_unicode_identifiers],
)
