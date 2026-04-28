from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='bs4',
    overlay_entries=['Lib/bs4'],
    verification_steps=[
        inline_verification_step(
            "bs4-smoke",
            """
from bs4 import BeautifulSoup

soup = BeautifulSoup("<html><body><p class='x'>one</p><p>two</p></body></html>", "html.parser")
assert soup.select_one("p.x").text == "one"
assert [p.text for p in soup.find_all("p")] == ["one", "two"]
""",
        )
    ],
)
