from libs import inline_verification_step, replace_text_once, simple_library, transform_source_text


def _patch_prompt_toolkit_init(text: str) -> str:
    old = '__version__ = metadata.version("prompt_toolkit")\n'
    new = (
        "try:\n"
        '    __version__ = metadata.version("prompt_toolkit")\n'
        "except metadata.PackageNotFoundError:\n"
        '    __version__ = "3.0.52"\n'
    )
    return replace_text_once(text, old, new, label="prompt_toolkit.__init__")


def _patch_prompt_toolkit_application(text: str) -> str:
    old = (
        "        # GraalPy has the functions, but they don't work\n"
        '        have_ctypes_signal = sys.implementation.name != "graalpy"\n'
    )
    new = (
        "        # GraalPy has the functions, but they don't work\n"
        '        have_ctypes_signal = sys.implementation.name != "graalpy"\n'
        "        if have_ctypes_signal:\n"
        "            try:\n"
        "                pythonapi.PyOS_getsig\n"
        "                pythonapi.PyOS_setsig\n"
        "            except AttributeError:\n"
        "                have_ctypes_signal = False\n"
    )
    return replace_text_once(text, old, new, label="prompt_toolkit.application.application")


def patch_prompt_toolkit_sources(context) -> None:
    transform_source_text(context, "Lib/prompt_toolkit/__init__.py", _patch_prompt_toolkit_init)
    transform_source_text(
        context,
        "Lib/prompt_toolkit/application/application.py",
        _patch_prompt_toolkit_application,
    )


LIBRARY_INTEGRATION = simple_library(
    name='prompt_toolkit',
    overlay_entries=['Lib/prompt_toolkit'],
    post_patch_hooks=[patch_prompt_toolkit_sources],
    verification_steps=[
        inline_verification_step(
            "prompt-toolkit-smoke",
            """
from prompt_toolkit.document import Document
from prompt_toolkit.formatted_text import HTML, to_formatted_text
from prompt_toolkit.validation import ValidationError, Validator

text = Document("hello world", cursor_position=5)
assert text.current_line_before_cursor == "hello"
assert to_formatted_text(HTML("<b>demo</b>"))[0][1] == "demo"
class NonEmpty(Validator):
    def validate(self, document):
        if not document.text:
            raise ValidationError(message="empty")
NonEmpty().validate(Document("x"))
""",
        )
    ],
)
