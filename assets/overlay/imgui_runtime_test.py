import imgui


def _configure_io() -> None:
    io = imgui.get_io()
    io.display_size = 640, 480
    io.delta_time = 1.0 / 60.0
    io.fonts.add_font_default()
    io.fonts.get_tex_data_as_rgba32()
    io.fonts.texture_id = 1


def main() -> None:
    ctx = imgui.create_context()
    try:
        _configure_io()
        for frame in range(3):
            imgui.new_frame()
            expanded, opened = imgui.begin("StaticPython imgui runtime", True)
            assert opened
            if expanded:
                imgui.text("imgui widget smoke")
                assert isinstance(imgui.button("Button"), bool)
                changed, checked = imgui.checkbox("Check", frame % 2 == 0)
                assert isinstance(changed, bool)
                assert isinstance(checked, bool)
                changed, value = imgui.slider_float("Float", 0.25, 0.0, 1.0)
                assert isinstance(changed, bool)
                assert 0.0 <= value <= 1.0
                changed, text = imgui.input_text("Text", "staticpython", 64)
                assert isinstance(changed, bool)
                assert isinstance(text, str)
                imgui.separator()
                imgui.begin_child("child", 180, 60, border=True)
                imgui.text("child content")
                imgui.end_child()
            imgui.end()
            imgui.render()
            draw_data = imgui.get_draw_data()
            assert draw_data is not None
            assert draw_data.commands_lists_count >= 0
        print("imgui_runtime_ok", flush=True)
    finally:
        imgui.destroy_context(ctx)


if __name__ == "__main__":
    main()
