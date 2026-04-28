from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="pycparser",
    overlay_entries=["Lib/pycparser"],
    verification_steps=[
        inline_verification_step(
            "pycparser-smoke",
            """
from pycparser import c_ast, c_generator, c_parser

parser = c_parser.CParser()
tree = parser.parse("int add(int a, int b) { return a + b; }")
functions = [node for _, node in tree.children() if isinstance(node, c_ast.FuncDef)]
assert len(functions) == 1
assert functions[0].decl.name == "add"
generated = c_generator.CGenerator().visit(tree)
assert "int add" in generated
assert "return a + b;" in generated
""",
        )
    ],
)
