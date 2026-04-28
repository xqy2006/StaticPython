from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="jsonpickle",
    overlay_entries=["Lib/jsonpickle"],
    verification_steps=[
        inline_verification_step(
            "jsonpickle-smoke",
            """
import jsonpickle


class Node:
    def __init__(self, name):
        self.name = name
        self.children = []


root = Node("root")
root.children.append(Node("leaf"))
encoded = jsonpickle.encode(root)
decoded = jsonpickle.decode(encoded)
assert decoded.name == "root"
assert decoded.children[0].name == "leaf"
assert "py/object" in encoded
""",
        )
    ],
)
