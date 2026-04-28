from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='packaging',
    overlay_entries=['Lib/packaging'],
    verification_steps=[
        inline_verification_step(
            "packaging-smoke",
            """
from packaging.markers import Marker
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

assert Version("1.2.3") < Version("2.0")
assert Version("1.5") in SpecifierSet(">=1,<2")
req = Requirement("demo[extra]>=1; python_version >= '3.8'")
assert req.name == "demo" and "extra" in req.extras
assert Marker("python_version >= '3.8'").evaluate()
""",
        )
    ],
)
