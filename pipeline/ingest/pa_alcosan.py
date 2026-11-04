"""ALCOSAN (Allegheny County Sanitary Authority, Pittsburgh) sewer overflow advisories -> data/build/events/pa-alcosan.json.

Source 1, the SOAK log (Sewer Overflow Advisory Key): https://www.alcosan.org/clean-water-plan/sewer-overflow-advisories/{n}
Server-rendered HTML (Sitefinity), five entries per page, newest first; no JSON, RSS or licence
text. Each entry is an alert date heading, one of three wordings and hand-typed times:
  "Overflows are in effect; Minimize contact with waterways"          In
  "Overflows have ceased; Waterways may still be impaired."            In, Out
  "System is in dry weather operation; No advisories are in effect"    In, Out, Dry (= Out + 48 h)
The program runs April 1 - October 31, 8 a.m. - 7 p.m.; changes outside those hours are posted at
8 a.m. the next day (the In/Out times are the overflow's, the alert date is the posting day).

Record rules:
- One event per advisory period: the entries that share an In time. event_type cso; status ongoing
  while the latest wording is "in effect", ended once "ceased" (or "dry") with ended_at = the Out
  time. started_at = In. advice_text is the latest wording; advice_window_hours 48 (Dry = Out + 48 h).
- The log is one status for the whole ALCOSAN system, not per outfall: discharger pa-alcosan
  (PA0025984), water_slugs the Allegheny, Monongahela and Ohio rivers at Pittsburgh with
  water_match "inferred" (raw.water_basis says so).
- Times are typed by hand. Read leniently, every correction listed in raw.time_corrections: a
  missing or wrong year ("08/20/205", "06/22/2016", "04/29/026", "9/3/26") takes the alert date's
  year; "04.29/2026", "08/17:2025", "12: 15 PM", "01:18AM" are read; "AN" is AM. A time that still
  cannot be read ("6:30" with no AM/PM, "12:15 Apm") or that lies far from its alert date ("06/18/2026"
  under July 18, 2026) is not used and is listed in raw.entry_problems. When another entry of the
  same period gives the time, the period keeps it; when none does, the record gets a parse_error
  (started_at / ended_at null). Entries of one period are matched by In time, and a mistyped In
  (same clock time, wrong day or month, or no AM/PM) joins the open period it matches unless its
  own readable Out differs from the period's (then it is another overflow at the same clock time). Entries that
  disagree on a readable time are kept as the latest entry says, with a parse_error for review.
- Times are America/New_York (implied; the page states no zone).
- data/build/pa-alcosan-state.json keeps every log entry seen (the default run reads pages 1-3,
  `--backfill` walks back to 2025); an entry that vanishes from a fully re-read stretch of the log
  (an edit at the source) moves to state["dropped_entries"]. Raw pages are saved when they change.

Source 2, ALCOSAN news posts (https://www.alcosan.org/news-and-events/featured-news): off-season
and non-CSO discharges appear only there (e.g. the 2026-03-06 plant power outage). Posts whose title
names a discharge, overflow, bypass, advisory, spill or outage are read; posts that link to an
earlier one, or are titled "Update on <that date>", join its incident. One event per incident,
same file, source_record_id "news-...": event_type sso when the posts say sanitary sewer overflow,
bypass when they say bypass or describe an untreated discharge at the treatment plant (wet well /
plant), else unknown with a parse_error. Times only when the post states them in a readable form
("between 6 - 8 p.m. this evening"), the volume when stated ("an estimated 20-million-gallon
discharge"), the 48-hour advice when stated. The posts name "the river" / "area waterways": the
three rivers are inferred as for the log.

Run from pipeline/: python -m ingest.pa_alcosan [--backfill]
Cadence: hourly in season (status changes are posted 8 a.m. - 7 p.m.); daily off season.
"""
from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import re
import sys
import time
from collections import Counter
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import (BUILD_DIR, HEADERS, event, now_iso, parse_volume_gal, read_json, save_raw, write_events,
                    write_json)
from ingest import pa_waters

SOURCE_ID = "pa-alcosan"
LOG_URL = "https://www.alcosan.org/clean-water-plan/sewer-overflow-advisories"
NEWS_URL = "https://www.alcosan.org/news-and-events/featured-news"
SITE = "https://www.alcosan.org"
STATE_PATH = BUILD_DIR / "pa-alcosan-state.json"
TZ = ZoneInfo("America/New_York")
DEFAULT_PAGES = 3
BACKFILL_FROM = date(2025, 1, 1)
MAX_PAGES = 400

DISCHARGER = {"discharger_id": "pa-alcosan", "discharger_name": "Allegheny County Sanitary Authority (ALCOSAN)",
              "npdes_permit": "PA0025984"}
