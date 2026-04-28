from libs import inline_verification_step, replace_text_once, simple_library, transform_source_text


def _patch_werkzeug_serving(text: str) -> str:
    old = '        self._server_version = f"Werkzeug/{importlib.metadata.version(\'werkzeug\')}"\n'
    new = (
        "        try:\n"
        '            werkzeug_version = importlib.metadata.version("werkzeug")\n'
        "        except importlib.metadata.PackageNotFoundError:\n"
        '            werkzeug_version = "3.1.8"\n'
        "\n"
        '        self._server_version = f"Werkzeug/{werkzeug_version}"\n'
    )
    return replace_text_once(text, old, new, label="werkzeug.serving")


def patch_werkzeug_sources(context) -> None:
    transform_source_text(context, "Lib/werkzeug/serving.py", _patch_werkzeug_serving)


LIBRARY_INTEGRATION = simple_library(
    name='werkzeug',
    overlay_entries=['Lib/werkzeug'],
    post_patch_hooks=[patch_werkzeug_sources],
    verification_steps=[
        inline_verification_step(
            "werkzeug-smoke",
            """
from werkzeug.datastructures import MultiDict
from werkzeug.routing import Map, Rule
from werkzeug.wrappers import Request, Response

mapping = Map([Rule("/hello/<name>", endpoint="hello")])
adapter = mapping.bind("example.com")
assert adapter.match("/hello/codex") == ("hello", {"name": "codex"})
assert MultiDict([("a", "1"), ("a", "2")]).getlist("a") == ["1", "2"]
response = Response("ok", status=201)
assert response.status_code == 201 and response.get_data(as_text=True) == "ok"
""",
        )
    ],
)
