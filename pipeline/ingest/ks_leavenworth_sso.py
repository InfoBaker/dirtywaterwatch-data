"""City of Leavenworth's Sanitary Sewer Overflow Transparency Reports (Kansas): the City's own page for each sewer
overflow, as dated sewage reports.

Source
  https://www.leavenworthks.gov/publicworks/page/sanitary-sewer-overflow-transparency-report (registry:
  ks-leavenworth-sso-transparency): an index of yearly pages (2020 to 2026), each listing that year's overflow pages
  ("Sanitary Sewer Overflow Reported on April 27, 2026 570 Evergreen St"). Each overflow page is a short narrative by
  the City's Water Pollution Control division: when staff were told or found it, the manhole or lift station, the
  stop time, the estimated gallons, where it went and the City's advice. The site answered the identified client on
  2026-11-14 (it answered 403 to plain clients on 2026-11-03). The hourly run reads the index, the current and last
  year's pages and any overflow page not read before; `--backfill` reads every year. Read 2026-11-14: 7 yearly pages,
  28 overflow pages (2020: 6, 2021: 2, 2022: 6, 2023: 7, 2024: 3, 2025: 2, 2026: 2). The City presents them as a
  transparency practice: no Kansas rule requires them (K.A.R. 28-16-27 sends overflows to KDHE only).

Record rules
  - One record per overflow page (source_record_id the page's path name). event_type "sso" (a collection-system
    overflow, a lift station's included); status unknown: the City's advice ("stay away from the creek water until
    testing is done and signs are removed") has no date and is kept as advice_text, never turned into an end.
  - Times (America/Chicago; Leavenworth County keeps Central time): the day is the title's date (the text's first date
    when the title has none). The first clock time with "a.m." or "p.m." in the text is the record's start, and
    raw.start_kind says what it marks: "notified" (staff were told: the overflow began at or before it), "found",
    "arrived", or "stated"; a time with no a.m. or p.m. ("Around 8:30 on the 27 of April") is not read and the record is
    dated to the day. "Ended at", "stopped ... at" or "ending bypass at" with a clock time is the end
    (raw.ended_at_precision minute). A "Posted" line, where a page has one, is published_at.
  - Volume: "estimated N gallons" (estimated).
  - Water: a named creek or river the text says the sewage entered, ran or flowed into (Three-Mile Creek, Five-Mile
    Creek, Seven-Mile Creek); "the creek" with no name is kept as raw.reached_water True and placed on no water.
  - Operator: the City of Leavenworth (KS0036366's permittee); a page about another system's lift station (the federal
    prison's) names that system in raw.system_note and is not assigned to the City.
  - Place: the street block of the title with its house number dropped (outfall_name); raw.county Leavenworth County.

Privacy: the pages name streets and, once, a facility's telephone number; house numbers and telephone numbers are
dropped before anything is stored (common.strip_house_numbers, common.scrub_text). data/raw keeps the parsed safe fields.
Run from pipeline/:  python -m ingest.ks_leavenworth_sso [--backfill] [--dir saved_pages/]
"""
from __future__ import annotations

import html
import json
import re
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import common
from common import HEADERS, event, now_iso, read_json, save_raw, write_events
from ingest.mo_kc_water_news import DATE, _month, sentences, waters

SOURCE_ID = "ks-leavenworth-sso-transparency"
BASE = "https://www.leavenworthks.gov"
INDEX = f"{BASE}/publicworks/page/sanitary-sewer-overflow-transparency-report"
TZ = ZoneInfo("America/Chicago")
AUTHORITY = "City of Leavenworth, Water Pollution Control (Sanitary Sewer Overflow Transparency Report)"
DISCHARGER_ID = "ks-leavenworth"
DISCHARGER = "City of Leavenworth"
YEAR_LINK = re.compile(r'href="(/publicworks/page/(20\d\d)-sanitary-sewer-overflow-transparency-reports?(?:-\d)?)"')
EVENT_LINK = re.compile(r'href="(/publicworks/page/sanitary-sewer-overflow-[^"]+)"')
AMPM = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(a|p)\.?\s*m\b\.?", re.I)
ADVICE = re.compile(r"[^.]*\b(?:stay (?:away from|out of)|avoid)\b[^.]*\.", re.I)
POSTED = re.compile(r"Posted\s+([A-Z][a-z]+)\.?\s*(\d{1,2}),\s*(\d{4})\s+at\s+(\d{1,2}):(\d{2})\s*([ap])\.?m", re.I)


def clock(m: re.Match) -> tuple[int, int]:
    """(hour, minute) of an AMPM match."""
    return int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0), int(m.group(2) or 0)


