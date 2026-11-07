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
  - Status: advisory_active while the year of the box has not ended. DANR's own window is the calendar year, so the
    advisory's end is that year's 31 December: raw.expires_on carries it, and once the fetch is past it the record is
    advisory_lifted with ended_at that date (the authority's rule, quoted in raw.end_basis; no other end is written).
  - A lake that leaves the box before the year ends keeps its record with raw.gone_from_page_since and its status (the
    page gives no lifting); a page whose box cannot be found writes ok=False and the previous records stay.
  - No coordinates on the page: the record is placed by the lake's name (the status build's name matching).
  - Only the lake, county and date are read: the page carries no personal data (strip_personal runs on raw all the
    same).

Run from pipeline/:  python -m ingest.sd_danr_hab_advisories [--file saved.html]
"""
from __future__ import annotations

import html
import re
import sys
from datetime import date
from email.utils import parsedate_to_datetime
from pathlib import Path

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events

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


def build(page: str, fetched: str, previous: list[dict], source_updated: str | None = None) -> tuple[list[dict], dict]:
    year, lines = parse(page)
    today = fetched[:10]
    expires = f"{year}-12-31"
    records: dict[str, dict] = {}
    for x in lines:
        srid = f"{year}:{slug(x['lake'])}:{slug(x['county'])}"
        over = today > expires
        raw = {"lake": x["lake"], "county": x["county"], "date": x["date"], "line": x["line"], "box_year": year,
               "expires_on": expires, "end_basis": f"DANR's page: \"{RULE}\"",
               "date_note": "the date DANR lists beside the lake; the page does not say whether it is the sampling or "
                            "the issue date", "page_url": URL}
        perr = None if x["date"][:4] == str(year) else f"date {x['date']} outside the box's year {year}"
        records[srid] = event(
            source_id=SOURCE_ID, source_record_id=srid, event_type="hab_advisory",
            status="advisory_lifted" if over else "advisory_active",
            waterbody_text=x["lake"], started_at=x["date"], ended_at=expires if over else None, time_precision="day",
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
        if exp and today > exp and p.get("status") == "advisory_active":
            p["status"], p["ended_at"] = "advisory_lifted", exp
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
