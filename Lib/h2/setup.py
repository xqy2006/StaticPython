from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="h2",
    overlay_entries=["Lib/h2"],
    verification_steps=[
        inline_verification_step(
            "h2-smoke",
            """
from h2.config import H2Configuration
from h2.connection import H2Connection

conn = H2Connection(config=H2Configuration(client_side=True, header_encoding="utf-8"))
conn.initiate_connection()
data = conn.data_to_send()
assert data.startswith(b"PRI * HTTP/2.0")
""",
        )
    ],
)
