"""Asks "Is this for work?" the first time you use a new app or website.

A small top-left prompt with Work / Not work buttons. You can click it, but clicking never
takes focus away from what you're doing, and it is hidden from screen capture (see osd.py).
If you ignore it, it fades away after 20 seconds and asks again another time.

    pythonw ask.pyw "site:leetcode.com" "leetcode.com"
    pythonw ask.pyw "app:code" "Visual Studio Code"
"""
import ctypes
import sys
import time
from ctypes import wintypes

from common import NOT_WORK, WORK, answer_of, load_labels, load_pause, save_label
from osd import (ACCENT, DT_CENTER, DT_END_ELLIPSIS, DT_LEFT, DT_VCENTER, FW_SEMIBOLD, IDC_ARROW, IDC_HAND,
                 MUTED, PINK, TEXT, TILE, OSDWindow, rgb, single_instance, user32)

user32.SetCursor.argtypes = [wintypes.HANDLE]
ACCENT_HOVER, TILE_HOVER, GOOD = rgb("#a5e4ff"), rgb("#505050"), rgb("#6ccb5f")
BLACK = rgb("#000000")


def below_other_popup(x, y, k):
    other = user32.FindWindowW("UptimeToast", None)
    if other:
        r = wintypes.RECT()
        user32.GetWindowRect(other, ctypes.byref(r))
        return x, r.bottom + int(10 * k)
    return x, y


class Ask(OSDWindow):
    CLASS = "UptimeAsk"
    CLICKABLE = True
    SHOW_MS = 20000

    def __init__(self, key, name):
        k = self.scale()
        self.key, self.name = key, name
        site = key.startswith("site:")
        self.glyph, self.color = ("", ACCENT) if site else ("", ACCENT)
        self.small = f"New {'site' if site else 'app'}  ·  {name}"
        self.big = "Is this for work?"
        self.f_small = self.font("Segoe UI Variable Text", 9, k=k)
        self.f_big = self.font("Segoe UI Variable Display", 14, FW_SEMIBOLD, k=k)
        self.f_btn = self.font("Segoe UI Variable Text", 10, k=k)
        self.f_icon = self.font("Segoe Fluent Icons", 15, k=k)
        self.hover = None
        self.done = None
        small_w = min(self.measure(self.f_small, self.small), int(260 * k))
        text_w = max(small_w, self.measure(self.f_big, self.big))
        self.btn_w = [max(int(72 * k), self.measure(self.f_btn, t) + int(28 * k)) for t in ("Work", "Not work")]
        width = int((16 + 40 + 14) * k) + text_w + int(36 * k) + sum(self.btn_w) + int((8 + 16) * k)
        height = int(72 * k)
        # lay out the buttons before the window exists, so the first paint has them
        x = width - int(16 * k)
        bh = int(32 * k)
        by = (height - bh) // 2
        self.buttons = []
        for label, value, bw in reversed(list(zip(("Work", "Not work"), (WORK, NOT_WORK), self.btn_w))):
            self.buttons.insert(0, (label, value, wintypes.RECT(x - bw, by, x, by + bh)))
            x -= bw + int(8 * k)
        self.text_right = x - int(12 * k)
        super().__init__(width, height)

    def position(self):
        x, y = super().position()
        return below_other_popup(x, y, self.k)

    def draw(self, dc):
        left = self.icon_tile(dc, self.glyph, self.color, self.f_icon)
        small, big = self.small, self.big
        if self.done:
            big = "Got it: work" if self.done == WORK else "Got it: not work"
        self.text(dc, self.f_small, MUTED, small,
                  wintypes.RECT(left, self.px(12), self.text_right, self.px(32)), DT_LEFT | DT_VCENTER | DT_END_ELLIPSIS)
        self.text(dc, self.f_big, (GOOD if self.done == WORK else PINK) if self.done else TEXT, big,
                  wintypes.RECT(left, self.px(30), self.text_right, self.px(60)))
        if self.done:
            return
        for i, (label, value, r) in enumerate(self.buttons):
            primary = value == WORK
            hovered = self.hover == i
            fill = (ACCENT_HOVER if hovered else ACCENT) if primary else (TILE_HOVER if hovered else TILE)
            self.round_rect(dc, r.left, r.top, r.right, r.bottom, self.px(4), fill)
            self.text(dc, self.f_btn, BLACK if primary else TEXT, label, wintypes.RECT(r.left, r.top, r.right, r.bottom),
                      DT_CENTER | DT_VCENTER)

    def on_mouse(self, x, y, clicked):
        if self.done:
            return
        hit = next((i for i, (_, _, r) in enumerate(self.buttons)
                    if r.left <= x < r.right and r.top <= y < r.bottom), None)
        user32.SetCursor(user32.LoadCursorW(None, ctypes.c_void_p(IDC_HAND if hit is not None else IDC_ARROW)))
        if hit != self.hover:
            self.hover = hit
            self.redraw()
        if clicked and hit is not None:
            self.done = self.buttons[hit][1]
            save_label(self.key, self.done, self.name)
            self.redraw()
            user32.SetTimer(self.hwnd, 9, 900, None)  # show "Got it" briefly, then fade

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == 0x113 and wparam == 9:  # WM_TIMER for the "Got it" delay
            user32.KillTimer(hwnd, 9)
            self.close()
            return 0
        return super()._wndproc(hwnd, msg, wparam, lparam)


def main():
    if len(sys.argv) < 2:
        return
    key = sys.argv[1]
    name = sys.argv[2] if len(sys.argv) > 2 else key.split(":", 1)[-1]
    pause = load_pause()
    if pause and time.time() < pause["until"]:
        return
    if answer_of(load_labels(), key):
        return  # already answered
    if not single_instance("UptimeAsk"):
        return  # one question at a time
    Ask(key, name).run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass
