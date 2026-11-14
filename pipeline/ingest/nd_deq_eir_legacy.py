"""North Dakota Department of Environmental Quality: General Environmental Incidents, historical (1975 to 2020), the
sewage rows -> data/build/events/nd-deq-eir-legacy.json

Source
  https://deq.nd.gov/FOIA/Spills/defaultarc.aspx/ (registry: nd-deq-eir-legacy-general; the trailing slash is part of
  the address DEQ links), an ASP.NET table of every General Environmental Incident report DEQ received from 1975 to
  2020 (4,452 records on 2026-11-14), fifteen rows a page, with a search box that searches every column but the dates.
  Columns: Incident ID (EIR#####), Date Reported, Date Incident, County, TwnRngSec, Latitude, Longitude, Contaminant,
  Volume, Units, Contained. No reporter, party or narrative column (the per-incident summary PDFs carry reporters'
  contact details and are never read). Reports since 2021 are in the state's unified spill system (HazConnect), whose
  public list refuses automated readers (a barrier in the register); DEQ did not migrate the archive into it.
  The archive is frozen: it is read at most once every REREAD_DAYS (the searches below, a few requests two seconds
  apart); between reads the previous records are carried unchanged.

What is read
  The search for each word in SEARCH_WORDS ("sewage", "sewer", "septic"; the search covers the Contaminant column),
  every result page. 2026-11-14: "sewage" 31 records, "sewer" 3, "septic" 3 (searches for "wastewater", "lagoon" and
  "effluent" were read once for the research: industrial and food-processing wastewater, and two plain "Wastewater"
  rows at a Traill County section that also holds a sugar factory, none of them read as sewage).
  A row is kept when its Contaminant names sewage, a sanitary sewer, a sewer or a septic system (SEWAGE) and not
  potable water (NOT_SEWAGE: "potable water out of septic truck"): 36 rows, 2003 to 2020.

Record rules
  - Key: the Incident ID. event_type plant_bypass when the contaminant says treated or effluent ("Treated sewage",
    "Mixture of treated and untreated domestic sewage", "Sanitary sewage effluent"), else sso; never unknown.
  - started_at: Date Incident, precision day; reported_at: Date Reported, precision day; no end (the table gives none;
    "Contained" is DEQ's containment flag, kept in raw.contained, never an end); status unknown. The archive is a
    record of the past: these reports are history, coloured by nothing today.
  - Clock: raw.time_zone from the county (pipeline/zones.py north_dakota_zone, 49 CFR 71.7(a)).
  - Volume: gallons as given; barrels (DEQ: "One barrel = 42 US gallons") converted, raw.volume_as_given keeps the
    figure; a blank volume is unknown, never zero.
  - Place: the row's point, rounded to 0.001 degree before anything is saved; a septic system's or on-site housing's
    row (PRIVATE_PLACE) keeps its county only (no point). The table names no receiving water: a report is placed from
    its point by the status build or listed with its county; nothing is geocoded.
  - Duplicates: two rows with the same incident day, point, contaminant and volume are one incident filed twice; the
    later Incident ID is duplicate_of the earlier (EIR2032 of EIR2031, 2013-08-31, Dunn County).
  - No operator: the table names no party, and a point near a city's plant is not its permit.
  - Privacy: only the columns above are read; the saved raw file holds the kept rows' safe columns only.

Run from pipeline/:  python -m ingest.nd_deq_eir_legacy [--dir saved_dir] [--force]
"""
from __future__ import annotations

import glob
import html
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

import zones
from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events

SOURCE_ID = "nd-deq-eir-legacy"
URL = "https://deq.nd.gov/FOIA/Spills/defaultarc.aspx/"
REPORTS_URL = "https://deq.nd.gov/WQ/4_Spill_Investigations/Reports.aspx"
AUTHORITY = "North Dakota Department of Environmental Quality (General Environmental Incidents, historical 1975-2020)"
SEARCH_WORDS = ("sewage", "sewer", "septic")
REREAD_DAYS = 30
COLUMNS = ("incident_id", "date_reported", "date_incident", "county", "twn_rng_sec", "latitude", "longitude",
           "contaminant", "volume", "units", "contained")
