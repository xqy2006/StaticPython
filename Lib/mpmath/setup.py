from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='mpmath',
    overlay_entries=['Lib/mpmath'],
    verification_steps=[
        inline_verification_step(
            "mpmath-smoke",
            """
import mpmath as mp

mp.mp.dps = 30
assert mp.sqrt(81) == 9
assert str(mp.factorial(5)) == "120.0"
assert abs(mp.sin(mp.pi / 2) - 1) < mp.mpf("1e-25")
""",
        )
    ],
)
