from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="py",
    overlay_entries=["Lib/py"],
    verification_steps=[
        inline_verification_step(
            "py-smoke",
            """
import py

path = py.path.local(".")
assert path.basename
tmp = py.path.local.mkdtemp()
try:
    child = tmp.join("demo.txt")
    child.write("staticpython", ensure=True)
    assert child.read() == "staticpython"
    assert child.check(file=1)
finally:
    tmp.remove(rec=1)
""",
        )
    ],
)
