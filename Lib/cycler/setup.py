from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="cycler",
    overlay_entries=["Lib/cycler"],
    verification_steps=[
        inline_verification_step(
            "cycler-smoke",
            """
from cycler import cycler

combined = cycler(color=["red", "blue"]) + cycler(linewidth=[1, 2])
assert list(combined) == [
    {"color": "red", "linewidth": 1},
    {"color": "blue", "linewidth": 2},
]
product = cycler(color=["red", "blue"]) * cycler(marker=["o", "x"])
assert len(product) == 4
assert {"color": "red", "marker": "o"} in list(product)
""",
        )
    ],
)
