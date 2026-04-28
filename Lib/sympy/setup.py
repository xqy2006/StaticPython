from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='sympy',
    overlay_entries=['Lib/sympy'],
    verification_steps=[
        inline_verification_step(
            "sympy-smoke",
            """
import sympy as sp

x = sp.Symbol("x")
assert sp.factor(x**2 - 1) == (x - 1) * (x + 1)
assert sp.integrate(2 * x, x) == x**2
assert sp.solve(sp.Eq(x + 2, 5), x) == [3]
""",
        )
    ],
)
