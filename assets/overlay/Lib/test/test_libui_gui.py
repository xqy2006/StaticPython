import asyncio
import ctypes
from ctypes import wintypes
import time
import unittest

import libui
import libui.declarative as declarative


user32 = ctypes.WinDLL("user32", use_last_error=True)


WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _enum_windows_for_pid(pid):
    windows = []

    @WNDENUMPROC
    def callback(hwnd, lparam):
        process_id = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(process_id))
        if process_id.value == pid and user32.IsWindowVisible(hwnd):
            length = user32.GetWindowTextLengthW(hwnd)
            title = ctypes.create_unicode_buffer(length + 1)
            klass = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, len(title))
            user32.GetClassNameW(hwnd, klass, len(klass))
            windows.append((title.value, klass.value))
        return True

    user32.EnumWindows(callback, 0)
    return windows


class LibuiGuiIntegrationTests(unittest.TestCase):
    def _wait_for_window(self, expected_title, timeout=5.0):
        pid = ctypes.windll.kernel32.GetCurrentProcessId()
        deadline = time.perf_counter() + timeout
        last_windows = []
        while time.perf_counter() < deadline:
            last_windows = _enum_windows_for_pid(pid)
            if any(title == expected_title for title, _klass in last_windows):
                return last_windows
            time.sleep(0.05)
        self.fail(f"window {expected_title!r} was not created, saw {last_windows!r}")

    def test_proxy_widgets_window(self):
        title = "libui proxy widgets"
        results = {}

        async def main():
            box = libui.VerticalBox(padded=True)
            hbox = libui.HorizontalBox(padded=True)
            label = libui.Label("Hello")
            label.hide()
            label.show()
            label.disable()
            label.enable()

            button = libui.Button("Press")
            button.text = "Press Me"
            button.on_clicked(lambda: None)

            entry = libui.Entry()
            entry.text = "sample"
            entry.read_only = True
            entry.read_only = False
            entry.on_changed(lambda: None)

            checkbox = libui.Checkbox("Flag")
            checkbox.checked = True
            checkbox.on_toggled(lambda: None)

            combo = libui.Combobox()
            combo.append("One")
            combo.append("Two")
            combo.selected = 1
            combo.on_selected(lambda: None)

            editable = libui.EditableCombobox()
            editable.append("Editable")
            editable.text = "Typed"
            editable.on_changed(lambda: None)

            radio = libui.RadioButtons()
            radio.append("A")
            radio.append("B")
            radio.selected = 0
            radio.on_selected(lambda: None)

            slider = libui.Slider(0, 100)
            slider.value = 10
            slider.has_tooltip = True
            slider.set_range(0, 200)
            slider.on_changed(lambda: None)
            slider.on_released(lambda: None)

            spinbox = libui.Spinbox(0, 10)
            spinbox.value = 3
            spinbox.on_changed(lambda: None)

            progress = libui.ProgressBar()
            progress.value = 55

            color_button = libui.ColorButton()
            color_button.color = (0.2, 0.4, 0.6, 1.0)
            color_button.on_changed(lambda: None)

            font_button = libui.FontButton()
            font_button.on_changed(lambda: None)
            results["font_keys"] = sorted(font_button.font.keys())

            date_picker = libui.DateTimePicker(type="date")
            date_picker.on_changed(lambda: None)

            multiline = libui.MultilineEntry(wrapping=True)
            multiline.text = "Line 1"
            multiline.append("\nLine 2")
            multiline.read_only = True
            multiline.read_only = False
            multiline.on_changed(lambda: None)

            separator = libui.Separator(vertical=False)

            form = libui.Form()
            form.padded = True
            form.append("Entry", entry)
            form.append("Checkbox", checkbox, stretchy=True)

            group = libui.Group("Group")
            group.title = "Changed Group"
            group.margined = True
            group.set_child(form)

            grid = libui.Grid()
            grid.padded = True
            grid.append(button, 0, 0, 1, 1, False, libui.Align.FILL, False, libui.Align.FILL)
            inserted = libui.Label("Inserted")
            grid.insert_at(
                inserted,
                button,
                libui.At.TRAILING,
                1,
                1,
                False,
                libui.Align.FILL,
                False,
                libui.Align.FILL,
            )

            tab = libui.Tab()
            tab.append("Form", group)
            tab.append("Grid", grid)
            tab.set_margined(0, True)
            tab.selected = 0
            tab.on_selected(lambda: None)

            hbox.append(tab, stretchy=True)
            hbox.append(separator)
            box.append(label)
            box.append(hbox, stretchy=True)
            box.append(combo)
            box.append(editable)
            box.append(radio)
            box.append(slider)
            box.append(spinbox)
            box.append(progress)
            box.append(color_button)
            box.append(font_button)
            box.append(date_picker)
            box.append(multiline, stretchy=True)

            window = libui.Window(title, 720, 620, has_menubar=False)
            window.margined = True
            window.borderless = False
            window.fullscreen = False
            window.resizeable = True
            window.on_closing(lambda: True)
            window.set_child(box)
            window.show()

            self._wait_for_window(title)
            results["window_title"] = window.title
            results["window_visible"] = libui.invoke_on_main(lambda: window._core.visible)
            results["button_text"] = button.text
            results["entry_text"] = entry.text
            results["checkbox_checked"] = checkbox.checked
            results["combo_selected"] = combo.selected
            results["editable_text"] = editable.text
            results["radio_selected"] = radio.selected
            results["slider_value"] = slider.value
            results["spinbox_value"] = spinbox.value
            results["progress_value"] = progress.value
            results["group_title"] = group.title
            results["tab_pages"] = tab.num_pages()
            results["tab_margined"] = tab.margined(0)

            await asyncio.sleep(0.4)
            window.hide()
            results["window_hidden"] = libui.invoke_on_main(lambda: window._core.visible)
            window.show()
            await asyncio.sleep(0.4)
            libui.quit()

        libui.run(main())

        self.assertEqual(results["window_title"], title)
        self.assertTrue(results["window_visible"])
        self.assertEqual(results["button_text"], "Press Me")
        self.assertEqual(results["entry_text"], "sample")
        self.assertTrue(results["checkbox_checked"])
        self.assertEqual(results["combo_selected"], 1)
        self.assertEqual(results["editable_text"], "Typed")
        self.assertEqual(results["radio_selected"], 0)
        self.assertEqual(results["slider_value"], 10)
        self.assertEqual(results["spinbox_value"], 3)
        self.assertEqual(results["progress_value"], 55)
        self.assertEqual(results["group_title"], "Changed Group")
        self.assertEqual(results["tab_pages"], 2)
        self.assertTrue(results["tab_margined"])
        self.assertFalse(results["window_hidden"])
        self.assertIn("family", results["font_keys"])

    def test_core_draw_objects_on_main_thread(self):
        results = {}

        def run_case():
            features = libui.OpenTypeFeatures()
            features.add("liga", True)
            clone = features.clone()
            clone.remove("liga")
            results["feature_get"] = features.get("liga")
            results["feature_removed"] = clone.get("liga")

            attr_string = libui.AttributedString("draw text")
            attr_string.set_attribute(
                libui.color_attribute(0.1, 0.2, 0.3, 1.0), 0, attr_string.length
            )
            attr_string.set_attribute(
                libui.features_attribute(features), 0, attr_string.length
            )
            seen = []
            attr_string.for_each_attribute(
                lambda attr, start, end: (seen.append((attr.type, start, end)), libui.ForEach.CONTINUE)[1]
            )
            results["attr_ranges"] = seen
            results["graphemes"] = attr_string.num_graphemes()
            results["byte_index"] = attr_string.grapheme_to_byte_index(3)
            results["grapheme_index"] = attr_string.byte_index_to_grapheme(3)

            image = libui.Image(2, 2)
            image.append(bytes([255, 0, 0, 255] * 4), 2, 2, 8)

            path = libui.DrawPath(fill_mode=libui.FillMode.WINDING)
            path.new_figure(0, 0)
            path.line_to(30, 0)
            path.bezier_to(20, 20, 10, 25, 0, 30)
            path.close_figure()
            path.end()

            arc_path = libui.DrawPath(fill_mode=libui.FillMode.ALTERNATE)
            arc_path.new_figure_with_arc(10, 10, 5, 0, 3.14 / 2, 0)
            arc_path.end()

            rect_path = libui.DrawPath(fill_mode=libui.FillMode.WINDING)
            rect_path.add_rectangle(5, 5, 10, 10)
            rect_path.end()

            brush = libui.DrawBrush()
            brush.type = libui.BrushType.LINEAR_GRADIENT
            brush.x0 = 0
            brush.y0 = 0
            brush.x1 = 100
            brush.y1 = 100
            brush.set_stops([(0.0, 1.0, 0.0, 0.0, 1.0), (1.0, 0.0, 0.0, 1.0, 1.0)])

            stroke = libui.DrawStrokeParams()
            stroke.cap = libui.LineCap.ROUND
            stroke.join = libui.LineJoin.BEVEL
            stroke.thickness = 2.0
            stroke.set_dashes([1.0, 2.0])

            matrix = libui.DrawMatrix()
            matrix.translate(4, 5)
            matrix.scale(0, 0, 2, 2)
            matrix.rotate(0, 0, 15)
            matrix.skew(0, 0, 0.1, 0.2)
            point = matrix.transform_point(1, 2)
            size = matrix.transform_size(3, 4)
            other = libui.DrawMatrix()
            other.translate(1, 1)
            matrix.multiply(other)

            font = libui.FontButton().font
            layout = libui.DrawTextLayout(attr_string, font, 200)
            results["layout_extents"] = layout.extents()
            results["path_ended"] = path.ended
            results["arc_ended"] = arc_path.ended
            results["rect_ended"] = rect_path.ended
            results["matrix_point"] = point
            results["matrix_size"] = size
            results["matrix_invertible"] = matrix.invertible()
            results["matrix_inverted"] = matrix.invert()

        import libui.core as core

        core.init()
        try:
            run_case()
        finally:
            core.uninit()
        self.assertTrue(results["feature_get"])
        self.assertFalse(results["feature_removed"])
        self.assertGreaterEqual(len(results["attr_ranges"]), 2)
        self.assertEqual(results["graphemes"], len("draw text"))
        self.assertEqual(results["byte_index"], 3)
        self.assertEqual(results["grapheme_index"], 3)
        self.assertTrue(results["path_ended"])
        self.assertTrue(results["arc_ended"])
        self.assertTrue(results["rect_ended"])
        self.assertEqual(len(results["layout_extents"]), 2)
        self.assertEqual(len(results["matrix_point"]), 2)
        self.assertEqual(len(results["matrix_size"]), 2)
        self.assertTrue(results["matrix_invertible"])
        self.assertTrue(results["matrix_inverted"])

    def test_table_and_menu_core_objects(self):
        results = {}

        def run_case():
            menu = libui.Menu("File")
            item = menu.append_item("Open")
            check = menu.append_check_item("Checked")
            menu.append_separator()
            menu.append_preferences_item()
            menu.append_about_item()
            menu.append_quit_item()
            item.on_clicked(lambda: None)
            check.on_clicked(lambda: None)
            check.checked = True
            results["menu_checked"] = check.checked

            rows = [{"name": "row1", "checked": 1, "progress": 42, "action": "Go"}]

            def num_columns():
                return 4

            def column_type(col):
                return (
                    libui.TableValueType.STRING,
                    libui.TableValueType.INT,
                    libui.TableValueType.INT,
                    libui.TableValueType.STRING,
                )[col]

            def num_rows():
                return len(rows)

            def cell_value(row, col):
                return (
                    rows[row]["name"],
                    rows[row]["checked"],
                    rows[row]["progress"],
                    rows[row]["action"],
                )[col]

            def set_cell_value(row, col, value):
                if col == 0:
                    rows[row]["name"] = value

            model = libui.TableModel(
                num_columns, column_type, num_rows, cell_value, set_cell_value
            )
            table = libui.Table(model)
            table.append_text_column("Name", 0, libui.TableModelColumn.ALWAYS_EDITABLE, -1)
            table.append_checkbox_column("Checked", 1, libui.TableModelColumn.ALWAYS_EDITABLE)
            table.append_progress_bar_column("Progress", 2)
            table.append_button_column("Action", 3, libui.TableModelColumn.ALWAYS_EDITABLE)
            table.set_column_width(0, 120)
            table.header_set_sort_indicator(0, libui.SortIndicator.ASCENDING)
            table.selection_mode = libui.SelectionMode.ZERO_OR_ONE
            model.row_changed(0)
            model.row_inserted(0)
            model.row_deleted(0)
            results["table_width"] = table.column_width(0)
            results["table_sort"] = table.header_sort_indicator(0)

        import libui.core as core

        core.init()
        try:
            run_case()
        finally:
            core.uninit()
        self.assertTrue(results["menu_checked"])
        self.assertGreaterEqual(results["table_width"], 0)
        self.assertIn(
            results["table_sort"],
            (libui.SortIndicator.NONE, libui.SortIndicator.ASCENDING, 0, 1),
        )

    def test_area_and_scrolling_area_window(self):
        title = "libui draw areas"
        results = {"draw_calls": 0}

        def make_draw_resources():
            attr_string = libui.AttributedString("draw")
            path = libui.DrawPath()
            path.add_rectangle(0, 0, 40, 30)
            path.end()
            brush = libui.DrawBrush()
            brush.type = libui.BrushType.SOLID
            brush.r = 0.2
            brush.g = 0.4
            brush.b = 0.7
            brush.a = 1.0
            stroke = libui.DrawStrokeParams()
            stroke.thickness = 1.0
            font = libui.FontButton().font
            return {"attr": attr_string, "path": path, "brush": brush, "stroke": stroke, "font": font}

        async def main():
            resources = libui.invoke_on_main(make_draw_resources)

            def on_draw(ctx, area_w, area_h, clip_x, clip_y, clip_w, clip_h):
                results["draw_calls"] += 1
                layout = libui.DrawTextLayout(resources["attr"], resources["font"], 200)
                ctx.fill(resources["path"], resources["brush"])
                ctx.stroke(resources["path"], resources["brush"], resources["stroke"])
                ctx.text(layout, 2, 2)

            area = libui.invoke_on_main(lambda: libui.Area(on_draw))
            scrolling = libui.invoke_on_main(lambda: libui.ScrollingArea(on_draw, 200, 200))
            box = libui.VerticalBox(padded=True)
            box.append(area, stretchy=True)
            box.append(scrolling, stretchy=True)

            window = libui.Window(title, 500, 400)
            window.set_child(box)
            window.show()
            self._wait_for_window(title)
            await asyncio.sleep(0.5)
            libui.invoke_on_main(area.queue_redraw_all)
            libui.invoke_on_main(scrolling.queue_redraw_all)
            await asyncio.sleep(0.8)
            libui.quit()

        libui.run(main())
        self.assertGreater(results["draw_calls"], 0)

    def test_declarative_widgets_and_app(self):
        title = "libui declarative coverage"
        results = {"draw_calls": 0}

        async def main():
            checked_state = declarative.State(True)
            text_state = declarative.State("hello")
            slider_state = declarative.State(25)
            spin_state = declarative.State(2)
            combo_state = declarative.State(1)
            radio_state = declarative.State(0)
            editable_state = declarative.State("editable")
            multi_state = declarative.State("line1")
            group_title = declarative.State("Group State")
            table_data = declarative.ListState(
                [{"name": "row", "checked": 1, "progress": 50, "action": "Run"}]
            )

            def on_draw(*args):
                results["draw_calls"] += 1

            draw_area_node = declarative.DrawArea(on_draw=on_draw)
            scrolling_area_node = declarative.ScrollingDrawArea(
                on_draw=on_draw, width=400, height=300
            )
            tab_node = declarative.Tab(
                (
                    "Lists",
                    declarative.VBox(
                        declarative.Combobox(["One", "Two"], combo_state),
                        declarative.RadioButtons(["A", "B"], radio_state),
                        declarative.EditableCombobox(["editable"], editable_state),
                        declarative.MultilineEntry(multi_state),
                        declarative.Separator(),
                    ),
                ),
                (
                    "Drawing",
                    declarative.Grid(
                        declarative.GridCell(draw_area_node, 0, 0, hexpand=True, vexpand=True),
                        declarative.GridCell(
                            scrolling_area_node, 1, 0, hexpand=True, vexpand=True
                        ),
                    ),
                ),
            )

            app = declarative.App(
                window=declarative.Window(
                    title=title,
                    width=860,
                    height=720,
                    has_menubar=True,
                    child=declarative.VBox(
                        declarative.Label(text_state.map(lambda value: value.upper())),
                        declarative.HBox(
                            declarative.Group(
                                group_title,
                                declarative.Form(
                                    ("Entry", declarative.Entry(text_state, on_changed=lambda value: None)),
                                    ("Checkbox", declarative.Checkbox("Checked", checked_state)),
                                    ("Slider", declarative.Slider(0, 100, slider_state)),
                                    ("Spinbox", declarative.Spinbox(0, 10, spin_state)),
                                    (
                                        "Progress",
                                        declarative.ProgressBar(
                                            slider_state.map(lambda value: min(100, value))
                                        ),
                                    ),
                                ),
                            ),
                            tab_node,
                        ),
                        declarative.DataTable(
                            table_data,
                            declarative.TextColumn("Name", "name", editable=True, width=150),
                            declarative.CheckboxColumn("Checked", "checked", editable=True),
                            declarative.ProgressColumn("Progress", "progress", width=120),
                            declarative.ButtonColumn("Action", "action", on_click=lambda row: None),
                        ),
                    ),
                ),
                menus=[
                    declarative.MenuDef(
                        "File",
                        declarative.MenuItem("Open", on_click=lambda: None),
                        declarative.CheckMenuItem("Checked", checked=checked_state),
                        declarative.MenuSeparator(),
                        declarative.PreferencesItem(),
                        declarative.AboutItem(),
                        declarative.QuitItem(),
                    )
                ],
            )

            app.build()
            app.show()
            self._wait_for_window(title)
            checked_state.value = False
            text_state.value = "changed"
            slider_state.value = 75
            spin_state.value = 5
            combo_state.value = 0
            radio_state.value = 1
            editable_state.value = "changed text"
            multi_state.value = "line2"
            group_title.value = "Updated Group"
            table_data[0] = {"name": "row2", "checked": 0, "progress": 80, "action": "Run"}

            libui.invoke_on_main(lambda: setattr(tab_node.widget, "selected", 1))
            libui.invoke_on_main(draw_area_node.widget.queue_redraw_all)
            libui.invoke_on_main(scrolling_area_node.widget.queue_redraw_all)
            await asyncio.sleep(1.0)
            results["window_title"] = libui.invoke_on_main(lambda: app.window.title)
            results["window_visible"] = libui.invoke_on_main(lambda: app.window.visible)
            libui.quit()

        libui.run(main())
        self.assertEqual(results["window_title"], title)
        self.assertTrue(results["window_visible"])
        self.assertGreater(results["draw_calls"], 0)


if __name__ == "__main__":
    unittest.main()
