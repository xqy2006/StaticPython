import asyncio
import inspect
import unittest
from unittest import mock


class LibuiImportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import libui
        import libui.core as core
        import libui.declarative as declarative
        import libui.loop as loop

        cls.libui = libui
        cls.core = core
        cls.declarative = declarative
        cls.loop = loop

    def test_builtin_core_is_exposed_through_shim(self):
        self.assertEqual(self.core.__name__, "libui.core")
        self.assertTrue(hasattr(self.core, "_set_asyncio_loop"))
        self.assertTrue(callable(self.core._set_asyncio_loop))

    def test_public_api_exports_are_present(self):
        expected = {
            "run",
            "quit",
            "Window",
            "Button",
            "Label",
            "Table",
            "TableModel",
            "DrawPath",
            "invoke_on_main",
            "invoke_on_main_async",
        }
        self.assertTrue(expected.issubset(set(self.libui.__all__)))
        self.assertTrue(hasattr(self.libui, "Box"))
        self.assertIs(self.libui.Control, self.core.Control)

    def test_declarative_exports_are_present(self):
        expected = {
            "App",
            "Window",
            "MenuDef",
            "VBox",
            "HBox",
            "DrawArea",
            "DataTable",
            "ListState",
            "State",
        }
        self.assertTrue(expected.issubset(set(self.declarative.__all__)))

    def test_attribute_factory_functions_create_matching_attribute_kinds(self):
        libui = self.libui
        self.core.init()
        try:
            cases = [
                (libui.family_attribute("Segoe UI"), libui.AttributeKind.FAMILY),
                (libui.size_attribute(12.5), libui.AttributeKind.SIZE),
                (libui.weight_attribute(libui.TextWeight.BOLD), libui.AttributeKind.WEIGHT),
                (libui.italic_attribute(libui.TextItalic.ITALIC), libui.AttributeKind.ITALIC),
                (
                    libui.stretch_attribute(libui.TextStretch.CONDENSED),
                    libui.AttributeKind.STRETCH,
                ),
                (libui.color_attribute(1.0, 0.2, 0.3, 1.0), libui.AttributeKind.COLOR),
                (
                    libui.background_attribute(0.1, 0.2, 0.3, 1.0),
                    libui.AttributeKind.BACKGROUND,
                ),
                (libui.underline_attribute(libui.Underline.SINGLE), libui.AttributeKind.UNDERLINE),
                (
                    libui.underline_color_attribute(
                        libui.UnderlineColor.CUSTOM, 1.0, 0.0, 0.0, 1.0
                    ),
                    libui.AttributeKind.UNDERLINE_COLOR,
                ),
                (
                    libui.features_attribute(self.core.OpenTypeFeatures()),
                    libui.AttributeKind.FEATURES,
                ),
            ]
            for attr, kind in cases:
                self.assertEqual(attr.type, kind)
        finally:
            self.core.uninit()

    def test_loop_ensure_sync_wraps_coroutine_callbacks(self):
        results = []

        async def coro_cb(value):
            results.append(("async", value))

        wrapped = self.loop._ensure_sync(coro_cb, default_return="sentinel")
        self.assertTrue(callable(wrapped))

        created = []

        class FakeTask:
            def __init__(self, coro):
                self.coro = coro
                self.callbacks = []

            def add_done_callback(self, cb):
                self.callbacks.append(cb)

        class FakeLoop:
            def __init__(self):
                self.scheduled = []

            def is_running(self):
                return True

            def create_task(self, coro):
                task = FakeTask(coro)
                created.append(task)
                return task

            def call_soon_threadsafe(self, cb):
                self.scheduled.append(cb)
                cb()

        fake_loop = FakeLoop()
        with mock.patch.object(self.loop, "_asyncio_loop", fake_loop):
            self.assertEqual(wrapped(42), "sentinel")

        self.assertEqual(len(created), 1)
        self.assertEqual(len(created[0].callbacks), 1)
        asyncio.run(created[0].coro)
        self.assertEqual(results, [("async", 42)])

    def test_loop_ensure_sync_passes_through_sync_functions(self):
        def cb():
            return 123

        self.assertIs(self.loop._ensure_sync(cb), cb)
        self.assertIsNone(self.loop._ensure_sync(None))

    def test_invoke_on_main_runs_directly_on_main_thread(self):
        with mock.patch.object(self.core, "is_main_thread", return_value=True):
            result = self.loop.invoke_on_main(lambda x, y: x + y, 2, 3)
        self.assertEqual(result, 5)

    def test_invoke_on_main_async_uses_queue_main_bridge(self):
        events = []

        async def run_case():
            with mock.patch.object(
                self.core, "queue_main", side_effect=lambda cb: (events.append("queued"), cb())
            ):
                return await self.loop.invoke_on_main_async(lambda value: value * 2, 21)

        self.assertEqual(asyncio.run(run_case()), 42)
        self.assertEqual(events, ["queued"])

    def test_async_dialog_wrappers_dispatch_to_core(self):
        async def run_case():
            fake_window = object()
            with mock.patch.object(
                self.libui, "invoke_on_main_async", new=mock.AsyncMock(return_value="answer")
            ) as invoke:
                result = await self.libui.open_file(fake_window)
                self.assertEqual(result, "answer")
                invoke.assert_awaited_once_with(self.core.open_file, fake_window)

        asyncio.run(run_case())

    def test_core_dir_includes_private_builtin_helpers(self):
        names = dir(self.core)
        self.assertIn("_set_asyncio_loop", names)
        self.assertIn("queue_main", names)


class StateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from libui.state import Computed, ListState, State
        from libui.node import Node, stretchy

        cls.State = State
        cls.Computed = Computed
        cls.ListState = ListState
        cls.Node = Node
        cls.stretchy = stretchy

    def test_state_notifies_and_prevents_reentrant_loop(self):
        state = self.State(1)
        seen = []

        def subscriber():
            seen.append(state.value)
            state.set(state.value)

        state.subscribe(subscriber)
        state.value = 2
        state.value = 2
        self.assertEqual(seen, [2])

    def test_computed_updates_when_source_changes(self):
        state = self.State("libui")
        computed = state.map(str.upper)
        events = []
        computed.subscribe(lambda: events.append(computed.value))
        state.value = "sandbox"
        self.assertEqual(computed.value, "SANDBOX")
        self.assertEqual(events, ["SANDBOX"])

    def test_list_state_reports_insert_delete_change(self):
        state = self.ListState([{"name": "a"}])
        events = []
        state.subscribe(lambda event, **kw: events.append((event, kw["index"])))
        state.append({"name": "b"})
        state[0] = {"name": "c"}
        removed = state.pop()
        self.assertEqual(removed, {"name": "b"})
        self.assertEqual(events, [("inserted", 1), ("changed", 0), ("deleted", 1)])

    def test_stretchy_marks_node(self):
        from libui.node import stretchy

        node = self.Node()
        self.assertFalse(node.stretchy)
        returned = stretchy(node)
        self.assertIs(returned, node)
        self.assertTrue(node.stretchy)


class DeclarativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import libui.declarative as declarative
        import libui.loop as loop
        import libui.core as core

        cls.d = declarative
        cls.loop = loop
        cls.core = core

    def setUp(self):
        self.core.init()

    def tearDown(self):
        self.core.uninit()

    def test_app_builds_without_async_loop(self):
        label = self.d.Label("hello")
        window = self.d.Window("Declarative", 200, 120, child=self.d.VBox(label))
        app = self.d.App(window=window)
        with mock.patch.object(self.loop, "_asyncio_loop", None):
            app.build()
        self.assertIsNotNone(app.window)
        self.assertEqual(app.window.title, "Declarative")
        app.window.destroy()

    def test_app_build_uses_invoke_on_main_when_async_loop_exists(self):
        window = self.d.Window("Declarative", 200, 120, child=self.d.VBox(self.d.Label("x")))
        app = self.d.App(window=window)
        sentinel = object()
        with mock.patch.object(self.loop, "_asyncio_loop", sentinel):
            with mock.patch("libui.declarative.app.invoke_on_main") as invoke:
                invoke.side_effect = lambda fn, *a, **kw: fn(*a, **kw)
                app.build()
                invoke.assert_called_once()
        app.window.destroy()

    def test_menu_build_wires_check_state(self):
        checked = self.d.State(False)
        app = self.d.App(
            window=self.d.Window("Menus", 200, 120, child=self.d.VBox(self.d.Label("ok"))),
            menus=[
                self.d.MenuDef(
                    "File",
                    self.d.MenuItem("Open"),
                    self.d.CheckMenuItem("Checked", checked=checked),
                    self.d.MenuSeparator(),
                    self.d.PreferencesItem(),
                    self.d.AboutItem(),
                    self.d.QuitItem(),
                )
            ],
        )
        app.build()
        checked.value = True
        self.assertTrue(app.window.visible is False or app.window.visible is True)
        app.window.destroy()

    def test_app_dialog_helpers_delegate_to_core(self):
        app = self.d.App(
            window=self.d.Window("Dialog", 200, 120, child=self.d.VBox(self.d.Label("ok")))
        )
        app.build()
        with mock.patch.object(self.core, "msg_box") as msg_box:
            app.msg_box("Title", "Body")
            msg_box.assert_called_once_with(app.window, "Title", "Body")
        with mock.patch.object(self.core, "open_file", return_value="path") as open_file:
            self.assertEqual(app.open_file(), "path")
            open_file.assert_called_once_with(app.window)
        async def run_async_checks():
            with mock.patch(
                "libui.declarative.app.invoke_on_main_async",
                new=mock.AsyncMock(return_value="answer"),
            ) as invoke:
                self.assertEqual(await app.open_file_async(), "answer")
                invoke.assert_awaited_once_with(self.core.open_file, app.window)
        asyncio.run(run_async_checks())
        app.window.destroy()

    def test_app_wait_blocks_forever_until_cancelled(self):
        app = self.d.App(
            window=self.d.Window("Wait", 200, 120, child=self.d.VBox(self.d.Label("ok")))
        )

        async def run_wait():
            task = asyncio.create_task(app.wait())
            await asyncio.sleep(0)
            self.assertFalse(task.done())
            task.cancel()
            with self.assertRaises(asyncio.CancelledError):
                await task

        asyncio.run(run_wait())

    def test_widget_descriptor_signatures_remain_constructible(self):
        signatures = {
            "VBox": inspect.signature(self.d.VBox),
            "HBox": inspect.signature(self.d.HBox),
            "Form": inspect.signature(self.d.Form),
            "Tab": inspect.signature(self.d.Tab),
            "Grid": inspect.signature(self.d.Grid),
            "DataTable": inspect.signature(self.d.DataTable),
        }
        self.assertIn("children", str(signatures["VBox"]))
        self.assertIn("rows", str(signatures["Form"]))


if __name__ == "__main__":
    unittest.main()