AUTHORITY = "ALCOSAN sewer overflow advisories"
WINDOW_BASIS = "ALCOSAN advisory log (Dry = Out + 48 h)"
PITTSBURGH = (-80.0065, 40.4417)   # the Point, where the three rivers meet
RIVERS = ["Allegheny River", "Monongahela River", "Ohio River"]
WATER_BASIS = ("The SOAK log is one system-wide status for the ALCOSAN service area, not per outfall; "
               "the three rivers at Pittsburgh are inferred from that scope.")
TZ_NOTE = "The log states no time zone; times are read as America/New_York."
STAGES = [("effect", re.compile(r"in\s+effect", re.I)),
          ("ceased", re.compile(r"ceased", re.I)),
          ("dry", re.compile(r"dry\s+weather", re.I))]
STAGE_RANK = {"effect": 0, "ceased": 1, "dry": 2, "unknown": -1}
NEWS_TITLE = re.compile(r"\b(discharges?|overflows?|bypass|advisory|spill|sewage|outage|sso)\b", re.I)


# ---------------------------------------------------------------- time parsing

def _clean(s: str) -> str:
    return re.sub(r"\s+", " ", htmllib.unescape(s or "").replace("\xa0", " ")).strip()


def parse_alert_date(s: str) -> date | None:
    s = _clean(s)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    return None


_DATE = re.compile(r"^(\d{1,2})\s*[/.:\-]\s*(\d{1,2})\s*[/.:\-]\s*(\d{1,4})$")
_CLOCK = re.compile(r"^(\d{1,2})\s*:\s*(\d{2})\s*([A-Za-z.]*)$")


def parse_log_time(raw: str | None, alert: date | None) -> tuple[datetime | None, list[str], str | None]:
    """'10/14/2026 - 09:09 AM' -> (aware datetime, corrections made, problem). Lenient: see module doc."""
    if raw is None or not str(raw).strip():
        return None, [], None
    s = _clean(raw)
    fixes: list[str] = []
    m = re.match(r"^(.*?\d)\s*-\s*(\d{1,2}\s*:.*)$", s)
    if not m:
        return None, fixes, f"unreadable time {s!r}"
    dpart, tpart = m.group(1).strip(), m.group(2).strip()
    dm = _DATE.match(dpart)
    if not dm:
        return None, fixes, f"unreadable date in {s!r}"
    if not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{2,4}", dpart.replace(" ", "")):
        fixes.append(f"date {dpart!r} read as {dm.group(1)}/{dm.group(2)}/{dm.group(3)}")
    mo, dd, ytxt = int(dm.group(1)), int(dm.group(2)), dm.group(3)
    y = int(ytxt)
    if len(ytxt) == 2:
        y = 2000 + y
        fixes.append(f"two-digit year {ytxt!r} read as {y}")
    if alert is not None and (len(ytxt) not in (2, 4) or abs(y - alert.year) > 1):
        fixes.append(f"year {ytxt!r} read as {alert.year} (the alert date's year)")
        y = alert.year
    cm = _CLOCK.match(tpart)
    if not cm:
        return None, fixes, f"unreadable clock time in {s!r}"
    hh, mi, ap = int(cm.group(1)), int(cm.group(2)), cm.group(3).lower().replace(".", "")
    if " :" in tpart or ": " in tpart:
        fixes.append(f"clock {tpart!r} read without spaces")
    if ap in ("am", "a"):
        half = "am"
    elif ap in ("pm", "p"):
        half = "pm"
    elif ap.startswith("a") and "p" not in ap:
        half = "am"
        fixes.append(f"{cm.group(3)!r} read as AM")
    elif ap.startswith("p") and "a" not in ap[1:]:
        half = "pm"
        fixes.append(f"{cm.group(3)!r} read as PM")
    elif ap == "":
        if hh == 0 or 13 <= hh <= 23:
            half = "24h"
        else:
            return None, fixes, f"no AM/PM in {s!r}"
    else:
        return None, fixes, f"unreadable AM/PM {cm.group(3)!r} in {s!r}"
    if half == "am" and hh == 12:
        hh = 0
    elif half == "pm" and hh < 12:
        hh += 12
    try:
        dt = datetime(y, mo, dd, hh, mi, tzinfo=TZ)
    except ValueError as e:
        return None, fixes, f"impossible date/time in {s!r} ({e})"
    if alert is not None:
        lag = (alert - dt.date()).days
        if (lag < -1 or lag > 10) and dt.year != alert.year:
            try:   # a year typo one off ("06/13/2024" under June 14, 2025): the alert's year if that fits
                alt = dt.replace(year=alert.year)
            except ValueError:
                alt = None
            if alt is not None and -1 <= (alert - alt.date()).days <= 10:
                fixes.append(f"year {dt.year} read as {alert.year} (the alert date's year)")
                dt, lag = alt, (alert - alt.date()).days
        if lag < -1 or lag > 10:
            return None, fixes, (f"{s!r} is {abs(lag)} days {'before' if lag > 0 else 'after'} the alert date "
                                 f"{alert.isoformat()}: not used")
    return dt, fixes, None


