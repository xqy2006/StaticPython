from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="slugify",
    project_name="python-slugify",
    overlay_entries=["Lib/slugify"],
    verification_steps=[
        inline_verification_step(
            "python-slugify-smoke",
            """
from slugify import slugify

assert slugify("Static Python: Café déjà vu!") == "static-python-cafe-deja-vu"
assert slugify("影師嗎", allow_unicode=True) == "影師嗎"
assert slugify("影師嗎") == "ying-shi-ma"
""",
        )
    ],
)
