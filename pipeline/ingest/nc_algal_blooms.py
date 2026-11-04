"""NC DEQ Division of Water Resources algal bloom reports -> data/build/events/nc-dwr-algal-bloom-reports.json
(and, with --backfill, data/build/events/nc-fish-kill-algal-bloom.json).

Source
  NC DEQ Division of Water Resources fish kill and algal bloom reports, public ArcGIS layers in the DEQ
  organisation, queried as JSON with points in WGS84:
    - current: North_Carolina_Fish_Kills_and_Algal_Blooms_Public_Reports/FeatureServer/0 ("Fish Kill and Algal
      Bloom Incidents"; 260 reports on 2026-11-04, January to November 2026, edited daily): incident_id,
      report_type (Algal Bloom / Fish Kill / Fish Kill and Algal Bloom), observation_date ("Date Incident First
      Observed"), waterbody, county, regional_office, area_impacted and units, investigation_status (Received /
      In Progress / Completed), final_investigation_comments ("Final Investigation Public Comments"), lab_id.
    - archive (--backfill, once): Fish_Kill_Algal_Bloom_Public_View/FeatureServer/0 (1,364 reports, 2020 to
      2026-03-10, no longer edited): probid, category (AlgalBloom / FishKill / BothFKAB), EventDate, Waterbody,
      County, RO, Confirmed (Yes / No / blank), CreationDate ("Submitted On").
  These are reports to DWR (many from the public) and DWR's findings, not advisories: DWR posts no advisory
  status. No licence; credit NC DEQ Division of Water Resources.

Record rules
  - Only reports that include an algal bloom become records (event_type hab_advisory, category bloom); fish kill
    reports alone are counted in meta.fish_kill_reports and are not events.
  - status "unknown" (a report, not an advisory): the status build shows a report for 7 days from the
    observation date as an unconfirmed bloom advisory, never red. started_at is the observation date
    (time_precision minute); no end. reported_at is the submission time where the layer has one (archive).
  - event_id nc-dwr-algal-bloom-reports:<incident_id> (else the globalid); archive nc-fish-kill-algal-bloom:<probid>
    (else the GlobalID). Reports that leave the current layer are kept. The two layers overlap in January to
    March 2026: an archive report with the same incident id, or the same observation minute and county, is
    duplicate_of the current record.
  - advice_text: the sentence of DWR's public comment that advises the public ("... avoid contact ..."), when
    there is one; the whole public comment stays in raw.
  - waterbody_text as given; water_slugs empty (no North Carolina water records yet).

Privacy
  Only the fields named above are requested: the reporter's own description (incident_details, details),
  nearby landmarks (often a home address) and the archive's Creator field are never read. The report point
  may be where a person lives: it is rounded to 0.001 degree (about 100 m; coord_precision_m 150). Public
  comments pass common.strip_personal (in event()) and build.redact.

Cadence: daily (reports arrive a few a week in season). Run from pipeline/:
  python -m ingest.nc_algal_blooms [--file layer.json] [--backfill [--backfill-file archive.json]]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, path_notes_to_meta, read_json, save_raw, write_events

SOURCE_ID = "nc-dwr-algal-bloom-reports"
ARCHIVE_ID = "nc-fish-kill-algal-bloom"
ORG = "https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services"
LAYER = f"{ORG}/North_Carolina_Fish_Kills_and_Algal_Blooms_Public_Reports/FeatureServer/0"
ARCHIVE_LAYER = f"{ORG}/Fish_Kill_Algal_Bloom_Public_View/FeatureServer/0"
PAGE_URL = "https://www.deq.nc.gov/about/divisions/water-resources/water-sciences-section/algal-blooms"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "NC DEQ Division of Water Resources (fish kill and algal bloom reports)"
FIELDS = ["objectid", "globalid", "incident_id", "report_type", "fish_kill_number", "observation_date", "area_impacted",
          "area_units", "regional_office", "county", "waterbody", "investigation_status", "final_investigation_comments",
          "lab_id"]
ARCHIVE_FIELDS = ["OBJECTID", "probid", "category", "GlobalID", "CreationDate", "County", "Waterbody", "ApproxArea",
                  "AreaUnits", "Duration", "EventDate", "RO", "Confirmed", "fkCount", "SubmitDate"]
ROUND = 3
BASIS = ("A report to NC DEQ of an algal bloom, with DWR's investigation status and public comment; not an advisory. "
         "The point is rounded to about 100 m.")
ADVICE_RE = re.compile(r"[^.\n]*\b(avoid contact|stay out|keep (children|pets)|prevent children)[^.\n]*\.", re.I)


def ms_iso(v) -> str | None:
    if v in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(v) / 1000, UTC).astimezone(TZ).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def clean(v) -> str:
    return " ".join(str(v if v is not None else "").split())


def advice(comment) -> str | None:
    m = ADVICE_RE.search(str(comment or ""))
    return clean(m.group(0)) if m else None


def point(g: dict) -> tuple[float | None, float | None]:
    try:
        return round(float(g["y"]), ROUND), round(float(g["x"]), ROUND)
    except (KeyError, TypeError, ValueError):
        return None, None


def query(sess: requests.Session, url: str, fields: list[str], oid: str, source: str) -> list[dict]:
    feats, offset = [], 0
    while True:
        r = sess.get(f"{url}/query", params={"where": "1=1", "outFields": ",".join(fields), "outSR": 4326, "f": "json",
                                              "orderByFields": oid, "resultOffset": offset, "resultRecordCount": 2000},
                     timeout=(15, 90))
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            raise RuntimeError(f"ArcGIS error: {d['error']}")
        got = d.get("features") or []
        feats += got
        if not d.get("exceededTransferLimit") or not got:
            break
        offset += len(got)
    save_raw(source, json.dumps({"layer": url, "features": feats}, ensure_ascii=False), "json")
    return feats


def keep(a: dict, fields: list[str]) -> dict:
    want = {f.lower() for f in fields}
    return {k: v for k, v in a.items() if k.lower() in want}


def is_bloom(kind) -> bool:
    s = clean(kind).lower().replace(" ", "")
    return "algal" in s or s == "bothfkab"


def current_record(f: dict, fetched_at: str) -> dict:
    a = keep(f.get("attributes") or {}, FIELDS)
    lat, lon = point(f.get("geometry") or {})
    rid = clean(a.get("incident_id")) or clean(a.get("globalid")).strip("{}").lower()
    comment = a.get("final_investigation_comments")
    raw = {**a, "_basis": BASIS, "_layer": LAYER}
    return event(
        source_id=SOURCE_ID, source_record_id=rid, event_type="hab_advisory", status="unknown",
        waterbody_text=clean(a.get("waterbody")) or None, water_slugs=[], water_match="none",
        lat=lat, lon=lon, coord_source="source" if lat is not None else None,
        coord_precision_m=150 if lat is not None else None,
        started_at=ms_iso(a.get("observation_date")), time_precision="minute" if a.get("observation_date") else None,
        fetched_at=fetched_at, material=None, authority=AUTHORITY, advice_text=advice(comment),
        source_url=f"{LAYER}/query?where=objectid%3D{a.get('objectid')}&outFields=*&f=json", raw=raw,
        parse_error=None if a.get("observation_date") else "no observation date",
    )


def archive_record(f: dict, fetched_at: str) -> dict:
    a = keep(f.get("attributes") or {}, ARCHIVE_FIELDS)
    lat, lon = point(f.get("geometry") or {})
    rid = clean(a.get("probid")) or clean(a.get("GlobalID")).strip("{}").lower()
    conf = clean(a.get("Confirmed")).lower()
    raw = {**a, "_basis": BASIS, "_layer": ARCHIVE_LAYER}
    if conf in ("yes", "no"):
        raw["_confirmed"] = conf == "yes"
    return event(
        source_id=ARCHIVE_ID, source_record_id=rid, event_type="hab_advisory", status="unknown",
        waterbody_text=clean(a.get("Waterbody")) or None, water_slugs=[], water_match="none",
        lat=lat, lon=lon, coord_source="source" if lat is not None else None,
        coord_precision_m=150 if lat is not None else None,
        started_at=ms_iso(a.get("EventDate")), time_precision="minute" if a.get("EventDate") else None,
        reported_at=ms_iso(a.get("CreationDate")), fetched_at=fetched_at, authority=AUTHORITY,
        source_url=f"{ARCHIVE_LAYER}/query?where=OBJECTID%3D{a.get('OBJECTID')}&outFields=*&f=json", raw=raw,
        parse_error=None if a.get("EventDate") else "no event date",
    )


def build(features: list[dict], fetched_at: str, prev_records: list[dict], archive: bool = False) -> tuple[list[dict], dict]:
    kind_field = "category" if archive else "report_type"
    make = archive_record if archive else current_record
    records, fish_only, kinds = {}, 0, Counter()
    for f in features:
        a = f.get("attributes") or {}
        kinds[clean(a.get(kind_field))] += 1
        if not is_bloom(a.get(kind_field)):
            fish_only += 1
            continue
        rec = make(f, fetched_at)
        if rec["event_id"] in records:
            rec["event_id"] += f":{a.get('OBJECTID') or a.get('objectid')}"
        records[rec["event_id"]] = rec
    kept = 0
    for p in prev_records:
        if p["event_id"] not in records:
            p.setdefault("raw", {})
            p["raw"]["_missing_from_layer_since"] = p["raw"].get("_missing_from_layer_since") or fetched_at
            records[p["event_id"]] = p
            kept += 1
    out = sorted(records.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats = {"layer_rows": len(features), "bloom_reports": len(out) - kept, "kept_from_earlier_runs": kept,
             "fish_kill_reports": fish_only, "report_types": dict(kinds),
             "with_coordinates": sum(1 for r in out if r.get("lat") is not None)}
    return out, stats


def mark_duplicates(archive: list[dict], current: list[dict]) -> int:
    """An archive report that the current layer also holds (the same incident id, or the same observation minute
    in the same county) is duplicate_of the current record."""
    by_id = {r["source_record_id"]: r["event_id"] for r in current}
    by_when = {(r.get("started_at"), clean((r.get("raw") or {}).get("county")).lower()): r["event_id"]
               for r in current if r.get("started_at")}
    n = 0
    for r in archive:
        hit = by_id.get(r["source_record_id"]) or by_when.get(
            (r.get("started_at"), clean((r.get("raw") or {}).get("County")).lower())) if r.get("started_at") else \
            by_id.get(r["source_record_id"])
        if hit:
            r["duplicate_of"] = hit
            r["raw"]["_duplicate_basis"] = "the current reports layer holds the same report"
            n += 1
    return n


def _features(path: str) -> list[dict]:
    d = json.loads(Path(path).read_text())
    return d.get("features") or []


def main(argv=None) -> int:
    from build import redact
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="a saved query response of the current layer")
    ap.add_argument("--backfill", action="store_true", help="also read the 2020 - March 2026 archive layer once")
    ap.add_argument("--backfill-file", help="a saved query response of the archive layer")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        feats = _features(args.file) if args.file else query(sess, LAYER, FIELDS, "objectid", SOURCE_ID)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    records, stats = build(feats, fetched_at, prev)
    records = redact.redact_events(records)
    meta = {**stats, "layer": LAYER, "page": PAGE_URL, "statewide": True, "registry_ids": [SOURCE_ID],
            "credit": "NC DEQ Division of Water Resources, fish kill and algal bloom reports"}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, meta=meta)
    print(f"{SOURCE_ID}: {stats['bloom_reports']} bloom reports, {stats['fish_kill_reports']} fish kill only, "
          f"{stats['kept_from_earlier_runs']} kept -> {path}")
    if args.backfill or args.backfill_file:
        try:
            af = _features(args.backfill_file) if args.backfill_file else \
                query(sess, ARCHIVE_LAYER, ARCHIVE_FIELDS, "OBJECTID", ARCHIVE_ID)
        except Exception as e:  # noqa: BLE001
            write_events(ARCHIVE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
            print(f"{ARCHIVE_ID}: FAILED {e}", file=sys.stderr)
            return 1
        arecs, astats = build(af, fetched_at, [], archive=True)
        astats["duplicate_of_current"] = mark_duplicates(arecs, records)
        arecs = redact.redact_events(arecs)
        ameta = {**astats, "layer": ARCHIVE_LAYER, "page": PAGE_URL, "frozen": True, "statewide": True,
                 "registry_ids": [ARCHIVE_ID], "credit": "NC DEQ Division of Water Resources, fish kill and algal bloom reports"}
        path_notes_to_meta(arecs, ameta)
        ap_ = write_events(ARCHIVE_ID, arecs, ok=True, meta=ameta)
        print(f"{ARCHIVE_ID}: {astats['bloom_reports']} bloom reports, {astats['fish_kill_reports']} fish kill only -> {ap_}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
