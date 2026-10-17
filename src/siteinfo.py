"""Find which website a browser window is on, by reading its address bar.

Uses Windows UI Automation through raw COM calls (ctypes only, no extra packages).
Lookups are cached per window and tab title, so the address bar is only read when you
switch windows or the page changes (about 50 ms each time).
"""
import ctypes
from ctypes import POINTER, byref, c_int, c_long, c_void_p, wintypes
from urllib.parse import urlsplit

ole32 = ctypes.WinDLL("ole32")
oleaut32 = ctypes.WinDLL("oleaut32")
oleaut32.SysFreeString.argtypes = [c_void_p]

UIA_CONTROL_TYPE = 30003
UIA_EDIT = 50004
UIA_VALUE = 30045
TREE_DESCENDANTS = 4
VT_I4, VT_BSTR = 3, 8


class GUID(ctypes.Structure):
    _fields_ = [("a", ctypes.c_uint32), ("b", ctypes.c_uint16), ("c", ctypes.c_uint16),
                ("d", ctypes.c_ubyte * 8)]


class VARIANT(ctypes.Structure):
    class _Value(ctypes.Union):
        _fields_ = [("lVal", c_long), ("bstrVal", c_void_p), ("raw", ctypes.c_ulonglong * 2)]
    _fields_ = [("vt", ctypes.c_ushort), ("r1", ctypes.c_ushort), ("r2", ctypes.c_ushort),
                ("r3", ctypes.c_ushort), ("v", _Value)]


def _guid(text):
    g = GUID()
    ole32.CLSIDFromString(ctypes.c_wchar_p(text), byref(g))
    return g


def _method(obj, index, *argtypes):
    """Call slot `index` of a COM object's vtable."""
    vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
    fn = ctypes.WINFUNCTYPE(ctypes.HRESULT, c_void_p, *argtypes)(vtbl[index])
    return lambda *args: fn(obj, *args)


def _release(obj):
    if obj:
        vtbl = ctypes.cast(obj, POINTER(POINTER(c_void_p))).contents
        ctypes.WINFUNCTYPE(ctypes.c_ulong, c_void_p)(vtbl[2])(obj)


def domain_of(address):
    """'https://www.leetcode.com/problems/x' or 'leetcode.com/x' -> 'leetcode.com'; None if not a site."""
    text = (address or "").strip()
    if not text or " " in text:
        return None                      # empty, or a search being typed
    if "://" not in text:
        text = "https://" + text
    try:
        parts = urlsplit(text)
    except ValueError:
        return None
    if parts.scheme not in ("http", "https"):
        return None                      # chrome://, edge://, about:, file:...
    host = (parts.hostname or "").lower()
    if "." not in host and host != "localhost":
        return None
    for prefix in ("www.", "m."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return host or None


def app_name(exe_path):
    """A program's friendly name from its file details ('Code.exe' -> 'Visual Studio Code')."""
    version = ctypes.WinDLL("version")
    try:
        size = version.GetFileVersionInfoSizeW(exe_path, None)
        if size:
            data = ctypes.create_string_buffer(size)
            if version.GetFileVersionInfoW(exe_path, 0, size, data):
                trans, n = c_void_p(), ctypes.c_uint()
                langs = [(0x0409, 0x04B0)]
                if version.VerQueryValueW(data, "\\VarFileInfo\\Translation", byref(trans), byref(n)) and n.value >= 4:
                    words = ctypes.cast(trans, POINTER(ctypes.c_ushort))
                    langs.insert(0, (words[0], words[1]))
                for lang, cp in langs:
                    for field in ("FileDescription", "ProductName"):
                        ptr, ln = c_void_p(), ctypes.c_uint()
                        if version.VerQueryValueW(data, f"\\StringFileInfo\\{lang:04x}{cp:04x}\\{field}",
                                                  byref(ptr), byref(ln)) and ln.value > 1:
                            name = ctypes.wstring_at(ptr, ln.value - 1).strip()
                            if name:
                                return name
    except OSError:
        pass
    import os
    return os.path.splitext(os.path.basename(exe_path or ""))[0] or "this app"


class SiteReader:
    def __init__(self):
        self.uia = None
        self.cond = None
        self.cache = {}
        try:
            ole32.CoInitializeEx(None, 2)  # apartment threaded, on the tracker's thread
            uia = c_void_p()
            if ole32.CoCreateInstance(byref(_guid("{ff48dba4-60ef-4201-aa87-54103eef594e}")), None, 1,
                                      byref(_guid("{30cbe57d-d9d0-452a-ab13-7ac5ac4825ee}")), byref(uia)) == 0:
                self.uia = uia
                is_edit = VARIANT(vt=VT_I4)
                is_edit.v.lVal = UIA_EDIT
                cond = c_void_p()
                _method(uia, 23, c_int, VARIANT, POINTER(c_void_p))(UIA_CONTROL_TYPE, is_edit, byref(cond))
                self.cond = cond
        except OSError:
            self.uia = None

    def _address(self, hwnd):
        if not (self.uia and self.cond):
            return None
        window = c_void_p()
        try:
            _method(self.uia, 6, wintypes.HWND, POINTER(c_void_p))(hwnd, byref(window))
        except OSError:
            return None
        if not window:
            return None
        try:
            edit = c_void_p()
            try:
                _method(window, 5, c_int, c_void_p, POINTER(c_void_p))(TREE_DESCENDANTS, self.cond, byref(edit))
            except OSError:
                return None
            if not edit:
                return None
            try:
                value = VARIANT()
                _method(edit, 10, c_int, POINTER(VARIANT))(UIA_VALUE, byref(value))
                if value.vt == VT_BSTR and value.v.bstrVal:
                    text = ctypes.wstring_at(value.v.bstrVal)
                    oleaut32.SysFreeString(value.v.bstrVal)
                    return text
            finally:
                _release(edit)
        finally:
            _release(window)
        return None

    def domain(self, hwnd, title):
        """Website of a browser window (cached until the window or tab title changes)."""
        key = (hwnd, title)
        if key not in self.cache:
            if len(self.cache) > 200:
                self.cache.clear()
            self.cache[key] = domain_of(self._address(hwnd))
        return self.cache[key]
