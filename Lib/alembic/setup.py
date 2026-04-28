from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="alembic",
    overlay_entries=["Lib/alembic"],
    verification_steps=[
        inline_verification_step(
            "alembic-smoke",
            """
from alembic.config import Config
from alembic.script.revision import RevisionMap, Revision

config = Config()
config.set_main_option("sqlalchemy.url", "sqlite:///:memory:")
assert config.get_main_option("sqlalchemy.url") == "sqlite:///:memory:"
rev = Revision("abc", None)
rev_map = RevisionMap(lambda: [rev])
assert rev_map.get_revision("abc").revision == "abc"
""",
        )
    ],
)