def clock_key(raw: str | None) -> tuple[int, int] | None:
    """The clock digits of a typed time, 12-hour (for matching a mistyped In to its period)."""
    m = re.search(r"-\s*(\d{1,2})\s*:\s*(\d{2})", _clean(raw or ""))
    return (int(m.group(1)) % 12, int(m.group(2))) if m else None


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


# ---------------------------------------------------------------- the log page

def parse_log_page(html: str) -> list[dict]:
    """Entries of one log page, newest first: {alert_date, status, in, out, dry}."""
    i = html.find("SOAK-alerts")
    if i < 0:
        return []
    block = html[i:]
    j = block.find('aria-label="Pagination"')
    block = block[:j] if j > 0 else block
    out = []
    for li in re.findall(r"<li[^>]*>(.*?)</li>", block, re.S):
        h = re.search(r"<h5[^>]*>(.*?)</h5>", li, re.S)
        if not h:
            continue
        body = _clean(re.sub(r"<[^>]+>", " ", li[h.end():]))
        times = {}
        for k, v in re.findall(r"\b(In|Out|Dry)\s*:\s*(.*?)(?=\s*\b(?:In|Out|Dry)\s*:|$)", body):
            times.setdefault(k.lower(), v.strip())
        status = re.split(r"\b(?:In|Out|Dry)\s*:", body, maxsplit=1)[0].strip()
        out.append({"alert_date": _clean(re.sub(r"<[^>]+>", " ", h.group(1))), "status": status,
                    "in": times.get("in"), "out": times.get("out"), "dry": times.get("dry")})
    return out


def stage_of(status: str) -> str:
    for name, rx in reversed(STAGES):   # "dry weather" before "ceased" before "in effect"
        if rx.search(status or ""):
            return name
    return "unknown"


def entry_key(e: dict) -> str:
    sig = "|".join(str(e.get(k) or "") for k in ("alert_date", "status", "in", "out", "dry"))
    return hashlib.sha1(sig.encode()).hexdigest()[:12]


def enrich(e: dict) -> dict:
    """Parsed fields of a stored entry (recomputed every run from the source strings)."""
    alert = parse_alert_date(e["alert_date"])
    x = {"alert": alert, "stage": stage_of(e["status"]), "fixes": [], "problems": []}
    if alert is None:
        x["problems"].append(f"unreadable alert date {e['alert_date']!r}")
    for k in ("in", "out", "dry"):
        dt, fixes, prob = parse_log_time(e.get(k), alert)
        x[k] = dt
        x["fixes"] += [f"{k}: {f}" for f in fixes]
        if prob:
            x["problems"].append(f"{k}: {prob}")
    return x


# ---------------------------------------------------------------- periods

def _chron(item):
    e, x = item
    alert = x["alert"] or date.min
    return (alert, x["in"] or datetime.combine(alert, datetime.min.time(), TZ), STAGE_RANK[x["stage"]],
            x["out"] or datetime.min.replace(tzinfo=TZ), e.get("_pos", 0))


def group_periods(entries: list[dict]) -> list[list[tuple[dict, dict]]]:
    """Entries (oldest first) -> periods (lists of (entry, parsed))."""
    items = sorted(((e, enrich(e)) for e in entries), key=_chron)
    periods: list[dict] = []
    for e, x in items:
        target = None
        recent = periods[-6:]
        if x["in"] is not None:
            target = next((p for p in reversed(recent) if x["in"] in p["ins"]), None)
        if target is None:
            ck = clock_key(e.get("in"))
            for p in reversed(recent):
                if p["closed"] or ck is None or ck not in p["clocks"]:
                    continue
                if x["alert"] and p["last_alert"] and (x["alert"] - p["last_alert"]).days > 10:
                    continue
                if x["in"] is not None and any(abs((x["in"] - t).days) > 40 for t in p["ins"]):
                    continue
                if x["in"] is not None and x["out"] is not None and p["outs"] and x["out"] not in p["outs"]:
                    continue   # both In and Out readable and different: another overflow at the same clock time
                target = p
                break
        if target is None:
            target = {"items": [], "ins": set(), "outs": set(), "clocks": set(), "closed": False, "last_alert": None}
            periods.append(target)
        target["items"].append((e, x))
        if x["in"] is not None:
            target["ins"].add(x["in"])
        if x["out"] is not None:
            target["outs"].add(x["out"])
        ck = clock_key(e.get("in"))
        if ck:
            target["clocks"].add(ck)
        target["last_alert"] = max(filter(None, [target["last_alert"], x["alert"]]), default=None)
        if x["stage"] == "dry":
            target["closed"] = True
    return [p["items"] for p in periods]


