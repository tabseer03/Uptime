"""First run of Uptime.exe: installs it for the current user.

Copies the exe to %USERPROFILE%\\Uptime\\app, points the Startup, Desktop and Start menu
shortcuts at it (replacing the Python version's ones of the same name) and starts tracking.
Your history and settings in %USERPROFILE%\\Uptime are never touched. Running a newer
Uptime.exe the same way updates it.
"""
import ctypes
import os
import shutil
import subprocess
import sys
import time

from common import DATA_DIR, FROZEN, _powershell

TEST = bool(os.environ.get("WTT_DATA_DIR"))  # a test install stays inside its test folder
APP = os.path.join(DATA_DIR, "app")
EXE = os.path.join(APP, "Uptime.exe")
FOLDERS = {"Startup": 7, "Desktop": 0x10, "Programs": 2}  # CSIDL_STARTUP, _DESKTOPDIRECTORY, _PROGRAMS


def q(s):
    return s.replace("'", "''")  # PowerShell single-quote escaping


def needed():
    """True when this is Uptime.exe running from anywhere but its installed place."""
    return FROZEN and os.path.normcase(os.path.abspath(sys.executable)) != os.path.normcase(EXE)


def folder(name):
    if TEST:
        path = os.path.join(DATA_DIR, "shortcuts", name)
        os.makedirs(path, exist_ok=True)
        return path
    buf = ctypes.create_unicode_buffer(260)
    ctypes.windll.shell32.SHGetFolderPathW(None, FOLDERS[name], None, 0, buf)
    return buf.value


def stop_running():
    """Stop the installed exe (any part of it) and the Python version's tracker, so the exe
    can be replaced and only one tracker runs. Nothing is lost: the tracker saves as it goes."""
    _powershell(
        "Get-CimInstance Win32_Process | Where-Object { "
        f"$_.ExecutablePath -eq '{q(EXE)}' -or ($_.CommandLine -and "
        f"$_.CommandLine.Replace('/', '\\') -like '*{q(APP)}\\tracker.pyw*') }} | "
        "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")


def make_shortcuts(extra):
    links = [("Startup", "Uptime (background).lnk", ["--tracker", *extra], "Records locked / sleep / shutdown time"),
             ("Desktop", "Uptime.lnk", extra, "See where your time goes"),
             ("Programs", "Uptime.lnk", extra, "See where your time goes")]
    script = ["$s = New-Object -ComObject WScript.Shell"]
    for where, name, args, description in links:
        script.append(
            f"$l = $s.CreateShortcut('{q(os.path.join(folder(where), name))}'); $l.TargetPath = '{q(EXE)}'; "
            f"$l.Arguments = '{q(subprocess.list2cmdline(args))}'; $l.WorkingDirectory = '{q(APP)}'; "
            f"$l.Description = '{q(description)}'; $l.IconLocation = '{q(EXE)},0'; $l.Save()")
    return _powershell("; ".join(script))


def install():
    extra = ["--data-dir", DATA_DIR] if TEST else []
    stop_running()
    os.makedirs(APP, exist_ok=True)
    for attempt in range(40):  # a stopped process can take a moment to let go of the file
        try:
            shutil.copy2(sys.executable, EXE)
            break
        except OSError:
            if attempt == 39:
                raise
            time.sleep(0.25)
    linked = make_shortcuts(extra)
    subprocess.Popen([EXE, "--tracker", *extra], cwd=APP, close_fds=True)
    message = ("Uptime is installed and tracking.\n\nIt starts by itself every time you log in. "
               "Open it any time from the Uptime shortcut on your Desktop or in the Start menu.")
    if not linked:
        message += f"\n\nWindows wouldn't create the shortcuts, so open it from:\n{EXE}"
    ctypes.windll.user32.MessageBoxW(None, message, "Uptime", 0x40)  # MB_ICONINFORMATION
    subprocess.Popen([EXE, *extra], cwd=APP, close_fds=True)
