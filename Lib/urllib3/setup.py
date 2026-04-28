from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='urllib3',
    overlay_entries=['Lib/urllib3'],
    verification_steps=[
        inline_verification_step(
            "urllib3-smoke",
            """
import urllib3
from urllib3.util import Retry, parse_url

url = parse_url("https://example.com:443/path?q=1")
assert url.scheme == "https" and url.host == "example.com" and url.port == 443
retry = Retry(total=3, status_forcelist=[500])
assert retry.total == 3 and retry.is_retry("GET", 500)
manager = urllib3.PoolManager(num_pools=1, maxsize=1)
assert manager.connection_pool_kw["maxsize"] == 1
""",
        )
    ],
)
