"""Shared base for Uptime's on-screen pop-ups (toast.pyw and ask.pyw).

Built straight on the Windows API (not Tk, which activates its windows while setting them
up). Every pop-up is created no-activate, always-on-top and out of the taskbar and Alt+Tab,
so it can never take focus, and it is excluded from screen capture so screen shares and
recordings don't show it. Subclasses draw their content and may accept clicks.
"""
import ctypes
import os
from ctypes import wintypes

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


class TRACKMOUSEEVENT(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("dwFlags", wintypes.DWORD), ("hwndTrack", wintypes.HWND),
                ("dwHoverTime", wintypes.DWORD)]


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
user32.InvalidateRect.argtypes = [wintypes.HWND, ctypes.c_void_p, wintypes.BOOL]
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
user32.SetWindowDisplayAffinity.argtypes = [wintypes.HWND, wintypes.DWORD]
user32.FindWindowW.restype = wintypes.HWND
user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
user32.LoadCursorW.restype = wintypes.HANDLE
user32.LoadCursorW.argtypes = [wintypes.HINSTANCE, ctypes.c_void_p]
user32.TrackMouseEvent.argtypes = [ctypes.POINTER(TRACKMOUSEEVENT)]
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
gdi32.GetStockObject.restype = wintypes.HGDIOBJ
gdi32.GetStockObject.argtypes = [ctypes.c_int]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
kernel32.CreateMutexW.restype = wintypes.HANDLE

WS_POPUP = 0x80000000
WS_EX_TOPMOST, WS_EX_TRANSPARENT, WS_EX_TOOLWINDOW = 0x8, 0x20, 0x80
WS_EX_LAYERED, WS_EX_NOACTIVATE = 0x80000, 0x08000000
WM_DESTROY, WM_PAINT, WM_TIMER, WM_NCHITTEST, WM_MOUSEACTIVATE = 0x2, 0xF, 0x113, 0x84, 0x21
WM_MOUSEMOVE, WM_LBUTTONUP, WM_MOUSELEAVE, WM_SETCURSOR = 0x200, 0x202, 0x2A3, 0x20
HTTRANSPARENT, MA_NOACTIVATE = -1, 3
SW_SHOWNOACTIVATE, LWA_ALPHA = 4, 0x2
SPI_GETWORKAREA, LOGPIXELSY = 0x30, 90
DT_LEFT, DT_CENTER, DT_VCENTER, DT_SINGLELINE, DT_NOPREFIX, DT_END_ELLIPSIS = 0x0, 0x1, 0x4, 0x20, 0x800, 0x8000
CLEARTYPE_QUALITY, TRANSPARENT_BK, PS_SOLID, NULL_BRUSH = 5, 1, 0, 5
FW_NORMAL, FW_SEMIBOLD = 400, 600
WDA_EXCLUDEFROMCAPTURE = 0x11
TME_LEAVE = 0x2
IDC_ARROW, IDC_HAND = 32512, 32649

TICK_MS = 15
TIMER_FADE_IN, TIMER_HOLD, TIMER_FADE_OUT = 1, 2, 3
MAX_ALPHA = 245


def rgb(hex_color):
    r, g, b = int(hex_color[1:3], 16), int(hex_color[3:5], 16), int(hex_color[5:7], 16)
    return r | (g << 8) | (b << 16)


BG, BORDER, TILE = rgb("#2b2b2b"), rgb("#3d3d3d"), rgb("#383838")
TEXT, MUTED, ACCENT, PINK = rgb("#ffffff"), rgb("#b5b5b5"), rgb("#60cdff"), rgb("#f472b6")


def single_instance(name):
    """True if this is the only pop-up of its kind showing right now."""
    kernel32.CreateMutexW(None, False, f"Local\\{name}")
    return ctypes.get_last_error() != 183


