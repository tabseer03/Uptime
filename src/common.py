"""Shared storage and analysis for Uptime."""
import hashlib
import json
import os
import sqlite3
import time
from collections import defaultdict
from datetime import date, datetime, timedelta

# Kept in the user folder rather than AppData: AppData writes from packaged apps can be
# redirected to a private copy that the rest of Windows never sees.
DATA_DIR = os.environ.get("WTT_DATA_DIR") or os.path.join(os.path.expanduser("~"), "Uptime")
DB_PATH = os.path.join(DATA_DIR, "data.db")

HEARTBEAT_SECONDS = 10      # how often the tracker records a sample
MAX_GAP_SECONDS = 60        # longer than this between samples = laptop was off/asleep
REBOOT_TOLERANCE = 120      # boot-time difference that means a restart happened

WASTED_KINDS = ("sleep", "shutdown", "locked", "distracted")
KIND_LABELS = {"sleep": "Laptop asleep", "shutdown": "Shut down", "locked": "Locked",
               "distracted": "Distracted", "active": "Active", "paused": "Paused", "rest": "Your sleep"}

# ---------------------------------------------------------------- distraction rules
# "site" rules match the title of the active browser tab; "app" rules match the program's
# file name (or the window title for Store apps). Keywords are case-insensitive.
RULES_PATH = os.path.join(DATA_DIR, "rules.json")
BROWSERS = {"chrome", "msedge", "brave", "firefox", "opera", "opera_gx", "vivaldi", "arc",
            "iexplore", "chromium", "zen", "librewolf", "waterfox", "thorium", "yandex"}
DEFAULT_RULES = [
    {"name": "Shopping", "type": "site", "enabled": True,
     "keywords": ["amazon.in", "amazon.com", "flipkart", "myntra", "meesho", "ajio", "nykaa",
                  "snapdeal", "tata cliq", "shopsy", "ebay", "aliexpress", "croma", "reliance digital"]},
    {"name": "Social media", "type": "site", "enabled": True,
     "keywords": ["instagram", "facebook", "twitter", "reddit", "snapchat", "pinterest"]},
    {"name": "Streaming", "type": "site", "enabled": True,
     "keywords": ["netflix", "prime video", "hotstar", "jiocinema", "sonyliv", "zee5", "twitch", "crunchyroll"]},
    {"name": "YouTube", "type": "site", "enabled": False, "keywords": ["youtube"]},
    {"name": "Games", "type": "app", "enabled": True,
     "keywords": ["steam", "epicgameslauncher", "riotclient", "valorant", "minecraft", "roblox"]},
    {"name": "Messaging", "type": "app", "enabled": False, "keywords": ["whatsapp", "telegram"]},
    {"name": "Music", "type": "app", "enabled": False, "keywords": ["spotify"]},
]


def load_rules():
    try:
        with open(RULES_PATH, encoding="utf-8") as f:
            rules = json.load(f)
        if isinstance(rules, list):
            return rules
    except (OSError, ValueError):
        pass
    return json.loads(json.dumps(DEFAULT_RULES))


def save_rules(rules):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = RULES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(rules, f, indent=2)
    os.replace(tmp, RULES_PATH)


def match_distraction(exe, title, rules, domain=None):
    """Return 'Rule|keyword' if the foreground window is a distraction, else None."""
    exe = exe.lower().removesuffix(".exe")
    title = title.lower()
    in_browser = exe in BROWSERS
    for rule in rules:
        if not rule.get("enabled", True):
            continue
        for kw in rule.get("keywords", []):
            k = kw.strip().lower()
            if not k:
                continue
            if rule.get("type") == "site":
                hit = in_browser and (k in title or (domain is not None and k in domain))
            else:
                hit = k in exe or (exe == "applicationframehost" and k in title)
            if hit:
                return f"{rule['name']}|{kw.strip()}"
    return None


# ---------------------------------------------------------------- settings
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
DEFAULT_SETTINGS = {
    "popup_on_return": True,        # after unlocking or waking the laptop
    "popup_on_distraction": True,   # when a distracting app or site comes to the front
    "popup_reminder_minutes": 10,   # repeat while you stay on the distraction (0 = never)
    "ask_new": True,                # ask "is this for work?" for new apps and sites
    "sleep_hours": 8,               # this much of each night's break is your sleep, not wasted
}


def load_settings():
    settings = dict(DEFAULT_SETTINGS)
    try:
        with open(SETTINGS_PATH, encoding="utf-8") as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            settings.update({k: v for k, v in saved.items() if k in DEFAULT_SETTINGS})
    except (OSError, ValueError):
        pass
    return settings


def save_settings(settings):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = SETTINGS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(settings, f, indent=2)
    os.replace(tmp, SETTINGS_PATH)


