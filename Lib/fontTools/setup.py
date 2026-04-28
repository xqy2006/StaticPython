from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="fontTools",
    project_name="fonttools",
    source_mapping={"Lib/fontTools": "Lib/fontTools"},
    verification_steps=[
        inline_verification_step(
            "fonttools-smoke",
            """
from fontTools.misc.transform import Transform
from fontTools.ttLib import TTFont, newTable

transform = Transform().scale(2, 3).translate(5, 7)
assert transform.transformPoint((1, 1)) == (12, 24)
font = TTFont(recalcBBoxes=False, recalcTimestamp=False)
font["name"] = newTable("name")
assert "name" in font
""",
        )
    ],
)
