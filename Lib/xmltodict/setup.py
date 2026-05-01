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

namespaced = xmltodict.parse(
    '<root xmlns:a="urn:test"><item id="1">ok</item><item id="2">fine</item><a:meta>yes</a:meta></root>',
    process_namespaces=True,
    namespaces={"urn:test": "ns"},
    force_list=("item",),
)
assert len(namespaced["root"]["item"]) == 2
assert namespaced["root"]["item"][1]["@id"] == "2"
assert namespaced["root"]["ns:meta"] == "yes"

fragment = xmltodict.unparse(
    {"root": {"item": [{"@id": "1", "#text": "ok"}]}},
    full_document=False,
)
assert '<item id="1">ok</item>' in fragment
""",
        )
    ],
)
