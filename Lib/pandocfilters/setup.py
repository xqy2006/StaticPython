from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="pandocfilters",
    overlay_entries=["Lib/pandocfilters.py"],
    verification_steps=[
        inline_verification_step(
            "pandocfilters-smoke",
            """
import json

from pandocfilters import Para, Str, applyJSONFilters, stringify

document = {
    "pandoc-api-version": [1, 22],
    "meta": {},
    "blocks": [Para([Str("StaticPython")])],
}

def uppercase(key, value, fmt, meta):
    if key == "Str":
        return Str(value.upper())
    return None

result = json.loads(applyJSONFilters([uppercase], json.dumps(document), format="html"))
assert result["blocks"][0]["c"][0]["c"] == "STATICPYTHON"
assert stringify(result) == "STATICPYTHON"
""",
        )
    ],
)
