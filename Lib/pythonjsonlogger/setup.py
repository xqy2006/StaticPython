from libs import inline_verification_step, pypi_library


LIBRARY_INTEGRATION = pypi_library(
    name="pythonjsonlogger",
    project_name="python-json-logger",
    source_mapping={
        "src/pythonjsonlogger": "Lib/pythonjsonlogger",
    },
    python_packages=["pythonjsonlogger"],
    verification_steps=[
        inline_verification_step(
            "python-json-logger-smoke",
            """
import io
import json
import logging

from pythonjsonlogger import jsonlogger

stream = io.StringIO()
handler = logging.StreamHandler(stream)
handler.setFormatter(jsonlogger.JsonFormatter())

logger = logging.getLogger("staticpython.pythonjsonlogger")
logger.handlers[:] = []
logger.setLevel(logging.INFO)
logger.propagate = False
logger.addHandler(handler)

logger.info("hello", extra={"answer": 42})
handler.flush()
payload = json.loads(stream.getvalue())

assert payload["message"] == "hello"
assert payload["answer"] == 42
""",
        )
    ],
)
