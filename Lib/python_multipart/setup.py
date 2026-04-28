from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="python_multipart",
    project_name="python-multipart",
    source_mapping={
        "python_multipart": "Lib/python_multipart",
        "multipart": "Lib/multipart",
    },
    python_packages=["python_multipart", "multipart"],
    verification_steps=[
        inline_verification_step(
            "python-multipart-smoke",
            """
from multipart.multipart import parse_options_header
from python_multipart.multipart import MultipartParser

value, options = parse_options_header('form-data; name="file"; filename="demo.txt"')
assert value == b"form-data"
assert options[b"name"] == b"file"
assert options[b"filename"] == b"demo.txt"
assert MultipartParser is not None
""",
        )
    ],
)
