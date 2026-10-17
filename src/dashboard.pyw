"""Dashboard: today's wasted time, averages, and daily / weekly / break history.

Styled after the Windows 11 dark theme (Start menu look).
"""
import os
import sys

from common import DATA_DIR

# pythonw has no console: send crash output to a log so failures are never silent.
if sys.stderr is None:
    os.makedirs(DATA_DIR, exist_ok=True)
    sys.stderr = open(os.path.join(DATA_DIR, "error.log"), "a", buffering=1, encoding="utf-8")
    import faulthandler
    faulthandler.enable(sys.stderr)

import atexit
import ctypes
import math
import subprocess
import time
import tkinter as tk
from collections import deque
from datetime import datetime, timedelta

from common import (DEFAULT_RULES, KIND_LABELS, NOT_WORK, WASTED_KINDS, WORK, connect, detail_label, fmt_dur,
                    key_name, load_labels, load_pause, load_rules, load_settings, save_label, save_pause,
                    save_rules, save_settings, schedule_resume, summary, tracked, wasted)

PREVIEW = bool(os.environ.get("WTT_DATA_DIR"))  # set by preview.pyw

try:  # crisp text on high-DPI screens
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass
try:  # 1 ms timer while the dashboard is open, so animations can run at high-refresh rates
    ctypes.windll.winmm.timeBeginPeriod(1)
    atexit.register(ctypes.windll.winmm.timeEndPeriod, 1)
except Exception:
    pass
try:  # own taskbar entry and icon instead of Python's
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("Uptime.Dashboard")
except Exception:
    pass

ICON_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "uptime.ico")

# ------------------------------------------------------------------ theme
BG = "#202020"
SURFACE = "#2b2b2b"
SURFACE_HI = "#353535"
BORDER = "#383838"
TEXT = "#ffffff"
TEXT2 = "#c5c5c5"
MUTED = "#9a9a9a"
ACCENT = "#60cdff"
GOOD = "#6ccb5f"
BAD = "#ff99a4"
COLORS = {"sleep": ACCENT, "shutdown": "#8b8b8b", "locked": "#f9b24e", "distracted": "#f472b6",
          "active": GOOD}
GLYPHS = {"sleep": "", "shutdown": "", "locked": "", "active": "",
          "clock": "", "refresh": "", "calendar": "", "week": "",
          "avg": "", "chevron": "", "empty": ""}

GLYPHS.update({"distracted": "", "site": "", "app": "", "delete": "",
               "add": "", "reset": "", "pause": "", "play": ""})
PAUSED = "#f9b24e"
PAUSE_CHOICES = (3, 4, 5)  # hours

CHART_DAYS = 14
REFRESH_MS = 60_000
K = 1.0  # DPI scale factor, set once the window exists


def px(n):
    return int(round(n * K))


def font(size, weight="", family="Segoe UI Variable Text"):
    if weight == "semibold":
        family = {"Segoe UI Variable Text": "Segoe UI Variable Text Semibold",
                  "Segoe UI Variable Display": "Segoe UI Variable Display Semib"}[family]
    return (family, size)


ICON_FONT = "Segoe Fluent Icons"


def round_rect(c, x1, y1, x2, y2, r, **kw):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2,
           x2 - r, y2, x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, **kw)


def set_bg(widget, color):
    """Recolor a widget and all its (non-canvas) children, used for hover."""
    if getattr(widget, "keep_bg", False):
        return
    try:
        widget.configure(bg=color)
    except tk.TclError:
        pass
    for child in widget.winfo_children():
        if not isinstance(child, tk.Canvas) or getattr(child, "follow_bg", False):
            set_bg(child, color)


def hoverable(widget, normal, hover, command=None):
    def enter(_):
        set_bg(widget, hover)

    def leave(e):
        x, y = widget.winfo_pointerxy()
        if widget.winfo_containing(x, y) not in _descendants(widget):
            set_bg(widget, normal)

    for w in _descendants(widget):
        w.bind("<Enter>", enter, add="+")
        w.bind("<Leave>", leave, add="+")
        if command:
            w.bind("<Button-1>", lambda e: command(), add="+")
            w.configure(cursor="hand2")


def _descendants(w):
    out = [w]
    for c in w.winfo_children():
        out.extend(_descendants(c))
    return out


# ------------------------------------------------------------------ widgets
class Card(tk.Canvas):
    """A rounded surface. Put content in .inner. fit=True sizes height to the content."""

    def __init__(self, parent, fit=True, pad=16, radius=8, color=SURFACE, **kw):
        super().__init__(parent, bg=parent["bg"], highlightthickness=0, height=1, **kw)
        self.fit, self.pad, self.radius, self.color = fit, px(pad), px(radius), color
        self.inner = tk.Frame(self, bg=color)
        self._win = self.create_window(self.pad, self.pad, window=self.inner, anchor="nw")
        self.bind("<Configure>", self._layout)
        if fit:
            # The inner frame isn't mapped while the canvas is too small to show it,
            # so size the card from the content's requested height once it is built.
            self.after_idle(self._fit)

    def _fit(self, _=None):
        h = self.inner.winfo_reqheight() + 2 * self.pad
        if int(self["height"]) != h:
            self.configure(height=h)

    def _layout(self, e):
        self.delete("shape")
        round_rect(self, 1, 1, e.width - 1, e.height - 1, self.radius,
                   fill=self.color, outline=BORDER, tags="shape")
        self.tag_lower("shape")
        self.itemconfigure(self._win, width=max(1, e.width - 2 * self.pad))
        if self.fit:
            self.after_idle(self._fit)
        else:
            self.itemconfigure(self._win, height=max(1, e.height - 2 * self.pad))


class RawWheel:
    """Recover precision-touchpad scroll amounts that Tk would otherwise round off.

    Tk 8.6 sums small WM_MOUSEWHEEL deltas until they reach 120 and only then reports a
    single notch, which turns a smooth two-finger swipe into big jumps. A message hook on
    this thread notes each message's true delta and rewrites it to a full +/-120, so Tk
    reports every message at once; the <MouseWheel> handler then uses the noted amount.
    The hook never calls into Tcl (it runs inside Tk's own message loop).
    """
    WH_GETMESSAGE, WM_MOUSEWHEEL, PM_REMOVE = 3, 0x020A, 1

    def __init__(self):
        self.pending = deque()
        self._hook = None
        try:
            from ctypes import wintypes

            class MSG(ctypes.Structure):
                _fields_ = [("hwnd", wintypes.HWND), ("message", wintypes.UINT),
                            ("wParam", wintypes.WPARAM), ("lParam", wintypes.LPARAM),
                            ("time", wintypes.DWORD), ("pt", wintypes.POINT)]

            user32 = ctypes.WinDLL("user32", use_last_error=True)
            HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM)
            user32.SetWindowsHookExW.restype = wintypes.HHOOK
            user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
            user32.CallNextHookEx.restype = ctypes.c_ssize_t
            user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
            user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]

            def proc(code, wparam, lparam):
                if code >= 0 and wparam == self.PM_REMOVE:
                    msg = MSG.from_address(lparam)
                    if msg.message == self.WM_MOUSEWHEEL:
                        delta = ctypes.c_short((msg.wParam >> 16) & 0xFFFF).value
                        if delta % 120:
                            self.pending.append((time.perf_counter(), delta))
                            full = (120 if delta > 0 else -120) & 0xFFFF
                            msg.wParam = (msg.wParam & 0xFFFF) | (full << 16)
                return user32.CallNextHookEx(None, code, wparam, lparam)

            self._proc = HOOKPROC(proc)  # keep a reference so it isn't garbage-collected
            tid = ctypes.windll.kernel32.GetCurrentThreadId()
            self._hook = user32.SetWindowsHookExW(self.WH_GETMESSAGE, self._proc, None, tid)
            if self._hook:
                atexit.register(user32.UnhookWindowsHookEx, self._hook)
        except Exception:
            self._hook = None  # fall back to Tk's rounded notches

    def take(self, tk_delta):
        """The real delta for the wheel event Tk is reporting now."""
        cutoff = time.perf_counter() - 0.5
        while self.pending and self.pending[0][0] < cutoff:
            self.pending.popleft()  # stale: Tk never reported it
        if self.pending and abs(tk_delta) == 120:
            return self.pending.popleft()[1]
        return tk_delta


