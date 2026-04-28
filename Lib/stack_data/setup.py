from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="stack_data",
    project_name="stack-data",
    overlay_entries=["Lib/stack_data"],
    verification_steps=[
        inline_verification_step(
            "stack-data-smoke",
            """
import linecache
import sys
import textwrap
from stack_data import FrameInfo, Line, Options

filename = "<stack_data_smoke>"
source_text = textwrap.dedent(
    '''
    import sys
    def probe():
        alpha = 20
        beta = [1, 2, 3]
        frame = sys._getframe()
        return frame
    '''
)
linecache.cache[filename] = (len(source_text), None, source_text.splitlines(True), filename)
namespace = {"sys": sys}
exec(compile(source_text, filename, "exec"), namespace)
frame = namespace["probe"]()
info = FrameInfo(frame, Options(before=1, after=1))
lines = list(info.lines)
variables = {variable.name: variable.value for variable in info.variables}
assert info.source.filename == filename
assert any(isinstance(line, Line) and line.is_current for line in lines)
assert variables["alpha"] == 20
assert variables["beta"] == [1, 2, 3]
""",
        )
    ],
)
