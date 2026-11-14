"""KC Water's wastewater overflow notices (Kansas City, Missouri): the City's own news posts "Customers Advised of
Wastewater Overflow near ..." and "KC Water Wastewater Facilities Experience Effects of Heavy Rain", as dated sewage
reports.

Source
  https://www.kcwater.us/news/ (registry: mo-kc-water-overflow-notices). The news archive is a WordPress post type the
  site's REST API does not expose and that has no feed of its own; the site search's RSS feed does carry it:
  https://www.kcwater.us/search/overflow/feed/rss2/?paged=N, ten posts a page, newest first, each with its title, link,
  publication time (pubDate, with its offset), its WordPress id (guid "?post_type=news1&p=NNNN") and its full text
  (content:encoded). The hourly run reads the first two pages; `--backfill` reads every page until one answers 404.
  Read 2026-11-14: 16 pages for "overflow" and 3 for "sewage", 152 news posts, 99 of them overflow notices (93
  overflows and 6 update posts) from July 2016 to August 2025 (2016: 2, 2017: 15, 2018: 7, 2019: 23, 2020: 14, 2021: 7,
  2022: 11, 2023: 6, 2024: 7, 2025: 1). Archive check the same day: the news index (/news/page/1 to 21, 206 posts)
  links 49 overflow posts, every one of them in the search feed; the feed holds 50 more the index no longer links. KC
  Water publishes
  some overflows, not every one: no rule or permit clause requiring the posts was found, and the volume, water and
  times are KC Water's own words.

Record rules
  - A post is an overflow notice when its title says wastewater overflow (or overflow, sewage spill, or "Effects of
    Heavy Rain" with a wastewater spill in its text) and it is not a rate, bond, grease or programme post (NOT_EVENT).
    "UPDATE:" posts are follow-ups: each is kept with duplicate_of the first notice for the same place within 14 days
    and, when the first notice gives no end and the update does, the update's end is the event's end (raw.end_from).
  - One record per post (source_record_id the WordPress post id). A post that names several pump stations (heavy-rain
    posts) stays one record: raw.multiple_sites, every water it names in raw.waters_named, the earliest start.
  - Times (America/Chicago, KC Water's clock; the posts give no offset): the event day is the first weekday-and-date or
    date the text gives (a date with no year takes the post's year, the year before when that would be after the post);
    "today" or "this morning" is the post's own Central day. The first clock time in that sentence is the record's start,
    and raw.start_kind says what it was: "start" (the text says the overflow began, started or occurred), "response"
    (KC Water's crews responded: the overflow began at or before it, raw.start_is_upper_bound), "report" (another
    party reported it). No time: day precision. An end ("ended", "ceased", "stopped") with a clock time is ended_at,
    raw.ended_at_precision minute, on the same day unless the sentence gives its own date or the time is before the
    start (the next day). "Continues" leaves the end open.
  - Volume: the first "N gallons" that is not a rate ("gallons per minute" is kept only as text); "approximately" or
    "estimated" makes it estimated.
  - Water: a named creek, river, branch, lake or fork in a sentence that says the wastewater entered, reached, flowed,
    spilled or leads into it, not a pump station's or plant's name ("Burlington Creek Pump Station"); the first is the
    receiving water (waterbody_text), the rest raw.waters_named. A post that names none is kept and placed on no water;
    raw.reached_water is False only when the text says the wastewater did not reach water.
  - event_type "sso" (a collection-system overflow); "plant_bypass" when the text names a treatment plant overflowing.
    status "unknown": the posts never publish an advisory lift, so the site's caution applies from the start.
  - Operator: the City of Kansas City, Missouri (KC Water); the plant permit is not assigned from the city name.

Privacy: the post titles and texts name street addresses ("near 4000 Mersington Ave."): every house number is dropped
from the stored title, location and text (common.strip_house_numbers), and the media contact line and the boilerplate
paragraphs are not kept. The post's own address (source_url, the citation) keeps the slug KC Water gave it; the feed's
tracking query is dropped. The feed's dc:creator (a staff account) is never read. data/raw keeps only the parsed safe
fields of each item, never the response.
Run from pipeline/:  python -m ingest.mo_kc_water_news [--backfill] [--file feed.xml ...]
"""
from __future__ import annotations

import html
import json
import re
import sys
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import common
from common import HEADERS, event, now_iso, read_json, save_raw, write_events