SEWAGE = re.compile(r"\bsewage\b|\bsanitary\s+sewer\b|\bsewer\b|\bseptic\b", re.I)
NOT_SEWAGE = re.compile(r"\bpotable\s+water\b", re.I)
TREATED = re.compile(r"\btreated\b|\beffluent\b", re.I)
PRIVATE_PLACE = re.compile(r"\bseptic\b|\bonsite\s+housing\b|\bresiden", re.I)
BARREL_GAL = 42


def parse_page(page: str) -> tuple[list[dict], int | None]:
    """(rows, the result's record count) of one table page."""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        tds = [html.unescape(re.sub(r"<[^>]+>", "", x)).replace("\xa0", " ").strip()
               for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
        if len(tds) >= len(COLUMNS) and re.match(r"^EIR\d+$", tds[0]):
            rows.append(dict(zip(COLUMNS, tds)))
    m = re.search(r"Records:\s*(?:<[^>]+>\s*)*([\d,]+)", page)
    return rows, (int(m.group(1).replace(",", "")) if m else None)


def _form(page: str) -> dict:
    return {n: html.unescape(v) for n, v in re.findall(r'name="(__[A-Z]+)"[^>]*value="([^"]*)"', page)}


def fetch_search(word: str, session: requests.Session) -> list[dict]:
    t = session.get(URL, timeout=(20, 120)).text
    time.sleep(2)
    t = session.post(URL, data={**_form(t), "TextBoxSearch": word, "ButtonSearch": "Search", "TextBoxPageIndex": ""},
                     timeout=(20, 120)).text
    rows, n = parse_page(t)
    pages = -(-(n or 0) // 15)
    for page in range(2, min(pages, 40) + 1):
        time.sleep(2)
        t = session.post(URL, data={**_form(t), "TextBoxSearch": word, "TextBoxPageIndex": str(page),
                                    "ButtonGotoPage": "Go"}, timeout=(20, 120)).text
        rows += parse_page(t)[0]
    if n is not None and len({r["incident_id"] for r in rows}) < n:
        raise ValueError(f"search {word!r}: {len(rows)} rows read of {n}")
    return rows


def _day(s: str) -> str | None:
    m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})$", (s or "").strip())
    return f"{m.group(3)}-{int(m.group(1)):02d}-{int(m.group(2)):02d}" if m else None


def _num(s: str) -> float | None:
    try:
        return float((s or "").replace(",", ""))
    except ValueError:
        return None


def keep(row: dict) -> bool:
    c = row.get("contaminant") or ""
    return bool(SEWAGE.search(c)) and not NOT_SEWAGE.search(c)


def safe_row(row: dict) -> dict:
    """The row as saved and kept in raw.row: the point rounded; a private place's point dropped."""
    out = {k: row.get(k) for k in COLUMNS}
    lat, lon = _num(row.get("latitude")), _num(row.get("longitude"))
    private = bool(PRIVATE_PLACE.search(row.get("contaminant") or ""))
    out["latitude"] = None if private or lat is None else round(lat, 3)
    out["longitude"] = None if private or lon is None else round(lon, 3)
    if private:
        out["twn_rng_sec"] = None
        out["point_withheld"] = "a septic system or on-site housing: the county only"
    return out


