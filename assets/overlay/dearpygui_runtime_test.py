import ctypes
from ctypes import wintypes
import os
import time

import dearpygui.dearpygui as dpg


user32 = ctypes.WinDLL("user32", use_last_error=True)
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def _enum_visible_windows_for_current_process():
    pid = os.getpid()
    windows = []

    @WNDENUMPROC
    def callback(hwnd, _lparam):
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


def _wait_for_window(title: str, timeout: float = 5.0):
    deadline = time.perf_counter() + timeout
    last_windows = []
    while time.perf_counter() < deadline:
        last_windows = _enum_visible_windows_for_current_process()
        if any(window_title == title for window_title, _klass in last_windows):
            return last_windows
        dpg.render_dearpygui_frame()
        time.sleep(0.05)
    raise RuntimeError(f"window {title!r} was not created, saw {last_windows!r}")


def main() -> None:
    title = "StaticPython DearPyGui runtime"
    dpg.create_context()
    try:
        with dpg.window(label="Controls", tag="main_window", width=360, height=220):
            dpg.add_text("dearpygui widget smoke")
            dpg.add_button(label="Button", tag="button")
            dpg.add_checkbox(label="Check", tag="check", default_value=True)
            dpg.add_slider_float(label="Float", tag="float", default_value=0.25, min_value=0.0, max_value=1.0)
            dpg.add_input_text(label="Text", tag="text", default_value="staticpython")
        dpg.create_viewport(title=title, width=480, height=320)
        dpg.setup_dearpygui()
        dpg.show_viewport()
        windows = _wait_for_window(title)
        assert any(window_title == title for window_title, _klass in windows)
        assert dpg.get_value("check") is True
        assert dpg.get_value("text") == "staticpython"
        assert abs(dpg.get_value("float") - 0.25) < 0.001
        for _ in range(4):
            dpg.render_dearpygui_frame()
        print("dearpygui_runtime_ok", windows, flush=True)
    finally:
        dpg.destroy_context()


if __name__ == "__main__":
    main()