# ---------------------------------------------------------------- pause
# While paused nothing of Uptime runs. pause.json says until when; a one-time Windows
# Task Scheduler entry starts the tracker again at that time (or at the next login).
PAUSE_PATH = os.path.join(DATA_DIR, "pause.json")
_DEFAULT_DIR = os.path.join(os.path.expanduser("~"), "Uptime")
TASK_NAME = "Uptime resume" + (
    "" if os.path.normcase(DATA_DIR) == os.path.normcase(_DEFAULT_DIR)
    else " " + hashlib.md5(os.path.normcase(DATA_DIR).encode()).hexdigest()[:8])
CREATE_NO_WINDOW = 0x08000000


def load_pause():
    """{'start': ts, 'until': ts} while a pause is set, else None."""
    try:
        with open(PAUSE_PATH, encoding="utf-8") as f:
            p = json.load(f)
        return p if isinstance(p, dict) and "until" in p else None
    except (OSError, ValueError):
        return None


def save_pause(start, until):
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = PAUSE_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"start": start, "until": until}, f)
    os.replace(tmp, PAUSE_PATH)


def clear_pause():
    try:
        os.remove(PAUSE_PATH)
    except OSError:
        pass


def _powershell(script):
    import subprocess
    try:
        return subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                              capture_output=True, text=True, timeout=60,
                              creationflags=CREATE_NO_WINDOW).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def schedule_resume(at, pythonw, tracker):
    """One-time task that starts the tracker at `at` (runs late if the laptop was asleep/off)."""
    when = datetime.fromtimestamp(at).strftime("%Y-%m-%dT%H:%M:%S")
    q = lambda s: s.replace("'", "''")  # noqa: E731  (PowerShell single-quote escaping)
    args = f'"{tracker}"'
    if os.environ.get("WTT_DATA_DIR"):  # a task can't carry environment variables, so pass it on
        args += f' --data-dir "{DATA_DIR}"'
    return _powershell(
        f"$a = New-ScheduledTaskAction -Execute '{q(pythonw)}' -Argument '{q(args)}' "
        f"-WorkingDirectory '{q(os.path.dirname(tracker))}'; "
        f"$t = New-ScheduledTaskTrigger -Once -At ([datetime]'{when}'); "
        "$s = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries "
        "-StartWhenAvailable -ExecutionTimeLimit ([TimeSpan]::Zero); "
        f"Register-ScheduledTask -TaskName '{q(TASK_NAME)}' -Action $a -Trigger $t -Settings $s "
        "-Description 'Starts Uptime again after a pause' -Force | Out-Null")


def cancel_resume():
    return _powershell(f"Unregister-ScheduledTask -TaskName '{TASK_NAME}' -Confirm:$false "
                       "-ErrorAction SilentlyContinue")


def wasted_today(conn, now=None):
    """Seconds wasted since local midnight (locked, asleep, off or distracted)."""
    now = now or time.time()
    today = datetime.fromtimestamp(now).date()
    return wasted(per_day(build_segments(conn)).get(today, {}))


# ---------------------------------------------------------------- work / not work answers
# Your answers to "is this for work?", keyed 'site:leetcode.com' or 'app:code'.
# They take priority over the keyword rules above.
LABELS_PATH = os.path.join(DATA_DIR, "labels.json")
WORK, NOT_WORK = "work", "not_work"
NOT_WORK_RULE = "Not work"   # detail prefix for time on things you marked "not work"

# Windows' own parts, and Uptime itself, are never asked about.
IGNORED_APPS = {
    "explorer", "searchhost", "searchapp", "searchui", "startmenuexperiencehost", "shellexperiencehost",
    "shellhost", "lockapp", "logonui", "textinputhost", "applicationframehost", "taskmgr", "dwm",
    "systemsettings", "rundll32", "consent", "openwith", "pickerhost", "sihost", "ctfmon",
    "python", "pythonw", "py", "pyw", "notificationcenter", "widgets", "winlogon", "screenclippinghost",
}


def label_key(exe, domain):
    """What an answer is stored under: the website in a browser, otherwise the program."""
    stem = (exe or "").lower().removesuffix(".exe")
    if stem in BROWSERS:
        return f"site:{domain}" if domain else None
    if not stem or stem in IGNORED_APPS:
        return None
    return f"app:{stem}"


def key_name(key):
    """'site:leetcode.com' -> 'leetcode.com'; 'app:code' -> 'code'."""
    return key.split(":", 1)[1] if key and ":" in key else (key or "")


def load_labels():
    """{key: {"answer": WORK or NOT_WORK, "name": display name}}"""
    try:
        with open(LABELS_PATH, encoding="utf-8") as f:
            labels = json.load(f)
        return {k: v for k, v in labels.items() if isinstance(v, dict)} if isinstance(labels, dict) else {}
    except (OSError, ValueError):
        return {}


