from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="hyperframe",
    overlay_entries=["Lib/hyperframe"],
    verification_steps=[
        inline_verification_step(
            "hyperframe-smoke",
            """
from hyperframe.frame import DataFrame, SettingsFrame

frame = SettingsFrame(stream_id=0)
serialized = frame.serialize()
parsed, length = SettingsFrame.parse_frame_header(memoryview(serialized[:9]))
parsed.parse_body(memoryview(serialized[9:9 + length]))
assert parsed.stream_id == 0

data_frame = DataFrame(stream_id=1)
data_frame.data = b"hello"
data_frame.flags.add("END_STREAM")
payload = data_frame.serialize()
parsed_data, data_length = DataFrame.parse_frame_header(memoryview(payload[:9]))
parsed_data.parse_body(memoryview(payload[9:9 + data_length]))
assert parsed_data.data == b"hello"
assert "END_STREAM" in parsed_data.flags
""",
        )
    ],
)
