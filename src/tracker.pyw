"""Background tracker: records every few seconds whether the laptop is active, locked,
or showing a distracting app or website.

Run with pythonw so no window appears. Time with no samples (sleep, hibernate,
shutdown) shows up as gaps, which the dashboard counts as wasted time.
"""
import ctypes
import hashlib
import os
import subprocess
import sys
import time
from ctypes import wintypes

if "--data-dir" in sys.argv[:-1]:  # used by the scheduled restart for a non-default data folder
    os.environ["WTT_DATA_DIR"] = sys.argv[sys.argv.index("--data-dir") + 1]

from common import (DATA_DIR, HEARTBEAT_SECONDS, MAX_GAP_SECONDS, PAUSE_PATH, REBOOT_TOLERANCE,
                    RULES_PATH, SETTINGS_PATH, cancel_resume, clear_pause, connect, load_pause,
                    load_rules, load_settings, match_distraction)

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
wtsapi32 = ctypes.WinDLL("wtsapi32", use_last_error=True)
user32.OpenInputDesktop.restype = wintypes.HANDLE
user32.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
user32.SwitchDesktop.argtypes = [wintypes.HANDLE]
user32.CloseDesktop.argtypes = [wintypes.HANDLE]
kernel32.GetTickCount64.restype = ctypes.c_ulonglong
kernel32.CreateMutexW.restype = wintypes.HANDLE
wtsapi32.WTSQuerySessionInformationW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, ctypes.c_int,
    ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(wintypes.DWORD)]
wtsapi32.WTSFreeMemory.argtypes = [ctypes.c_void_p]
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.QueryFullProcessImageNameW.argtypes = [
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

DESKTOP_SWITCHDESKTOP = 0x0100
ERROR_ALREADY_EXISTS = 183
WTS_SESSION_INFO_EX = 25
WTS_SESSIONSTATE_LOCK = 0
WTS_SESSIONSTATE_UNLOCK = 1


def _session_id():
    sid = wintypes.DWORD()
    kernel32.ProcessIdToSessionId(kernel32.GetCurrentProcessId(), ctypes.byref(sid))
    return sid.value


SESSION_ID = _session_id()


def _wts_lock_state():
    """Ask Windows whether this session is locked. Returns True/False, or None if unknown."""
    buf, size = ctypes.c_void_p(), wintypes.DWORD()
    if not wtsapi32.WTSQuerySessionInformationW(None, SESSION_ID, WTS_SESSION_INFO_EX,
                                                ctypes.byref(buf), ctypes.byref(size)):
        return None
    try:
        # WTSINFOEXW: Level (DWORD), then WTSINFOEX_LEVEL1_W aligned to 8 bytes:
        # SessionId, SessionState, SessionFlags -> SessionFlags sits at byte 16.
        flags = ctypes.c_int32.from_address(buf.value + 16).value
    finally:
        wtsapi32.WTSFreeMemory(buf)
    if flags == WTS_SESSIONSTATE_LOCK:
        return True
    if flags == WTS_SESSIONSTATE_UNLOCK:
        return False
    return None


def _desktop_locked():
    """Fallback: while the lock screen is up, the user's desktop can't be switched to."""
    hdesk = user32.OpenInputDesktop(0, False, DESKTOP_SWITCHDESKTOP)
    if not hdesk:
        return True
    try:
        return not user32.SwitchDesktop(hdesk)
    finally:
        user32.CloseDesktop(hdesk)


def is_locked():
    state = _wts_lock_state()
    return _desktop_locked() if state is None else state


def boot_time():
    # GetTickCount64 keeps counting through sleep, so this only changes after a restart.
    return time.time() - kernel32.GetTickCount64() / 1000.0


def foreground_window():
    """(program file name, window title) of the window in front, or ('', '')."""
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return "", ""
    title = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, title, 512)
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    exe = ""
    hproc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if hproc:
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            if kernel32.QueryFullProcessImageNameW(hproc, 0, buf, ctypes.byref(size)):
                exe = os.path.basename(buf.value)
        finally:
            kernel32.CloseHandle(hproc)
    return exe, title.value


class Rules:
    """Distraction rules, reloaded whenever the dashboard saves rules.json."""

    def __init__(self):
        self.mtime = None
        self.rules = load_rules()

    def current(self):
        try:
            mtime = os.path.getmtime(RULES_PATH)
        except OSError:
            mtime = None
        if mtime != self.mtime:
            self.mtime = mtime
            self.rules = load_rules()
        return self.rules


def sample(rules):
    """Current (state, detail): locked, distracted (with what), or active."""
    if is_locked():
        return "locked", None
    detail = match_distraction(*foreground_window(), rules.current())
    return ("distracted", detail) if detail else ("active", None)


