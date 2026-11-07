"""South Dakota DANR harmful algal bloom advisories (the list on DANR's HAB page).

Source
  https://danr.sd.gov/Conservation/WatershedProtection/HAB.aspx (registry: sd-danr-hab-advisories), South Dakota
  Department of Agriculture and Natural Resources, Watershed Protection Program. No key, no licence stated. The page
  opens with a box headed "Harmful Algal Bloom Advisories <year>" that lists each lake under advisory with its county
  and a date ("Twin Lakes (Spink County) 6/15/2026"), under DANR's rule, quoted on the page: "Harmful Algal Bloom
  Advisories occur when water quality test results indicate that high risk conditions exist for water recreators or
  there has been a confirmed report of symptoms of algal toxin exposure. Advisories expire at the end of the calendar
  year and apply to an entire lake/waterbody due to the likelihood that high risk conditions will persist or reoccur."
  On 2026-11-07 the box listed five lakes (dates 2026-06-15 to 2026-09-15). DANR's yearly advisory map layers stop at
  2024, so this list is the state's only current publication of its advisories (press releases aside).

Record rules
  - One hab_advisory record per lake line: waterbody_text the lake as written, raw.county its county, started_at the
    line's date (time_precision day; the page does not say whether it is the sampling or the issue date, so
    raw.date_note says so), source_record_id <year>:<lake slug>:<county slug> (stable while the line stays).
  - Status and end: DANR's own window is the calendar year ("Advisories expire at the end of the calendar year"), so
    every record's ended_at is that year's 31 December, the authority's end, quoted in raw.end_basis (review
    2026-11-07 P1-1: without it the status build ages an advisory out 14 days after its date). The record is
    advisory_active while the fetch is on or before that day and advisory_lifted after it; no other end is written.
  - A lake that leaves the box before the year ends keeps its record with raw.gone_from_page_since and its status (the
    page gives no lifting); a page whose box cannot be found writes ok=False and the previous records stay.
  - No coordinates on the page: the record is placed by the lake's name (the status build's name matching), with
    raw.placement_hint giving the lake, its county and the state, so a same-named lake in another county is not taken
    (research/sd/receiving-waters-missing.json lists the five lakes with their counties for the water batch).
  - Only the lake, county and date are read: the page carries no personal data (strip_personal runs on raw all the
    same).

Run from pipeline/:  python -m ingest.sd_danr_hab_advisories [--file saved.html]
"""
from __future__ import annotations

import html
import re
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from common import DATA_DIR, EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events

SOURCE_ID = "sd-danr-hab-advisories"
URL = "https://danr.sd.gov/Conservation/WatershedProtection/HAB.aspx"
AUTHORITY = "South Dakota Department of Agriculture and Natural Resources (harmful algal bloom advisories)"
RULE = ("Advisories expire at the end of the calendar year and apply to an entire lake/waterbody due to the likelihood "
        "that high risk conditions will persist or reoccur.")
HEADING = re.compile(r"Harmful Algal Bloom Advisories\s+(\d{4})", re.I)
LINE = re.compile(r"<strong>\s*(?P<lake>[^<(]+?)\s*\((?P<county>[^)<]+?)\)\s*</strong>\s*(?P<date>\d{1,2}/\d{1,2}/\d{4})",
                  re.I)


def slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", (s or "").lower())).strip("-")


def parse(page: str) -> tuple[int, list[dict]]:
    """(year, [{lake, county, date}]) from the advisory box; ValueError when the box is not on the page."""
    m = HEADING.search(page)
    if not m:
        raise ValueError("no 'Harmful Algal Bloom Advisories <year>' box on the page")
    year = int(m.group(1))
    box = page[m.end():]
    end = re.search(r'<h2 class="title">|Harmful Algal Blooms \(HABs\)</h2>', box)
    box = box[:end.start()] if end else box[:6000]
    out = []
    for x in LINE.finditer(box):
        mo, dy, yr = (int(v) for v in x.group("date").split("/"))
        out.append({"lake": html.unescape(x.group("lake")).strip(), "county": html.unescape(x.group("county")).strip(),
                    "date": date(yr, mo, dy).isoformat(), "line": re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ",
                                                                                          x.group(0))).strip()})
    return year, out


# The dates are South Dakota days: a county of the reference file (49 CFR 71.7(b)) keeps Mountain time, the rest
# Central. Stanley County is split (its Fort Pierre corner keeps Central time): a lake listed there is read in Mountain
# time, the later day's end. SOL 2026-11-07 wave 2 P1-1: the advisory ending December 31 runs to that day's end in
# its own zone, not New York's.
ZONE_FILE = DATA_DIR / "reference" / "sd-mountain-time-counties.json"
CENTRAL = "America/Chicago"


