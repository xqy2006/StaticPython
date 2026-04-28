from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='shellingham',
    overlay_entries=['Lib/shellingham'],
    verification_steps=[
        inline_verification_step(
            "shellingham-smoke",
            """
import shellingham

try:
    shell = shellingham.detect_shell()
except shellingham.ShellDetectionFailure:
    shell = None
assert shell is None or (isinstance(shell, tuple) and len(shell) == 2)
assert issubclass(shellingham.ShellDetectionFailure, OSError)
""",
        )
    ],
)
