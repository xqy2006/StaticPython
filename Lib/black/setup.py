from libs import inline_verification_step, replace_text_once, simple_library, transform_source_text


def patch_black_sources(context) -> None:
    def patch_linegen(text: str) -> str:
        text = replace_text_once(
            text,
            "        \u00d8: set[str] = set()\n",
            "        _empty_parens: set[str] = set()\n",
            label="black linegen ascii empty parens name",
        )
        return text.replace("parens=\u00d8", "parens=_empty_parens").replace(
            "keywords=\u00d8", "keywords=_empty_parens"
        )

    transform_source_text(context, "Lib/black/linegen.py", patch_linegen)


LIBRARY_INTEGRATION = simple_library(
    name="black",
    dependencies=["aiohttp"],
    source_mapping={
        "_black_version.py": "Lib/_black_version.py",
        "black": "Lib/black",
        "blackd": "Lib/blackd",
        "blib2to3": "Lib/blib2to3",
    },
    runtime_resource_paths=[
        "Lib/blib2to3/Grammar.txt",
        "Lib/blib2to3/PatternGrammar.txt",
    ],
    python_packages=["black", "blackd", "blib2to3"],
    post_patch_hooks=[patch_black_sources],
    verification_steps=[
        inline_verification_step(
            "black-smoke",
            """
import black

source = "def add(a,b):\\n return a+b\\n"
formatted = black.format_str(source, mode=black.FileMode())
assert "def add(a, b):" in formatted
assert "return a + b" in formatted
""",
        )
        ,
        inline_verification_step(
            "blackd-smoke",
            """
import blackd

app = blackd.make_app()
assert app is not None
assert len(app.router.routes()) == 1
""",
        )
    ],
)