def record(row: dict, fetched: str) -> dict:
    r = safe_row(row)
    c = r["contaminant"] or ""
    et = "plant_bypass" if TREATED.search(c) else "sso"
    tz, basis = zones.north_dakota_zone(r["county"] or None)
    vol, unit = _num(r["volume"]), (r["units"] or "").strip().lower()
    gal = None
    if vol is not None and vol > 0:
        gal = vol * BARREL_GAL if unit.startswith("barrel") else vol if unit.startswith("gallon") else None
    raw = {"row": r, "state": "ND", "county": f"{r['county']} County" if r["county"] else None,
           "time_zone": tz, "time_zone_basis": basis, "contained": r["contained"] or None,
           "contained_note": "DEQ's containment flag; not an end time and not a statement about any water",
           "_type_basis": f"the contaminant as written: {c!r}",
           "archive_note": ("DEQ's archive of incident reports from 1975 to 2020; reports since 2021 are in the state's "
                            "unified spill system")}
    if r.get("point_withheld"):
        raw["point_withheld"] = r["point_withheld"]
    if vol is not None:
        raw["volume_as_given"] = f"{r['volume']} {r['units']}".strip()
    perr = None if _day(r["date_incident"]) else f"no incident date read from {r['date_incident']!r}"
    return event(
        source_id=SOURCE_ID, source_record_id=r["incident_id"], event_type=et, status="unknown",
        lat=r["latitude"], lon=r["longitude"], coord_source="source" if r["latitude"] is not None else None,
        coord_precision_m=100 if r["latitude"] is not None else None,
        started_at=_day(r["date_incident"]), time_precision="day", reported_at=_day(r["date_reported"]),
        fetched_at=fetched, material=c or None, volume_gal=int(round(gal)) if gal is not None else None,
        volume_text=raw.get("volume_as_given"), estimate_flag="unknown", authority=AUTHORITY, source_url=URL,
        raw=raw, parse_error=perr)


def build(rows: list[dict], fetched: str) -> tuple[list[dict], dict]:
    by_id: dict[str, dict] = {}
    for r in rows:
        by_id.setdefault(r["incident_id"], r)
    kept = [r for r in by_id.values() if keep(r)]
    recs = [record(r, fetched) for r in sorted(kept, key=lambda r: int(r["incident_id"][3:]))]
    first: dict[tuple, str] = {}
    for rec in recs:
        k = (rec["started_at"], rec["lat"], rec["lon"], (rec["material"] or "").lower(), rec["volume_text"])
        if k in first and rec["lat"] is not None:
            rec["duplicate_of"] = first[k]
            rec["raw"]["_duplicate_basis"] = ("the same incident day, point, contaminant and volume as an earlier "
                                              "Incident ID: one incident filed twice")
        else:
            first.setdefault(k, rec["event_id"])
    recs.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": ["nd-deq-eir-legacy-general"], "url": URL, "search_words": list(SEARCH_WORDS),
            "rows_read": len(by_id), "kept": len(recs),
            "dropped_not_sewage": sorted(r["incident_id"] for r in by_id.values() if not keep(r)),
            "types": {t: sum(1 for r in recs if r["event_type"] == t) for t in ("sso", "plant_bypass")},
            "rows_read_at": fetched, "frozen": "1975 to 2020; DEQ's reports since 2021 are in its unified spill system",
            "credit": "North Dakota Department of Environmental Quality, General Environmental Incidents - Historical",
            "caveat": ("DEQ's archive of incident reports from 1975 to 2020, the rows whose contaminant names sewage, a "
                       "sewer or a septic system. No end, no receiving water and no responsible party are given."),
            "time_basis": "Date Incident and Date Reported are dates; read in the county's zone (49 CFR 71.7(a))."}
    return recs, meta


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fetched = now_iso()
    prev = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    last = (prev.get("meta") or {}).get("rows_read_at")
    try:
        if "--dir" in argv:
            rows = []
            for f in sorted(glob.glob(str(Path(argv[argv.index("--dir") + 1]) / "search-*.html"))):
                rows += parse_page(Path(f).read_text(errors="replace"))[0]
        else:
            if last and "--force" not in argv and prev.get("ok") and \
                    datetime.now(timezone.utc) - datetime.fromisoformat(last.replace("Z", "+00:00")) < \
                    timedelta(days=REREAD_DAYS):
                write_events(SOURCE_ID, prev.get("records", []), meta=prev.get("meta"))
                print(f"{SOURCE_ID}: frozen archive read {last}; {len(prev.get('records', []))} records carried")
                return 0
            s = requests.Session()
            s.headers.update(HEADERS)
            rows = []
            for w in SEARCH_WORDS:
                rows += fetch_search(w, s)
                time.sleep(2)
            save_raw(SOURCE_ID, json.dumps([safe_row(r) for r in rows if keep(r)], indent=1), "json")
        recs, meta = build(rows, fetched)
        if not recs:
            raise ValueError("no sewage row read from the archive")
    except Exception as e:  # noqa: BLE001 (any failure keeps the previous records)
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {meta['rows_read']} rows read, {meta['kept']} sewage reports -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
