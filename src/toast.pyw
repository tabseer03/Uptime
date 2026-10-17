"""A small on-screen pop-up with today's wasted time, like Windows' volume or "plugged in" OSD.

Built straight on the Windows API (not Tk, which activates its windows while setting them
up): the window is created click-through, no-activate, always-on-top and out of the
taskbar, so it can never take focus or block a click. It is also excluded from screen
capture, so screen shares and recordings don't show it. It fades in at the top-left
corner, stays a few seconds and fades away. The tracker starts it as a short-lived process:

    pythonw toast.pyw back [seconds_away]
    pythonw toast.pyw distracted "Shopping|flipkart"
"""
import ctypes
import os
import random
import sys
from ctypes import wintypes

from common import connect, fmt_dur, wasted_today

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    pass

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
dwmapi = ctypes.WinDLL("dwmapi")

LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)


class WNDCLASSEXW(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", WNDPROC),
                ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
                ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
                ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON)]


class PAINTSTRUCT(ctypes.Structure):
    _fields_ = [("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
                ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL), ("rgbReserved", ctypes.c_byte * 32)]


user32.DefWindowProcW.restype = LRESULT
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.RegisterClassExW.argtypes = [ctypes.POINTER(WNDCLASSEXW)]
user32.CreateWindowExW.restype = wintypes.HWND
user32.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                   ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                   wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID]
user32.BeginPaint.restype = wintypes.HDC
user32.BeginPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.EndPaint.argtypes = [wintypes.HWND, ctypes.POINTER(PAINTSTRUCT)]
user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.SetLayeredWindowAttributes.argtypes = [wintypes.HWND, wintypes.COLORREF, wintypes.BYTE, wintypes.DWORD]
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
user32.FillRect.argtypes = [wintypes.HDC, ctypes.POINTER(wintypes.RECT), wintypes.HBRUSH]
user32.DrawTextW.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.RECT), wintypes.UINT]
user32.SystemParametersInfoW.argtypes = [wintypes.UINT, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
user32.GetDC.restype = wintypes.HDC
user32.GetDC.argtypes = [wintypes.HWND]
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HRGN, wintypes.BOOL]
gdi32.CreateFontW.restype = wintypes.HFONT
gdi32.CreateFontW.argtypes = [ctypes.c_int] * 5 + [wintypes.DWORD] * 8 + [wintypes.LPCWSTR]
gdi32.SelectObject.restype = wintypes.HGDIOBJ
gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HGDIOBJ]
gdi32.DeleteObject.argtypes = [wintypes.HGDIOBJ]
gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
gdi32.CreateSolidBrush.argtypes = [wintypes.COLORREF]
gdi32.CreatePen.restype = wintypes.HPEN
gdi32.CreatePen.argtypes = [ctypes.c_int, ctypes.c_int, wintypes.COLORREF]
gdi32.RoundRect.argtypes = [wintypes.HDC] + [ctypes.c_int] * 6
gdi32.SetTextColor.argtypes = [wintypes.HDC, wintypes.COLORREF]
gdi32.SetBkMode.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.GetDeviceCaps.argtypes = [wintypes.HDC, ctypes.c_int]
gdi32.GetTextExtentPoint32W.argtypes = [wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.POINTER(wintypes.SIZE)]
gdi32.CreateRoundRectRgn.restype = wintypes.HRGN
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
WDA_EXCLUDEFROMCAPTURE = 0x11
gdi32.GetStockObject.restype = wintypes.HGDIOBJ
gdi32.GetStockObject.argtypes = [ctypes.c_int]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.CreateMutexW.restype = wintypes.HANDLE

WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x8, 0x20, 0x80
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x80000, 0x08000000
WM_DESTROY, WM_PAINT, WM_TIMER, WM_NCHITTEST, WM_MOUSEACTIVATE = 0x2, 0xF, 0x113, 0x84, 0x21
HTTRANSPARENT, MA_NOACTIVATE = -1, 3
SW_SHOWNOACTIVATE, LWA_ALPHA = 4, 0x2
SPI_GETWORKAREA, LOGPIXELSY = 0x30, 90
DT_LEFT, DT_VCENTER, DT_SINGLELINE, DT_CENTER, DT_NOPREFIX = 0x0, 0x4, 0x20, 0x1, 0x800
CLEARTYPE_QUALITY, TRANSPARENT_BK, PS_SOLID = 5, 1, 0
FW_NORMAL, FW_SEMIBOLD = 400, 600