def page_text(h: str) -> tuple[str, str]:
    """(title, the page's narrative) from an overflow page."""
    m = re.search(r'<h1 id="page-title">(.*?)</h1>', h, re.S)
    title = html.unescape(re.sub(r"<[^>]+>", "", m.group(1))).strip() if m else ""
    i = h.find('<div class="region region-content">')
    j = h.find('<ul class="menu jquerymenu">', i if i >= 0 else 0)
    body = h[i:j] if i >= 0 and j > i else h
    body = re.sub(r"<script.*?</script>|<style.*?</style>", " ", body, flags=re.S)
    t = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", body))).strip()
    t = re.split(r"Share/Save through Social Media", t)[0]
    if t.startswith(title):
        t = t[len(title):].strip()
    return title, t


def title_day(title: str) -> date | None:
    m = DATE.search(title)
    if not m or not m.group(3):
        return None
    try:
        return date(int(m.group(3)), _month(m.group(1)), int(m.group(2)))
    except (ValueError, StopIteration):
        return None


def place_of(title: str) -> str | None:
    t = re.sub(r"(?i)transparency report", "", title)
    m = re.search(r"\b(?:at|in the|20\d\d)\s+((?:\d+\s+(?:and\s+\d+\s+)?)?[A-Z0-9][\w .'-]*?)\s*(?:reported\b.*)?$", t)
    if not m:
        m = re.search(r"Overflow:\s*(.+?)\s*-", t)
    if not m:
        return None
    s = common.strip_house_numbers(m.group(1)).strip(" .-")
    s = re.sub(r"\[house number removed\]\s*", "", s)
    s = re.sub(r"\b\d+\s+(?!blocks?\b)", "", s)          # "151 Walnut Creek", "1300 Sanders": a number not a block's
    return re.sub(r"\s+", " ", s).strip(" .-") or None


def record(path: str, h: str, at: str) -> dict:
    title, text = page_text(h)
    clean = common.scrub_text(common.strip_house_numbers(text))
    day = title_day(title)
    if day is None:
        m = DATE.search(text)
        day = title_day(m.group(0)) if m and m.group(3) else None
    ss = sentences(clean)
    start, prec, kind = (day.isoformat() if day else None), "day", None
    for s in ss[:3]:
        if re.search(r"\b(?:ended|stopped|stopping|ceased)\b", s, re.I):
            continue                                   # the stop time is never the start
        tm = AMPM.search(s)
        if tm and day:
            h_, mi = clock(tm)
            start = datetime(day.year, day.month, day.day, h_, mi, tzinfo=TZ).isoformat()
            prec = "minute"
            kind = ("notified" if re.search(r"notified|informed|received a call|contacted|call", s, re.I) else
                    "found" if re.search(r"notic|found|discover|could be seen", s, re.I) else
                    "arrived" if re.search(r"arrived", s, re.I) else "stated")
            break
    end, end_basis = None, None
    for s in ss:
        if not re.search(r"\b(?:ended|stopped|stopping|ending bypass|ceased)\b", s, re.I):
            continue
        w = re.search(r"\b(?:ended|stopped|stopping|ending|ceased)\b", s, re.I)
        tm = next((m for m in AMPM.finditer(s) if m.start() > w.start()), None)
        if tm and day:
            h_, mi = clock(tm)
            e = datetime(day.year, day.month, day.day, h_, mi, tzinfo=TZ)
            if prec == "minute" and e < datetime.fromisoformat(start):
                e += timedelta(days=1)
            end, end_basis = e.isoformat(), "the stop time the City's page gives"
        break
    v = re.search(r"([\d,]+)\s*gallons", clean)
    vol, flag = (common.parse_volume_gal(v.group(1))[0], "estimated") if v else (None, "unknown")
    ws = waters(clean)
    adv = ADVICE.search(clean)
    posted = POSTED.search(h)
    pub = None
    if posted:
        try:
            hh = int(posted.group(4)) % 12 + (12 if posted.group(6).lower() == "p" else 0)
            pd = datetime(int(posted.group(3)), _month(posted.group(1)), int(posted.group(2)), hh, int(posted.group(5)),
                          tzinfo=TZ)
            pub = pd.isoformat()
        except (ValueError, StopIteration):
            pub = None
    prison = bool(re.search(r"Bureau of Prisons|\bBOP\b", clean))
    raw = {"state": "KS", "time_zone": "America/Chicago", "county": "Leavenworth County",
           "title": common.strip_house_numbers(title), "page_text": clean[:1500], "start_kind": kind,
           "start_is_upper_bound": kind in ("notified", "found", "arrived", "stated", None),
           "start_basis": ("the day in the page's title; the page gives no clock time it can be read by" if prec == "day"
                           else f"the time the City's page gives ({kind}); the overflow began at or before it"),
           "waters_named": ws, "reached_water": True if ws or re.search(r"\bcreek\b|\bstream\b", clean, re.I) else None,
           "volume_basis": "the City's estimate" if v else None, "provenance": "operator",
           "time_basis": "the City's clock times, read as Central time (America/Chicago)"}
    if end:
        raw["ended_at_precision"], raw["end_basis"] = "minute", end_basis
    if prison:
        raw["system_note"] = ("the page reports an overflow at a lift station serving the federal prison, which the "
                                "page says is containing it; not assigned to the City")
    return event(
        source_id=SOURCE_ID, source_record_id=path.rstrip("/").rsplit("/", 1)[-1], event_type="sso", status="unknown",
        discharger_id=None if prison else DISCHARGER_ID, discharger_name=None if prison else DISCHARGER,
        outfall_name=place_of(title), waterbody_text=ws[0] if ws else None, started_at=start,
        time_precision=prec if start else None, ended_at=end, published_at=pub, reported_at=None, fetched_at=at,
        material="sewage", volume_gal=vol, volume_text=v.group(0) if v else None, estimate_flag=flag,
        authority=AUTHORITY, advice_text=adv.group(0).strip() if adv else None, source_url=BASE + path,
        parse_error=None if day else "no date in the page's title or text", raw=raw)


