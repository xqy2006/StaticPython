from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="marshmallow",
    overlay_entries=["Lib/marshmallow"],
    verification_steps=[
        inline_verification_step(
            "marshmallow-smoke",
            """
from marshmallow import Schema, ValidationError, fields

class UserSchema(Schema):
    name = fields.Str(required=True)
    age = fields.Int(required=True)

schema = UserSchema()
loaded = schema.load({"name": "Ada", "age": "42"})
assert loaded == {"name": "Ada", "age": 42}
assert schema.dump(loaded) == {"name": "Ada", "age": 42}
try:
    schema.load({"age": "bad"})
except ValidationError as exc:
    assert "name" in exc.messages and "age" in exc.messages
else:
    raise AssertionError("marshmallow accepted invalid input")
""",
        )
    ],
)
