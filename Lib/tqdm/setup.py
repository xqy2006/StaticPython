from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='tqdm',
    overlay_entries=['Lib/tqdm'],
    verification_steps=[
        inline_verification_step(
            "tqdm-smoke",
            """
from tqdm import tqdm

assert "100%" in tqdm.format_meter(10, 10, 1.0)
bar = tqdm(iterable=[1, 2, 3], disable=True)
assert list(bar) == [1, 2, 3]
""",
        )
    ],
)
