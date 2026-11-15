"""City of Leavenworth's Sanitary Sewer Overflow Transparency Reports (Kansas): the City's own page for each sewer
overflow, as dated sewage reports.

Source
  https://www.leavenworthks.gov/publicworks/page/sanitary-sewer-overflow-transparency-report (registry:
  ks-leavenworth-sso-transparency): an index of yearly pages (2020 to 2026), each listing that year's overflow pages
  ("Sanitary Sewer Overflow Reported on April 27, 2026 1234 Example St"). Each overflow page is a short narrative by
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
from ingest.mo_kc_water_news import DATE, _month, date_positions, migrate_water_text, safe_text, sentences, water_text, waters

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


def record_id(path: str) -> str:
    """The page's path name with every number dropped but a year and a day after its month
    ("sanitary-sewer-overflow-reported-april-27-2026-evergreen-st"): the identifier carries no house or block number.
    Idempotent, so an identifier made by an earlier version maps to the same one (re-review P1-8)."""
    toks = path.rstrip("/").rsplit("/", 1)[-1].split("-")
    # a number is kept only in a date position: a year-shaped house number is dropped too (verification P1-4); a
    # page's posting stamp ("-p202604271530", added where two pages share an identifier) is kept
    dated = date_positions(toks)
    return "-".join(t for i, t in enumerate(toks) if not t.isdigit() or i in dated)


# raw fields an earlier version saved that the records no longer carry
FORBIDDEN_RAW = ("page_text", "text", "narrative")


def migrate(prev: list[dict]) -> dict[str, dict]:
    """Earlier saves brought to the current rules at the next read (re-review P1-8, P1-9): one record per page under
    the canonical identifier (an identifier with a house number maps onto it; the newer read wins, the first sighting
    is kept), the page address that carries a house number replaced by the City's index page as the citation, no
    page text kept."""
    out: dict[str, dict] = {}
    for r in sorted(prev, key=lambda x: x.get("fetched_at") or ""):
        rid = record_id(r.get("source_record_id") or "")
        r["source_record_id"], r["event_id"] = rid, f"{SOURCE_ID}:{rid}"
        raw = r.setdefault("raw", {})
        for k in FORBIDDEN_RAW:
            raw.pop(k, None)
        url = r.get("source_url") or ""
        if url.startswith(BASE + "/publicworks/page/sanitary-sewer-overflow"):
            r["source_url"] = raw.get("cited_page") or INDEX
        raw.setdefault("cited_page", r["source_url"])
        migrate_water_text(r)
        # every retained free-text field through the same scrub as a fresh read, for a record whose page is not read
        # again (verification P1-4)
        raw["title"] = safe_text(raw.get("title"))
        r["advice_text"] = safe_text(r.get("advice_text"))
        if r.get("outfall_name"):
            r["outfall_name"] = re.sub(r"\[house number removed\]\s*", "", safe_text(r["outfall_name"])).strip(" .-") \
                or None
        old = out.get(r["event_id"])
        if old:
            firsts = [x for x in (old["raw"].get("first_seen_at"), raw.get("first_seen_at")) if x]
            raw["first_seen_at"] = min(firsts) if firsts else None
        out[r["event_id"]] = r
    return out


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


def end_day(s: str, w: re.Match, day: date) -> tuple[date | None, bool]:
    """(the end clause's date, whether the sentence gave one): a date after the stop verb first ("stopped May 29 at 4
    p.m."), else the one date before it in the same sentence ("On May 29, 2020, the overflow stopped at 4 p.m."); a
    sentence with several dates before the verb and none after is ambiguous (None, True: no end). A date without a year
    takes the report day's year, or the next when it would fall before the report day (December 31 to January 1)."""
    after = list(DATE.finditer(s[w.start():]))
    before = [m for m in DATE.finditer(s[:w.start()])]
    if after:
        dm = after[0]
    elif len(before) == 1:
        dm = before[0]
    elif len(before) > 1:
        return None, True
    else:
        return day, False
    try:
        y = int(dm.group(3)) if dm.group(3) else day.year
        d = date(y, _month(dm.group(1)), int(dm.group(2)))
        if not dm.group(3) and d < day:
            d = date(y + 1, d.month, d.day)
        return d, True
    except (ValueError, StopIteration):
        return None, True


def record(path: str, h: str, at: str, cite: str | None = None) -> dict:
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
            eday, dm = end_day(s, w, day)            # the end clause's own date, before or after the verb (P2-3)
            if eday is None:
                break                                # several dates and none is the end's: no end, never a guess
            e = datetime(eday.year, eday.month, eday.day, h_, mi, tzinfo=TZ)
            if not dm and re.search(r"next day|following day|next morning", s, re.I):
                e += timedelta(days=1)
            elif not dm and prec == "minute" and e < datetime.fromisoformat(start):
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
           "title": safe_text(title), "start_kind": kind,
           "start_is_upper_bound": kind in ("notified", "found", "arrived", "stated", None),
           "start_basis": ("the day in the page's title; the page gives no clock time it can be read by" if prec == "day"
                           else f"the time the City's page gives ({kind}); the overflow began at or before it"),
           "waters_named": ws, "reached_water": True if ws or re.search(r"\bcreek\b|\bstream\b", clean, re.I) else None,
           "volume_basis": "the City's estimate" if v else None, "provenance": "operator",
           "_placement": "named_water_only", "cited_page": cite or INDEX,
           "citation_note": ("the City's transparency report page that lists this overflow; the overflow's own page "
                             "address carries a street address, so it is not kept"),
           "time_basis": "the City's clock times, read as Central time (America/Chicago)"}
    if end:
        raw["ended_at_precision"], raw["end_basis"] = "minute", end_basis
    if prison:
        raw["system_note"] = ("the page reports an overflow at a lift station serving the federal prison, which the "
                                "page says is containing it; not assigned to the City")
    return event(
        source_id=SOURCE_ID, source_record_id=record_id(path), event_type="sso", status="unknown",
        discharger_id=None if prison else DISCHARGER_ID, discharger_name=None if prison else DISCHARGER,
        outfall_name=place_of(title), waterbody_text=water_text(ws), started_at=start,
        time_precision=prec if start else None, ended_at=end, published_at=pub, reported_at=None, fetched_at=at,
        material="sewage", volume_gal=vol, volume_text=v.group(0) if v else None, estimate_flag=flag,
        authority=AUTHORITY, advice_text=safe_text(adv.group(0).strip()) if adv else None, source_url=cite or INDEX,
        parse_error=None if day else "no date in the page's title or text", raw=raw)


