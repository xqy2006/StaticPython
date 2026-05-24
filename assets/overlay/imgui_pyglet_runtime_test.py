import ctypes
from ctypes import wintypes
import os
import time

import imgui
import pyglet
from pyglet.gl.lib import MissingFunctionException
from imgui.integrations.pyglet import create_renderer


pyglet.options["debug_gl"] = False
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


def _window_is_visible(title: str) -> bool:
    return any(window_title == title for window_title, _klass in _enum_visible_windows_for_current_process())


def main() -> None:
    title = "StaticPython imgui pyglet runtime"
    ctx = imgui.create_context()
    try:
        window = pyglet.window.Window(width=480, height=320, caption=title, visible=True)
    except MissingFunctionException as exc:
        # GitHub's Windows runner may expose only the generic OpenGL 1.1
        # driver. That is an environment limit, not a pyimgui static-link
        # failure, so keep this backend test active wherever OpenGL exists.
        print(f"imgui_pyglet_runtime_skipped opengl_unavailable={exc}", flush=True)
        imgui.destroy_context(ctx)
        return
    renderer = create_renderer(window)
    state = {"frames": 0, "saw_window": False}

    @window.event
    def on_draw():
        renderer.process_inputs()
        imgui.new_frame()
        imgui.set_next_window_size(320, 160)
        imgui.begin("StaticPython")
        imgui.text("pyimgui + pyglet")
        imgui.button("Button")
        imgui.slider_float("Value", 0.5, 0.0, 1.0)
        imgui.end()

        window.clear()
        imgui.render()
        renderer.render(imgui.get_draw_data())
        state["frames"] += 1
        if _window_is_visible(title):
            state["saw_window"] = True
        if state["frames"] >= 4:
            window.close()

    pyglet.clock.schedule_once(lambda _dt: window.close(), 8.0)
    try:
        pyglet.app.run()
        assert state["frames"] >= 1
        assert state["saw_window"]
        print(f"imgui_pyglet_runtime_ok frames={state['frames']}", flush=True)
    finally:
        try:
            renderer.shutdown()
        finally:
            imgui.destroy_context(ctx)
            time.sleep(0.05)


if __name__ == "__main__":
    main()
