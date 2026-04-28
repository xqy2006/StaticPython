from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="platformdirs",
    overlay_entries=["Lib/platformdirs"],
    verification_steps=[
        inline_verification_step(
            "platformdirs-smoke",
            """
from platformdirs import user_cache_dir, user_config_dir

cache_dir = user_cache_dir("StaticPython", "StaticPython")
config_dir = user_config_dir("StaticPython", "StaticPython")
assert "StaticPython" in cache_dir
assert "StaticPython" in config_dir
""",
        )
    ],
)
