from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='itsdangerous',
    overlay_entries=['Lib/itsdangerous'],
    verification_steps=[
        inline_verification_step(
            "itsdangerous-smoke",
            """
from itsdangerous import BadSignature, URLSafeSerializer, URLSafeTimedSerializer

serializer = URLSafeSerializer("secret")
token = serializer.dumps({"value": 3})
assert serializer.loads(token) == {"value": 3}
try:
    serializer.loads(token + "x")
except BadSignature:
    pass
else:
    raise AssertionError("tampered token was accepted")
assert URLSafeTimedSerializer("secret").loads(URLSafeTimedSerializer("secret").dumps("ok")) == "ok"
""",
        )
    ],
)
