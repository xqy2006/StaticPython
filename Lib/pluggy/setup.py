from libs import inline_verification_step, simple_library


LIBRARY_INTEGRATION = simple_library(
    name="pluggy",
    overlay_entries=["Lib/pluggy"],
    verification_steps=[
        inline_verification_step(
            "pluggy-smoke",
            """
import pluggy

hookspec = pluggy.HookspecMarker("staticpython")
hookimpl = pluggy.HookimplMarker("staticpython")

class Spec:
    @hookspec
    def answer(self, value):
        pass

class Plugin:
    @hookimpl
    def answer(self, value):
        return value + 1

manager = pluggy.PluginManager("staticpython")
manager.add_hookspecs(Spec)
manager.register(Plugin())
assert manager.hook.answer(value=41) == [42]
""",
        )
    ],
)
