from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='pygments',
    overlay_entries=['Lib/pygments'],
    verification_steps=[
        inline_verification_step(
            "pygments-smoke",
            """
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer, get_lexer_by_name

html = highlight("print('x')\\n", PythonLexer(), HtmlFormatter())
assert "highlight" in html and "print" in html
assert get_lexer_by_name("python").name == "Python"
""",
        )
    ],
)
