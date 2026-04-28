from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='soupsieve',
    overlay_entries=['Lib/soupsieve'],
    verification_steps=[
        inline_verification_step(
            "soupsieve-smoke",
            """
import soupsieve
from bs4 import BeautifulSoup

soup = BeautifulSoup("<div><p class='a'>one</p><p>two</p></div>", "html.parser")
selector = soupsieve.compile("p.a")
assert selector.select_one(soup).text == "one"
assert [node.text for node in soupsieve.select("p", soup)] == ["one", "two"]
""",
        )
    ],
)
