from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="selenium",
    overlay_entries=["Lib/selenium"],
    verification_steps=[
        inline_verification_step(
            "selenium-smoke",
            """
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys

options = Options()
options.add_argument("--headless=new")
capabilities = options.to_capabilities()
assert capabilities["browserName"] == "chrome"
assert "--headless=new" in capabilities["goog:chromeOptions"]["args"]
assert By.CSS_SELECTOR == "css selector"
assert Keys.ENTER == "\\ue007"
""",
        )
    ],
)
