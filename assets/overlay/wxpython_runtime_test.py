from __future__ import annotations

import wx


class DemoFrame(wx.Frame):
    def __init__(self) -> None:
        super().__init__(None, title="StaticPython wxPython smoke", size=(420, 260))
        panel = wx.Panel(self)
        box = wx.BoxSizer(wx.VERTICAL)

        title = wx.StaticText(panel, label="wxPython is running from the StaticPython executable.")
        title.SetFont(title.GetFont().Bold())
        box.Add(title, 0, wx.ALL, 12)

        entry = wx.TextCtrl(panel, value="editable text")
        box.Add(entry, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        gauge = wx.Gauge(panel, range=100)
        gauge.SetValue(65)
        box.Add(gauge, 0, wx.EXPAND | wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        buttons = wx.BoxSizer(wx.HORIZONTAL)
        buttons.Add(wx.Button(panel, label="Button"), 0, wx.RIGHT, 8)
        buttons.Add(wx.CheckBox(panel, label="Check box"), 0, wx.ALIGN_CENTER_VERTICAL)
        box.Add(buttons, 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        bitmap = wx.Bitmap(32, 32)
        dc = wx.MemoryDC(bitmap)
        dc.SetBackground(wx.Brush(wx.Colour(44, 128, 196)))
        dc.Clear()
        dc.SetPen(wx.Pen(wx.Colour(255, 255, 255), 3))
        dc.DrawLine(6, 16, 26, 16)
        dc.DrawLine(16, 6, 16, 26)
        dc.SelectObject(wx.NullBitmap)
        box.Add(wx.StaticBitmap(panel, bitmap=bitmap), 0, wx.LEFT | wx.RIGHT | wx.BOTTOM, 12)

        panel.SetSizer(box)


def main() -> int:
    app = wx.App(False)
    frame = DemoFrame()
    frame.Show()

    timer = wx.Timer(frame)
    frame.Bind(wx.EVT_TIMER, lambda event: frame.Close())
    timer.StartOnce(500)
    app.MainLoop()
    app.Destroy()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