SOURCE_ID = "mo-kc-water-overflow-notices"
FEED = "https://www.kcwater.us/search/overflow/feed/rss2/"
INDEX = "https://www.kcwater.us/news/"
TZ = ZoneInfo("America/Chicago")
AUTHORITY = "KC Water (City of Kansas City, Missouri), news post"
DISCHARGER_ID = "mo-kansas-city-mo0024911"
DISCHARGER = "City of Kansas City, Missouri (KC Water)"
NS = {"content": "http://purl.org/rss/1.0/modules/content/"}
LIVE_PAGES = 2

EVENT_TITLE = re.compile(r"\boverflow\b|\bsewage\b|\bspill|effects of heavy rain", re.I)
NOT_EVENT = re.compile(r"\bbonds?\b|\brates?\b|task force|invests?\b|upgrades? at|grease|fats, oils|keep out the rain|"
                       r"green infrastructure|capital improvement|celebrat|award|grant|reminds customers|tunnel|"
                       r"\bprojects?\b(?!.*overflow near)", re.I)
UPDATE = re.compile(r"^\s*update\s*:\s*", re.I)
MONTHS = {m: i for i, m in enumerate(["january", "february", "march", "april", "may", "june", "july", "august",
                                      "september", "october", "november", "december"], 1)}
MONTH_RE = r"(January|February|March|April|May|June|July|August|September|October|November|December|Jan\.?|Feb\.?|" \
           r"Mar\.?|Apr\.?|Jun\.?|Jul\.?|Aug\.?|Sept?\.?|Oct\.?|Nov\.?|Dec\.?)"
DATE = re.compile(MONTH_RE + r"\s+(\d{1,2})\s*(?:st|nd|rd|th)?\b(?:\s*,?\s*(\d{4}))?", re.I)
TIME = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a|p)\.?\s*m\b\.?|\b(noon|midnight)\b|"
                  r"\b(\d{1,2}):(\d{2})\s+(?:this|in the)\s+(morning|afternoon|evening)\b", re.I)
WATER_WORDS = r"(?:Creek|River|R\.|Branch|Lake|Fork|Run)"
WATER = re.compile(r"\b((?:(?:[A-Z][\w'’]*|of)\s+){0,3}" + WATER_WORDS + r")(?!\s+(?:Pump|Wastewater|Treatment|"
                   r"Diversion|Basin|Lift|Interceptor|Park(?:way)?|Road|Rd|Drive|Dr|Blvd|Boulevard|Avenue|Ave|Street|St))")
ENTRY = re.compile(r"\benter|\breach|\bflow|\bspill|\bleads?\b|\binto\b|\bdischarg|\bwent\b|\bsend|\bcarried", re.I)
NO_WATER = re.compile(r"did not (?:reach|enter)|no (?:waste ?water|sewage) (?:reached|entered)|never reached", re.I)
SKIP_WATERS = re.compile(r"^(?:the|a|an|of|local|nearby|small|unnamed)\b", re.I)


def items(body: bytes) -> list[dict]:
    """The feed's items as dicts (title, link, pubDate, guid, text); the text is the post's own paragraphs."""
    root = ET.fromstring(body)
    out = []
    for it in root.iter("item"):
        c = it.find("content:encoded", NS)
        out.append({"title": html.unescape(it.findtext("title") or "").strip(), "link": (it.findtext("link") or "").strip().split("?")[0],
                    "date": (it.findtext("pubDate") or "").strip(), "guid": (it.findtext("guid") or "").strip(),
                    "html": c.text if c is not None and c.text else ""})
    return out


def post_text(h: str) -> str:
    """The post's paragraphs as one string, without the boilerplate and the media contact (module docstring)."""
    t = html.unescape(re.sub(r"<[^>]+>", " ", h or ""))
    t = re.sub(r"\s+", " ", t).strip()
    t = re.split(r"Buried underneath|For more information|KC Water maintains and operates|###", t)[0]
    t = re.sub(r"^\(Kansas City, Mo\.?\)\s*[–-]\s*", "", t)
    return common.strip_house_numbers(t).strip()


def post_id(it: dict) -> str:
    m = re.search(r"[?&]p=(\d+)", it.get("guid") or "")
    return m.group(1) if m else re.sub(r"[^a-z0-9]+", "-", it["link"].rstrip("/").rsplit("/", 1)[-1].lower())


def pub_dt(it: dict) -> datetime | None:
    try:
        return parsedate_to_datetime(it["date"]).astimezone(TZ)
    except (TypeError, ValueError, IndexError):
        return None


