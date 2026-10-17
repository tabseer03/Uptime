"""Shared storage and analysis for Uptime."""
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
KIND_LABELS = {"sleep": "Sleep", "shutdown": "Shut down", "locked": "Locked",
               "distracted": "Distracted", "active": "Active"}

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


def match_distraction(exe, title, rules):
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
                hit = in_browser and k in title
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


def wasted_today(conn, now=None):
    """Seconds wasted since local midnight (locked, asleep, off or distracted)."""
    now = now or time.time()
    today = datetime.fromtimestamp(now).date()
    return wasted(per_day(build_segments(conn)).get(today, {}))


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

def build_segments(conn):
    """Return a sorted list of (start, end, kind, detail) covering all tracked time.

    kind is 'active', 'locked', 'distracted', 'sleep' or 'shutdown'; detail says what the
    distraction was. Gaps between recorded periods are sleep (same boot) or shutdown.
    """
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
        if kind == "active":
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