RAW_WHEEL = RawWheel()


class SmoothScroller:
    """Pixel-precise scrolling for a tk.Canvas (self.canvas).

    Mouse-wheel notches glide to their target with time-based easing at up to ~144 fps.
    Precision-touchpad input (small, rapid deltas) moves the view immediately so it
    tracks your fingers with no added delay.
    """
    WHEEL_STEP = 110      # pixels per 120 units of wheel delta (before DPI scaling)
    FRAME_MS = 7          # ~144 fps frame budget (needs the 1 ms system timer set at startup)
    TAU = 0.045           # easing time constant in seconds: ~90% of the way in 0.1 s
    _instances = []

    def _init_scroller(self):
        self.canvas.configure(yscrollincrement=1)
        self._target = 0.0
        self._anim = None
        self._last_frame = 0.0
        self._settle = None
        if not SmoothScroller._instances:  # one dispatcher for every list
            self.bind_all("<MouseWheel>", SmoothScroller._dispatch, add="+")
        SmoothScroller._instances.append(self)

    @staticmethod
    def _dispatch(e):
        delta = RAW_WHEEL.take(e.delta)  # the touchpad's true amount, not Tk's 120 notch
        w = e.widget.winfo_containing(e.x_root, e.y_root)
        while w is not None and w not in SmoothScroller._instances:
            w = w.master
        if w is not None:
            w._wheel(delta)

    def _content_height(self):
        region = self.canvas.cget("scrollregion").split()
        return float(region[3]) if len(region) == 4 else 0.0

    def _max_offset(self):
        return max(0.0, self._content_height() - self.canvas.winfo_height())

    def _wheel(self, delta):
        if self._max_offset() <= 0:
            return
        now = time.perf_counter()
        move = -delta / 120 * px(self.WHEEL_STEP)
        if delta % 120:
            # Precision touchpad: many tiny deltas, so follow them directly (no easing lag).
            if self._anim is not None:
                self.after_cancel(self._anim)
                self._anim = None
            self._target = min(max(self.canvas.canvasy(0) + move, 0.0), self._max_offset())
            self.canvas.yview_moveto(self._target / self._content_height())
            self._scrolled(done=False)
            if self._settle is not None:
                self.after_cancel(self._settle)
            self._settle = self.after(120, lambda: self._scrolled(done=True))
            return
        self._target = min(max(self._target + move, 0.0), self._max_offset())
        if self._anim is None:
            self._last_frame = now
            self._animate()

    def _animate(self):
        total = self._content_height()
        cur = self.canvas.canvasy(0)
        diff = self._target - cur
        if abs(diff) < 0.5 or total <= 0:
            if total > 0:
                self.canvas.yview_moveto(self._target / total)
            self._anim = None
            self._scrolled(done=True)
            return
        now = time.perf_counter()
        dt, self._last_frame = max(now - self._last_frame, 0.001), now
        step = diff * (1 - math.exp(-dt / self.TAU))
        if abs(step) < 1:
            step = math.copysign(min(1.0, abs(diff)), diff)
        self.canvas.yview_moveto((cur + step) / total)
        self._scrolled(done=False)
        self.canvas.update_idletasks()  # draw now, then wait only for the rest of the frame
        spent_ms = (time.perf_counter() - now) * 1000
        self._anim = self.after(max(1, round(self.FRAME_MS - spent_ms)), self._animate)

    def _reset_scroll(self):
        if self._anim is not None:
            self.after_cancel(self._anim)
            self._anim = None
        self._target = 0.0
        self.canvas.yview_moveto(0)

    def _scrolled(self, done):
        self._draw_thumb()

    def _draw_thumb(self):
        c = self.canvas
        c.delete("thumb")
        top, bottom = c.yview()
        if bottom - top >= 1:
            return
        h = c.winfo_height()
        y0 = c.canvasy(0)
        round_rect(c, c.winfo_width() - px(5), y0 + top * h + 2, c.winfo_width() - px(2),
                   y0 + bottom * h - 2, px(2), fill="#5d5d5d", outline="", tags="thumb")


