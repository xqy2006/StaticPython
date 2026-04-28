from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="pyasn1_modules",
    project_name="pyasn1-modules",
    overlay_entries=["Lib/pyasn1_modules"],
    verification_steps=[
        inline_verification_step(
            "pyasn1-modules-smoke",
            """
from pyasn1_modules import rfc5280

assert rfc5280.Certificate.componentType
assert rfc5280.id_ce_basicConstraints.prettyPrint() == "2.5.29.19"
assert rfc5280.Version("v3") == 2
""",
        )
    ],
)
