"""Baltimore City DPW Sewer Overflow Map (SSO_Points2) -> data/build/events/md-baltimore-sso.json

Source
  Baltimore City Department of Public Works, "Sanitary Sewer Overflow (SSO) Public Notices"
  (ArcGIS Experience f064b1b0addd4017ac179f1652e182e0), map service layer
  https://dpwdata.baltimorecity.gov/pubgis/rest/services/Public/SSO_Points2/MapServer/0
  queried as JSON (where 1=1, every field, paged by OBJECTID). About 100 rows: every City SSO of the
  last ~four months (the interactive-maps page: "the most recent four months"), with START_DATETIME,
  END_DATETIME, EST_VOLUME (gallons), EST_FLOW (gpm), STATUS, REC_WATERS, WATERSHED, RESPONSIBILITY,
  SITE_TYPE (Standard / Structured SSO / ENS), Latitude/Longitude and waiver/penalty fields. No
  licence on the service (copyrightText empty); credit "Baltimore City Department of Public Works".

Record rules (research/md/report.md 2.3, sources.json md-baltimore-dpw-sso-map)
  - One sso record per OBJECTID (source_record_id). The layer keeps ~four months, so records of
    earlier runs that have left the layer are kept (raw._missing_from_layer_since): the events file
    is the history seen so far.
  - Times: the date fields hold local wall-clock time stored as if it were UTC (a 2026-10-11 11:15
    start matches MDE's 11:15 for the same overflow). Each epoch value is read as UTC, and the
    resulting wall-clock time is labelled America/New_York (raw._time_basis). SSO_DATE repeats the
    start and is kept in raw only.
  - Rows with no START_DATETIME (about half; all "Standard" sites) take SSO_DATE as the start
    (raw._start_basis): it equals START_DATETIME wherever both are filled, but on these rows it carries
    seconds, so it may be the time the record was entered.
  - STATUS: PROG (In Progress) -> status ongoing, ended_at null (an END_DATETIME present while in
    progress is kept in raw._end_while_in_progress); 24HR / 5DAY / FORM with an end -> ended; no end
    -> unknown. The STATUS history seen across runs is kept in raw._status_seen.
  - Volume: EST_VOLUME is an estimate (estimate_flag estimated); it is filled or revised when the
    5-day report is filed. EST_FLOW (gpm) stays in raw.
  - REC_WATERS is coded (24 names in the layer's domain); 2 out of 3 rows leave it empty, and then
    waterbody_text is null (WATERSHED, the 8-digit basin, is kept in raw._watershed_name, not as a
    receiving water). Names are matched within Maryland against the point (ingest/md_waters.py);
    Jones Falls, Gwynns Falls, Herring Run and most City streams have no openboatlaunch record yet.
  - Operator: RESPONSIBILITY DPW -> md-baltimore-city-dpw, CO -> md-baltimore-county-dpw; Private,
    Facility and Unknown name no operator (discharger_id null) and say so in discharger_name.
  - No publication or edit time in the layer: published_at and source_updated_at stay null; the
    first time this module saw each record is raw._first_seen_at (our clock, not the City's).
  - The MDE statewide table repeats City SSOs; ingest/md_mde_overflows.py (run after this module)
    marks its copies duplicate_of the record here, which carries the end time and the point.

Cadence: hourly (a record started at 12:20 was on the layer the same day with STATUS PROG).
Run from pipeline/:  python -m ingest.md_baltimore_sso [--file layer.json]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from build import redact
from common import (BUILD_DIR, EVENTS_DIR, HEADERS, ROOT, event, now_iso, path_notes_to_meta, read_json, save_raw,
                    write_events, write_json)
from ingest import md_waters

SOURCE_ID = "md-baltimore-sso"
LAYER = "https://dpwdata.baltimorecity.gov/pubgis/rest/services/Public/SSO_Points2/MapServer/0"
PAGE_URL = "https://experience.arcgis.com/experience/f064b1b0addd4017ac179f1652e182e0"
STATE_FILE = BUILD_DIR / "md-baltimore-sso-state.json"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "Baltimore City Department of Public Works (Sewer Overflow Map)"
DATE_FIELDS = ("SSO_DATE", "START_DATETIME", "END_DATETIME", "WAIVER_REQUESTED", "WAIVER_GRANTED",
               "WAIVER_CLOSED", "WAIVER_DENIED")
TIME_BASIS = ("The layer stores local wall-clock time as if it were UTC: each epoch value is read as UTC and the "
              "wall-clock time labelled America/New_York.")
# REC_WATERS coded values (the layer's domain; research/md/sources.json lists the same 24)
REC_WATERS = {
    "ARGO": "Argonne Run", "ARMI": "Armistead Creek", "BIDD": "Biddison Run", "CHIN": "Chinquapin Run",
    "COLG": "Colgate Creek", "CRTB": "Curtis Bay", "CRTC": "Curtis Creek", "DEAD": "Dead Run",
    "GUNP": "Gunpowder Falls", "GWYN": "Gwynns Falls", "HERR": "Herring Run", "HARB": "Inner Harbor",
    "JF": "Jones Falls", "LRR": "Loch Raven Reservoir", "MAID": "Maidens Choice Creek", "MID": "Middle Branch",
    "MOOR": "Moores Run", "MTPL": "Mt Pleasant Run", "NWHB": "Northwest Harbor", "PAT": "Patapsco River",
    "SHCV": "Stonehouse Cove", "SR": "Stony Run", "TIFF": "Tiffany Run", "WEST": "Western Run",
}
# the names openboatlaunch uses for two coded waters (the point is still checked against the box)
MATCH_AS = {"MID": "Middle Branch Patapsco River", "HARB": "Northwest Harbor"}
WATERSHEDS = {2130904: "Jones Falls", 2130901: "Back River", 2130903: "Baltimore Harbor", 2130905: "Gwynns Falls",
              2130906: "Patapsco River L N Br"}
STATUS_NAMES = {"PROG": "In Progress", "5DAY": "5 Day Report Submitted", "24HR": "24 Hour Report Submitted",
                "FORM": "Paper Form Submittal"}
RESPONSIBILITY = {
    "DPW": ("md-baltimore-city-dpw", "Baltimore City Department of Public Works"),
    "CO": ("md-baltimore-county-dpw", "Baltimore County Department of Public Works and Transportation"),
    "PRI": (None, "Private (property owner; not named by the source)"),
    "FAC": (None, "Facility (not named by the source)"),
    "UNK": (None, None),
}
SITE_RE = re.compile(r"\bSSO\s+Site\s*#\s*(\d+)", re.I)


def wall_clock(ms) -> datetime | None:
    """An epoch-ms value that holds local wall-clock time stored as UTC -> aware America/New_York."""
    if ms is None or ms == "":
        return None
    try:
        t = datetime.fromtimestamp(float(ms) / 1000, UTC)
    except (TypeError, ValueError, OverflowError, OSError):
        return None
    return t.replace(tzinfo=None).replace(tzinfo=TZ)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def fnum(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None


def query_layer(sess: requests.Session) -> tuple[list[dict], bytes]:
    """Every feature (attributes only; Latitude/Longitude are fields) and the raw pages as one JSON."""
    feats, pages, offset = [], [], 0
    while True:
        params = {"where": "1=1", "outFields": "*", "returnGeometry": "false", "orderByFields": "OBJECTID",
                  "resultOffset": offset, "resultRecordCount": 1000, "f": "json"}
        r = sess.get(f"{LAYER}/query", params=params, timeout=(15, 90))
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            raise RuntimeError(f"ArcGIS error: {d['error']}")
        pages.append(d)
        got = d.get("features") or []
        feats += got
        if not d.get("exceededTransferLimit") or not got or offset > 50_000:
            break
        offset += len(got)
    raw = json.dumps({"layer": LAYER, "pages": pages}, ensure_ascii=False).encode()
    return [f.get("attributes") or {} for f in feats], raw


def decoded_dates(a: dict) -> dict:
    return {k: iso(wall_clock(a.get(k))) for k in DATE_FIELDS if a.get(k) not in (None, "")}


def place(a: dict, lat, lon) -> tuple[str | None, list[str], str, dict]:
    code = (a.get("REC_WATERS") or "").strip() or None
    note: dict = {}
    if not code:
        return None, [], "none", {"why_none": "REC_WATERS empty (the layer names no receiving water)"}
    if code == "N/A":
        return "N/A", [], "none", {"why_none": "REC_WATERS N/A"}
    name = REC_WATERS.get(code)
    if not name:
        return code, [], "none", {"why_none": f"unknown REC_WATERS code {code!r}"}
    point = (lon, lat) if lat is not None and lon is not None else None
    slugs, notes = md_waters.match_waters(MATCH_AS.get(code, name), None, point, "Baltimore City")
    if MATCH_AS.get(code):
        note["matched_as"] = MATCH_AS[code]
    if notes:
        note["name_notes"] = notes
    if not slugs:
        note["why_none"] = f"no Maryland water record named {name!r} near the point"
    return name, slugs, ("name" if slugs else "none"), note


def to_record(a: dict, fetched_at: str, prev: dict | None) -> dict:
    oid = a.get("OBJECTID")
    base = dict(source_id=SOURCE_ID, source_record_id=str(oid), fetched_at=fetched_at,
                source_url=f"{LAYER}/query?where=OBJECTID%3D{oid}&outFields=*&f=json")
    raw = {k: v for k, v in a.items()}
    try:
        return build_record(a, base, raw, prev)
    except Exception as e:  # noqa: BLE001 - never drop a record
        return event(**base, event_type="unknown", status="unknown", raw=raw, authority=AUTHORITY,
                     parse_error=f"{type(e).__name__}: {e}")


def build_record(a: dict, base: dict, raw: dict, prev: dict | None) -> dict:
    problems = []
    raw["_decoded_times"] = decoded_dates(a)
    raw["_time_basis"] = TIME_BASIS
    start, end = wall_clock(a.get("START_DATETIME")), wall_clock(a.get("END_DATETIME"))
    if start is None and a.get("SSO_DATE"):
        start = wall_clock(a.get("SSO_DATE"))
        raw["_start_basis"] = ("START_DATETIME is empty: started_at is SSO_DATE (the layer's DATE field, equal to "
                               "START_DATETIME wherever both are filled). Its seconds suggest the time the record was "
                               "entered, so the overflow may have begun earlier.")
    code = (a.get("STATUS") or "").strip().upper()
    raw["_status_name"] = STATUS_NAMES.get(code)
    if code == "PROG":
        status, ended_at = "ongoing", None
        if end is not None:
            raw["_end_while_in_progress"] = iso(end)
    elif end is not None:
        status, ended_at = "ended", iso(end)
    else:
        status, ended_at = "unknown", None
    if end is not None and start is not None and end < start:
        problems.append("END_DATETIME before START_DATETIME: ended_at left empty")
        ended_at = None
        if status == "ended":
            status = "unknown"

    lat, lon = fnum(a.get("Latitude")), fnum(a.get("Longitude"))
    if lat is not None and lon is not None and not md_waters.in_md(lon, lat):
        raw["_coords_rejected"] = {"lat": lat, "lon": lon, "why": "not in Maryland"}
        lat = lon = None
    water, slugs, match, wnote = place(a, lat, lon)
    if wnote:
        raw["_water"] = wnote
    ws = a.get("WATERSHED")
    if ws is not None:
        raw["_watershed_name"] = WATERSHEDS.get(ws)

    vol = fnum(a.get("EST_VOLUME"))
    gal = int(round(vol)) if vol is not None and vol >= 0 else None
    vtext = f"{vol:,.2f}".rstrip("0").rstrip(".") + " gallons (EST_VOLUME)" if vol is not None else None
    resp = (a.get("RESPONSIBILITY") or "").strip().upper() or None
    did, dname = RESPONSIBILITY.get(resp, (None, None)) if resp else (None, None)
    raw["_responsibility"] = {"DPW": "DPW", "CO": "County", "PRI": "Private", "FAC": "Facility", "UNK": "Unknown"}.get(resp or "", resp)
    loc = " ".join(str(a.get("LOCATION") or "").split()) or None
    m = SITE_RE.search(loc or "")

    # carried across runs: first sighting and the STATUS values seen
    p_raw = (prev or {}).get("raw") or {}
    raw["_first_seen_at"] = p_raw.get("_first_seen_at") or base["fetched_at"]
    seen = list(p_raw.get("_status_seen") or [])
    if not seen or seen[-1].get("status") != code:
        seen.append({"status": code or None, "first_seen_at": base["fetched_at"]})
    raw["_status_seen"] = seen
    if prev and p_raw.get("_volume_seen"):
        vs = list(p_raw["_volume_seen"])
    else:
        vs = []
    if gal is not None and (not vs or vs[-1].get("gallons") != gal):
        vs.append({"gallons": gal, "first_seen_at": base["fetched_at"]})
    if vs:
        raw["_volume_seen"] = vs

    return event(
        **base, event_type="sso", status=status,
        discharger_id=did, discharger_name=dname, npdes_permit=None,
        outfall_id=f"SSO Site #{m.group(1)}" if m else None, outfall_name=loc,
        waterbody_text=water, water_slugs=slugs, water_match=match,
        lat=lat, lon=lon, coord_source="source" if lat is not None else None, coord_precision_m=None,
        started_at=iso(start), ended_at=ended_at, time_precision="minute" if start else None,
        reported_at=None, published_at=None, source_updated_at=None,
        material=None, volume_gal=gal, volume_text=vtext, estimate_flag="estimated" if gal is not None else "unknown",
        authority=AUTHORITY, advice_text=None, advice_window_hours=None, advice_window_basis=None,
        raw=raw, parse_error="; ".join(problems) or None,
    )


def build(features: list[dict], fetched_at: str, prev_records: list[dict]) -> tuple[list[dict], dict]:
    prev = {r["event_id"]: r for r in prev_records}
    records, seen = [], set()
    for a in features:
        if a.get("OBJECTID") is None:
            continue
        eid = f"{SOURCE_ID}:{a['OBJECTID']}"
        if eid in seen:
            continue
        seen.add(eid)
        records.append(to_record(a, fetched_at, prev.get(eid)))
    kept = 0
    for eid, r in prev.items():
        if eid in seen:
            continue
        r.setdefault("raw", {})
        r["raw"]["_missing_from_layer_since"] = r["raw"].get("_missing_from_layer_since") or fetched_at
        records.append(r)
        kept += 1
    records.sort(key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats = {"layer_rows": len(seen), "kept_from_earlier_runs": kept,
             "by_status": dict(Counter(r["status"] for r in records)),
             "water_match": dict(Counter(r["water_match"] for r in records)),
             "with_coordinates": sum(1 for r in records if r.get("lat") is not None)}
    return records, stats


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="read this saved query response instead of the layer")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    try:
        if args.file:
            d = json.loads(Path(args.file).read_text())
            pages = d.get("pages") or [d]
            features = [f.get("attributes") or {} for p in pages for f in p.get("features") or []]
            raw_bytes = None
        else:
            sess = requests.Session()
            sess.headers.update(HEADERS)
            features, raw_bytes = query_layer(sess)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    state = read_json(STATE_FILE, {}) or {}
    raw_path = state.get("raw_path")
    if raw_bytes is not None:
        sha = hashlib.sha256(json.dumps(features, sort_keys=True).encode()).hexdigest()
        if sha != state.get("sha256"):
            raw_path = str(save_raw(SOURCE_ID, raw_bytes, "json").relative_to(ROOT))
            state = {"sha256": sha, "raw_path": raw_path, "saved_at": fetched_at}
        state["fetched_at"] = fetched_at
        write_json(STATE_FILE, state)
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    records, stats = build(features, fetched_at, prev)
    records = redact.redact_events(records)      # private individuals' names in quoted text (build/redact.py)
    meta = {**stats, "layer": LAYER, "raw_path": raw_path, "time_basis": TIME_BASIS,
            "credit": "Baltimore City Department of Public Works, Sewer Overflow Map (SSO_Points2)",
            "registry_ids": ["md-baltimore-dpw-sso-map"]}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {stats['layer_rows']} layer rows, {stats['kept_from_earlier_runs']} kept from earlier runs; "
          f"status {stats['by_status']}; water match {stats['water_match']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
