import ctypes
from ctypes import wintypes
import os
import time

from fltk import *


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
        check()
        last_windows = _enum_visible_windows_for_current_process()
        if any(window_title == title for window_title, _klass in last_windows):
            return last_windows
        time.sleep(0.05)
    raise RuntimeError(f"window {title!r} was not created, saw {last_windows!r}")


def main() -> None:
    title = "StaticPython pyfltk runtime"
    window = Window(100, 100, 420, 240, title)
    browser = Browser(10, 10, 400, 70)
    browser.add("first row")
    browser.add("second row")
    button = Button(10, 95, 100, 30, "Button")
    check_button = CheckButton(130, 95, 120, 30, "Check")
    check_button.value(1)
    slider = HorValueSlider(10, 140, 260, 24, "Value")
    slider.minimum(0.0)
    slider.maximum(1.0)
    slider.value(0.5)
    output = Output(10, 180, 260, 24, "Output")
    output.value("ready")
    window.end()
    window.show()

    try:
        windows = _wait_for_window(title)
        assert any(window_title == title for window_title, _klass in windows)
        assert button.label() == "Button"
        assert check_button.value() == 1
        assert abs(slider.value() - 0.5) < 0.001
        assert output.value() == "ready"
        print("pyfltk_window_seen", windows, flush=True)
    finally:
        window.hide()
        for _ in range(10):
            check()
            time.sleep(0.02)
    print("pyfltk_runtime_ok", flush=True)


if __name__ == "__main__":
    main()
