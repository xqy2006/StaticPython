from libs import inline_verification_step, replace_text_once, simple_library, transform_source_text


def patch_jedi_sources(context) -> None:
    def patch_environment(text: str) -> str:
        helper = (
            "\n\n"
            "def _staticpython_should_use_same_process_environment() -> bool:\n"
            "    return bool(getattr(sys, \"_staticpython\", False))\n"
        )
        text = replace_text_once(
            text,
            "_CURRENT_VERSION = '%s.%s' % (sys.version_info.major, sys.version_info.minor)\n",
            "_CURRENT_VERSION = '%s.%s' % (sys.version_info.major, sys.version_info.minor)\n" + helper,
            label="jedi staticpython same-process helper",
        )
        return replace_text_once(
            text,
            "def _try_get_same_env():\n"
            "    env = SameEnvironment()\n",
            "def _try_get_same_env():\n"
            "    if _staticpython_should_use_same_process_environment():\n"
            "        return InterpreterEnvironment()\n"
            "    env = SameEnvironment()\n",
            label="jedi staticpython same-process environment",
        )

    transform_source_text(context, "Lib/jedi/api/environment.py", patch_environment)


LIBRARY_INTEGRATION = simple_library(
    name="jedi",
    overlay_entries=["Lib/jedi"],
    post_patch_hooks=[patch_jedi_sources],
    verification_steps=[
        inline_verification_step(
            "jedi-smoke",
            """
import jedi

script = jedi.Script("import math\\nmath.sq")
completions = script.complete(2, 7)
names = {item.name for item in completions}
assert "sqrt" in names
inferred = jedi.Script("value = 42\\nvalue").infer(2, 5)
assert inferred and inferred[0].name == "int"
""",
        )
    ],
)