def run(pages: dict[str, str], prev: list[dict], at: str,
        cites: dict[str, str] | None = None) -> tuple[list[dict], dict]:
    """cites: page path -> the year page that lists it (the citation without a street address)."""
    recs = migrate(prev)
    stats = {"pages": 0, "undated": 0}
    read = [record(path, h, at, (cites or {}).get(path)) for path, h in sorted(pages.items())]
    groups: dict[str, list[dict]] = {}
    for r in read:
        groups.setdefault(r["event_id"], []).append(r)
    for base, rs in groups.items():
        if len(rs) < 2:
            continue
        # distinct pages whose identifiers match once the house numbers are dropped (two overflows on one street on
        # one day; verification P2-3): each gets its posting stamp, then an ordinal if that is shared too; the earlier
        # save under the shared identifier is replaced by them (its first sighting kept)
        legacy = recs.pop(base, None)
        seen: dict[str, int] = {}
        for r in rs:
            stamp = re.sub(r"\D", "", r.get("published_at") or "")[:12]
            rid = f"{r['source_record_id']}-p{stamp}" if stamp else r["source_record_id"]
            seen[rid] = seen.get(rid, 0) + 1
            if seen[rid] > 1 or not stamp:
                rid = f"{rid}-n{seen[rid]}"
            r["source_record_id"], r["event_id"] = rid, f"{SOURCE_ID}:{rid}"
            if legacy:
                r["raw"]["first_seen_at"] = (legacy.get("raw") or {}).get("first_seen_at")
    for r in read:
        stats["pages"] += 1
        stats["undated"] += r["started_at"] is None
        old = recs.get(r["event_id"])
        r["raw"]["first_seen_at"] = (old or {}).get("raw", {}).get("first_seen_at") or r["raw"].get("first_seen_at") or at
        recs[r["event_id"]] = r
    for r in recs.values():
        r["fetched_at"] = at
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    return out, stats


def fetch(prev: list[dict], backfill: bool) -> tuple[dict[str, str], list[str]]:
    idx = requests.get(INDEX, headers=HEADERS, timeout=(20, 120))
    idx.raise_for_status()
    years = sorted(set(YEAR_LINK.findall(idx.text)), key=lambda x: x[1], reverse=True)
    if not backfill:
        years = years[:2]
    paths: list[str] = []
    cites: dict[str, str] = {}
    for ypath, _ in years:
        y = requests.get(BASE + ypath, headers=HEADERS, timeout=(20, 120))
        y.raise_for_status()
        found = [p for p in EVENT_LINK.findall(y.text) if "transparency-report" not in p or "reported" in p or
                 re.search(r"overflow-\d", p) or "kickapoo" in p]
        paths += found
        for p in found:
            cites.setdefault(p, BASE + ypath)
    pages = {}
    for p in dict.fromkeys(paths):
        # the last two years' pages are read again each run, so a page the City corrects is read again
        r = requests.get(BASE + p, headers=HEADERS, timeout=(20, 120))
        r.raise_for_status()                          # a refused page is a failed run, never an empty one
        pages[p] = r.text
    return pages, [y for y, _ in years], cites


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = (read_json(path, {}) or {}).get("records") or []
    try:
        if "--dir" in argv:
            d = Path(argv[argv.index("--dir") + 1])
            pages = {f"/publicworks/page/{f.stem}": f.read_text() for f in sorted(d.glob("*.html"))}
            years, cites = [], {}
        else:
            pages, years, cites = fetch(prev, "--backfill" in argv)
        recs, stats = run(pages, prev, now_iso(), cites)
    except (requests.RequestException, OSError, ValueError, KeyError, IndexError, TypeError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
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
