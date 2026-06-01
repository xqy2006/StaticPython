import ctypes
from ctypes import wintypes
import os
import time

import glfw
import imgui
from OpenGL import GL
from OpenGL.error import NullFunctionError
from imgui.integrations.glfw import GlfwRenderer


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
    title = "StaticPython imgui glfw runtime"
    errors = []

    def error_callback(code, message):
        errors.append((code, message))

    glfw.set_error_callback(error_callback)
    if not glfw.init():
        print(f"imgui_glfw_runtime_skipped glfw_init_failed={errors!r}", flush=True)
        return

    ctx = imgui.create_context()
    renderer = None
    window = None
    try:
        glfw.window_hint(glfw.CONTEXT_VERSION_MAJOR, 2)
        glfw.window_hint(glfw.CONTEXT_VERSION_MINOR, 0)
        glfw.window_hint(glfw.VISIBLE, glfw.TRUE)
        window = glfw.create_window(480, 320, title, None, None)
        if window is None:
            print(f"imgui_glfw_runtime_skipped create_window_failed={errors!r}", flush=True)
            return

        glfw.make_context_current(window)
        glfw.swap_interval(0)
        try:
            GL.glGetError()
        except (NullFunctionError, AttributeError) as exc:
            print(f"imgui_glfw_runtime_skipped opengl_unavailable={exc}", flush=True)
            return

        renderer = GlfwRenderer(window)
        frames = 0
        saw_window = False
        deadline = time.monotonic() + 8.0
        while not glfw.window_should_close(window) and time.monotonic() < deadline:
            glfw.poll_events()
            renderer.process_inputs()
            imgui.new_frame()
            imgui.set_next_window_size(320, 160)
            expanded, _opened = imgui.begin("StaticPython")
            if expanded:
                imgui.text("pyimgui + static GLFW")
                assert isinstance(imgui.button("Button"), bool)
                changed, value = imgui.slider_float("Value", 0.5, 0.0, 1.0)
                assert isinstance(changed, bool)
                assert 0.0 <= value <= 1.0
            imgui.end()
            GL.glViewport(0, 0, *glfw.get_framebuffer_size(window))
            GL.glClearColor(0.1, 0.15, 0.18, 1.0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            imgui.render()
            renderer.render(imgui.get_draw_data())
            glfw.swap_buffers(window)
            frames += 1
            if _window_is_visible(title):
                saw_window = True
            if frames >= 4 and saw_window:
                break

        assert frames >= 1
        assert saw_window
        print(f"imgui_glfw_runtime_ok frames={frames}", flush=True)
    finally:
        try:
            if renderer is not None:
                renderer.shutdown()
        finally:
            if window is not None:
                glfw.destroy_window(window)
            imgui.destroy_context(ctx)
            glfw.terminate()
            time.sleep(0.05)


if __name__ == "__main__":
    main()
