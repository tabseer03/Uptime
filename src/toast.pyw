"""A small on-screen pop-up with today's wasted time, like Windows' volume or "plugged in" OSD.

Click-through, never takes focus, hidden from screen capture (see osd.py). It fades in at
the top-left corner, stays a few seconds and fades away. If you've set goals for today, a
few more lines show what's still left to do. The tracker starts it as a
short-lived process:

    pythonw toast.pyw back [seconds_away]
    pythonw toast.pyw distracted "Shopping|flipkart"
"""
import ctypes
import random
import sys
import time
from ctypes import wintypes

from common import connect, day_goals, fmt_dur, goals_left, load_pause, load_settings, morning_return, wasted_today
from osd import ACCENT, FW_SEMIBOLD, MUTED, PINK, TEXT, OSDWindow, rgb, single_instance, user32

RESTING, GOOD = rgb("#a5a8ff"), rgb("#6ccb5f")
MIN_TEXT_W = 320       # the "Still to do" list wraps onto more lines rather than widening the pop-up
LINE_H = 19

BACK_LINES = ["Welcome back", "Back at it", "There you are"]
NUDGES = ["Is this worth it?", "Close it and get back to work", "This is going on your record",
          "Your future self is watching", "One more minute? Sure..."]


def todo_line(kind):
    """(label, [items], colour) for today's goals, or None if there's nothing to say."""
    items = day_goals()["items"]
    left = goals_left(items)
    if left:
        return "Still to do", left, TEXT
    if items and kind == "back":
        return "Goals", ["All done for today. Nice work!"], GOOD
    return None


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
    try:
        seconds = float(arg or 0)
    except ValueError:
        seconds = 0
    hours = load_settings().get("sleep_hours", 8)
    if hours and morning_return(seconds):
        slept = fmt_dur(min(seconds, hours * 3600))
        return "", RESTING, f"Good morning  ·  {slept} of sleep not counted", f"{total} wasted today"
    away = f"  ·  away {fmt_dur(seconds)}" if seconds >= 60 else ""
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

    def __init__(self, glyph, color, small, big, todo=None):
        k = self.scale()
        self.glyph, self.color, self.small, self.big, self.todo = glyph, color, small, big, todo
        self.f_small = self.font("Segoe UI Variable Text", 9, k=k)
        self.f_big = self.font("Segoe UI Variable Display", 15, FW_SEMIBOLD, k=k)
        self.f_icon = self.font("Segoe Fluent Icons", 15, k=k)
        text_w = max(self.measure(self.f_small, small), self.measure(self.f_big, big))
        height = int(72 * k)
        if todo:
            text_w = max(text_w, int(MIN_TEXT_W * k))
            self.label_w = self.measure(self.f_small, todo[0] + "  ")
            self.lines = self.wrap(todo[1], text_w - self.label_w)
            height = int((60 + LINE_H * len(self.lines) + 12) * k)
        super().__init__(int((16 + 40 + 14 + 22) * k) + text_w, height)

    def wrap(self, items, width):
        """Lay out 'a, b, c' over as many lines as needed, keeping each item on one line if it fits."""
        lines, cur = [], ""
        for n, item in enumerate(items):
            piece = item + ("," if n < len(items) - 1 else "")
            for word in ([piece] if self.measure(self.f_small, piece) <= width else piece.split(" ")):
                cand = f"{cur} {word}" if cur else word
                if cur and self.measure(self.f_small, cand) > width:
                    lines.append(cur)
                    cand = word
                cur = cand
        return lines + [cur] if cur else lines

    def position(self):
        x, y = super().position()
        return below_other_popup(x, y, self.k)

    def draw(self, dc):
        left = self.icon_tile(dc, self.glyph, self.color, self.f_icon, top=self.px(16))
        self.text(dc, self.f_small, MUTED, self.small, wintypes.RECT(left, self.px(12), self.w, self.px(32)))
        self.text(dc, self.f_big, TEXT, self.big, wintypes.RECT(left, self.px(30), self.w, self.px(60)))
        if self.todo:
            label, _, color = self.todo
            self.text(dc, self.f_small, ACCENT, label, wintypes.RECT(left, self.px(60), self.w, self.px(60 + LINE_H)))
            for n, line in enumerate(self.lines):
                y = self.px(60 + LINE_H * n)
                self.text(dc, self.f_small, color, line,
                          wintypes.RECT(left + self.label_w, y, self.w, y + self.px(LINE_H)))


def main():
    pause = load_pause()
    if pause and time.time() < pause["until"]:
        return  # paused: show nothing
    if not single_instance("UptimeToast"):
        return  # one pop-up at a time
    kind = sys.argv[1] if len(sys.argv) > 1 else "back"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    Toast(*message(kind, arg), todo=todo_line(kind)).run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a pop-up must never bother you with an error
