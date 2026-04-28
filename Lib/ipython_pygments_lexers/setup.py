from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="ipython_pygments_lexers",
    project_name="ipython-pygments-lexers",
    source_mapping={"ipython_pygments_lexers.py": "Lib/ipython_pygments_lexers.py"},
    verification_steps=[
        inline_verification_step(
            "ipython-pygments-lexers-smoke",
            """
from pygments import lex
from ipython_pygments_lexers import IPythonConsoleLexer

tokens = list(lex("In [1]: 1 + 1\\n", IPythonConsoleLexer()))
assert tokens
assert any("In [1]" in value for _, value in tokens)
""",
        )
    ],
)
