"""The single-file Uptime.exe: one program that can be any part of Uptime.

    Uptime.exe                the dashboard (the first time, it installs Uptime instead)
    Uptime.exe --tracker      the background tracker
    Uptime.exe --toast ...    a pop-up, with the same arguments as toast.pyw
    Uptime.exe --ask ...      "Is this for work?", with the same arguments as ask.pyw
    Uptime.exe --morning      today's goals window

Any of them can add --data-dir <folder> to use another data folder (used for tests).
Build it with "Build Uptime.exe.cmd".
"""
import os
import sys

if "--data-dir" in sys.argv[:-1]:  # before anything works out the data folder
    i = sys.argv.index("--data-dir")
    os.environ["WTT_DATA_DIR"] = sys.argv[i + 1]
    del sys.argv[i:i + 2]


def main():
    part = sys.argv[1] if len(sys.argv) > 1 else ""
    if part in ("--toast", "--ask"):
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        try:
            if part == "--toast":
                import toast as popup
            else:
                import ask as popup
            popup.main()
        except Exception:
            pass  # a pop-up must never bother you with an error
    elif part == "--tracker":
        sys.argv = [sys.argv[0]] + sys.argv[2:]
        import tracker
        tracker.main()
    else:
        import installer
        if part != "--morning" and installer.needed():
            installer.install()
            return
        import dashboard
        dashboard.run()


if __name__ == "__main__":
    main()
