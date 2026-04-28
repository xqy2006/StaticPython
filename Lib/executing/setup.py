from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="executing",
    overlay_entries=["Lib/executing"],
    verification_steps=[
        inline_verification_step(
            "executing-smoke",
            """
import linecache
import sys
import textwrap
from executing import Source, only

filename = "<executing_smoke>"
source_text = textwrap.dedent(
    '''
    import sys
    def inspect_frame(frame):
        return Source.executing(frame)
    def probe():
        value = 21
        return inspect_frame(sys._getframe())
    '''
)
linecache.cache[filename] = (len(source_text), None, source_text.splitlines(True), filename)
namespace = {"Source": Source, "sys": sys}
exec(compile(source_text, filename, "exec"), namespace)
execution = namespace["probe"]()
assert type(execution.node).__name__ == "Call"
assert execution.text() == "inspect_frame(sys._getframe())"
assert only([42]) == 42
""",
        )
    ],
)
