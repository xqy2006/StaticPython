from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='jinja2',
    overlay_entries=['Lib/jinja2'],
    verification_steps=[
        inline_verification_step(
            "jinja2-smoke",
            """
from jinja2 import DictLoader, Environment

env = Environment(loader=DictLoader({"demo.html": "Hello {{ name|upper }}"}))
template = env.get_template("demo.html")
assert template.render(name="codex") == "Hello CODEX"
assert env.from_string("{{ items|join(',') }}").render(items=[1, 2, 3]) == "1,2,3"
""",
        )
    ],
)
