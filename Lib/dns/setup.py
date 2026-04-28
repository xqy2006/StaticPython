from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="dns",
    project_name="dnspython",
    overlay_entries=["Lib/dns"],
    verification_steps=[
        inline_verification_step(
            "dnspython-smoke",
            """
import dns.name
import dns.rdatatype
from dns.message import make_query

name = dns.name.from_text("example.com.")
assert name.to_text() == "example.com."
message = make_query(name, dns.rdatatype.A)
assert message.question[0].name == name
""",
        )
    ],
)
