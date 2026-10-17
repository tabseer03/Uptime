"""A small on-screen pop-up with today's wasted time, like Windows' volume or "plugged in" OSD.

Click-through, never takes focus, hidden from screen capture (see osd.py). It fades in at
the top-left corner, stays a few seconds and fades away. The tracker starts it as a
short-lived process:

    pythonw toast.pyw back [seconds_away]
    pythonw toast.pyw distracted "Shopping|flipkart"
"""
import ctypes
import random
import sys
import time
from ctypes import wintypes

from common import connect, fmt_dur, load_pause, wasted_today
from osd import (ACCENT, FW_SEMIBOLD, MUTED, PINK, TEXT, OSDWindow, single_instance, user32)

BACK_LINES = ["Welcome back", "Back at it", "There you are"]
NUDGES = ["Is this worth it?", "Close it and get back to work", "This is going on your record",
          "Your future self is watching", "One more minute? Sure..."]


def message(kind, arg):
    """(icon glyph, icon colour, small line, big line)."""
    conn = connect()
    try:
        total = fmt_dur(wasted_today(conn))
    finally:
        conn.close()
    if kind == "distracted":
        rule, _, kw = (arg or "Distracted").partition("|")
        what = f"{rule} · {kw}" if kw else rule
        return "", PINK, f"{what}  —  {random.choice(NUDGES)}", f"{total} wasted today"
    away = ""
    try:
        if arg and float(arg) >= 60:
            away = f"  ·  away {fmt_dur(float(arg))}"
    except ValueError:
        pass
    return "", ACCENT, random.choice(BACK_LINES) + away, f"{total} wasted today"


def below_other_popup(x, y, k):
    """If a "work?" prompt is showing in the corner, sit just below it."""
    other = user32.FindWindowW("UptimeAsk", None)
    if other:
        r = wintypes.RECT()
        user32.GetWindowRect(other, ctypes.byref(r))
        return x, r.bottom + int(10 * k)
    return x, y


class Toast(OSDWindow):
    CLASS = "UptimeToast"

    def __init__(self, glyph, color, small, big):
        k = self.scale()
        self.glyph, self.color, self.small, self.big = glyph, color, small, big
        self.f_small = self.font("Segoe UI Variable Text", 9, k=k)
        self.f_big = self.font("Segoe UI Variable Display", 15, FW_SEMIBOLD, k=k)
        self.f_icon = self.font("Segoe Fluent Icons", 15, k=k)
        text_w = max(self.measure(self.f_small, small), self.measure(self.f_big, big))
        super().__init__(int((16 + 40 + 14 + 22) * k) + text_w, int(72 * k))

    def position(self):
        x, y = super().position()
        return below_other_popup(x, y, self.k)

    def draw(self, dc):
        left = self.icon_tile(dc, self.glyph, self.color, self.f_icon)
        self.text(dc, self.f_small, MUTED, self.small, wintypes.RECT(left, self.px(12), self.w, self.px(32)))
        self.text(dc, self.f_big, TEXT, self.big, wintypes.RECT(left, self.px(30), self.w, self.px(60)))


def main():
    pause = load_pause()
    if pause and time.time() < pause["until"]:
        return  # paused: show nothing
    if not single_instance("UptimeToast"):
        return  # one pop-up at a time
    kind = sys.argv[1] if len(sys.argv) > 1 else "back"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    Toast(*message(kind, arg)).run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a pop-up must never bother you with an error