def run(pages: dict[str, str], prev: list[dict], at: str) -> tuple[list[dict], dict]:
    recs = {r["event_id"]: r for r in prev}
    stats = {"pages": 0, "undated": 0}
    for path, h in sorted(pages.items()):
        r = record(path, h, at)
        stats["pages"] += 1
        stats["undated"] += r["started_at"] is None
        old = recs.get(r["event_id"])
        r["raw"]["first_seen_at"] = (old or {}).get("raw", {}).get("first_seen_at") or at
        recs[r["event_id"]] = r
    for r in recs.values():
        r["fetched_at"] = at
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    return out, stats


def fetch(prev: list[dict], backfill: bool) -> tuple[dict[str, str], list[str]]:
    seen = {r["source_url"].replace(BASE, "") for r in prev}
    idx = requests.get(INDEX, headers=HEADERS, timeout=(20, 120))
    idx.raise_for_status()
    years = sorted(set(YEAR_LINK.findall(idx.text)), key=lambda x: x[1], reverse=True)
    if not backfill:
        years = years[:2]
    paths: list[str] = []
    for ypath, _ in years:
        y = requests.get(BASE + ypath, headers=HEADERS, timeout=(20, 120))
        y.raise_for_status()
        paths += [p for p in EVENT_LINK.findall(y.text) if "transparency-report" not in p or "reported" in p or
                  re.search(r"overflow-\d", p) or "kickapoo" in p]
    pages = {}
    for p in dict.fromkeys(paths):
        if p in seen and not backfill:
            continue
        r = requests.get(BASE + p, headers=HEADERS, timeout=(20, 120))
        if r.ok:
            pages[p] = r.text
    return pages, [y for y, _ in years]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = (read_json(path, {}) or {}).get("records") or []
    try:
        if "--dir" in argv:
            d = Path(argv[argv.index("--dir") + 1])
            pages = {f"/publicworks/page/{f.stem}": f.read_text() for f in sorted(d.glob("*.html"))}
            years = []
        else:
            pages, years = fetch(prev, "--backfill" in argv)
    except (requests.RequestException, OSError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    recs, stats = run(pages, prev, now_iso())
    save_raw(SOURCE_ID, json.dumps([{k: r.get(k) for k in ("source_url", "started_at", "ended_at", "volume_gal",
                                                           "waterbody_text", "outfall_name")} | {"title": r["raw"]["title"]}
                                    for r in recs], ensure_ascii=False, indent=1), "json")
    out = write_events(SOURCE_ID, recs, meta={
        "registry_ids": [SOURCE_ID], "url": INDEX, **stats, "year_pages_read": years,
        "credit": "City of Leavenworth, Kansas, Water Pollution Control",
        "caveat": ("The City's own reports of its sewer overflows, published as a transparency practice; dated to the "
                   "time staff were told or found the overflow. The City's advice to stay away from the creek holds "
                   "until its tests and signs say otherwise, a time it does not publish."),
        "cadence": "every refresh (the index, the last two years' pages and any new overflow page)"})
    print(f"{SOURCE_ID}: {len(recs)} records ({stats}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
