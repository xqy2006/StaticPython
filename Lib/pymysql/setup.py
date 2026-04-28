from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='pymysql',
    overlay_entries=['Lib/pymysql'],
    verification_steps=[
        inline_verification_step(
            "pymysql-smoke",
            """
import pymysql
from pymysql.converters import escape_string
from pymysql.cursors import DictCursor

assert pymysql.VERSION_STRING
assert escape_string("a'b") == "a\\\\'b"
assert DictCursor.__name__ == "DictCursor"
""",
        )
    ],
)