def _settle(values: list[tuple[datetime, int]], label: str, problems: list[str]) -> datetime | None:
    """Several entries' readings of one time (value, entry order): the agreed one, else the latest
    entry's, with a note."""
    if not values:
        return None
    distinct = Counter(v for v, _ in values)
    if len(distinct) == 1:
        return values[0][0]
    latest = max(values, key=lambda t: t[1])[0]
    problems.append(f"entries disagree on the {label} time ({', '.join(sorted(iso(v) for v in distinct))}); "
                    f"the latest entry's {iso(latest)} is used (review)")
    return latest


def period_record(items: list[tuple[dict, dict]], waters: dict) -> dict:
    problems: list[str] = []
    ins = [(x["in"], k) for k, (e, x) in enumerate(items) if x["in"] is not None]
    outs = [(x["out"], k) for k, (e, x) in enumerate(items) if x["out"] is not None and x["stage"] in ("ceased", "dry")]
    drys = [(x["dry"], k) for k, (e, x) in enumerate(items) if x["dry"] is not None]
    started = _settle(ins, "In", problems)
    ended = _settle(outs, "Out", problems)
    dry_at = _settle(drys, "Dry", problems)
    top = max(items, key=lambda it: (STAGE_RANK[it[1]["stage"]], it[1]["alert"] or date.min))
    stage = top[1]["stage"]
    if stage == "unknown":
        problems.append(f"unrecognised wording {top[0]['status']!r}")
    status = {"effect": "ongoing", "ceased": "ended", "dry": "ended"}.get(stage, "unknown")
    if started is None:
        problems.append("no readable In time in any entry of this period")
    if status == "ended" and ended is None:
        problems.append("overflows ceased but no readable Out time in any entry of this period")
    if started and ended and ended < started:
        problems.append(f"Out {iso(ended)} is before In {iso(started)}")
    first_alert = min((x["alert"] for _, x in items if x["alert"]), default=None)
    if started:
        rid = f"soak-{started:%Y%m%dT%H%M}"
    else:
        rid = f"soak-unparsed-{first_alert or 'nodate'}-{entry_key(items[0][0])}"
    entry_problems = [{"alert_date": e["alert_date"], "status": e["status"], "problem": p}
                      for e, x in items for p in x["problems"]]
    if entry_problems and (started is None or (status == "ended" and ended is None)):
        problems += [f"{p['alert_date']}: {p['problem']}" for p in entry_problems]
    raw = {
        "entries": [{k: e.get(k) for k in ("alert_date", "status", "in", "out", "dry")} | {"stage": x["stage"]}
                    for e, x in items],
        "stage": stage, "dry_at": iso(dry_at),
        "time_corrections": [{"alert_date": e["alert_date"], "correction": f} for e, x in items for f in x["fixes"]],
        "entry_problems": entry_problems,
        "system_wide": True, "water_basis": WATER_BASIS, "timezone_note": TZ_NOTE,
        "alert_dates_note": "Alert dates are the posting days (day only); overnight changes are posted at 8 a.m.",
    }
    return event(
        source_id=SOURCE_ID, source_record_id=rid, event_type="cso", status=status, **DISCHARGER,
        waterbody_text="Allegheny, Monongahela and Ohio rivers (ALCOSAN service area, system-wide)",
        water_slugs=waters["slugs"], water_match="inferred" if waters["slugs"] else "none",
        started_at=iso(started), ended_at=iso(ended) if status == "ended" else None, time_precision="minute",
        published_at=(datetime.combine(first_alert, datetime.min.time(), TZ).isoformat()
                      if started is None and first_alert else None),
        material=None, volume_gal=None, volume_text=None, estimate_flag="unknown",
        authority=AUTHORITY, advice_text=top[0]["status"] or None, advice_window_hours=48,
        advice_window_basis=WINDOW_BASIS, source_url=LOG_URL, raw=raw,
        parse_error="; ".join(problems) if problems else None,
    )


