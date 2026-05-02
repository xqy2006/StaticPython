from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="jupyter_lsp",
    project_name="jupyter-lsp",
    overlay_entries=["Lib/jupyter_lsp"],
    runtime_resource_paths=[
        "Lib/jupyter_lsp/schema",
        "Lib/jupyter_lsp/specs",
    ],
    materialized_paths=[
        "Lib/jupyter_lsp/schema/schema.json",
    ],
    verification_steps=[
        inline_verification_step(
            "jupyter-lsp-smoke",
            """
from pathlib import Path

from jupyter_lsp.manager import LanguageServerManager
from jupyter_lsp.schema import LANGUAGE_SERVER_SPEC, LANGUAGE_SERVER_SPEC_MAP, SERVERS_RESPONSE
import jupyter_lsp

assert (Path(jupyter_lsp.__file__).parent / "schema" / "schema.json").exists()

spec = {
    "version": 2,
    "argv": ["pylsp"],
    "languages": ["python"],
    "display_name": "Python LSP",
    "mime_types": ["text/x-python"],
    "requires_documents_on_disk": False,
}

LANGUAGE_SERVER_SPEC.validate(spec)
LANGUAGE_SERVER_SPEC_MAP.validate({"pylsp": spec})
SERVERS_RESPONSE.validate({"version": 2, "sessions": {}, "specs": {"pylsp": spec}})

manager = LanguageServerManager()
assert manager.virtual_documents_dir == ".virtual_documents"
assert manager.language_servers == {}
assert manager.conf_d_language_servers == {}
""",
        )
    ],
)
