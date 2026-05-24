import time

import glfw
import imgui
from imgui.integrations.glfw import GlfwRenderer
from OpenGL import GL


def main() -> None:
    if not glfw.init():
        raise RuntimeError("glfw.init() failed")

    window = None
    impl = None
    ctx = None
    try:
        glfw.window_hint(glfw.VISIBLE, glfw.FALSE)
        window = glfw.create_window(320, 180, "StaticPython imgui glfw runtime", None, None)
        if not window:
            raise RuntimeError("glfw.create_window() failed")

        glfw.make_context_current(window)
        ctx = imgui.create_context()
        impl = GlfwRenderer(window)

        for _ in range(3):
            glfw.poll_events()
            impl.process_inputs()
            imgui.new_frame()
            imgui.text_unformatted("Hello from StaticPython")
            imgui.button("Button")
            imgui.render()

            width, height = glfw.get_framebuffer_size(window)
            GL.glViewport(0, 0, width, height)
            GL.glClearColor(0.1, 0.2, 0.3, 1.0)
            GL.glClear(GL.GL_COLOR_BUFFER_BIT)
            impl.render(imgui.get_draw_data())
            glfw.swap_buffers(window)
            time.sleep(0.02)
    finally:
        if impl is not None:
            impl.shutdown()
        if ctx is not None:
            imgui.destroy_context(ctx)
        if window is not None:
            glfw.destroy_window(window)
        glfw.terminate()
    print("imgui_glfw_runtime_ok", flush=True)


if __name__ == "__main__":
    main()
