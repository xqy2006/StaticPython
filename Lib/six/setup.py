from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='six',
    overlay_entries=['Lib/six.py'],
    verification_steps=[
        inline_verification_step(
            "six-smoke",
            """
import six

assert six.text_type("demo") == "demo"
assert list(six.moves.range(3)) == [0, 1, 2]
assert six.ensure_text(b"demo") == "demo"
assert six.iteritems({"a": 1}).__next__() == ("a", 1)
""",
        )
    ],
)
