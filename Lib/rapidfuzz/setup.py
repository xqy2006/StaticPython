from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="rapidfuzz",
    project_name="RapidFuzz",
    source_mapping={
        "src/rapidfuzz": "Lib/rapidfuzz",
    },
    verification_imports=["rapidfuzz"],
    verification_steps=[
        inline_verification_step(
            "rapidfuzz-smoke",
            """
from rapidfuzz import fuzz, process
from rapidfuzz.distance import Levenshtein

assert fuzz.ratio("static python", "static python") == 100
assert fuzz.partial_ratio("single-file python", "python") == 100
assert Levenshtein.distance("kitten", "sitting") == 3
choice = process.extractOne("static", ["dynamic", "static", "frozen"])
assert choice[0] == "static", choice
""",
        )
    ],
)