class ScrollList(SmoothScroller, tk.Frame):
    """Scrollable column of ordinary widgets (for short lists with buttons and inputs)."""

    def __init__(self, parent, bg):
        tk.Frame.__init__(self, parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.body = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window(0, 0, window=self.body, anchor="nw")
        self.body.bind("<Configure>", lambda e: self._sync())
        self.canvas.bind("<Configure>", lambda e: (
            self.canvas.itemconfigure(self._win, width=e.width - px(10)), self._sync()))
        self._init_scroller()

    def _sync(self):
        self.canvas.configure(scrollregion=(0, 0, 0, self.body.winfo_reqheight()))
        self._target = min(self._target, self._max_offset())
        self.after_idle(self._draw_thumb)

    def clear(self):
        for c in self.body.winfo_children():
            c.destroy()
        self._reset_scroll()


class CanvasList(SmoothScroller, tk.Frame):
    """Long list drawn directly on one canvas: no per-row widgets, so it scrolls smoothly.

    Each row is a dict: glyph, color, title, subtitle, and optionally value, note and
    bar (stats dict drawn as a 24h stacked bar).
    """
    ROW_H = 58
    VALUE_W = 150
    BAR_W = 180

    def __init__(self, parent, bg):
        tk.Frame.__init__(self, parent, bg=bg)
        self.bg = bg
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True)
        self.rows, self.empty_text = [], ""
        self._hover = None
        self.canvas.bind("<Configure>", lambda e: self._draw())
        self.canvas.bind("<Motion>", lambda e: self._set_hover(self._row_at(e.y)))
        self.canvas.bind("<Leave>", lambda e: self._set_hover(None))
        self._init_scroller()

    def set_rows(self, rows, empty_text=""):
        self.rows, self.empty_text = rows, empty_text
        self._hover = None
        self._target = min(self._target, max(0.0, len(rows) * px(self.ROW_H) - self.canvas.winfo_height()))
        self._draw()

    def _row_at(self, y):
        i = int(self.canvas.canvasy(y) // px(self.ROW_H))
        return i if 0 <= i < len(self.rows) else None

    def _set_hover(self, i):
        if i == self._hover:
            return
        self._hover = i
        c = self.canvas
        c.delete("hover")
        if i is not None:
            rh = px(self.ROW_H)
            round_rect(c, 0, i * rh + 1, c.winfo_width() - px(10), (i + 1) * rh - 1, px(6),
                       fill=SURFACE_HI, outline="", tags="hover")
            c.tag_lower("hover")

    def _scrolled(self, done):
        self._draw_thumb()
        if done:  # the row under the pointer changed while the list moved
            x, y = self.canvas.winfo_pointerxy()
            inside = self.canvas.winfo_containing(x, y) is self.canvas
            self._set_hover(self._row_at(y - self.canvas.winfo_rooty()) if inside else None)

    def _draw(self):
        c = self.canvas
        c.delete("all")
        w = c.winfo_width()
        if w < 50:
            return
        rh = px(self.ROW_H)
        if not self.rows:
            c.configure(scrollregion=(0, 0, w, c.winfo_height()))
            c.create_text(w / 2, px(70), text=GLYPHS["empty"], font=(ICON_FONT, 22), fill=MUTED)
            c.create_text(w / 2, px(105), text=self.empty_text, font=font(10), fill=MUTED)
            return
        c.configure(scrollregion=(0, 0, w, len(self.rows) * rh))
        right = w - px(10) - px(14)              # right edge of the value column
        bar_x2 = right - px(self.VALUE_W) - px(16)
        text_max = (bar_x2 - px(self.BAR_W) - px(16)) - px(62)
        for i, r in enumerate(self.rows):
            y = i * rh
            ty = y + (rh - px(34)) / 2
            round_rect(c, px(8), ty, px(42), ty + px(34), px(6), fill=SURFACE_HI, outline="")
            c.create_text(px(25), ty + px(17), text=r["glyph"], fill=r["color"], font=(ICON_FONT, 13))
            c.create_text(px(62), y + rh / 2 - px(9), text=r["title"], anchor="w", fill=TEXT,
                          font=font(10), width=text_max)
            c.create_text(px(62), y + rh / 2 + px(10), text=r["subtitle"], anchor="w", fill=MUTED,
                          font=font(9), width=text_max)
            if r.get("value") is not None:
                vy = y + rh / 2 - (px(9) if r.get("note") else 0)
                c.create_text(right, vy, text=r["value"], anchor="e", fill=TEXT, font=font(11, "semibold"))
                if r.get("note"):
                    c.create_text(right, y + rh / 2 + px(10), text=r["note"], anchor="e", fill=MUTED,
                                  font=font(9))
            if r.get("bar") is not None:
                self._bar(bar_x2 - px(self.BAR_W), y + rh / 2 - px(3), r["bar"])
        if self._hover is not None:
            h, self._hover = self._hover, None
            self._set_hover(h)
        self._draw_thumb()

    def _bar(self, x, y, stats, total=86400):
        c, w, h = self.canvas, px(self.BAR_W), px(6)
        round_rect(c, x, y, x + w, y + h, h / 2, fill="#3d3d3d", outline="")
        for k in WASTED_KINDS:
            seg = w * min(stats.get(k, 0), total) / total
            if seg >= 1:
                c.create_rectangle(x, y, x + seg, y + h, fill=COLORS[k], outline="")
                x += seg


def icon_badge(parent, glyph, color, bg, size=34):
    c = tk.Canvas(parent, width=px(size), height=px(size), bg=bg, highlightthickness=0)
    c.follow_bg = True
    round_rect(c, 0, 0, px(size), px(size), px(6), fill=SURFACE_HI, outline="")
    c.create_text(px(size) / 2, px(size) / 2, text=glyph, fill=color, font=(ICON_FONT, 13))
    return c


# ------------------------------------------------------------------ app
class Dashboard(tk.Tk):
    def __init__(self):
        super().__init__()
        global K
        K = self.winfo_fpixels("1i") / 96.0
        self.title("Uptime (preview)" if PREVIEW else "Uptime")
        self.configure(bg=BG)
        w, h = px(1040), min(px(820), self.winfo_screenheight() - px(80))
        self.geometry(f"{w}x{h}+{(self.winfo_screenwidth() - w) // 2}+{max(0, (self.winfo_screenheight() - h) // 2 - px(20))}")
        self.minsize(px(860), px(620))
        self.tab = "overview"

        self._build_header()
        self._build_cards()
        self._build_nav()
        self.page = tk.Frame(self, bg=BG)
        self.page.pack(fill="both", expand=True, padx=px(28), pady=(0, px(24)))
        self._build_pages()

        self.update_idletasks()
        self._dark_titlebar()
        if os.path.exists(ICON_PATH):
            self.iconbitmap(default=ICON_PATH)
        self.refresh()
        self._bring_to_front()

    def _bring_to_front(self):
        self.deiconify()
        self.lift()
        self.attributes("-topmost", True)
        self.after(300, lambda: self.attributes("-topmost", False))
        self.focus_force()

    def _dark_titlebar(self):
        try:
            hwnd = ctypes.windll.user32.GetParent(self.winfo_id())
            dwm = ctypes.windll.dwmapi
            on = ctypes.c_int(1)
            dwm.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(on), 4)   # immersive dark mode
            r, g, b = int(BG[1:3], 16), int(BG[3:5], 16), int(BG[5:7], 16)
            color = ctypes.c_int(r | g << 8 | b << 16)
            dwm.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(color), 4)  # caption color
            ctypes.windll.user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, 0x27)   # redraw frame
        except Exception:
            pass

    # -------------------------------------------------------- header & cards
    def _build_header(self):
        bar = tk.Frame(self, bg=BG)
        bar.pack(fill="x", padx=px(28), pady=(px(22), px(14)))
        tk.Label(bar, text=GLYPHS["clock"], font=(ICON_FONT, 20), fg=ACCENT, bg=BG).pack(side="left")
        titles = tk.Frame(bar, bg=BG)
        titles.pack(side="left", padx=(px(12), 0))
        tk.Label(titles, text="Uptime", font=font(20, "semibold", "Segoe UI Variable Display"),
                 fg=TEXT, bg=BG).pack(anchor="w")
        if PREVIEW:
            tk.Label(titles, text="Preview of v2 · running on a copy of your data · your installed app is untouched",
                     font=font(10), fg=ACCENT, bg=BG).pack(anchor="w")
        else:
            tk.Label(titles, text="See where your time goes, and win back the hours you lose",
                     font=font(10), fg=MUTED, bg=BG).pack(anchor="w")

        refresh = tk.Frame(bar, bg=BG, padx=px(10), pady=px(6))
        refresh.pack(side="right")
        tk.Label(refresh, text=GLYPHS["refresh"], font=(ICON_FONT, 12), fg=TEXT, bg=BG).pack()
        hoverable(refresh, BG, SURFACE_HI, self.refresh)

        self.status = tk.Canvas(bar, bg=BG, highlightthickness=0, height=px(30), width=px(10))
        self.status.pack(side="right", padx=(0, px(8)))

        self.pause_btn = tk.Frame(bar, bg=SURFACE, padx=px(12), pady=px(5),
                                  highlightthickness=1, highlightbackground=BORDER)
        self.pause_btn.pack(side="right", padx=(0, px(8)))
        self.pause_icon = tk.Label(self.pause_btn, text=GLYPHS["pause"], font=(ICON_FONT, 9), fg=TEXT, bg=SURFACE)
        self.pause_icon.pack(side="left", padx=(0, px(8)))
        self.pause_text = tk.Label(self.pause_btn, text="Pause", font=font(10), fg=TEXT, bg=SURFACE)
        self.pause_text.pack(side="left")
        hoverable(self.pause_btn, SURFACE, SURFACE_HI, self._pause_clicked)
        self.pause_panel = None

    def _draw_status(self, text, color):
        c = self.status
        c.delete("all")
        t = c.create_text(px(28), px(15), text=text, anchor="w", fill=TEXT2, font=font(10))
        w = c.bbox(t)[2] + px(14)
        c.configure(width=w)
        c.tag_lower(round_rect(c, 0, 1, w, px(29), px(14), fill=SURFACE, outline=BORDER))
        c.create_oval(px(13), px(11), px(21), px(19), fill=color, outline="")

    def _build_cards(self):
        row = tk.Frame(self, bg=BG)
        row.pack(fill="x", padx=px(28))
        self.cards = {}
        spec = [("today", "Wasted today", "locked", COLORS["locked"]),
                ("active", "Active today", "active", GOOD),
                ("avg_day", "Average per day", "calendar", ACCENT),
                ("avg_week", "Average per week", "week", "#c7a5ff")]
        for i, (key, title, glyph, color) in enumerate(spec):
            row.columnconfigure(i, weight=1, uniform="cards")
            card = Card(row, pad=18)
            card.grid(row=0, column=i, sticky="ew", padx=(0 if i == 0 else px(12), 0))
            top = tk.Frame(card.inner, bg=SURFACE)
            top.pack(fill="x")
            tk.Label(top, text=GLYPHS[glyph], font=(ICON_FONT, 12), fg=color, bg=SURFACE).pack(side="left")
            tk.Label(top, text=title, font=font(10), fg=TEXT2, bg=SURFACE).pack(side="left", padx=(px(8), 0))
            value = tk.Label(card.inner, text="-", font=font(24, "semibold", "Segoe UI Variable Display"),
                             fg=TEXT, bg=SURFACE)
            value.pack(anchor="w", pady=(px(8), 0))
            note = tk.Label(card.inner, text="", font=font(9), fg=MUTED, bg=SURFACE)
            note.pack(anchor="w")
            self.cards[key] = (value, note)

    def _set_card(self, key, value, note):
        self.cards[key][0].config(text=value)
        self.cards[key][1].config(text=note)

    # -------------------------------------------------------- navigation
    def _build_nav(self):
        nav = tk.Frame(self, bg=BG)
        nav.pack(fill="x", padx=px(22), pady=(px(22), px(12)))
        self.nav_items = {}
        for key, label in [("overview", "Overview"), ("daily", "Daily"),
                           ("weekly", "Weekly"), ("distractions", "Distractions"),
                           ("breaks", "Breaks")]:
            item = tk.Frame(nav, bg=BG, padx=px(8))
            item.pack(side="left")
            lbl = tk.Label(item, text=label, font=font(11), bg=BG, fg=MUTED, padx=px(6), pady=px(4))
            lbl.pack()
            ind = tk.Canvas(item, height=px(3), width=px(18), bg=BG, highlightthickness=0)
            ind.pack()
            for w in (item, lbl):
                w.bind("<Button-1>", lambda e, k=key: self.show(k))
                w.configure(cursor="hand2")
            lbl.bind("<Enter>", lambda e, l=lbl, k=key: l.config(fg=TEXT) if k != self.tab else None)
            lbl.bind("<Leave>", lambda e, l=lbl, k=key: l.config(fg=MUTED) if k != self.tab else None)
            self.nav_items[key] = (lbl, ind)

    def show(self, key):
        self.tab = key
        for k, (lbl, ind) in self.nav_items.items():
            sel = k == key
            lbl.config(fg=TEXT if sel else MUTED,
                       font=font(11, "semibold") if sel else font(11))
            ind.delete("all")
            if sel:
                round_rect(ind, 0, 0, px(18), px(3), px(1.5), fill=ACCENT, outline="")
        for k, frame in self.pages.items():
            if k == key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        if key == "overview":
            self.after_idle(self._draw_chart)

    def _section_header(self, parent, title, action=None, target=None):
        row = tk.Frame(parent, bg=SURFACE)
        row.pack(fill="x", pady=(0, px(10)))
        tk.Label(row, text=title, font=font(12, "semibold"), fg=TEXT, bg=SURFACE).pack(side="left")
        if action:
            btn = tk.Frame(row, bg=SURFACE_HI, padx=px(10), pady=px(3))
            btn.pack(side="right")
            tk.Label(btn, text=action, font=font(10), fg=TEXT, bg=SURFACE_HI).pack(side="left")
            tk.Label(btn, text=GLYPHS["chevron"], font=(ICON_FONT, 8), fg=TEXT,
                     bg=SURFACE_HI).pack(side="left", padx=(px(8), 0))
            hoverable(btn, SURFACE_HI, "#3f3f3f", lambda: self.show(target))
        return row

    # -------------------------------------------------------- pages
    def _build_pages(self):
        self.pages = {}

        # Overview: chart + recent breaks (like the Start menu's "Recent")
        ov = tk.Frame(self.page, bg=BG)
        self.pages["overview"] = ov
        chart_card = Card(ov, pad=18)
        chart_card.pack(fill="x")
        self._section_header(chart_card.inner, f"Last {CHART_DAYS} days", "Daily history", "daily")
        self.chart = tk.Canvas(chart_card.inner, height=px(220), bg=SURFACE, highlightthickness=0)
        self.chart.pack(fill="x")
        self.chart.bind("<Configure>", lambda e: self._draw_chart())
        self.chart.bind("<Motion>", self._chart_hover)
        self.chart.bind("<Leave>", lambda e: (setattr(self, "_hover", None), self._draw_chart()))

        recent_card = Card(ov, fit=False, pad=18)
        recent_card.pack(fill="both", expand=True, pady=(px(14), 0))
        self._section_header(recent_card.inner, "Recent breaks", "Show all", "breaks")
        self.recent = tk.Frame(recent_card.inner, bg=SURFACE)
        self.recent.pack(fill="both", expand=True)
        self.recent.columnconfigure(0, weight=1, uniform="r")
        self.recent.columnconfigure(1, weight=1, uniform="r")

        for key, title in [("daily", "Daily history"), ("weekly", "Weekly history"),
                           ("breaks", "All breaks")]:
            frame = tk.Frame(self.page, bg=BG)
            card = Card(frame, fit=False, pad=18)
            card.pack(fill="both", expand=True)
            hdr = self._section_header(card.inner, title)
            if key == "daily":
                legend = tk.Frame(hdr, bg=SURFACE)
                legend.pack(side="right")
                self._legend(legend, SURFACE)
            lst = CanvasList(card.inner, SURFACE)
            lst.pack(fill="both", expand=True)
            self.pages[key] = frame
            setattr(self, f"{key}_list", lst)
        self._build_distractions_page()
        self.show("overview")

    def _legend(self, parent, bg):
        for k in WASTED_KINDS:
            dot = tk.Canvas(parent, width=px(10), height=px(10), bg=bg, highlightthickness=0)
            round_rect(dot, 0, 0, px(10), px(10), px(3), fill=COLORS[k], outline="")
            dot.pack(side="left", padx=(px(14), px(6)))
            tk.Label(parent, text=KIND_LABELS[k], font=font(9), fg=TEXT2, bg=bg).pack(side="left")

    def _row(self, parent, glyph, color, title, subtitle, right_value=None, right_note=None,
             extra=None):
        """A Windows-style list item: icon tile, two lines of text, value on the right."""
        row = tk.Frame(parent, bg=SURFACE, padx=px(8), pady=px(7))
        icon_badge(row, glyph, color, SURFACE).pack(side="left")
        text = tk.Frame(row, bg=SURFACE)
        text.pack(side="left", padx=(px(12), 0), fill="x", expand=True)
        tk.Label(text, text=title, font=font(10), fg=TEXT, bg=SURFACE, anchor="w").pack(fill="x")
        tk.Label(text, text=subtitle, font=font(9), fg=MUTED, bg=SURFACE, anchor="w").pack(fill="x")
        if right_value is not None:
            right = tk.Frame(row, bg=SURFACE)
            right.pack(side="right", padx=(px(12), px(6)))
            tk.Label(right, text=right_value, font=font(11, "semibold"), fg=TEXT, bg=SURFACE,
                     anchor="e", width=16).pack(fill="x")
            if right_note:
                tk.Label(right, text=right_note, font=font(9), fg=MUTED, bg=SURFACE,
                         anchor="e", width=16).pack(fill="x")
        if extra:
            extra(row).pack(side="right", padx=(px(16), 0))
        return row

    def _empty(self, parent, text):
        box = tk.Frame(parent, bg=SURFACE)
        box.pack(fill="both", expand=True, pady=px(30))
        tk.Label(box, text=GLYPHS["empty"], font=(ICON_FONT, 22), fg=MUTED, bg=SURFACE).pack()
        tk.Label(box, text=text, font=font(10), fg=MUTED, bg=SURFACE).pack(pady=(px(8), 0))

    # -------------------------------------------------------- distractions page
    def _build_distractions_page(self):
        frame = tk.Frame(self.page, bg=BG)
        self.pages["distractions"] = frame
        card = Card(frame, fit=False, pad=18)
        card.pack(fill="both", expand=True)
        lst = ScrollList(card.inner, SURFACE)
        lst.pack(fill="both", expand=True)
        body = lst.body

        self._section_header(body, "Top distractions this week")
        self.top_box = tk.Frame(body, bg=SURFACE)
        self.top_box.pack(fill="x")

        hdr = tk.Frame(body, bg=SURFACE)
        hdr.pack(fill="x", pady=(px(26), 0))
        tk.Label(hdr, text="Pop-ups", font=font(12, "semibold"), fg=TEXT, bg=SURFACE).pack(side="left")
        self._pill_button(hdr, "Show a test pop-up", lambda: self._show_toast("back"),
                          GLYPHS["clock"]).pack(side="right")
        tk.Label(body, text="A small reminder of today's wasted time in the top-left corner. It never takes "
                            "focus, clicks pass through it, and it stays out of screen shares and recordings.",
                 font=font(9), fg=MUTED, bg=SURFACE, anchor="w").pack(fill="x", pady=(px(4), px(10)))
        self.popups_box = tk.Frame(body, bg=SURFACE)
        self.popups_box.pack(fill="x")
        self._fill_popups()

        hdr = tk.Frame(body, bg=SURFACE)
        hdr.pack(fill="x", pady=(px(26), 0))
        tk.Label(hdr, text="Your answers", font=font(12, "semibold"), fg=TEXT, bg=SURFACE).pack(side="left")
        tk.Label(body, text="Apps and sites you've said are for work or not. Click an answer to change it, "
                            "or delete it to be asked again. Your answers win over the rules below.",
                 font=font(9), fg=MUTED, bg=SURFACE, anchor="w").pack(fill="x", pady=(px(4), px(10)))
        self.answers_box = tk.Frame(body, bg=SURFACE)
        self.answers_box.pack(fill="x")
        self._fill_answers()

        hdr = tk.Frame(body, bg=SURFACE)
        hdr.pack(fill="x", pady=(px(26), 0))
        tk.Label(hdr, text="What counts as a distraction", font=font(12, "semibold"),
                 fg=TEXT, bg=SURFACE).pack(side="left")
        self._pill_button(hdr, "Reset to defaults", self._reset_rules, GLYPHS["reset"]).pack(side="right")
        tk.Label(body, text="Websites are recognised from the browser tab's title, apps from the program's name. "
                            "Changes apply within a few seconds.",
                 font=font(9), fg=MUTED, bg=SURFACE, anchor="w").pack(fill="x", pady=(px(4), px(10)))
        self.rules_box = tk.Frame(body, bg=SURFACE)
        self.rules_box.pack(fill="x")
        self._build_add_form(body)
        self._fill_rules()

    # -------------------------------------------------------- pause
    def _app_file(self, name):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), name)

    def _pythonw(self):
        return os.path.join(os.path.dirname(sys.executable), "pythonw.exe")

    def _pause_clicked(self):
        if self._active_pause():
            self._resume_now()
        elif self.pause_panel is not None:
            self._close_pause_panel()
        else:
            self._open_pause_panel()

    @staticmethod
    def _active_pause():
        p = load_pause()
        return p if p and time.time() < p["until"] else None

    def _open_pause_panel(self):
        card = Card(self, pad=20, color="#2f2f2f")
        card.configure(bg=BG)
        self.pause_panel = card
        inner = card.inner
        tk.Label(inner, text="Pause Uptime", font=font(13, "semibold"), fg=TEXT, bg="#2f2f2f",
                 anchor="w").pack(fill="x")
        tk.Label(inner, text="Uptime turns off completely: no tracking, no pop-ups and nothing running. "
                             "It starts again by itself. Paused time doesn't count as wasted.",
                 font=font(9), fg=TEXT2, bg="#2f2f2f", anchor="w", justify="left",
                 wraplength=px(330)).pack(fill="x", pady=(px(6), px(14)))
        seg = tk.Frame(inner, bg="#1f1f1f", highlightthickness=1, highlightbackground=BORDER)
        seg.pack(fill="x")
        self.pause_hours = PAUSE_CHOICES[0]
        self.hour_btns = {}
        for h in PAUSE_CHOICES:
            b = tk.Label(seg, text=f"{h} hours", font=font(10), pady=px(6), cursor="hand2")
            b.pack(side="left", fill="x", expand=True)
            b.bind("<Button-1>", lambda e, h=h: self._set_pause_hours(h))
            self.hour_btns[h] = b
        self.pause_until = tk.Label(inner, text="", font=font(9), fg=MUTED, bg="#2f2f2f", anchor="w")
        self.pause_until.pack(fill="x", pady=(px(8), px(14)))
        self._set_pause_hours(self.pause_hours)
        row = tk.Frame(inner, bg="#2f2f2f")
        row.pack(fill="x")
        self._pill_button(row, "Pause now", self._pause_now, GLYPHS["pause"], primary=True).pack(side="left")
        cancel = self._pill_button(row, "Cancel", self._close_pause_panel)
        cancel.pack(side="left", padx=(px(8), 0))
        self.pause_msg = tk.Label(inner, text="", font=font(9), fg=MUTED, bg="#2f2f2f", anchor="w",
                                  justify="left", wraplength=px(330))
        self.pause_msg.pack(fill="x", pady=(px(8), 0))
        card.place(relx=1.0, x=-px(28), y=px(78), anchor="ne", width=px(380))
        tk.Misc.lift(card)  # raise the widget (Canvas.lift would raise a drawing item instead)

    def _close_pause_panel(self):
        if self.pause_panel is not None:
            self.pause_panel.destroy()
            self.pause_panel = None

    def _set_pause_hours(self, h):
        self.pause_hours = h
        for k, b in self.hour_btns.items():
            b.config(bg=SURFACE_HI if k == h else "#1f1f1f", fg=TEXT if k == h else MUTED)
        until = datetime.now() + timedelta(hours=h)
        day = "" if until.date() == datetime.now().date() else " tomorrow"
        self.pause_until.config(text=f"Uptime will be off until {until:%H:%M}{day}.")

    def _pause_now(self):
        self.pause_msg.config(text="Pausing…", fg=MUTED)
        self.update_idletasks()
        start = time.time()
        until = start + self.pause_hours * 3600
        save_pause(start, until)                      # the tracker sees this and stops itself
        ok = schedule_resume(until, self._pythonw(), self._app_file("tracker.pyw"))
        if ok:
            self.destroy()                            # turn the dashboard off too
            return
        self.pause_msg.config(
            text="Paused, but Windows wouldn't schedule the automatic restart. Uptime will start "
                 "again at your next login, or open this window and click Resume now.", fg=BAD)
        self.after(4000, self.refresh)

    def _resume_now(self):
        p = load_pause()
        if p:
            save_pause(p.get("start", time.time()), time.time())  # pause ends now
        try:
            subprocess.Popen([self._pythonw(), self._app_file("tracker.pyw")],
                             cwd=os.path.dirname(self._app_file("tracker.pyw")))
        except OSError:
            pass
        self._draw_status("Starting…", GOOD)
        self.after(2500, self.refresh)

    def _fill_popups(self):
        box = self.popups_box
        for c in box.winfo_children():
            c.destroy()
        s = load_settings()
        mins = s["popup_reminder_minutes"]
        items = [("popup_on_return", GLYPHS["clock"], ACCENT, "When I come back",
                  "After unlocking or waking the laptop"),
                 ("popup_on_distraction", GLYPHS["distracted"], COLORS["distracted"], "When I open a distraction",
                  f"And again every {mins} minutes while I stay on it" if mins else "Once each time"),
                 ("ask_new", GLYPHS["site"], ACCENT, "Ask about new apps and sites",
                  "“Is this for work?” the first time you use something new")]
        for key, glyph, color, title, sub in items:
            on = bool(s[key])
            row = tk.Frame(box, bg=SURFACE, padx=px(8), pady=px(7))
            row.pack(fill="x")
            icon_badge(row, glyph, color if on else MUTED, SURFACE).pack(side="left")
            text = tk.Frame(row, bg=SURFACE)
            text.pack(side="left", padx=(px(12), 0), fill="x", expand=True)
            tk.Label(text, text=title, font=font(10), fg=TEXT if on else MUTED, bg=SURFACE,
                     anchor="w").pack(fill="x")
            tk.Label(text, text=sub, font=font(9), fg=MUTED, bg=SURFACE, anchor="w").pack(fill="x")
            tk.Label(row, text="On" if on else "Off", font=font(9), fg=TEXT2, bg=SURFACE,
                     width=4, anchor="e").pack(side="right", padx=(0, px(44)))
            self._toggle(row, on, lambda k=key: self._toggle_setting(k)).pack(side="right", padx=(px(8), px(6)))
            hoverable(row, SURFACE, SURFACE_HI)

    def _fill_answers(self):
        box = self.answers_box
        for c in box.winfo_children():
            c.destroy()
        labels = load_labels()
        if not labels:
            tk.Label(box, text="No answers yet. Uptime will ask the first time you use a new app or site.",
                     font=font(10), fg=MUTED, bg=SURFACE, anchor="w").pack(fill="x", padx=px(8), pady=px(6))
            return
        order = sorted(labels.items(), key=lambda kv: (kv[1].get("answer") != NOT_WORK, kv[1].get("name", "").lower()))
        for key, entry in order:
            site = key.startswith("site:")
            work = entry.get("answer") == WORK
            row = tk.Frame(box, bg=SURFACE, padx=px(8), pady=px(6))
            row.pack(fill="x")
            icon_badge(row, GLYPHS["site" if site else "app"], GOOD if work else COLORS["distracted"],
                       SURFACE).pack(side="left")
            text = tk.Frame(row, bg=SURFACE)
            text.pack(side="left", padx=(px(12), 0), fill="x", expand=True)
            tk.Label(text, text=entry.get("name") or key_name(key), font=font(10), fg=TEXT, bg=SURFACE,
                     anchor="w").pack(fill="x")
            tk.Label(text, text="Website" if site else "App", font=font(9), fg=MUTED, bg=SURFACE,
                     anchor="w").pack(fill="x")
            delete = tk.Label(row, text=GLYPHS["delete"], font=(ICON_FONT, 11), fg=MUTED, bg=SURFACE,
                              padx=px(10), pady=px(6), cursor="hand2")
            delete.pack(side="right")
            delete.bind("<Button-1>", lambda e, k=key: self._set_answer(k, None))
            delete.bind("<Enter>", lambda e, w=delete: w.config(fg=BAD))
            delete.bind("<Leave>", lambda e, w=delete: w.config(fg=MUTED))
            pill_bg = "#1f3a24" if work else "#3d1f30"
            pill = tk.Label(row, text="Work" if work else "Not work", font=font(9, "semibold"),
                            fg=GOOD if work else COLORS["distracted"], bg=pill_bg, padx=px(12), pady=px(3),
                            cursor="hand2", width=8)
            pill.pack(side="right", padx=(0, px(14)))
            pill.keep_bg = True  # keeps its own colour when the row is highlighted
            hoverable(row, SURFACE, SURFACE_HI)
            pill.bind("<Button-1>", lambda e, k=key, w=work: self._set_answer(k, NOT_WORK if w else WORK), add="+")

    def _set_answer(self, key, value):
        save_label(key, value)
        self._fill_answers()

    def _toggle_setting(self, key):
        s = load_settings()
        s[key] = not s[key]
        save_settings(s)
        self._fill_popups()

    def _show_toast(self, kind, arg=""):
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toast.pyw")
        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
        try:
            subprocess.Popen([pythonw, script, kind, arg], cwd=os.path.dirname(script))
        except OSError:
            pass

    def _pill_button(self, parent, text, command, glyph=None, primary=False):
        bg, hover, fg = (ACCENT, "#8fdcff", "#000000") if primary else (SURFACE_HI, "#3f3f3f", TEXT)
        btn = tk.Frame(parent, bg=bg, padx=px(12), pady=px(5))
        if glyph:
            tk.Label(btn, text=glyph, font=(ICON_FONT, 9), fg=fg, bg=bg).pack(side="left", padx=(0, px(8)))
        tk.Label(btn, text=text, font=font(10), fg=fg, bg=bg).pack(side="left")
        hoverable(btn, bg, hover, command)
        return btn

    def _toggle(self, parent, on, command):
        """Windows 11 style on/off switch."""
        w, h = px(40), px(20)
        c = tk.Canvas(parent, width=w + 2, height=h + 2, bg=SURFACE, highlightthickness=0, cursor="hand2")
        c.follow_bg = True
        if on:
            round_rect(c, 1, 1, w, h, h / 2, fill=ACCENT, outline=ACCENT)
            c.create_oval(w - h + px(5), px(5), w - px(4), h - px(4), fill="#000000", outline="")
        else:
            round_rect(c, 1, 1, w, h, h / 2, fill=SURFACE, outline="#9a9a9a")
            c.create_oval(px(5), px(5), h - px(4), h - px(4), fill="#cfcfcf", outline="")
        c.bind("<Button-1>", lambda e: command())
        return c

    def _fill_top_distractions(self):
        box = self.top_box
        for c in box.winfo_children():
            c.destroy()
        week, today = self.data["distractions_week"], self.data["distractions_today"]
        if not week:
            self._empty(box, "No distractions caught this week. Keep it up!")
            return
        for detail, secs in list(week.items())[:10]:
            sub = f"Today {fmt_dur(today.get(detail, 0))}"
            row = self._row(box, GLYPHS["distracted"], COLORS["distracted"], detail_label(detail), sub,
                            fmt_dur(secs), "this week")
            row.pack(fill="x")
            hoverable(row, SURFACE, SURFACE_HI)

    def _fill_rules(self):
        box = self.rules_box
        for c in box.winfo_children():
            c.destroy()
        self.rules = load_rules()
        for i, rule in enumerate(self.rules):
            on = rule.get("enabled", True)
            row = tk.Frame(box, bg=SURFACE, padx=px(8), pady=px(7))
            row.pack(fill="x")
            kind = "site" if rule.get("type") == "site" else "app"
            icon_badge(row, GLYPHS[kind], COLORS["distracted"] if on else MUTED, SURFACE).pack(side="left")
            text = tk.Frame(row, bg=SURFACE)
            text.pack(side="left", padx=(px(12), 0), fill="x", expand=True)
            tk.Label(text, text=rule.get("name", "Untitled"), font=font(10), fg=TEXT if on else MUTED,
                     bg=SURFACE, anchor="w").pack(fill="x")
            kws = ", ".join(rule.get("keywords", []))
            if len(kws) > 90:
                kws = kws[:88] + "…"
            tk.Label(text, text=f"{'Website' if kind == 'site' else 'App'} · {kws}", font=font(9), fg=MUTED,
                     bg=SURFACE, anchor="w").pack(fill="x")
            delete = tk.Label(row, text=GLYPHS["delete"], font=(ICON_FONT, 11), fg=MUTED, bg=SURFACE,
                              padx=px(10), pady=px(6), cursor="hand2")
            delete.pack(side="right")
            delete.bind("<Button-1>", lambda e, i=i: self._delete_rule(i))
            delete.bind("<Enter>", lambda e, w=delete: w.config(fg=BAD))
            delete.bind("<Leave>", lambda e, w=delete: w.config(fg=MUTED))
            tk.Label(row, text="On" if on else "Off", font=font(9), fg=TEXT2, bg=SURFACE,
                     width=4, anchor="e").pack(side="right", padx=(0, px(10)))
            self._toggle(row, on, lambda i=i: self._toggle_rule(i)).pack(side="right", padx=(px(8), px(6)))
            hoverable(row, SURFACE, SURFACE_HI)

    def _save_rules(self):
        save_rules(self.rules)
        self._fill_rules()

    def _toggle_rule(self, i):
        self.rules[i]["enabled"] = not self.rules[i].get("enabled", True)
        self._save_rules()

    def _delete_rule(self, i):
        del self.rules[i]
        self._save_rules()

    def _reset_rules(self):
        self.rules = [dict(r, keywords=list(r["keywords"])) for r in DEFAULT_RULES]
        self._save_rules()

    def _build_add_form(self, body):
        tk.Label(body, text="Add your own", font=font(11, "semibold"), fg=TEXT, bg=SURFACE,
                 anchor="w").pack(fill="x", pady=(px(22), px(8)))
        form = tk.Frame(body, bg=SURFACE)
        form.pack(fill="x", padx=(px(8), px(8)))
        form.columnconfigure(2, weight=1)

        def field(col, label, width):
            tk.Label(form, text=label, font=font(9), fg=MUTED, bg=SURFACE, anchor="w").grid(
                row=0, column=col, sticky="w", padx=(0, px(12)))
            e = tk.Entry(form, width=width, font=font(10), bg="#1f1f1f", fg=TEXT, insertbackground=TEXT,
                         relief="flat", highlightthickness=1, highlightbackground=BORDER, highlightcolor=ACCENT)
            e.grid(row=1, column=col, sticky="ew", padx=(0, px(12)), ipady=px(5))
            return e

        self.new_name = field(0, "Name", 16)
        tk.Label(form, text="Type", font=font(9), fg=MUTED, bg=SURFACE, anchor="w").grid(
            row=0, column=1, sticky="w", padx=(0, px(12)))
        seg = tk.Frame(form, bg="#1f1f1f", highlightthickness=1, highlightbackground=BORDER)
        seg.grid(row=1, column=1, sticky="ns", padx=(0, px(12)))
        self.new_type = "site"
        self.type_btns = {}
        for key, label in (("site", "Website"), ("app", "App")):
            b = tk.Label(seg, text=label, font=font(10), padx=px(12), cursor="hand2")
            b.pack(side="left", fill="y")
            b.bind("<Button-1>", lambda e, k=key: self._set_new_type(k))
            self.type_btns[key] = b
        self._set_new_type("site")
        self.new_keywords = field(2, "Keywords in the tab title or program name, separated by commas", 30)
        self._pill_button(form, "Add", self._add_rule, GLYPHS["add"], primary=True).grid(
            row=1, column=3, sticky="ns")
        self.add_msg = tk.Label(body, text="e.g.  Name: Cricket  ·  Website  ·  cricbuzz, espncricinfo",
                                font=font(9), fg=MUTED, bg=SURFACE, anchor="w")
        self.add_msg.pack(fill="x", padx=px(8), pady=(px(8), px(6)))

    def _set_new_type(self, key):
        self.new_type = key
        for k, b in self.type_btns.items():
            b.config(bg=SURFACE_HI if k == key else "#1f1f1f", fg=TEXT if k == key else MUTED)

    def _add_rule(self):
        name = self.new_name.get().strip()
        kws = [k.strip() for k in self.new_keywords.get().split(",") if k.strip()]
        if not name or not kws:
            self.add_msg.config(text="Give it a name and at least one keyword.", fg=BAD)
            return
        self.rules.append({"name": name, "type": self.new_type, "enabled": True, "keywords": kws})
        self._save_rules()
        self.new_name.delete(0, "end")
        self.new_keywords.delete(0, "end")
        self.add_msg.config(text=f"Added “{name}”. It starts counting within a few seconds.", fg=GOOD)

    # -------------------------------------------------------- data
    def refresh(self):
        conn = connect()
        try:
            self.data = summary(conn)
        finally:
            conn.close()
        d = self.data
        today = d["days"].get(d["today"], {})

        self._set_card("today", fmt_dur(wasted(today)), self._breakdown(today, limit=2) or "Nothing wasted yet")
        self._set_card("active", fmt_dur(today.get("active", 0)), "Unlocked and not distracted")
        self._set_card("avg_day", fmt_dur(d["avg_day"]), d["avg_day_basis"].capitalize())
        self._set_card("avg_week", fmt_dur(d["avg_week"]), d["avg_week_basis"].capitalize())

        pause = self._active_pause()
        self.pause_icon.config(text=GLYPHS["play"] if pause else GLYPHS["pause"])
        self.pause_text.config(text="Resume now" if pause else "Pause")
        if pause:
            until = datetime.fromtimestamp(pause["until"])
            day = "" if until.date() == datetime.now().date() else f" {until:%a}"
            self._draw_status(f"Paused until {until:%H:%M}{day}", PAUSED)
        elif d["last_heartbeat"] is None:
            self._draw_status("Not started", BAD)
        elif d["tracker_running"]:
            self._draw_status("Tracking", GOOD)
        else:
            last = datetime.fromtimestamp(d["last_heartbeat"]).strftime("%d %b %H:%M")
            self._draw_status(f"Not running · last seen {last}", BAD)

        self._fill_recent()
        self._fill_daily()
        self._fill_weekly()
        self._fill_breaks()
        self._fill_top_distractions()
        self._draw_chart()

        if hasattr(self, "_job"):
            self.after_cancel(self._job)
        self._job = self.after(REFRESH_MS, self.refresh)

    @staticmethod
    def _breakdown(stats, sep=" · ", limit=None):
        kinds = [k for k in WASTED_KINDS if stats.get(k, 0) >= 60]
        if limit:  # keep the biggest ones, in their usual order
            top = set(sorted(kinds, key=lambda k: -stats[k])[:limit])
            kinds = [k for k in kinds if k in top]
        return sep.join(f"{KIND_LABELS[k]} {fmt_dur(stats[k])}" for k in kinds)

    @staticmethod
    def _short_detail(detail):
        """'Shopping|myntra' -> 'Shopping (myntra)' for use inside a ' · ' separated list."""
        rule, _, kw = (detail or "Distracted").partition("|")
        return f"{rule} ({kw})" if kw else rule

    def _break_items(self):
        for start, end, kinds in self.data["breaks"]:
            if end - start < 60:
                continue  # ignore sub-minute blips
            main = max(kinds, key=kinds.get)[0]
            s, e = datetime.fromtimestamp(start), datetime.fromtimestamp(end)
            when = f"{s:%a %d %b, %H:%M} – " + (f"{e:%H:%M}" if s.date() == e.date() else f"{e:%a %H:%M}")
            what = " · ".join(
                f"{self._short_detail(d) if k == 'distracted' else KIND_LABELS[k]} {fmt_dur(v)}"
                for (k, d), v in sorted(kinds.items(), key=lambda kv: -kv[1]) if v >= 30)
            yield main, end - start, when, what

    def _fill_recent(self):
        for c in self.recent.winfo_children():
            c.destroy()
        items = list(self._break_items())[:8]
        if not items:
            self._empty(self.recent, "Breaks will show up here once you lock or sleep your laptop.")
            return
        for i, (kind, dur, when, what) in enumerate(items):
            row = self._row(self.recent, GLYPHS[kind], COLORS[kind], f"{fmt_dur(dur)}  ·  {what}", when)
            row.grid(row=i // 2, column=i % 2, sticky="ew", padx=(0, px(6)) if i % 2 == 0 else (px(6), 0))
            hoverable(row, SURFACE, SURFACE_HI)

    def _fill_daily(self):
        now = datetime.now()
        rows = []
        for day in sorted(self.data["days"], reverse=True):
            s = self.data["days"][day]
            span = 86400.0
            if day == self.data["today"]:
                span = (now - datetime.combine(day, datetime.min.time())).total_seconds()
            w, tr = wasted(s), tracked(s)
            sub = self._breakdown(s) or "No wasted time"
            sub += f"  ·  Active {fmt_dur(s.get('active', 0))}"
            if s.get("paused", 0) >= 60:
                sub += f"  ·  Paused {fmt_dur(s['paused'])}"
            if span - tr >= 600:
                sub += f"  ·  Not tracked {fmt_dur(span - tr)}"
            title = "Today" if day == self.data["today"] else f"{day:%A, %d %B}"
            rows.append(dict(glyph=GLYPHS["calendar"], color=ACCENT, title=title, subtitle=sub,
                             value=fmt_dur(w), note=f"{100 * w / tr:.0f}% of tracked" if tr else "", bar=s))
        self.daily_list.set_rows(rows, "No days tracked yet.")

    def _fill_weekly(self):
        rows = []
        for monday in sorted(self.data["weeks"], reverse=True):
            days = self.data["weeks"][monday]
            stats = [self.data["days"][d] for d in days]
            w = sum(wasted(s) for s in stats)
            act = sum(s.get("active", 0) for s in stats)
            title = f"{monday:%d %b} – {monday + timedelta(days=6):%d %b %Y}"
            sub = f"{len(days)} day{'s' if len(days) != 1 else ''} tracked  ·  Active {fmt_dur(act)}"
            avg = {k: sum(s.get(k, 0) for s in stats) / len(days) for k in WASTED_KINDS}
            rows.append(dict(glyph=GLYPHS["week"], color="#c7a5ff", title=title, subtitle=sub,
                             value=fmt_dur(w), note=f"{fmt_dur(w / len(days))} per day", bar=avg))
        self.weekly_list.set_rows(rows, "No weeks tracked yet.")

    def _fill_breaks(self):
        rows = [dict(glyph=GLYPHS[kind], color=COLORS[kind], title=what, subtitle=when, value=fmt_dur(dur))
                for kind, dur, when, what in self._break_items()]
        self.breaks_list.set_rows(rows, "No breaks recorded yet.")

    # -------------------------------------------------------- chart
    def _chart_geometry(self):
        W, H = self.chart.winfo_width(), int(self.chart["height"])
        left, right, top, bottom = px(34), px(4), px(30), px(36)
        today = self.data["today"]
        days = [today - timedelta(days=i) for i in range(CHART_DAYS - 1, -1, -1)]
        slot = (W - left - right) / CHART_DAYS
        return W, H, left, right, top, bottom, days, slot

    def _draw_chart(self, hover=None):
        c = self.chart
        c.delete("all")
        if not hasattr(self, "data") or c.winfo_width() < 50:
            return
        W, H, left, right, top, bottom, days, slot = self._chart_geometry()
        ph = H - top - bottom
        bw = min(px(26), slot * 0.55)

        # legend
        lx = left
        for k in WASTED_KINDS:
            round_rect(c, lx, px(4), lx + px(10), px(14), px(3), fill=COLORS[k], outline="")
            t = c.create_text(lx + px(16), px(9), text=KIND_LABELS[k], anchor="w", fill=TEXT2, font=font(9))
            lx = c.bbox(t)[2] + px(18)

        for h in (0, 6, 12, 18, 24):
            y = top + ph * (1 - h / 24)
            c.create_line(left, y, W - right, y, fill="#3a3a3a", dash=(2, 4) if h else ())
            c.create_text(left - px(8), y, text=f"{h}h", anchor="e", fill=MUTED, font=font(8))

        if hover is not None:
            x0 = left + slot * hover
            round_rect(c, x0 + px(2), top - px(6), x0 + slot - px(2), top + ph + px(30), px(6),
                       fill="#333333", outline="")

        for i, d in enumerate(days):
            x = left + slot * i + (slot - bw) / 2
            stats = self.data["days"].get(d, {})
            segs = [(k, ph * stats.get(k, 0) / 86400) for k in WASTED_KINDS if stats.get(k, 0) > 0]
            y = top + ph
            for j, (k, h) in enumerate(segs):
                if j == len(segs) - 1 and h > px(4):   # round the top of the bar
                    round_rect(c, x, y - h, x + bw, y, px(4), fill=COLORS[k], outline="")
                    c.create_rectangle(x, y - min(h, px(4)) , x + bw, y, fill=COLORS[k], outline="")
                else:
                    c.create_rectangle(x, y - h, x + bw, y, fill=COLORS[k], outline="")
                y -= h
            is_today = d == self.data["today"]
            c.create_text(x + bw / 2, top + ph + px(11), text="Today" if is_today else d.strftime("%a"),
                          fill=TEXT if is_today or hover == i else MUTED, font=font(8))
            if not is_today:
                c.create_text(x + bw / 2, top + ph + px(25), text=d.strftime("%d"),
                              fill=TEXT if hover == i else MUTED, font=font(8))

        avg = self.data["avg_day"]
        if avg:
            y = top + ph * (1 - min(avg, 86400) / 86400)
            c.create_line(left, y, W - right, y, fill=BAD, dash=(5, 3))
            t = c.create_text(W - right - px(6), y - px(9), text=f"avg {fmt_dur(avg)}", anchor="e",
                              fill=BAD, font=font(8))
            c.tag_lower(round_rect(c, *self._pad(c.bbox(t), 4), px(4), fill=SURFACE, outline=""), t)

        if hover is not None:
            self._tooltip(days[hover], left + slot * hover + slot / 2, top)

    @staticmethod
    def _pad(bbox, p):
        return bbox[0] - px(p), bbox[1] - px(p / 2), bbox[2] + px(p), bbox[3] + px(p / 2)

    def _tooltip(self, day, cx, top):
        c = self.chart
        stats = self.data["days"].get(day, {})
        lines = [(f"{day:%a %d %b}", TEXT, font(9, "semibold")),
                 (f"Wasted {fmt_dur(wasted(stats))}", TEXT, font(9))]
        lines += [(f"{KIND_LABELS[k]}  {fmt_dur(stats.get(k, 0))}", COLORS[k], font(9)) for k in WASTED_KINDS]
        lines.append((f"Active  {fmt_dur(stats.get('active', 0))}", GOOD, font(9)))
        items = []
        y = top + px(6)
        for text, color, f in lines:
            items.append(c.create_text(0, y, text=text, fill=color, font=f, anchor="nw"))
            y = c.bbox(items[-1])[3] + px(1)
        x1, y1, x2, y2 = c.bbox(*items)
        w = x2 - x1
        x = cx + px(18)
        if x + w + px(24) > c.winfo_width():
            x = cx - px(18) - w
        for it in items:
            c.move(it, x, 0)
        bg = round_rect(c, x - px(10), y1 - px(8), x + w + px(10), y2 + px(8), px(6),
                        fill="#2f2f2f", outline="#4a4a4a")
        c.tag_lower(bg, items[0])

    def _chart_hover(self, e):
        if not hasattr(self, "data"):
            return
        W, H, left, right, top, bottom, days, slot = self._chart_geometry()
        i = int((e.x - left) // slot)
        hover = i if 0 <= i < CHART_DAYS and e.x >= left else None
        if hover != getattr(self, "_hover", "x"):
            self._hover = hover
            self._draw_chart(hover)


if __name__ == "__main__":
    try:
        Dashboard().mainloop()
    except Exception:
        # pythonw has no console, so record the error and tell the user where it is.
        import os
        import traceback
        from tkinter import messagebox
        log = os.path.join(DATA_DIR, "error.log")
        os.makedirs(DATA_DIR, exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}]\n{traceback.format_exc()}")
        messagebox.showerror("Uptime", f"Uptime couldn't start.\n\nDetails were saved to:\n{log}")
        raise