def is_notice(title: str, text: str) -> bool:
    if NOT_EVENT.search(title) and not re.search(r"overflow (?:near|at)\b", title, re.I):
        return False
    if re.search(r"effects of heavy rain", title, re.I):
        return bool(re.search(r"(?:waste ?water|sewage)[^.]{0,80}\b(?:spill|overflow|enter)", text, re.I))
    return bool(EVENT_TITLE.search(title))


def sentences(text: str) -> list[str]:
    # not after "p.m.", "a.m.", "St.", "Ave." and the like: "at 6:00 p.m. Thursday, June 9" is one sentence
    return [s.strip() for s in re.split(r"(?<![ap]\.m\.)(?<!\b[A-Z]\.)(?<!\bSt\.)(?<!\bMo\.)(?<!\bRd\.)(?<!\bDr\.)"
                                        r"(?<!\bAve\.)(?<!\bBlvd\.)(?<!Jan\.)(?<!Feb\.)(?<!Mar\.)(?<!Apr\.)(?<!Jun\.)(?<!Jul\.)(?<!Aug\.)"
                                        r"(?<!Sep\.)(?<!Sept\.)(?<!Oct\.)(?<!Nov\.)(?<!Dec\.)(?<=[.!?])\s+(?=[A-Z0-9])", text) if s.strip()]


def _month(s: str) -> int:
    k = s.lower().rstrip(".")
    return next(v for m, v in MONTHS.items() if m.startswith(k[:3]))


def find_date(s: str, pub: date) -> date | None:
    m = DATE.search(s)
    if m:
        y = int(m.group(3)) if m.group(3) else pub.year
        try:
            d = date(y, _month(m.group(1)), int(m.group(2)))
        except ValueError:
            return None
        if not m.group(3) and d > pub:
            d = date(y - 1, d.month, d.day)
        return d
    if re.search(r"\btoday\b|\bthis (?:morning|afternoon|evening)\b|\btonight\b", s, re.I):
        return pub
    return None


def clock(m: re.Match) -> tuple[int, int]:
    if m.group(4):
        return (12, 0) if m.group(4).lower() == "noon" else (0, 0)
    if m.group(5):                                    # "7:46 this morning"
        h, mi = int(m.group(5)) % 12, int(m.group(6))
        return (h if m.group(7).lower() == "morning" else h + 12), mi
    h, mi = int(m.group(1)) % 12, int(m.group(2) or 0)
    return (h + 12 if m.group(3).lower() == "p" else h), mi


def times(text: str, pub: date) -> dict:
    """{start, start_kind, precision, end, end_basis} read from the text (module docstring)."""
    out = {"start": None, "start_kind": None, "precision": None, "end": None, "end_basis": None}
    ss = sentences(text)
    day, si = None, None
    for i, s in enumerate(ss):
        d = find_date(s, pub)
        if d:
            day, si = d, i
            break
    if day is None:
        return out
    s = ss[si]
    kind = ("start" if re.search(r"\b(?:began|begun|started|start(?:ing)?|occurred|beginning)\b", s, re.I) else
            "response" if re.search(r"\brespon(?:d|ded|se)\b", s, re.I) else
            "report" if re.search(r"\breport(?:ed|s)?\b|\bnotified\b|\bdiscovered\b|\bfound\b", s, re.I) else
            "stated")
    # a sentence about the start that only gives a date: a later sentence of the same post may give the start time
    tm = TIME.search(s) or next((TIME.search(x) for x in ss[si + 1:si + 2]
                                if re.search(r"\b(?:began|started|occurred)\b", x, re.I) and TIME.search(x)), None)
    if tm:
        h, mi = clock(tm)
        start = datetime(day.year, day.month, day.day, h, mi, tzinfo=TZ)
        out.update(start=start.isoformat(), precision="minute")
    else:
        start = None
        out.update(start=day.isoformat(), precision="day")
    out["start_kind"] = kind
    for x in ss[si:]:
        if not re.search(r"\b(?:ended|ceased|stopped|end(?:ed)? at)\b", x, re.I):
            continue
        if re.search(r"\bcontinu", x, re.I) and not re.search(r"\bended\b", x, re.I):
            break
        ems = list(TIME.finditer(x))
        # the end time is the one after the end word ("It ended later that same day at 4:45 p.m.")
        w = re.search(r"\b(?:ended|ceased|stopped)\b", x, re.I)
        after = [m for m in ems if w and m.start() > w.start()]
        if not after or start is None:
            break
        h, mi = clock(after[0])
        d2 = find_date(x[w.start():] if w else x, pub) or day
        end = datetime(d2.year, d2.month, d2.day, h, mi, tzinfo=TZ)
        basis = "the time the post gives for the overflow's end"
        if end < start:
            if re.search(r"next day|following day|the next morning", x, re.I) or d2 == day:
                end += timedelta(days=1)
                basis += " (before the start time, so the next day)"
        if end >= start:
            out.update(end=end.isoformat(), end_basis=basis)
        break
    return out


def volume(text: str) -> tuple[int | None, str, str | None]:
    for m in re.finditer(r"((?:approximately|about|an estimated|estimated|nearly|over|more than)?\s*[\d,]+(?:\.\d+)?)\s*"
                         r"(?:total\s+)?gallons(\s+(?:per|a|an)\s+(?:minute|hour|day))?", text, re.I):
        if m.group(2):
            return None, "unknown", m.group(0).strip()
        v, flag = common.parse_volume_gal(m.group(1))
        if re.search(r"approximately|about|estimated|nearly", m.group(1), re.I):
            flag = "estimated"
        return v, flag, m.group(0).strip()
    return None, "unknown", None


def waters(text: str) -> list[str]:
    out = []
    for s in sentences(text):
        if not ENTRY.search(s):
            continue
        for m in WATER.finditer(s):
            name = re.sub(r"\s+", " ", m.group(1)).strip()
            name = re.sub(r"^(?:into|to|the|entered|entering|reached|reach|and|of)\s+", "", name, flags=re.I)
            name = re.sub(r"\bR\.$", "River", name)
            if SKIP_WATERS.match(name) or len(name.split()) < 2:
                continue
            if name not in out:
                out.append(name)
    return out


def place_text(title: str) -> str | None:
    m = re.search(r"\b(?:near|at)\s+(.+)$", UPDATE.sub("", title), re.I)
    return common.strip_house_numbers(m.group(1)).strip(" .") if m else None


def record(it: dict, at: str) -> dict | None:
    text = post_text(it["html"])
    title = UPDATE.sub("", it["title"]).strip()
    if not is_notice(title, text):
        return None
    pub = pub_dt(it)
    t = times(text, pub.date() if pub else date.today())
    v, flag, vtext = volume(text)
    ws = waters(text)
    plant = bool(re.search(r"treatment plant[^.]{0,60}\b(?:overflow|spill|bypass)|\bWWTP\b", text, re.I)) and \
        not re.search(r"pump station", title, re.I)
    pid = post_id(it)
    place = place_text(title)
    raw = {"state": "MO", "time_zone": "America/Chicago", "title": common.strip_house_numbers(title),
           "is_update": bool(UPDATE.match(it["title"])), "post_text": text[:1500], "start_kind": t["start_kind"],
           "start_is_upper_bound": t["start_kind"] in ("response", "report", "stated"),
           "start_basis": {"start": "the time the post says the overflow began",
                           "response": "the time KC Water's crews responded; the overflow began at or before it",
                           "report": "the time the post says the overflow was reported or found; it began at or before it",
                           "stated": "the first time the post gives for the overflow; the post does not say what it marks",
                           None: "the post gives no date for the overflow: the record is not dated"}[t["start_kind"]],
           "waters_named": ws, "reached_water": False if NO_WATER.search(text) else (True if ws else None),
           "multiple_sites": bool(re.search(r"effects of heavy rain", title, re.I)), "place_text": place,
           "volume_text": vtext, "time_basis": "KC Water's clock times, read as Central time (America/Chicago)",
           "provenance": "operator"}
    if t["end"]:
        raw["ended_at_precision"], raw["end_basis"] = "minute", t["end_basis"]
    if not t["start"]:
        return event(source_id=SOURCE_ID, source_record_id=pid, event_type="sso", status="unknown",
                     discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER, outfall_name=place,
                     waterbody_text=ws[0] if ws else None, published_at=pub.isoformat() if pub else None,
                     reported_at=None, fetched_at=at, authority=AUTHORITY, source_url=it["link"],
                     parse_error="no date for the overflow in the post", raw=raw)
    return event(
        source_id=SOURCE_ID, source_record_id=pid, event_type="plant_bypass" if plant else "sso", status="unknown",
        discharger_id=DISCHARGER_ID, discharger_name=DISCHARGER, outfall_name=place,
        waterbody_text=ws[0] if ws and raw["reached_water"] is not False else None,
        started_at=t["start"], ended_at=t["end"], time_precision=t["precision"],
        published_at=pub.isoformat() if pub else None, reported_at=None, fetched_at=at,
        material="wastewater", volume_gal=v, volume_text=vtext, estimate_flag=flag, authority=AUTHORITY,
        source_url=it["link"], raw=raw)


