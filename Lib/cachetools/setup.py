from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="cachetools",
    overlay_entries=["Lib/cachetools"],
    verification_steps=[
        inline_verification_step(
            "cachetools-smoke",
            """
from cachetools import LRUCache, cached

cache = LRUCache(maxsize=2)
cache["a"] = 1
cache["b"] = 2
cache["c"] = 3
assert "a" not in cache and cache["b"] == 2 and cache["c"] == 3

calls = {"count": 0}

@cached(cache={})
def add(a, b):
    calls["count"] += 1
    return a + b

assert add(2, 3) == 5
assert add(2, 3) == 5
assert calls["count"] == 1
""",
        )
    ],
)