FADE_MS, SHOW_MS, TICK_MS = 160, 4200, 15
MAX_ALPHA = 245
TIMER_FADE_IN, TIMER_HOLD, TIMER_FADE_OUT = 1, 2, 3

BACK_LINES = ["Welcome back", "Back at it", "There you are"]
NUDGES = ["Is this worth it?", "Close it and get back to work", "This is going on your record",
          "Your future self is watching", "One more minute? Sure..."]


def rgb(hex_color):
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return r | (g << 8) | (b << 16)


BG, BORDER, TILE = rgb("#2b2b2b"), rgb("#3d3d3d"), rgb("#383838")
TEXT, MUTED, ACCENT, PINK = rgb("#ffffff"), rgb("#b5b5b5"), rgb("#60cdff"), rgb("#f472b6")


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


class Toast:
    def __init__(self, glyph, color, small, big):
        self.glyph, self.color, self.small, self.big = glyph, color, small, big
        self.alpha = 0
        screen = user32.GetDC(None)
        self.k = gdi32.GetDeviceCaps(screen, LOGPIXELSY) / 96.0
        user32.ReleaseDC(None, screen)
        self.f_small = self._font("Segoe UI Variable Text", 9, FW_NORMAL)
        self.f_big = self._font("Segoe UI Variable Display", 15, FW_SEMIBOLD)
        self.f_icon = self._font("Segoe Fluent Icons", 15, FW_NORMAL)

        text_w = max(self._measure(self.f_small, small), self._measure(self.f_big, big))
        self.w = self.px(16 + 40 + 14 + 22) + text_w
        self.h = self.px(72)

        self._proc = WNDPROC(self._wndproc)  # keep a reference for the lifetime of the window
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._proc,
                         hInstance=hinst, lpszClassName="UptimeToast")
        user32.RegisterClassExW(ctypes.byref(wc))

        work = wintypes.RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work), 0)
        x = work.left + self.px(16)   # top-left corner of the screen (above any top taskbar)
        y = work.top + self.px(16)
        ex = WS_EX_TOPMOST | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE
        self.hwnd = user32.CreateWindowExW(ex, "UptimeToast", "Uptime", WS_POPUP,
                                           x, y, self.w, self.h, None, None, hinst, None)
        # Leave the pop-up out of screen sharing, screen recording and screenshots: it shows
        # on your monitor only (Windows 10 2004 or later).
        if not os.environ.get("UPTIME_TOAST_CAPTURABLE"):  # set only for testing
            user32.SetWindowDisplayAffinity(self.hwnd, WDA_EXCLUDEFROMCAPTURE)
        # Windows 11 draws smooth rounded corners for us; older Windows gets a rounded region.
        corner = ctypes.c_int(3)  # DWMWCP_ROUNDSMALL
        if dwmapi.DwmSetWindowAttribute(self.hwnd, 33, ctypes.byref(corner), 4) != 0:
            r = self.px(8)
            user32.SetWindowRgn(self.hwnd, gdi32.CreateRoundRectRgn(0, 0, self.w + 1, self.h + 1, r * 2, r * 2), True)
        user32.SetLayeredWindowAttributes(self.hwnd, 0, 0, LWA_ALPHA)
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        user32.SetTimer(self.hwnd, TIMER_FADE_IN, TICK_MS, None)

    def px(self, n):
        return int(round(n * self.k))

    def _font(self, face, pt, weight):
        return gdi32.CreateFontW(-int(round(pt * self.k * 96 / 72)), 0, 0, 0, weight,
                                 0, 0, 0, 1, 0, 0, CLEARTYPE_QUALITY, 0, face)

    def _measure(self, font, text):
        dc = user32.GetDC(None)
        old = gdi32.SelectObject(dc, font)
        size = wintypes.SIZE()
        gdi32.GetTextExtentPoint32W(dc, text, len(text), ctypes.byref(size))
        gdi32.SelectObject(dc, old)
        user32.ReleaseDC(None, dc)
        return size.cx

    def _text(self, dc, font, color, text, rect, flags):
        gdi32.SelectObject(dc, font)
        gdi32.SetTextColor(dc, color)
        user32.DrawTextW(dc, text, -1, ctypes.byref(rect), flags | DT_SINGLELINE | DT_NOPREFIX)

    def _paint(self):
        ps = PAINTSTRUCT()
        dc = user32.BeginPaint(self.hwnd, ctypes.byref(ps))
        bg = gdi32.CreateSolidBrush(BG)
        user32.FillRect(dc, ctypes.byref(wintypes.RECT(0, 0, self.w, self.h)), bg)
        gdi32.SetBkMode(dc, TRANSPARENT_BK)
        # border
        pen = gdi32.CreatePen(PS_SOLID, 1, BORDER)
        hollow = gdi32.GetStockObject(5)  # NULL_BRUSH
        old_pen, old_brush = gdi32.SelectObject(dc, pen), gdi32.SelectObject(dc, hollow)
        r = self.px(8)
        gdi32.RoundRect(dc, 0, 0, self.w, self.h, r * 2, r * 2)
        # icon tile
        tile = gdi32.CreateSolidBrush(TILE)
        tile_pen = gdi32.CreatePen(PS_SOLID, 1, TILE)
        gdi32.SelectObject(dc, tile)
        gdi32.SelectObject(dc, tile_pen)
        t = self.px(40)
        tx, ty = self.px(16), (self.h - t) // 2
        gdi32.RoundRect(dc, tx, ty, tx + t, ty + t, self.px(12), self.px(12))
        self._text(dc, self.f_icon, self.color, self.glyph, wintypes.RECT(tx, ty, tx + t, ty + t),
                   DT_CENTER | DT_VCENTER)
        # two lines of text
        left = tx + t + self.px(14)
        self._text(dc, self.f_small, MUTED, self.small,
                   wintypes.RECT(left, self.px(12), self.w, self.px(32)), DT_LEFT | DT_VCENTER)
        self._text(dc, self.f_big, TEXT, self.big,
                   wintypes.RECT(left, self.px(30), self.w, self.px(60)), DT_LEFT | DT_VCENTER)
        gdi32.SelectObject(dc, old_pen)
        gdi32.SelectObject(dc, old_brush)
        for obj in (bg, pen, tile, tile_pen):
            gdi32.DeleteObject(obj)
        user32.EndPaint(self.hwnd, ctypes.byref(ps))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_PAINT:
            self._paint()
            return 0
        if msg == WM_NCHITTEST:
            return HTTRANSPARENT          # clicks go to whatever is underneath
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE
        if msg == WM_TIMER:
            step = max(1, MAX_ALPHA * TICK_MS // FADE_MS)
            if wparam == TIMER_FADE_IN:
                self.alpha = min(MAX_ALPHA, self.alpha + step)
                user32.SetLayeredWindowAttributes(hwnd, 0, self.alpha, LWA_ALPHA)
                if self.alpha >= MAX_ALPHA:
                    user32.KillTimer(hwnd, TIMER_FADE_IN)
                    user32.SetTimer(hwnd, TIMER_HOLD, SHOW_MS, None)
            elif wparam == TIMER_HOLD:
                user32.KillTimer(hwnd, TIMER_HOLD)
                user32.SetTimer(hwnd, TIMER_FADE_OUT, TICK_MS, None)
            elif wparam == TIMER_FADE_OUT:
                self.alpha = max(0, self.alpha - step // 2 or 1)  # fade out a bit slower
                user32.SetLayeredWindowAttributes(hwnd, 0, self.alpha, LWA_ALPHA)
                if self.alpha <= 0:
                    user32.DestroyWindow(hwnd)
            return 0
        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def run(self):
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))


def main():
    # Only one pop-up at a time; a second one simply doesn't show.
    kernel32.CreateMutexW(None, False, "Local\\UptimeToast")
    if ctypes.get_last_error() == 183:
        return
    kind = sys.argv[1] if len(sys.argv) > 1 else "back"
    arg = sys.argv[2] if len(sys.argv) > 2 else None
    Toast(*message(kind, arg)).run()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        pass  # a pop-up must never bother you with an error
