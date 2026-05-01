from libs import inline_verification_step, replace_text_once, simple_library, transform_source_text, write_source_text


def _patch_flask_testing(text: str) -> str:
    old = (
        "    if not _werkzeug_version:\n"
        '        _werkzeug_version = importlib.metadata.version("werkzeug")\n'
    )
    new = (
        "    if not _werkzeug_version:\n"
        "        try:\n"
        '            _werkzeug_version = importlib.metadata.version("werkzeug")\n'
        "        except importlib.metadata.PackageNotFoundError:\n"
        '            _werkzeug_version = "3.1.8"\n'
    )
    return replace_text_once(text, old, new, label="flask.testing")


def patch_flask_sources(context) -> None:
    transform_source_text(context, "Lib/flask/testing.py", _patch_flask_testing)
    write_source_text(
        context,
        "Lib/flask/sansio/__init__.py",
        (
            "from .app import App as App\n"
            "from .blueprints import Blueprint as Blueprint\n"
            "from .blueprints import BlueprintSetupState as BlueprintSetupState\n"
            "from .scaffold import Scaffold as Scaffold\n"
            "from .scaffold import _sentinel as _sentinel\n"
        ),
    )


LIBRARY_INTEGRATION = simple_library(
    name="flask",
    overlay_entries=["Lib/flask"],
    post_patch_hooks=[patch_flask_sources],
    verification_steps=[
        inline_verification_step(
            "flask-smoke",
            """
from flask import Blueprint, Flask, jsonify, render_template_string, request, url_for

app = Flask(__name__)
api = Blueprint("api", __name__)

@app.get("/hello/<name>")
def hello(name):
    return jsonify(name=name, query=request.args.get("q"))

@api.post("/sum")
def total():
    payload = request.get_json()
    return jsonify(total=sum(payload["values"]))

app.register_blueprint(api, url_prefix="/api")

with app.test_client() as client:
    response = client.get("/hello/codex?q=ok")
    assert response.status_code == 200
    assert response.get_json() == {"name": "codex", "query": "ok"}
    response = client.post("/api/sum", json={"values": [1, 2, 3]})
    assert response.status_code == 200
    assert response.get_json() == {"total": 6}
    with app.test_request_context():
        assert url_for("hello", name="x") == "/hello/x"
    with app.app_context():
        assert render_template_string("Hello {{ name }}", name="Codex") == "Hello Codex"
""",
        )
    ],
)