def county_zone(county: str | None) -> tuple[str, str]:
    """(IANA zone, basis) for a lake DANR lists in this county."""
    doc = read_json(ZONE_FILE, None) or {}
    name = re.sub(r"(?i)\s+county$", "", str(county or "")).strip().lower()
    cite = (doc.get("law") or {}).get("cite") or "49 CFR 71.7(b)"
    for c in (doc.get("counties") or []) + (doc.get("split_counties") or []):
        if re.sub(r"(?i)\s+county$", "", c.get("county") or "").strip().lower() == name and name:
            return doc.get("zone") or "America/Denver", f"{c['county']} keeps Mountain time ({cite})"
    return CENTRAL, (f"{county} County keeps Central time ({cite})" if county else
                     "no county listed: Central time, the state's eastern part")


def local_day(fetched: str, tz: str) -> str:
    """The calendar day (YYYY-MM-DD) in tz at the fetch time (UTC ISO)."""
    return datetime.fromisoformat(fetched.replace("Z", "+00:00")).astimezone(ZoneInfo(tz)).date().isoformat()


def build(page: str, fetched: str, previous: list[dict], source_updated: str | None = None) -> tuple[list[dict], dict]:
    year, lines = parse(page)
    expires = f"{year}-12-31"
    records: dict[str, dict] = {}
    for x in lines:
        srid = f"{year}:{slug(x['lake'])}:{slug(x['county'])}"
        tz, tz_basis = county_zone(x["county"])
        # the lake's own calendar day (fetched is UTC): December 31 lasts to its end in the lake's zone
        over = local_day(fetched, tz) > expires
        raw = {"lake": x["lake"], "county": x["county"], "date": x["date"], "line": x["line"], "box_year": year,
               "time_zone": tz, "time_zone_basis": tz_basis,
               "expires_on": expires, "end_basis": f"DANR's page: \"{RULE}\"",
               "date_note": "the date DANR lists beside the lake; the page does not say whether it is the sampling or "
                            "the issue date", "page_url": URL,
               "placement_hint": {"name": x["lake"], "county": x["county"], "state": "SD",
                                  "basis": "the county DANR lists beside the lake: a same-named lake elsewhere in the "
                                           "state is not this one"}}
        perr = None if x["date"][:4] == str(year) else f"date {x['date']} outside the box's year {year}"
        records[srid] = event(
            source_id=SOURCE_ID, source_record_id=srid, event_type="hab_advisory",
            status="advisory_lifted" if over else "advisory_active",
            waterbody_text=x["lake"], started_at=x["date"], ended_at=expires, time_precision="day",
            source_updated_at=source_updated, fetched_at=fetched, authority=AUTHORITY, advice_text=RULE,
            source_url=URL, raw=raw, parse_error=perr)
    kept = 0
    for p in previous:
        sid = p.get("source_record_id")
        if sid in records:
            continue
        p = dict(p)
        p["raw"] = {**(p.get("raw") or {}), "gone_from_page_since": (p.get("raw") or {}).get("gone_from_page_since")
                    or fetched}
        exp = p["raw"].get("expires_on")
        if exp:
            p["ended_at"] = exp
            tz = p["raw"].get("time_zone") or county_zone(p["raw"].get("county"))[0]
            if local_day(fetched, tz) > exp and p.get("status") == "advisory_active":
                p["status"] = "advisory_lifted"
        records[sid] = p
        kept += 1
    out = sorted(records.values(), key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "url": URL, "box_year": year, "on_page": len(lines),
            "kept_from_previous": kept, "advisory_active": sum(1 for r in out if r["status"] == "advisory_active"),
            "cadence": "page read every run; DANR updates the list when it issues an advisory"}
    return out, meta


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fetched = now_iso()
    updated = None
    try:
        if "--file" in argv:
            page = Path(argv[argv.index("--file") + 1]).read_text(errors="replace")
        else:
            r = requests.get(URL, headers=HEADERS, timeout=60)
            r.raise_for_status()
            page = r.text
            save_raw(SOURCE_ID, r.content, "html")
            if r.headers.get("Last-Modified"):
                updated = parsedate_to_datetime(r.headers["Last-Modified"]).strftime("%Y-%m-%dT%H:%M:%SZ")
        prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
        recs, meta = build(page, fetched, prev, updated)
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records)
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {meta['on_page']} on the page ({meta['box_year']}), {len(recs)} records, "
          f"{meta['advisory_active']} active -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