def bound_unclosed(records: list[dict]) -> int:
    """An 'in effect' period with no 'ceased' entry of its own, followed by a later period that
    ceased: the log is one status for the whole system, so "Overflows have ceased" at that later Out
    time means this period had ended by then. Status ended, ended_at null, time_precision "bound",
    raw._ended_before = that Out time (build/status.py counts the 48 h from it). Returns the count."""
    soak = sorted((r for r in records if r["source_record_id"].startswith("soak-") and r["started_at"]),
                  key=lambda r: datetime.fromisoformat(r["started_at"]))
    n = 0
    for i, r in enumerate(soak):
        if r["status"] != "ongoing":
            continue
        start = datetime.fromisoformat(r["started_at"])
        later = next((q for q in soak[i + 1:] if q["ended_at"] and datetime.fromisoformat(q["ended_at"]) > start), None)
        if not later:
            continue
        r["status"], r["time_precision"] = "ended", "bound"
        r["raw"]["_ended_before"] = later["ended_at"]
        r["raw"]["_ended_before_basis"] = (
            f"No 'ceased' entry was posted for this In time; the log's next 'Overflows have ceased' entry "
            f"(period {later['source_record_id']}, Out {later['ended_at']}) is system-wide, so overflows had "
            "ceased by then.")
        note = "no 'ceased' entry for this In time: end bounded by the next system-wide 'ceased' Out time (review)"
        r["parse_error"] = f"{r['parse_error']}; {note}" if r["parse_error"] else note
        n += 1
    return n


# ---------------------------------------------------------------- news posts

def parse_news_list(html: str) -> list[dict]:
    out, seen = [], set()
    for m in re.finditer(r'<div class="title">\s*<a\s+href="([^"]*/news-and-events/featured-news/news/[^"]+)"[^>]*>(.*?)</a>'
                         r'\s*</div>\s*<span class="text-muted">\s*(.*?)\s*</span>', html, re.S):
        url = m.group(1) if m.group(1).startswith("http") else SITE + m.group(1)
        if url in seen:
            continue
        seen.add(url)
        out.append({"url": url, "title": _clean(re.sub(r"<[^>]+>", " ", m.group(2))), "posted": _clean(m.group(3))})
    return out


def parse_posted(s: str | None) -> datetime | None:
    s = _clean(s or "")
    for fmt in ("%b %d, %Y, %I:%M %p", "%B %d, %Y, %I:%M %p", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=TZ)
        except ValueError:
            pass
    return None


def parse_post(html: str) -> dict:
    i, j = html.find("<main"), html.find("</main>")
    main = html[i:j] if i >= 0 else html
    title = re.search(r"<h3[^>]*>(.*?)</h3>", main, re.S)
    posted = re.search(r'<span class="text-muted">\s*(.*?)\s*</span>', main, re.S)
    body = main[posted.end():] if posted else main
    k = body.find("simple-social")
    body = body[:k] if k > 0 else body
    links = sorted({(h if h.startswith("http") else SITE + h)
                    for h in re.findall(r'href="([^"]*/news-and-events/featured-news/news/[^"]+)"', body)})
    text = re.sub(r"<(br|/p|/li|/h\d)[^>]*>", "\n", body)
    text = _clean(re.sub(r"<[^>]+>", " ", text).replace("\n", " \n "))
    return {"title": _clean(re.sub(r"<[^>]+>", " ", title.group(1))) if title else None,
            "posted": _clean(posted.group(1)) if posted else None, "text": text, "links": links}


ROAD = re.compile(r"\b\d+(?:st|nd|rd|th)\s+street\s+bypass\b|\bstreet\s+bypass\b", re.I)


def classify(text: str) -> tuple[str, str | None]:
    t = ROAD.sub(" ", text)
    if re.search(r"sanitary sewer overflow|\bSSOs?\b", t, re.I):
        return "sso", "the post says sanitary sewer overflow"
    if re.search(r"\bbypass(?:ed|es|ing)?\b", t, re.I):
        return "bypass", "the post says bypass"
    if re.search(r"wet well|treatment plant|wastewater treatment", t, re.I) and re.search(r"discharg", t, re.I):
        return "bypass", ("untreated discharge at the treatment plant (the post describes the plant / wet well "
                          "discharging; it does not use the word bypass)")
    return "unknown", None


_HOUR = r"(\d{1,2})(?::(\d{2}))?\s*(a\.?\s?m\.?|p\.?\s?m\.?)?"
WINDOW = re.compile(rf"between\s+{_HOUR}\s*(?:–|—|-|to|and)\s*{_HOUR}", re.I)
RELATIVE_DAY = re.compile(r"\b(this evening|tonight|today|this morning|this afternoon)\b", re.I)


def _h(hh, mm, ap, fallback_ap):
    ap = (ap or fallback_ap or "").lower().replace(".", "").replace(" ", "")
    h = int(hh) % 12 + (12 if ap == "pm" else 0)
    return h, int(mm or 0), bool(ap)


def sentences(text: str) -> list[str]:
    """Split at a full stop followed by a capital letter ("8 p.m. this evening" stays whole)."""
    return [x.strip() for x in re.split(r"(?<=[.!?])\s+(?=[A-Z\u201c\"])", text or "") if x.strip()]


