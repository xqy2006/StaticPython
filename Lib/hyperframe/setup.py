from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="hyperframe",
    overlay_entries=["Lib/hyperframe"],
    verification_steps=[
        inline_verification_step(
            "hyperframe-smoke",
            """
from hyperframe.frame import SettingsFrame

frame = SettingsFrame(stream_id=0)
serialized = frame.serialize()
parsed, length = SettingsFrame.parse_frame_header(memoryview(serialized[:9]))
parsed.parse_body(memoryview(serialized[9:9 + length]))
assert parsed.stream_id == 0
""",
        )
    ],
)
