<p align="center"><img src="screenshots/icon.png" width="96" alt="Uptime icon"></p>

<h1 align="center">Uptime</h1>

<p align="center"><i>A simple, fun little project that helps me cut down on distractions… by making me feel guilty about them.</i></p>

---

I wanted an honest answer to *"where did my day actually go?"*. Uptime runs quietly in the background on my Windows laptop. It adds up every minute the laptop is **locked, asleep, shut down**, or sitting on a **shopping or social media site**. Then it shows me the total in a big, unforgiving number.

It turns out that seeing *"Wasted today: 6h 12m"* and *"Shopping · flipkart: 1h 40m this week"* is surprisingly good motivation to close the tab and get back to work. 😅

![Overview](screenshots/v2_overview.png)

## What it does

- **Tracks wasted time automatically.** It counts time locked (Win+L), asleep, shut down (yes, including sleep at night), and time on distracting apps or websites.
- **Catches distractions.** Shopping (Amazon, Flipkart, Myntra, Meesho…), social media (Instagram, Reddit…), streaming (Netflix, Hotstar…) and games count as **Distracted** time.
- **Shows your history.** You get a 14-day chart, daily and weekly history, and a log of every break.
- **Averages.** It shows average wasted time per day and per week.
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
- **Sleep and shutdown.** Gaps with no recordings mean the laptop was asleep or off. If Windows restarted during the gap, it counts as **Shut down**; otherwise it counts as **Sleep**.
- **Dashboard.** `src/dashboard.pyw` is the dashboard, built with Tkinter and drawn to match Windows 11's dark theme.
- **Averages.** They only use full days, meaning days that were at least 90% tracked, so a half-tracked first day doesn't skew them.

## Uninstall

```powershell
powershell -ExecutionPolicy Bypass -File src\uninstall.ps1              # keeps your history
powershell -ExecutionPolicy Bypass -File src\uninstall.ps1 -DeleteData  # removes everything
```

---

<p align="center"><i>Built for fun. Use responsibly. Guilt is a feature, not a bug.</i></p>