def post_times(text: str, posted: datetime | None) -> tuple[datetime | None, datetime | None, str | None]:
    """'between 6 – 8 p.m. this evening' in a post dated Mar 6 -> (18:00, 20:00, the sentence)."""
    if posted is None:
        return None, None, None
    for sent in sentences(text):
        m = WINDOW.search(sent)
        if not m or not RELATIVE_DAY.search(sent):
            continue
        h1, m1, ok1 = _h(m.group(1), m.group(2), m.group(3), m.group(6))
        h2, m2, ok2 = _h(m.group(4), m.group(5), m.group(6), m.group(3))
        if not (ok1 or ok2):
            continue
        d = posted.date()
        a = datetime(d.year, d.month, d.day, h1, m1, tzinfo=TZ)
        b = datetime(d.year, d.month, d.day, h2, m2, tzinfo=TZ)
        if b < a:
            continue
        return a, b, sent.strip()
    return None, None, None


VOLUME = re.compile(r"((?:an?\s+)?(?:estimated|approximately|about|roughly|nearly)?\s*[\d.,]+[\s-]+million[\s-]+gallons?)", re.I)


EVENT_WORDS = re.compile(r"discharg|overflow|bypass|advis|lifted|resolved|outage|wet well|gallon|hours|manhole|"
                         r"waterway|river|stuck|clean-up|notified", re.I)


def excerpt(text: str | None) -> list[str]:
    """The post's sentences about the incident, without quotations (staff remarks)."""
    return [x for x in sentences(text or "") if EVENT_WORDS.search(x) and not re.search(r"[\u201c\u201d\"]|\bsaid\b", x)]


def in_season(d: date | None) -> bool | None:
    return None if d is None else (4 <= d.month <= 10)


def group_incidents(posts: dict) -> list[list[dict]]:
    """Discharge posts (oldest first) -> incidents: a post linking to an earlier post, or titled
    'Update on <Month> <day>' for an earlier post's day, joins that post's incident."""
    order = sorted(posts.values(), key=lambda p: p.get("posted_at") or "")
    incidents: list[list[dict]] = []
    where: dict[str, int] = {}
    for p in order:
        idx = next((where[u] for u in p.get("links") or [] if u in where), None)
        if idx is None:
            m = re.search(r"\bupdate on (\w+ \d{1,2})(?:st|nd|rd|th)?\b", p.get("title") or "", re.I)
            if m and p.get("posted_at"):
                yr = p["posted_at"][:4]
                try:
                    d = datetime.strptime(f"{m.group(1)} {yr}", "%B %d %Y").date()
                except ValueError:
                    d = None
                for u, k in where.items():
                    q = posts[u]
                    if d and q.get("posted_at") and abs((date.fromisoformat(q["posted_at"][:10]) - d).days) <= 1:
                        idx = k
                        break
        if idx is None:
            incidents.append([])
            idx = len(incidents) - 1
        incidents[idx].append(p)
        where[p["url"]] = idx
    return incidents


def incident_record(posts: list[dict], waters: dict) -> dict:
    first = posts[0]
    text = " ".join(p.get("text") or "" for p in posts)
    etype, basis = classify(" ".join([p.get("title") or "" for p in posts] + [text]))
    posted = datetime.fromisoformat(first["posted_at"]) if first.get("posted_at") else None
    started, ended, time_sentence = post_times(first.get("text") or "", posted)
    problems = []
    if etype == "unknown":
        problems.append("the posts do not say bypass or sanitary sewer overflow, nor describe a plant discharge (review)")
    if started is None:
        problems.append("no discharge time stated in a form the parser reads")
    resolved = next((p for p in posts if re.search(r"\b(lifted|resolved|ceased|has ended|window ended)\b",
                                                    (p.get("title") or "") + " " + (p.get("text") or ""), re.I)), None)
    status = "ended" if ended or resolved else "unknown"
    vol = next((m.group(1).strip() for p in posts for m in [VOLUME.search(p.get("text") or "")] if m), None)
    gal, est = parse_volume_gal(vol) if vol else (None, "unknown")
    advice = next((s for s in sentences(first.get("text") or "")
                   if re.search(r"\b(stay out|avoid|limit contact|minimi[sz]e contact)\b", s, re.I)), None)
    hours = int(re.search(r"(\d+)\s*hours", advice).group(1)) if advice and re.search(r"(\d+)\s*hours", advice) else None
    slug = re.sub(r"^.*/news/", "", first["url"]).strip("/")
    d = date.fromisoformat(first["posted_at"][:10]) if first.get("posted_at") else None
    raw = {
        "posts": [{"url": p["url"], "title": p.get("title"), "posted": p.get("posted"), "excerpt": excerpt(p.get("text"))}
                  for p in posts],
        "excerpt_note": "Sentences about the discharge and the advice; quoted remarks by staff are left out.",
        "classification_basis": basis, "time_basis": time_sentence,
        "time_basis_note": ("started_at/ended_at are the time window the post states for the incident; exact "
                            "discharge times are not given") if time_sentence else None,
        "advisory_lifted_post": ({"url": resolved["url"], "posted": resolved.get("posted")} if resolved else None),
        "in_soak_season": in_season(d),
        "water_basis": "The posts name 'the river' / 'area waterways'; the three rivers at Pittsburgh are inferred.",
        "timezone_note": "Post times carry no zone; read as America/New_York.",
    }
    last = max(posts, key=lambda p: p.get("posted_at") or "")
    return event(
        source_id=SOURCE_ID, source_record_id="news-" + re.sub(r"[^a-z0-9]+", "-", slug.lower()).strip("-"),
        event_type=etype, status=status, **DISCHARGER,
        waterbody_text="the river / area waterways (Allegheny, Monongahela and Ohio rivers inferred)",
        water_slugs=waters["slugs"], water_match="inferred" if waters["slugs"] else "none",
        started_at=iso(started), ended_at=iso(ended), time_precision="hour" if started else None,
        reported_at=first.get("posted_at"), published_at=first.get("posted_at"),
        source_updated_at=last.get("posted_at") if len(posts) > 1 else None,
        material=None, volume_gal=gal, volume_text=vol, estimate_flag=est if vol else "unknown",
        authority="ALCOSAN news post", advice_text=advice, advice_window_hours=hours,
        advice_window_basis="ALCOSAN news post" if hours else None, source_url=first["url"], raw=raw,
        parse_error="; ".join(problems) if problems else None,
    )


