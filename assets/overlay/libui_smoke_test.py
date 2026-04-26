import asyncio
import time

import libui


async def main():
    box = libui.VerticalBox(padded=True)
    box.append(libui.Label("libui builtin smoke test"))
    box.append(libui.Button("OK"))

    win = libui.Window("libui smoke", 320, 120)
    win.margined = True
    win.set_child(box)
    win.show()
    print("window_shown", flush=True)

    await asyncio.sleep(6.0)
    print("quit_requested", flush=True)
    libui.quit()


if __name__ == "__main__":
    started = time.perf_counter()
    print("smoke_start", flush=True)
    libui.run(main())
    print(f"smoke_done elapsed={time.perf_counter() - started:.3f}", flush=True)
