from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name='sqlparse',
    overlay_entries=['Lib/sqlparse'],
    verification_steps=[
        inline_verification_step(
            "sqlparse-smoke",
            """
import sqlparse

statements = sqlparse.split("select 1; select 2;")
assert statements == ["select 1;", "select 2;"]
formatted = sqlparse.format("select * from demo where id=1", keyword_case="upper", reindent=True)
assert "SELECT" in formatted and "FROM" in formatted
""",
        )
    ],
)
