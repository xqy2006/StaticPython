from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='loguru',
    overlay_entries=['Lib/loguru'],
    verification_steps=[
        inline_verification_step(
            "loguru-smoke",
            """
import io
from loguru import logger

buffer = io.StringIO()
handler_id = logger.add(buffer, format="{level}:{message}")
try:
    logger.warning("demo")
finally:
    logger.remove(handler_id)
assert "WARNING:demo" in buffer.getvalue()
""",
        )
    ],
)
