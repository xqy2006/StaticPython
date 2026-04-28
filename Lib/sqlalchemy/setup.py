from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="sqlalchemy",
    project_name="SQLAlchemy",
    overlay_entries=["Lib/sqlalchemy"],
    verification_steps=[
        inline_verification_step(
            "sqlalchemy-smoke",
            """
import sqlalchemy as sa

engine = sa.create_engine("sqlite:///:memory:")
metadata = sa.MetaData()
table = sa.Table("demo", metadata, sa.Column("id", sa.Integer, primary_key=True), sa.Column("name", sa.String))
metadata.create_all(engine)
with engine.begin() as conn:
    conn.execute(table.insert(), [{"name": "a"}, {"name": "b"}])
    rows = conn.execute(sa.select(table.c.name).order_by(table.c.id)).scalars().all()
    count = conn.scalar(sa.select(sa.func.count()).select_from(table))
assert rows == ["a", "b"]
assert count == 2
assert "demo" in sa.inspect(engine).get_table_names()
""",
        )
    ],
)
