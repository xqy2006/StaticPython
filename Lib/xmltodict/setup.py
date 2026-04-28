from libs import inline_verification_step, pypi_library


LIBRARY_INTEGRATION = pypi_library(
    name="xmltodict",
    source_mapping={"xmltodict.py": "Lib/xmltodict.py"},
    python_packages=["xmltodict"],
    verification_steps=[
        inline_verification_step(
            "xmltodict-smoke",
            """
import xmltodict

data = xmltodict.parse("<root><item id='1'>ok</item></root>")
assert data["root"]["item"]["@id"] == "1"
assert data["root"]["item"]["#text"] == "ok"
xml = xmltodict.unparse(data)
assert "<root>" in xml and "<item id=\\"1\\">ok</item>" in xml
""",
        )
    ],
)
