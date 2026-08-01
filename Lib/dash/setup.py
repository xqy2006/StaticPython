from __future__ import annotations

from libs import pypi_library, replace_regex_once, transform_source_text


def _patch_dash_plotly_version(text: str) -> str:
    if "getattr(plotly, \"__version__\", None)" in text:
        return text
    if "metadata.version(\"plotly\")" not in text:
        return text
    return replace_regex_once(
        text,
        r'(?ms)^plotly_version = None\nif find_spec\("plotly"\):\n    plotly_version = metadata\.version\("plotly"\)\n',
        "plotly_version = None\n"
        'if find_spec("plotly"):\n'
        "    try:\n"
        '        plotly_version = metadata.version("plotly")\n'
        "    except metadata.PackageNotFoundError:\n"
        "        import plotly\n"
        '        plotly_version = getattr(plotly, "__version__", None)\n',
        label="dash plotly version metadata fallback",
    )


def patch_dash_sources(context) -> None:
    transform_source_text(context, "Lib/dash/dash.py", _patch_dash_plotly_version)


LIBRARY_INTEGRATION = pypi_library(
    name="dash",
    # Dash 4.3+ makes Pydantic 2 (and therefore pydantic-core's Rust native
    # extension) a mandatory runtime dependency. Keep the verified baseline at
    # the newest release without that dependency until the Rust static-pack ABI
    # is available; version-matrix jobs can still override this pin explicitly.
    release_version="4.2.0",
    source_mapping={
        "dash": "Lib/dash",
    },
    python_packages=["dash"],
    source_ignore_patterns=["tests"],
    post_patch_hooks=[patch_dash_sources],
    smoke_tests=[
        {
            "name": "construct-no-server-app",
            "kind": "inline",
            "code": (
                "from dash import Dash, dcc, html; "
                "app = Dash('staticpython_dash_smoke', server=False); "
                "app.layout = html.Div([html.H1('StaticPython'), dcc.Graph(id='plot')]); "
                "assert app.layout.children[0].children == 'StaticPython'; "
                "assert app.layout.children[1].id == 'plot'"
            ),
        }
    ],
)
