from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='redis',
    overlay_entries=['Lib/redis'],
    verification_steps=[
        inline_verification_step(
            "redis-smoke",
            """
import redis
from redis.connection import parse_url

client = redis.Redis.from_url("redis://localhost:6379/2?decode_responses=True")
kwargs = client.connection_pool.connection_kwargs
assert kwargs["host"] == "localhost"
assert kwargs["db"] == 2
parsed = parse_url("redis://:pass@example.com:6380/1")
assert parsed["host"] == "example.com" and parsed["port"] == 6380 and parsed["db"] == 1
""",
        )
    ],
)
