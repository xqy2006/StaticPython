from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="uvicorn",
    overlay_entries=["Lib/uvicorn"],
    verification_steps=[
        inline_verification_step(
            "uvicorn-smoke",
            """
from uvicorn.config import Config
from uvicorn.importer import import_from_string

config = Config("uvicorn.main:main", loop="asyncio", http="h11", lifespan="off", log_config=None)
assert config.app == "uvicorn.main:main"
assert import_from_string("uvicorn.config:Config") is Config
""",
        )
    ],
)