# ---------------------------------------------------------------- fetch and run

def river_slugs() -> dict:
    slugs, missing = [], []
    for name in RIVERS:
        s = pa_waters.named(name, PITTSBURGH)
        (slugs.append(s) if s else missing.append(name))
    return {"slugs": slugs, "missing": missing}


def get(sess: requests.Session, url: str) -> str:
    r = sess.get(url, timeout=60)
    r.raise_for_status()
    return r.text


def save_if_changed(state: dict, name: str, content: str, ext: str, signature: str | None = None) -> None:
    """Save a raw page when its content (or the signature given: the parsed entries, since the page
    carries per-request tokens) changed since the last saved copy."""
    h = hashlib.sha256((signature if signature is not None else content).encode()).hexdigest()
    if state.setdefault("raw_hashes", {}).get(name) != h:
        save_raw(SOURCE_ID, content, ext)
        state["raw_hashes"][name] = h


def fetch_log(sess, state: dict, backfill: bool) -> tuple[list[dict], int, bool]:
    """(entries newest first, pages read, complete) for pages 1-3, or back to 2025 with backfill."""
    entries, n, prev_sig = [], 0, None
    last = MAX_PAGES if backfill else DEFAULT_PAGES
    complete = True
    while n < last:
        n += 1
        url = LOG_URL if n == 1 else f"{LOG_URL}/{n}"
        try:
            html = get(sess, url)
        except Exception as e:
            if n == 1:
                raise
            print(f"pa-alcosan: page {n} failed ({e}); stopping", file=sys.stderr)
            complete = False
            break
        page = parse_log_page(html)
        sig = [entry_key(e) for e in page]
        if not page or sig == prev_sig:
            break
        prev_sig = sig
        save_if_changed(state, f"log-p{n}", html, f"log-p{n}.html", signature="|".join(sig))
        for k, e in enumerate(page):
            e["_pos"] = -(len(entries) + k)   # newer entries sort later on ties
        entries += page
        if backfill:
            dates = [d for d in (parse_alert_date(e["alert_date"]) for e in page) if d]
            if dates and min(dates) < BACKFILL_FROM:
                break
            time.sleep(1)
    return entries, n, complete


def merge_entries(state: dict, fetched: list[dict], now: str, complete: bool) -> dict:
    store = state.setdefault("entries", {})
    seen_keys, counts = set(), Counter()
    for e in fetched:
        k = entry_key(e)
        counts[k] += 1
        if counts[k] > 1:
            k = f"{k}#{counts[k]}"
        seen_keys.add(k)
        rec = store.setdefault(k, {kk: e.get(kk) for kk in ("alert_date", "status", "in", "out", "dry")} | {"first_seen_at": now})
        rec["last_seen_at"] = now
        rec["_pos"] = e.get("_pos", 0)
    dropped = 0
    dates = [d for d in (parse_alert_date(e["alert_date"]) for e in fetched) if d]
    if complete and dates:
        lo, hi = min(dates), max(dates)
        for k in list(store):
            d = parse_alert_date(store[k]["alert_date"])
            if k not in seen_keys and d and lo < d <= hi:
                state.setdefault("dropped_entries", {})[k] = {**store.pop(k), "dropped_at": now}
                dropped += 1
    return {"fetched": len(fetched), "new": sum(1 for k in seen_keys if store[k]["first_seen_at"] == now),
            "dropped": dropped}


