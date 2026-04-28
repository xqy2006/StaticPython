from libs import inline_verification_step, pypi_library


LIBRARY_INTEGRATION = pypi_library(
    name="socks",
    project_name="PySocks",
    source_mapping={
        "socks.py": "Lib/socks.py",
        "sockshandler.py": "Lib/sockshandler.py",
    },
    python_packages=["socks", "sockshandler"],
    verification_steps=[
        inline_verification_step(
            "pysocks-smoke",
            """
import socks

sock = socks.socksocket()
sock.set_proxy(socks.SOCKS5, "localhost", 1080, username="user", password="pass")
assert sock.proxy[0] == socks.SOCKS5
assert sock.proxy[1] == "localhost"
assert sock.proxy[2] == 1080
assert socks.PROXY_TYPE_HTTP == socks.HTTP
sock.close()
""",
        )
    ],
)
