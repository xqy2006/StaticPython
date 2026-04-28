from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="mako",
    project_name="Mako",
    overlay_entries=["Lib/mako"],
    verification_steps=[
        inline_verification_step(
            "mako-smoke",
            """
from mako.lookup import TemplateLookup
from mako.template import Template

assert Template("hello ${name}").render(name="codex") == "hello codex"
lookup = TemplateLookup()
lookup.put_string("demo", "${x + y}")
assert lookup.get_template("demo").render(x=2, y=3) == "5"
""",
        )
    ],
)
