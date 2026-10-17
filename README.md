<p align="center"><img src="screenshots/icon.png" width="96" alt="Uptime icon"></p>

<h1 align="center">Uptime</h1>

<p align="center"><i>A simple, fun little project that helps me cut down on distractions… by making me feel guilty about them.</i></p>

---

I wanted an honest answer to *"where did my day actually go?"*. Uptime runs quietly in the background on my Windows laptop. It adds up every minute the laptop is **locked, asleep, shut down**, or sitting on a **shopping or social media site**. Then it shows me the total in a big, unforgiving number.

It turns out that seeing *"Wasted today: 6h 12m"* and *"Shopping · flipkart: 1h 40m this week"* is surprisingly good motivation to close the tab and get back to work. 😅

![Overview](screenshots/v2_overview.png)

## What it does

- **Tracks wasted time automatically.** It counts time locked (Win+L), asleep or shut down, and time on distracting apps or websites.
- **Doesn't count your sleep.** Each morning, up to 8 hours of the night's laptop-off break counts as **Your sleep**, not wasted time (you can change the hours, or set 0 to turn it off). Stay up past that and the extra still counts.
- **Catches distractions.** Shopping (Amazon, Flipkart, Myntra, Meesho…), social media (Instagram, Reddit…), streaming (Netflix, Hotstar…) and games count as **Distracted** time.
- **Shows your history.** You get a 14-day chart, daily and weekly history, and a log of every break.
- **Averages.** It shows average wasted time per day and per week.
- **Asks about anything new.** The first time you use a new app or website, a small prompt asks *"Is this for work?"*. Answer **Not work** and time there counts as distracted from then on. Answer **Work** and you're never asked again. Websites are recognised by their real address (e.g. `leetcode.com`), not just the tab title. You can review and change your answers in the dashboard.
- **Nudges you with a pop-up.** A small Windows-style pop-up in the top-left corner shows *"5h 12m wasted today"* when you come back to the laptop, when you open a distraction, and every 10 minutes while you stay on one. It never takes focus, clicks pass straight through it, and it doesn't appear in screen shares or recordings.
- **Pauses on demand.** Pause for 3, 4 or 5 hours and Uptime switches off completely, with no tracking, no pop-ups and nothing running. It starts again by itself, and paused time doesn't count as wasted.
- **Lets you set your own rules.** Turn categories on or off, or add your own sites and apps. YouTube, messaging and music start off, because they aren't always distractions.
- **Looks like Windows 11.** It has a dark Windows 11-style dashboard, with smooth 144 Hz scrolling that works with precision touchpads too.

| Distractions | Breaks |
|---|---|
| ![Distractions](screenshots/v2_distractions.png) | ![Breaks](screenshots/v2_breaks.png) |

## Install

You need **Windows 10/11** and **Python 3** from [python.org](https://www.python.org/), with "Add to PATH" ticked. Uptime uses only Python's built-in libraries.

1. Download or clone this repo.
2. Double-click **`Install Uptime.cmd`**.
3. Open **Uptime** from your Desktop or the Start menu.

Tracking starts right away and runs at every login. Your data stays on your laptop, in `%USERPROFILE%\Uptime`.

## How it works

- **Background tracker.** `src/tracker.pyw` runs with no window. Every 10 seconds it records:
  - whether the session is locked, using the Windows session lock state
  - which window is in front, and whether it matches a distraction rule (websites by browser tab title, apps by program name)
- **Laptop asleep and shutdown.** Gaps with no recordings mean the laptop was asleep or off. If Windows restarted during the gap, it counts as **Shut down**; otherwise it counts as **Laptop asleep**.
- **Your sleep.** Each night's longest off/locked break (at least 3 hours, overlapping 12 am–9 am) is treated as sleep. The last 8 hours before you came back count as **Your sleep** and aren't wasted. This applies to past days too.
- **Pop-ups.** `src/toast.pyw` is the pop-up and `src/ask.pyw` is the "Is this for work?" prompt. Both share `src/osd.py`, which builds them directly on the Windows API rather than Tkinter: they never take focus (the prompt's buttons can be clicked without stealing focus), and they're excluded from screen capture. You can switch each one on or off in **Distractions → Pop-ups**.
- **Websites.** `src/siteinfo.py` reads the browser's address bar through Windows UI Automation, using only `ctypes`, to find the site you're on. It only reads when you switch windows or the page changes. Your answers live in `%USERPROFILE%\Uptime\labels.json` and take priority over the keyword rules.
- **Pause.** The dashboard's **Pause** button writes the pause end time and registers a one-time Windows Task Scheduler entry to restart the tracker. The tracker notices the pause and exits. When it restarts, it records the gap as **Paused** and removes the scheduled task. Click **Resume now** in the dashboard to end a pause early.
- **Dashboard.** `src/dashboard.pyw` is the dashboard, built with Tkinter and drawn to match Windows 11's dark theme.
- **Averages.** They only use full days, meaning days that were at least 90% tracked, so a half-tracked first day doesn't skew them.

## Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File src\uninstall.ps1              # keeps your history
powershell -ExecutionPolicy Bypass -File src\uninstall.ps1 -DeleteData  # removes everything
```

---

<p align="center"><i>Built for fun. Use responsibly. Guilt is a feature, not a bug.</i></p>