def link_updates(recs: dict[str, dict]) -> int:
    """An update post is a copy of the first notice for the same place within 14 days (module docstring)."""
    n = 0
    firsts = [r for r in recs.values() if not r["raw"].get("is_update")]
    for r in recs.values():
        if not r["raw"].get("is_update") or not r.get("started_at"):
            continue
        key = re.sub(r"[^a-z]", "", (r["raw"].get("place_text") or "").lower())
        cands = [f for f in firsts if f.get("started_at") and key and
                 re.sub(r"[^a-z]", "", (f["raw"].get("place_text") or "").lower()) == key and
                 abs((datetime.fromisoformat(f["started_at"][:10]) -
                      datetime.fromisoformat(r["started_at"][:10])).days) <= 14]
        if not cands:
            continue
        f = min(cands, key=lambda f: f["published_at"] or "")
        r["duplicate_of"] = f["event_id"]
        f["raw"].setdefault("updates", [])
        if r["source_url"] not in f["raw"]["updates"]:
            f["raw"]["updates"].append(r["source_url"])
        if not f.get("ended_at") and r.get("ended_at"):
            f["ended_at"] = r["ended_at"]
            f["raw"].update(ended_at_precision="minute", end_from=r["source_url"],
                            end_basis="the end time KC Water's update post gives")
        n += 1
    return n


def run(feeds: list[bytes], prev: list[dict], at: str) -> tuple[list[dict], dict]:
    recs = {r["event_id"]: r for r in prev}
    stats = {"items": 0, "news_posts": 0, "notices": 0, "not_notices": 0, "undated": 0}
    seen = set()
    for body in feeds:
        for it in items(body):
            if it["link"] in seen:
                continue
            seen.add(it["link"])
            stats["items"] += 1
            if "/news/" not in it["link"]:
                continue
            stats["news_posts"] += 1
            r = record(it, at)
            if r is None:
                stats["not_notices"] += 1
                continue
            stats["notices"] += 1
            stats["undated"] += r["started_at"] is None
            old = recs.get(r["event_id"])
            if old and old["raw"].get("first_seen_at"):
                r["raw"]["first_seen_at"] = old["raw"]["first_seen_at"]
            else:
                r["raw"]["first_seen_at"] = at
            recs[r["event_id"]] = r
    stats["updates_linked"] = link_updates(recs)
    for r in recs.values():
        r["fetched_at"] = at
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    return out, stats


def safe_feed(body: bytes) -> bytes:
    """What data/raw keeps of a feed page: the parsed, scrubbed fields of each item, never the response."""
    keep = []
    for it in items(body):
        keep.append({"title": common.strip_house_numbers(it["title"]), "link": it["link"], "date": it["date"],
                     "guid": it["guid"], "text": post_text(it["html"])[:1500]})
    return json.dumps({"url": FEED, "items": keep}, ensure_ascii=False, indent=1).encode()


def fetch(backfill: bool) -> list[bytes]:
    out = []
    for n in range(1, 60 if backfill else LIVE_PAGES + 1):
        r = requests.get(FEED, params={"paged": n} if n > 1 else None, headers=HEADERS, timeout=(20, 120))
        if r.status_code == 404:
            break
        r.raise_for_status()
        out.append(r.content)
    save_raw(SOURCE_ID, b"[" + b",".join(safe_feed(b) for b in out) + b"]", "json")
    return out


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = (read_json(path, {}) or {}).get("records") or []
    try:
        if "--file" in argv:
            feeds = [Path(a).read_bytes() for a in argv[argv.index("--file") + 1:] if not a.startswith("--")]
        else:
            feeds = fetch("--backfill" in argv)
    except (requests.RequestException, OSError, ET.ParseError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    recs, stats = run(feeds, prev, now_iso())
    out = write_events(SOURCE_ID, recs, meta={
        "registry_ids": [SOURCE_ID], "url": INDEX, "feed": FEED, **stats,
        "credit": "KC Water, City of Kansas City, Missouri (news posts)",
        "caveat": ("KC Water publishes some of its overflows as news posts; no rule requiring the posts was found, so "
                   "an overflow with no post is not shown here. Times are KC Water's own; a crew's response time is "
                   "not the overflow's start."),
        "cadence": "every refresh (the first two feed pages); --backfill reads the whole archive"})
    print(f"{SOURCE_ID}: {len(recs)} records ({stats}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
