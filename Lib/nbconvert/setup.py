from libs import (
    inline_verification_step,
    replace_text_once,
    script_verification_step,
    simple_library,
    transform_source_text,
)


def patch_nbconvert_sources(context) -> None:
    def patch_exporter_base(text: str) -> str:
        text = replace_text_once(
            text,
            "from .exporter import Exporter\n",
            """from .exporter import Exporter


_STATICPYTHON_EXPORTERS = {
    "asciidoc": "nbconvert.exporters.asciidoc.ASCIIDocExporter",
    "custom": "nbconvert.exporters.templateexporter.TemplateExporter",
    "html": "nbconvert.exporters.html.HTMLExporter",
    "latex": "nbconvert.exporters.latex.LatexExporter",
    "markdown": "nbconvert.exporters.markdown.MarkdownExporter",
    "notebook": "nbconvert.exporters.notebook.NotebookExporter",
    "pdf": "nbconvert.exporters.pdf.PDFExporter",
    "python": "nbconvert.exporters.python.PythonExporter",
    "qtpdf": "nbconvert.exporters.qtpdf.QtPDFExporter",
    "qtpng": "nbconvert.exporters.qtpng.QtPNGExporter",
    "rst": "nbconvert.exporters.rst.RSTExporter",
    "script": "nbconvert.exporters.script.ScriptExporter",
    "slides": "nbconvert.exporters.slides.SlidesExporter",
    "webpdf": "nbconvert.exporters.webpdf.WebPDFExporter",
}


class _StaticPythonExporterEntryPoint:
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def load(self):
        return import_item(self.value)


def _iter_exporter_entries():
    exporters = list(entry_points(group="nbconvert.exporters"))
    if exporters:
        return exporters
    return [
        _StaticPythonExporterEntryPoint(name, value)
        for name, value in _STATICPYTHON_EXPORTERS.items()
    ]
""",
            label="nbconvert exporter fallback helpers",
        )
        text = replace_text_once(
            text,
            '        exporters = entry_points(group="nbconvert.exporters")\n',
            '        exporters = _iter_exporter_entries()\n',
            label="nbconvert get_exporter fallback call",
        )
        return replace_text_once(
            text,
            '    exporters = sorted(e.name for e in entry_points(group="nbconvert.exporters"))\n',
            '    exporters = sorted(e.name for e in _iter_exporter_entries())\n',
            label="nbconvert get_export_names fallback call",
        )

    transform_source_text(context, "Lib/nbconvert/exporters/base.py", patch_exporter_base)


LIBRARY_INTEGRATION = simple_library(
    name="nbconvert",
    source_mapping={
        "nbconvert": "Lib/nbconvert",
        "share/templates": "share/jupyter/nbconvert/templates",
    },
    post_patch_hooks=[patch_nbconvert_sources],
    verification_steps=[
        inline_verification_step(
            "nbconvert-smoke",
            """
from nbformat import v4
from nbconvert.exporters import HTMLExporter, ScriptExporter
from nbconvert.exporters.base import get_export_names, get_exporter

notebook = v4.new_notebook()
notebook.cells.append(v4.new_markdown_cell("# StaticPython"))
notebook.cells.append(v4.new_code_cell("answer = 40 + 2\\nanswer"))

export_names = set(get_export_names())
assert {"notebook"} <= export_names
assert get_exporter("html").__name__ == "HTMLExporter"
script_exporter_class = get_exporter("script")
assert script_exporter_class.__name__ in {"ScriptExporter", "PythonExporter"}

html_exporter = HTMLExporter()
html_body, html_resources = html_exporter.from_notebook_node(notebook)
assert "<h1" in html_body and "StaticPython" in html_body
assert html_exporter.get_template_names()[0] == "lab"
assert '<div class="highlight hl-ipython3"><pre>' in html_body
assert "answer" in html_body and "40" in html_body and "2" in html_body
assert isinstance(html_resources, dict)

script_exporter = ScriptExporter()
script_body, script_resources = script_exporter.from_notebook_node(notebook)
assert "answer = 40 + 2" in script_body
assert script_resources.get("output_extension") in {".txt", ".py"}
""",
            timeout=600,
        ),
        script_verification_step(
            "nbconvert-runtime",
            "scripts/nbconvert_runtime.py",
            timeout=600,
        ),
    ],
)