def answer_of(labels, key):
    entry = labels.get(key) if key else None
    return entry.get("answer") if entry else None


def save_label(key, value, name=None):
    """value is WORK, NOT_WORK, or None to forget the answer (it will be asked again)."""
    labels = load_labels()
    if value is None:
        labels.pop(key, None)
    else:
        labels[key] = {"answer": value, "name": name or labels.get(key, {}).get("name") or key_name(key)}
    os.makedirs(DATA_DIR, exist_ok=True)
    tmp = LABELS_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(labels, f, indent=2, sort_keys=True)
    os.replace(tmp, LABELS_PATH)


def detail_label(detail):
    """'Shopping|flipkart' -> 'Shopping · flipkart'."""
    return " · ".join(p for p in (detail or "").split("|") if p) or "Distracted"


def connect():
    os.makedirs(DATA_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("""CREATE TABLE IF NOT EXISTS periods (
        id    INTEGER PRIMARY KEY,
        start REAL NOT NULL,
        end   REAL NOT NULL,
        state TEXT NOT NULL,      -- 'active' or 'locked'
        boot  REAL NOT NULL       -- system boot time, used to tell sleep from shutdown
    )""")
    cols = {r[1] for r in conn.execute("PRAGMA table_info(periods)")}
    if "detail" not in cols:  # added in v2: what the distraction was, e.g. 'Shopping|flipkart'
        conn.execute("ALTER TABLE periods ADD COLUMN detail TEXT")
        conn.commit()
    return conn


# ---------------------------------------------------------------- analysis

OFF_KINDS = ("sleep", "shutdown", "locked")   # the laptop was not being used
NIGHT_WINDOW = (0, 9)                          # a night's break overlaps 00:00-09:00 ...
MIN_NIGHT = 3 * 3600                           # ... and lasts at least 3 hours


def credit_your_sleep(segs, hours):
    """Count up to `hours` of each night's longest laptop-off break as 'rest' (you asleep).

    The credited part is the last `hours` before you came back; anything longer than
    that stays wasted (laptop off, but you were up). Applies to past days too.
    """
    if not hours or hours <= 0:
        return segs
    runs, cur = [], None                       # contiguous stretches of off-time
    for start, end, kind, _ in segs:
        if kind in OFF_KINDS:
            if cur and abs(cur[1] - start) < 1:
                cur[1] = end
            else:
                cur = [start, end]
                runs.append(cur)
        else:
            cur = None
    nights = {}                                # morning date -> longest break that night
    for start, end in runs:
        if end - start < MIN_NIGHT:
            continue
        d = datetime.fromtimestamp(start).date()
        while True:
            ws = datetime.combine(d, datetime.min.time()).timestamp() + NIGHT_WINDOW[0] * 3600
            if ws > end:
                break
            we = ws + (NIGHT_WINDOW[1] - NIGHT_WINDOW[0]) * 3600
            if start < we and end > ws and end - start > nights.get(d, (0, 0, 0))[0]:
                nights[d] = (end - start, start, end)
            d += timedelta(days=1)
    windows = sorted({(max(s, e - hours * 3600), e) for _, s, e in nights.values()})
    if not windows:
        return segs
    out = []
    for start, end, kind, detail in segs:
        if kind not in OFF_KINDS:
            out.append((start, end, kind, detail))
            continue
        cur = start
        for ws, we in windows:
            if we <= cur or ws >= end:
                continue
            if ws > cur:
                out.append((cur, ws, kind, detail))
            out.append((max(cur, ws), min(end, we), "rest", None))
            cur = min(end, we)
        if cur < end:
            out.append((cur, end, kind, detail))
    return out


def build_segments(conn, sleep_hours=None):
    """Return a sorted list of (start, end, kind, detail) covering all tracked time.

    kind is 'active', 'locked', 'distracted', 'sleep' or 'shutdown' (the laptop asleep),
    'rest' (you asleep, see credit_your_sleep) or 'paused'; detail says what the
    distraction was. Gaps between recorded periods are sleep (same boot) or shutdown.
    """
    if sleep_hours is None:
        sleep_hours = load_settings().get("sleep_hours", 8)
    return credit_your_sleep(_raw_segments(conn), sleep_hours)


def _raw_segments(conn):
    rows = conn.execute("SELECT start, end, state, boot, detail FROM periods ORDER BY start").fetchall()
    segs = []
    prev_end = prev_boot = None
    for start, end, state, boot, detail in rows:
        if prev_end is not None:
            if start - prev_end > 1:
                kind = "shutdown" if abs(boot - prev_boot) > REBOOT_TOLERANCE else "sleep"
                segs.append((prev_end, start, kind, None))
            start = max(start, prev_end)
        if end > start:
            segs.append((start, end, state, detail))
        prev_end = end if prev_end is None else max(end, prev_end)
        prev_boot = boot
    return segs


def _midnight_after(ts):
    d = datetime.fromtimestamp(ts).date() + timedelta(days=1)
    return datetime.combine(d, datetime.min.time()).timestamp()


def per_day(segs):
    """{date: {kind: seconds}} with segments split at local midnight."""
    days = defaultdict(lambda: defaultdict(float))
    for start, end, kind, _ in segs:
        cur = start
        while cur < end:
            chunk_end = min(end, _midnight_after(cur))
            days[datetime.fromtimestamp(cur).date()][kind] += chunk_end - cur
            cur = chunk_end
    return days


def wasted(day_stats):
    return sum(day_stats.get(k, 0.0) for k in WASTED_KINDS)


def tracked(day_stats):
    return sum(day_stats.values())


def breaks(segs):
    """Merge back-to-back wasted segments (e.g. locked -> sleep -> locked) into one break.

    Returns a list of (start, end, {(kind, detail): seconds}), newest first.
    """
    out = []
    for start, end, kind, detail in segs:
        if kind not in WASTED_KINDS:  # active or paused time is not a break
            continue
        key = (kind, detail if kind == "distracted" else None)
        if out and abs(out[-1][1] - start) < 1:
            out[-1][1] = end
            out[-1][2][key] = out[-1][2].get(key, 0) + (end - start)
        else:
            out.append([start, end, {key: end - start}])
    return [tuple(b) for b in reversed(out)]


def distraction_totals(segs, since):
    """{detail: seconds} of distracted time after `since`, largest first."""
    totals = defaultdict(float)
    for start, end, kind, detail in segs:
        if kind == "distracted" and end > since:
            totals[detail] += end - max(start, since)
    return dict(sorted(totals.items(), key=lambda kv: -kv[1]))


def is_complete_day(d, day_stats, today=None):
    """A day counts toward averages if it is over and at least 90% of it was tracked."""
    today = today or date.today()
    return d < today and tracked(day_stats) >= 0.9 * 86400


def summary(conn, now=None):
    now = now or time.time()
    segs = build_segments(conn)
    days = per_day(segs)
    today = datetime.fromtimestamp(now).date()

    complete = [d for d in days if is_complete_day(d, days[d], today)]
    if complete:
        avg_day = sum(wasted(days[d]) for d in complete) / len(complete)
        avg_basis = f"{len(complete)} full day{'s' if len(complete) != 1 else ''}"
    elif days:
        # No full day yet: estimate from the share of tracked time that was wasted.
        tot_tracked = sum(tracked(s) for s in days.values())
        tot_wasted = sum(wasted(s) for s in days.values())
        avg_day = 86400 * tot_wasted / tot_tracked if tot_tracked else 0.0
        avg_basis = "estimate - no full day tracked yet"
    else:
        avg_day, avg_basis = 0.0, "no data yet"

    # Weeks run Monday-Sunday. A week is complete when all 7 days are complete.
    weeks = defaultdict(list)
    for d in days:
        weeks[d - timedelta(days=d.weekday())].append(d)
    full_weeks = [w for w, ds in weeks.items()
                  if len(ds) == 7 and all(is_complete_day(d, days[d], today) for d in ds)]
    if full_weeks:
        avg_week = sum(wasted(days[d]) for w in full_weeks for d in weeks[w]) / len(full_weeks)
        week_basis = f"{len(full_weeks)} full week{'s' if len(full_weeks) != 1 else ''}"
    else:
        avg_week = avg_day * 7
        week_basis = "daily average x 7"

    midnight = datetime.combine(today, datetime.min.time()).timestamp()
    week_start = datetime.combine(today - timedelta(days=today.weekday()), datetime.min.time()).timestamp()
    last_beat = conn.execute("SELECT MAX(end) FROM periods").fetchone()[0]
    return {
        "segments": segs,
        "days": days,
        "weeks": weeks,
        "today": today,
        "avg_day": avg_day,
        "avg_day_basis": avg_basis,
        "avg_week": avg_week,
        "avg_week_basis": week_basis,
        "breaks": breaks(segs),
        "distractions_today": distraction_totals(segs, midnight),
        "distractions_week": distraction_totals(segs, week_start),
        "last_heartbeat": last_beat,
        "tracker_running": last_beat is not None and now - last_beat < MAX_GAP_SECONDS,
    }


def fmt_dur(seconds):
    seconds = int(round(seconds))
    h, rem = divmod(seconds, 3600)
    m = rem // 60
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m"