class Settings:
    """Pop-up settings, reloaded whenever the dashboard saves settings.json."""

    def __init__(self):
        self.mtime = None
        self.values = load_settings()

    def current(self):
        try:
            mtime = os.path.getmtime(SETTINGS_PATH)
        except OSError:
            mtime = None
        if mtime != self.mtime:
            self.mtime = mtime
            self.values = load_settings()
        return self.values


class Popups:
    """Decides when to show the on-screen pop-up (toast.pyw) with today's wasted time."""
    MIN_AWAY = 30          # seconds away before "welcome back" is worth showing
    MIN_GAP = 20           # never show distraction pop-ups closer together than this

    def __init__(self):
        self.settings = Settings()
        self.away_since = None
        self.last_shown = 0.0
        self.script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "toast.pyw")

    def show(self, *args):
        self.last_shown = time.time()
        try:
            subprocess.Popen([sys.executable, self.script, *map(str, args)],
                             cwd=os.path.dirname(self.script), close_fds=True)
        except OSError:
            pass

    def update(self, prev, state, detail, now, continuous):
        """prev is the previous (state, detail, end time) or None."""
        s = self.settings.current()
        if not continuous and prev is not None and self.away_since is None:
            self.away_since = prev[2]           # asleep / shut down since the last sample
        if state == "locked":
            if self.away_since is None:
                self.away_since = prev[2] if prev else now
            return
        if self.away_since is not None:         # just came back
            away, self.away_since = now - self.away_since, None
            if away >= self.MIN_AWAY and s["popup_on_return"]:
                self.show("back", int(away))
                return
        if state != "distracted" or not s["popup_on_distraction"]:
            return
        if now - self.last_shown < self.MIN_GAP:
            return
        new = prev is None or prev[0] != "distracted" or prev[1] != detail or not continuous
        remind = s["popup_reminder_minutes"] and now - self.last_shown >= 60 * s["popup_reminder_minutes"]
        if new or remind:
            self.show("distracted", detail)


def wait_for_change(rules, current, seconds):
    """Sleep up to `seconds`, waking early if the state changes (so pop-ups are prompt)
    or a pause was requested."""
    for _ in range(seconds):
        time.sleep(1)
        if os.path.exists(PAUSE_PATH):
            return
        try:
            if sample(rules) != current:
                return
        except Exception:
            pass


def paused_now():
    p = load_pause()
    return p is not None and time.time() < p["until"]


def resume_from_pause(conn, pause):
    """Record the pause as 'paused' time (not wasted), then clear it and its scheduled task."""
    now = time.time()
    last = conn.execute("SELECT end, boot FROM periods ORDER BY id DESC LIMIT 1").fetchone()
    start = max(pause.get("start", now), last[0] if last else 0)
    end = min(now, pause["until"])
    if end > start:
        conn.execute("INSERT INTO periods (start, end, state, boot, detail) VALUES (?, ?, 'paused', ?, NULL)",
                     (start, end, last[1] if last else boot_time()))
        conn.commit()
    clear_pause()
    cancel_resume()


def main():
    # One tracker per data folder (so a preview can run next to the installed app).
    name = "Local\\UptimeTracker_" + hashlib.md5(DATA_DIR.lower().encode()).hexdigest()[:12]
    kernel32.CreateMutexW(None, False, name)
    if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
        sys.exit(0)  # already running

    pause = load_pause()
    if pause and time.time() < pause["until"]:
        sys.exit(0)  # paused: stay off (e.g. logged in during a pause)

    conn = connect()
    if pause:
        resume_from_pause(conn, pause)
    rules = Rules()
    popups = Popups()
    last = conn.execute(
        "SELECT id, end, state, boot, detail FROM periods ORDER BY id DESC LIMIT 1").fetchone()
    state = detail = None

    while True:
        if paused_now():
            conn.close()
            sys.exit(0)  # the dashboard asked us to pause: turn off completely
        try:
            now = time.time()
            state, detail = sample(rules)
            boot = boot_time()
            continuous = (last is not None and 0 <= now - last[1] <= MAX_GAP_SECONDS
                          and abs(boot - last[3]) <= REBOOT_TOLERANCE)
            prev = (last[2], last[4], last[1]) if last else None
            if continuous and last[2] == state and last[4] == detail:
                conn.execute("UPDATE periods SET end = ? WHERE id = ?", (now, last[0]))
                last = (last[0], now, state, last[3], detail)
            else:
                # A change right after the last sample starts where that one ended.
                start = last[1] if continuous else now
                cur = conn.execute(
                    "INSERT INTO periods (start, end, state, boot, detail) VALUES (?, ?, ?, ?, ?)",
                    (start, now, state, boot, detail))
                last = (cur.lastrowid, now, state, boot, detail)
            conn.commit()
            popups.update(prev, state, detail, now, continuous)
        except Exception:
            pass  # never die on a transient error (e.g. database briefly busy)
        wait_for_change(rules, (state, detail), HEARTBEAT_SECONDS)


if __name__ == "__main__":
    main()
