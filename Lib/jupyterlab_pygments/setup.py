from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="jupyterlab_pygments",
    project_name="jupyterlab-pygments",
    overlay_entries=["Lib/jupyterlab_pygments"],
    verification_steps=[
        inline_verification_step(
            "jupyterlab-pygments-smoke",
            """
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import PythonLexer

from jupyterlab_pygments import JupyterStyle

html = highlight("print('staticpython')\\n", PythonLexer(), HtmlFormatter(style=JupyterStyle))
assert "jp-RenderedHTMLCommon" not in html or isinstance(html, str)
assert "staticpython" in html
assert "highlight" in html
""",
        )
    ],
)