class OSDWindow:
    CLASS = "UptimeOSD"
    CLICKABLE = False      # False: clicks pass straight through to the window underneath
    SHOW_MS = 4200
    FADE_MS = 160

    def __init__(self, width, height):
        screen = user32.GetDC(None)
        self.k = gdi32.GetDeviceCaps(screen, LOGPIXELSY) / 96.0
        user32.ReleaseDC(None, screen)
        self.w, self.h = width, height
        self.alpha = 0
        self.closing = False
        self._proc = WNDPROC(self._wndproc)  # keep a reference for the lifetime of the window
        hinst = kernel32.GetModuleHandleW(None)
        wc = WNDCLASSEXW(cbSize=ctypes.sizeof(WNDCLASSEXW), lpfnWndProc=self._proc,
                         hInstance=hinst, lpszClassName=self.CLASS,
                         hCursor=user32.LoadCursorW(None, ctypes.c_void_p(IDC_ARROW)))
        user32.RegisterClassExW(ctypes.byref(wc))

        x, y = self.position()
        ex = WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_LAYERED | WS_EX_NOACTIVATE
        if not self.CLICKABLE:
            ex |= WS_EX_TRANSPARENT
        self.hwnd = user32.CreateWindowExW(ex, self.CLASS, "Uptime", WS_POPUP,
                                           x, y, self.w, self.h, None, None, hinst, None)
        if not os.environ.get("UPTIME_TOAST_CAPTURABLE"):  # set only for testing
            user32.SetWindowDisplayAffinity(self.hwnd, WDA_EXCLUDEFROMCAPTURE)
        corner = ctypes.c_int(3)  # Windows 11 smooth rounded corners; older Windows gets a region
        if dwmapi.DwmSetWindowAttribute(self.hwnd, 33, ctypes.byref(corner), 4) != 0:
            r = self.px(8)
            user32.SetWindowRgn(self.hwnd, gdi32.CreateRoundRectRgn(0, 0, self.w + 1, self.h + 1, r * 2, r * 2), True)
        user32.SetLayeredWindowAttributes(self.hwnd, 0, 0, LWA_ALPHA)
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        user32.SetTimer(self.hwnd, TIMER_FADE_IN, TICK_MS, None)

    # ---- helpers for subclasses
    def px(self, n):
        return int(round(n * self.k))

    @staticmethod
    def scale():
        screen = user32.GetDC(None)
        k = gdi32.GetDeviceCaps(screen, LOGPIXELSY) / 96.0
        user32.ReleaseDC(None, screen)
        return k

    @staticmethod
    def font(face, pt, weight=FW_NORMAL, k=1.0):
        return gdi32.CreateFontW(-int(round(pt * k * 96 / 72)), 0, 0, 0, weight,
                                 0, 0, 0, 1, 0, 0, CLEARTYPE_QUALITY, 0, face)

    @staticmethod
    def measure(font, text):
        dc = user32.GetDC(None)
        old = gdi32.SelectObject(dc, font)
        size = wintypes.SIZE()
        gdi32.GetTextExtentPoint32W(dc, text, len(text), ctypes.byref(size))
        gdi32.SelectObject(dc, old)
        user32.ReleaseDC(None, dc)
        return size.cx

    def position(self):
        """Top-left corner of the screen."""
        work = wintypes.RECT()
        user32.SystemParametersInfoW(SPI_GETWORKAREA, 0, ctypes.byref(work), 0)
        k = self.k if hasattr(self, "k") else 1.0
        return work.left + int(16 * k), work.top + int(16 * k)

    def text(self, dc, font, color, text, rect, flags=DT_LEFT | DT_VCENTER):
        gdi32.SelectObject(dc, font)
        gdi32.SetTextColor(dc, color)
        user32.DrawTextW(dc, text, -1, ctypes.byref(rect), flags | DT_SINGLELINE | DT_NOPREFIX)

    def round_rect(self, dc, x1, y1, x2, y2, radius, fill, outline=None):
        brush = gdi32.CreateSolidBrush(fill) if fill is not None else None
        pen = gdi32.CreatePen(PS_SOLID, 1, outline if outline is not None else fill)
        old_b = gdi32.SelectObject(dc, brush or gdi32.GetStockObject(NULL_BRUSH))
        old_p = gdi32.SelectObject(dc, pen)
        gdi32.RoundRect(dc, x1, y1, x2, y2, radius * 2, radius * 2)
        gdi32.SelectObject(dc, old_b)
        gdi32.SelectObject(dc, old_p)
        if brush:
            gdi32.DeleteObject(brush)
        gdi32.DeleteObject(pen)

    def icon_tile(self, dc, glyph, color, icon_font):
        t = self.px(40)
        tx, ty = self.px(16), (self.h - t) // 2
        self.round_rect(dc, tx, ty, tx + t, ty + t, self.px(6), TILE)
        self.text(dc, icon_font, color, glyph, wintypes.RECT(tx, ty, tx + t, ty + t), DT_CENTER | DT_VCENTER)
        return tx + t + self.px(14)

    def close(self):
        """Start fading out (then the window closes and the process ends)."""
        if not self.closing:
            self.closing = True
            user32.KillTimer(self.hwnd, TIMER_FADE_IN)
            user32.KillTimer(self.hwnd, TIMER_HOLD)
            user32.SetTimer(self.hwnd, TIMER_FADE_OUT, TICK_MS, None)

    def redraw(self):
        user32.InvalidateRect(self.hwnd, None, False)

    # ---- to override
    def draw(self, dc):
        pass

    def on_mouse(self, x, y, clicked):
        pass

    # ---- window procedure
    def _paint(self):
        ps = PAINTSTRUCT()
        dc = user32.BeginPaint(self.hwnd, ctypes.byref(ps))
        bg = gdi32.CreateSolidBrush(BG)
        user32.FillRect(dc, ctypes.byref(wintypes.RECT(0, 0, self.w, self.h)), bg)
        gdi32.DeleteObject(bg)
        gdi32.SetBkMode(dc, TRANSPARENT_BK)
        self.round_rect(dc, 0, 0, self.w, self.h, self.px(8), None, BORDER)
        self.draw(dc)
        user32.EndPaint(self.hwnd, ctypes.byref(ps))

    def _wndproc(self, hwnd, msg, wparam, lparam):
        if msg == WM_PAINT:
            self._paint()
            return 0
        if msg == WM_NCHITTEST and not self.CLICKABLE:
            return HTTRANSPARENT
        if msg == WM_MOUSEACTIVATE:
            return MA_NOACTIVATE              # clicking never takes focus
        if msg in (WM_MOUSEMOVE, WM_LBUTTONUP):
            x = ctypes.c_short(lparam & 0xFFFF).value
            y = ctypes.c_short((lparam >> 16) & 0xFFFF).value
            if msg == WM_MOUSEMOVE:
                tme = TRACKMOUSEEVENT(ctypes.sizeof(TRACKMOUSEEVENT), TME_LEAVE, hwnd, 0)
                user32.TrackMouseEvent(ctypes.byref(tme))
            self.on_mouse(x, y, msg == WM_LBUTTONUP)
            return 0
        if msg == WM_MOUSELEAVE:
            self.on_mouse(-1, -1, False)
            return 0
        if msg == WM_TIMER:
            step = max(1, MAX_ALPHA * TICK_MS // self.FADE_MS)
            if wparam == TIMER_FADE_IN:
                self.alpha = min(MAX_ALPHA, self.alpha + step)
                user32.SetLayeredWindowAttributes(hwnd, 0, self.alpha, LWA_ALPHA)
                if self.alpha >= MAX_ALPHA:
                    user32.KillTimer(hwnd, TIMER_FADE_IN)
                    user32.SetTimer(hwnd, TIMER_HOLD, self.SHOW_MS, None)
            elif wparam == TIMER_HOLD:
                self.close()
            elif wparam == TIMER_FADE_OUT:
                self.alpha = max(0, self.alpha - max(1, step // 2))
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
