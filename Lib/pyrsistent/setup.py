from libs import inline_verification_step, pypi_library


LIBRARY_INTEGRATION = pypi_library(
    name="pyrsistent",
    source_mapping={
        "pyrsistent": "Lib/pyrsistent",
    },
    python_packages=["pyrsistent"],
    verification_steps=[
        inline_verification_step(
            "pyrsistent-smoke",
            """
from pyrsistent import freeze, m, pmap, pvector, thaw

vec = pvector([1, 2, 3])
assert vec.append(4).tolist() == [1, 2, 3, 4]
assert vec.tolist() == [1, 2, 3]

mapping = pmap({"name": "staticpython"}).set("answer", 42)
assert mapping["answer"] == 42
assert m(a=1).transform(["a"], lambda value: value + 1)["a"] == 2

frozen = freeze({"items": [1, 2], "meta": {"ok": True}})
assert thaw(frozen) == {"items": [1, 2], "meta": {"ok": True}}
""",
        )
    ],
)
