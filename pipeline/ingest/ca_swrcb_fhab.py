"""California freshwater harmful algal bloom reports (FHAB) -> data/build/events/ca-swrcb-fhab.json

Source
  State Water Resources Control Board, Freshwater and Estuarine Harmful Algal Bloom (FHAB) program, "Surface Water -
  Freshwater Harmful Algal Blooms" on data.ca.gov (package surface-water-freshwater-harmful-algal-blooms), resource "FHAB
  Bloom Reports" (c6a36b91-ad38-4611-8750-87ee99e497dd; CKAN datastore, about 3,700 rows, one per bloom report and
  advisory, refreshed daily). Licence: public domain (data.ca.gov "Other (Public Domain)"). Credit "California State
  Water Resources Control Board, FHAB Bloom Reports (data.ca.gov)". The map is mywaterquality.ca.gov/habs.
  Advisory levels are the California Cyanobacteria and Harmful Algal Bloom Network's trigger levels (Caution, Warning,
  Danger) and the algal mat alert sign, recommended by the FHAB program or the water body's manager.

What is read (privacy)
  Only FIELDS are asked for (datastore `fields`): the report's id, type and dates, the water body, landmark, county,
  point, texture, the advisory's id, level, dates and detail, and the case's status and end. Never asked for: the
  reporter's management-organization text, the response author (Response_Update_By) and the case lead (Case_Lead),
  which name people. The landmark (typed by the reporter) passes common.scrub_text and loses street house numbers;
  common.strip_personal runs on every raw (in event()). tests/test_ca_swrcb_fhab.py proves a personal field never
  reaches a record.

Records (event_type hab_advisory: blooms, the plum category, never a sewage colour)
  - Key: Bloom_Report_ID and Advisory_ID (a report linked to several advisories is one row per advisory).
  - A report with an advisory level (ADVISORY_LEVELS): started_at = AdvisoryStartDate (else the advisory's date, else
    the observation date), day precision. AdvisoryEndDate given -> advisory_lifted at that date. No end and the FHAB
    case closed with a case end date -> advisory_lifted at the case end (raw._end_basis says the end is the case's);
    otherwise advisory_active, with source_updated_at the latest of the last field sample, the advisory date and the
    report date: the status build stops colouring an advisory 14 days after it was last confirmed.
  - A report with no advisory level whose case is open (or not yet assigned) and that was created in the last 14
    days: status unknown (a bloom reported, not yet assessed), started_at the observation date.
  - Every other report (no advisory recommended: none, testing below the posting triggers, general awareness, a
    de-posting) is left out and counted in meta.left_out.
  - waterbody_text: the official water body name, else the name as reported; outfall_name: the landmark; point as
    given (coord_source source).

Reading (what each run costs): one package_show (about 10 KB) each hour; the table (about 3 MB with these fields) only
when its last_modified changed, about once a day. Every report is rebuilt each time (no window: the table is small).
Run from pipeline/:  python -m ingest.ca_swrcb_fhab [--file saved.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

import requests

from common import (BUILD_DIR, EVENTS_DIR, HEADERS, event, now_iso, path_notes_to_meta, read_json, scrub_text,
                    strip_house_numbers, write_events, write_json)
from ingest import ca_datagov

SOURCE_ID = "ca-swrcb-fhab"
PACKAGE = "surface-water-freshwater-harmful-algal-blooms"
RESOURCE = "c6a36b91-ad38-4611-8750-87ee99e497dd"
PAGE = "https://data.ca.gov/dataset/surface-water-freshwater-harmful-algal-blooms"
MAP = "https://mywaterquality.ca.gov/habs/"
STATE_FILE = BUILD_DIR / "ca-swrcb-fhab-state.json"
AUTHORITY = "California State Water Resources Control Board (FHAB program)"
CREDIT = "California State Water Resources Control Board, FHAB Bloom Reports (data.ca.gov)"
FIELDS = ["Bloom_Report_ID", "Report_Type", "Bloom_Date_Created", "Water_Body_Name", "Official_Water_Body_Name",
          "Landmark", "County", "Regional_Water_Board", "Bloom_Latitude", "Bloom_Longitude", "Observation_Date",
          "Bloom_Texture", "Water_Body_Type", "Advisory_ID", "Advisory_Recommended", "Advisory_Date",
          "AdvisoryStartDate", "AdvisoryEndDate", "AdvisoryDetail", "Advisory_Date_of_Recommendation", "Case_ID",
          "Case_Status", "Case_End_Date", "Last_Field_Result_Sample_Date"]
ADVISORY_LEVELS = {"caution": "Caution", "warning": "Warning", "danger": "Danger",
                   "algal mat alert sign": "Algal mat alert sign"}
NEW_REPORT_DAYS = 14
BOUNDS = (-124.6, 32.4, -114.0, 42.1)
RULES_VERSION = 1          # a run whose table is unchanged still rebuilds the records when this changes


def clean(v) -> str:
    return " ".join(str(v if v is not None else "").split())


def day(v) -> str | None:
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", clean(v))
    return m.group(1) if m else None


def fnum(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def level(row: dict) -> str | None:
    for part in clean(row.get("Advisory_Recommended")).split(";"):
        lv = ADVISORY_LEVELS.get(part.strip().lower())
        if lv:
            return lv
    return None


def build_record(row: dict, fetched_at: str) -> dict | tuple[str, str]:
    a = {k: row.get(k) for k in FIELDS}
    if a.get("Landmark"):
        a["Landmark"] = strip_house_numbers(scrub_text(clean(a["Landmark"])), street_word_only=True)
    rid, aid = clean(a.get("Bloom_Report_ID")), clean(a.get("Advisory_ID"))
    rid = rid.split(".")[0]
    aid = aid.split(".")[0] if aid else ""
    key = f"{rid}-{aid}" if aid else rid
    raw = {**a, "_first_seen_at": fetched_at}
    lv = level(a)
    fetched = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
    created = day(a.get("Bloom_Date_Created"))
    case_open = clean(a.get("Case_Status")).lower() in ("", "open", "ongoing", "re-opened")
    if lv:
        start = day(a.get("AdvisoryStartDate")) or day(a.get("Advisory_Date")) or day(a.get("Observation_Date"))
        end = day(a.get("AdvisoryEndDate"))
        raw["advisory_level"] = lv
        if end and start and end < start:
            raw["_end_not_used"] = f"the advisory end ({end}) is before its start"
            end = None
        if end:
            status = "advisory_lifted"
        elif not case_open and day(a.get("Case_End_Date")):
            end, status = day(a.get("Case_End_Date")), "advisory_lifted"
            raw["_end_basis"] = "the advisory gives no end date; the FHAB case it belongs to was closed on this date"
        else:
            status = "advisory_active"
        advice = f"{lv} advisory for cyanobacteria (harmful algal bloom), as recommended in the FHAB report"
    elif case_open and created and created >= (fetched - timedelta(days=NEW_REPORT_DAYS)).date().isoformat():
        start, end, status = day(a.get("Observation_Date")) or created, None, "unknown"
        raw["_basis"] = "a bloom reported and not yet assessed: no advisory has been recommended"
        advice = None
    else:
        return ("left out", "no advisory recommended")
    updated = max([d for d in (day(a.get("Last_Field_Result_Sample_Date")), day(a.get("Advisory_Date")), created,
                               day(a.get("Advisory_Date_of_Recommendation"))) if d], default=None)
    lat, lon = fnum(a.get("Bloom_Latitude")), fnum(a.get("Bloom_Longitude"))
    if lat is not None and not (BOUNDS[1] <= lat <= BOUNDS[3] and BOUNDS[0] <= (lon or 0) <= BOUNDS[2]):
        raw["_coords_rejected"] = f"the point ({lat}, {lon}) lies outside California"
        lat = lon = None
    water = clean(a.get("Official_Water_Body_Name")) or clean(a.get("Water_Body_Name")) or None
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="hab_advisory", status=status,
        outfall_name=clean(a.get("Landmark")) or None, waterbody_text=water, lat=lat, lon=lon,
        coord_source="source" if lat is not None else None, started_at=start, ended_at=end,
        time_precision="day" if (start or end) else None, reported_at=created, published_at=None,
        source_updated_at=updated, fetched_at=fetched_at, authority=AUTHORITY, advice_text=advice,
        source_url=f"https://data.ca.gov/dataset/{PACKAGE}/resource/{RESOURCE}", raw=raw)


def build(rows: list[dict], fetched_at: str) -> tuple[list[dict], dict]:
    recs, left, seen = [], Counter(), set()
    for row in rows:
        r = build_record(row, fetched_at)
        if isinstance(r, tuple):
            left[r[1]] += 1
            continue
        if r["event_id"] in seen:
            continue
        seen.add(r["event_id"])
        recs.append(r)
    recs.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats = {"rows_read": len(rows), "by_status": dict(Counter(r["status"] for r in recs)),
             "by_level": dict(Counter((r.get("raw") or {}).get("advisory_level") or "not assessed" for r in recs)),
             "left_out": dict(left)}
    return recs, stats


def main(argv=None) -> int:
    from build import redact
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read a saved datastore_search answer (or a list of rows) instead of data.ca.gov")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    state = read_json(STATE_FILE, {}) or {}
    prev = read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        if args.file:
            d = json.loads(Path(args.file).read_text())
            rows = d if isinstance(d, list) else (d.get("result") or {}).get("records") or d.get("records") or []
            rows = [{k: x.get(k) for k in FIELDS} for x in rows]
            modified = None
        else:
            modified = ca_datagov.resource_modified(sess, PACKAGE, RESOURCE)
            if modified and modified == state.get("modified") and prev.get("records") \
                    and state.get("rules") == RULES_VERSION:
                meta = {**(prev.get("meta") or {}), "checked_at": fetched_at}
                write_events(SOURCE_ID, prev["records"], ok=True, error=None, meta=meta)
                print(f"{SOURCE_ID}: table unchanged since {modified}; {len(prev['records'])} records kept")
                return 0
            rows = ca_datagov.search(sess, RESOURCE, FIELDS)
        if not rows:
            raise RuntimeError("the table answered no rows")
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    recs, stats = build(rows, fetched_at)
    old = {r["event_id"]: r for r in prev.get("records") or []}
    for r in recs:
        p = old.get(r["event_id"])
        if p:
            r["raw"]["_first_seen_at"] = (p.get("raw") or {}).get("_first_seen_at") or r["raw"]["_first_seen_at"]
    recs = redact.redact_events(recs)
    if not args.file:
        state.update(modified=modified, rules=RULES_VERSION, fetched_at=fetched_at)
        write_json(STATE_FILE, state)
    meta = {**stats, "table_modified": modified, "page": PAGE, "map": MAP, "credit": CREDIT,
            "license": "Public domain (data.ca.gov)", "registry_ids": [SOURCE_ID],
            "time_basis": "dates as the table gives them (day precision)",
            "left_out_note": ("Bloom reports with no advisory recommended (none, testing below the posting triggers, "
                              "general awareness or a de-posting) are counted, not shown.")}
    path_notes_to_meta(recs, meta)
    path = write_events(SOURCE_ID, recs, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {stats['rows_read']} rows, {len(recs)} records {stats['by_status']}; left out "
          f"{stats['left_out']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
