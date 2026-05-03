from libs import replace_text_once, simple_library, transform_source_text


def patch_pyparsing_unicode_identifiers(context) -> None:
    def patch(text: str) -> str:
        text = replace_text_once(
            text,
            (
                "        \u6f22\u5b57 = Kanji\n"
                "        \u30ab\u30bf\u30ab\u30ca = Katakana\n"
                "        \u3072\u3089\u304c\u306a = Hiragana\n"
            ),
            (
                '        locals()["\\u6f22\\u5b57"] = Kanji\n'
                '        locals()["\\u30ab\\u30bf\\u30ab\\u30ca"] = Katakana\n'
                '        locals()["\\u3072\\u3089\\u304c\\u306a"] = Hiragana\n'
            ),
            label="pyparsing unicode Japanese aliases",
        )
        return replace_text_once(
            text,
            (
                "    \u0627\u0644\u0639\u0631\u0628\u064a\u0629 = Arabic\n"
                "    \u4e2d\u6587 = Chinese\n"
                "    \u043a\u0438\u0440\u0438\u043b\u043b\u0438\u0446\u0430 = Cyrillic\n"
                "    \u0395\u03bb\u03bb\u03b7\u03bd\u03b9\u03ba\u03ac = Greek\n"
                "    \u05e2\u05b4\u05d1\u05e8\u05b4\u05d9\u05ea = Hebrew\n"
                "    \u65e5\u672c\u8a9e = Japanese\n"
                "    \ud55c\uad6d\uc5b4 = Korean\n"
                "    \u0e44\u0e17\u0e22 = Thai\n"
                "    \u0926\u0947\u0935\u0928\u093e\u0917\u0930\u0940 = Devanagari\n"
            ),
            (
                '    locals()["\\u0627\\u0644\\u0639\\u0631\\u0628\\u064a\\u0629"] = Arabic\n'
                '    locals()["\\u4e2d\\u6587"] = Chinese\n'
                '    locals()["\\u043a\\u0438\\u0440\\u0438\\u043b\\u043b\\u0438\\u0446\\u0430"] = Cyrillic\n'
                '    locals()["\\u0395\\u03bb\\u03bb\\u03b7\\u03bd\\u03b9\\u03ba\\u03ac"] = Greek\n'
                '    locals()["\\u05e2\\u05b4\\u05d1\\u05e8\\u05b4\\u05d9\\u05ea"] = Hebrew\n'
                '    locals()["\\u65e5\\u672c\\u8a9e"] = Japanese\n'
                '    locals()["\\ud55c\\uad6d\\uc5b4"] = Korean\n'
                '    locals()["\\u0e44\\u0e17\\u0e22"] = Thai\n'
                '    locals()["\\u0926\\u0947\\u0935\\u0928\\u093e\\u0917\\u0930\\u0940"] = Devanagari\n'
            ),
            label="pyparsing unicode language aliases",
        )

    transform_source_text(context, "Lib/pyparsing/unicode.py", patch)


LIBRARY_INTEGRATION = simple_library(
    name="pyparsing",
    overlay_entries=["Lib/pyparsing"],
    post_patch_hooks=[patch_pyparsing_unicode_identifiers],
)