def fetch_news(sess, state: dict, now: str) -> tuple[int, str | None]:
    posts = state.setdefault("news_posts", {})
    try:
        listing = parse_news_list(get(sess, NEWS_URL))
    except Exception as e:
        return 0, f"news list: {e}"
    errors = []
    for item in listing:
        if not NEWS_TITLE.search(item["title"]):
            continue
        old = posts.get(item["url"])
        if old and old.get("first_seen_at") and old["first_seen_at"] < (datetime.fromisoformat(now.replace("Z", "+00:00"))
                                                                        - timedelta(days=7)).isoformat():
            continue   # read again during its first week (posts get "UPDATE" paragraphs)
        try:
            html = get(sess, item["url"])
        except Exception as e:
            errors.append(f"{item['url']}: {e}")
            continue
        p = parse_post(html)
        h = hashlib.sha256(f"{p['title']}|{p['posted']}|{p['text']}".encode()).hexdigest()
        if (old or {}).get("hash") != h:
            save_raw(SOURCE_ID, html, "news-" + re.sub(r"[^a-z0-9]+", "-", item["url"].rsplit("/", 1)[-1].lower())[:60] + ".html")
        posted = parse_posted(p["posted"] or item["posted"])
        posts[item["url"]] = {"url": item["url"], "title": p["title"] or item["title"], "posted": p["posted"] or item["posted"],
                              "posted_at": iso(posted), "text": p["text"], "links": [u for u in p["links"] if u != item["url"]],
                              "hash": h, "first_seen_at": (old or {}).get("first_seen_at") or now, "fetched_at": now}
        time.sleep(0.5)
    return len(listing), "; ".join(errors) or None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backfill", action="store_true", help="walk the log pages back to 2025")
    args = ap.parse_args(argv)
    state = read_json(STATE_PATH, {}) or {}
    now = now_iso()
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        fetched, pages, complete = fetch_log(sess, state, args.backfill)
    except Exception as e:
        write_events(SOURCE_ID, [], ok=False, error=f"log: {e}")
        print(f"pa-alcosan: FAILED {e}", file=sys.stderr)
        return 1
    if not fetched:
        write_events(SOURCE_ID, [], ok=False, error="log page 1 has no SOAK entries (layout changed?)")
        print("pa-alcosan: FAILED no entries on page 1", file=sys.stderr)
        return 1
    merged = merge_entries(state, fetched, now, complete)
    listed, news_err = fetch_news(sess, state, now)
    state["last_run_at"] = now
    write_json(STATE_PATH, state)

    waters = river_slugs()
    periods = group_periods(list(state["entries"].values()))
    records = [period_record(items, waters) for items in periods]
    ids = Counter(r["event_id"] for r in records)
    for r in records:   # two periods with one In time (a duplicated typo): keep both, distinctly
        if ids[r["event_id"]] > 1:
            r["event_id"] += f"-{entry_key(r['raw']['entries'][0])}"
            r["source_record_id"] = r["event_id"].split(":", 1)[1]
    bounded = bound_unclosed(records)
    news_posts = {u: p for u, p in state.get("news_posts", {}).items() if p.get("posted_at")}
    records += [incident_record(inc, waters) for inc in group_incidents(news_posts) if inc]
    records.sort(key=lambda r: r["started_at"] or r["published_at"] or "", reverse=True)
    dates = [parse_alert_date(e["alert_date"]) for e in state["entries"].values()]
    meta = {
        "pages_read": pages, "mode": "backfill" if args.backfill else f"pages 1-{DEFAULT_PAGES}",
        "entries_fetched": merged["fetched"], "entries_new": merged["new"], "entries_dropped": merged["dropped"],
        "entries_stored": len(state["entries"]), "log_from": min(filter(None, dates), default=None),
        "log_to": max(filter(None, dates), default=None),
        "periods": len(periods), "periods_end_bounded": bounded, "news_posts_listed": listed, "news_posts_read": len(news_posts),
        "news_error": news_err, "water_slugs": waters["slugs"], "rivers_without_slug": waters["missing"],
        "parse_errors": sum(1 for r in records if r["parse_error"]),
        "time_corrections": sum(len(r["raw"].get("time_corrections") or []) for r in records),
        "scope": WATER_BASIS, "timezone_note": TZ_NOTE, "log_url": LOG_URL, "news_url": NEWS_URL,
        "covers_permits": [DISCHARGER["npdes_permit"]], "statewide": False,
    }
    path = write_events(SOURCE_ID, records, ok=True, error=news_err, meta=meta)
    c = Counter((r["event_type"], r["status"]) for r in records)
    print(f"pa-alcosan: {len(records)} events {dict(c)}; {merged['fetched']} entries read from {pages} pages "
          f"({merged['new']} new), {len(news_posts)} news posts -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
