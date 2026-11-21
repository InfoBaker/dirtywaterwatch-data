"""NC DEQ Division of Marine Fisheries coastal swimming advisories -> data/build/events/nc-rwq-advisories.json

Source (since 2026-11-21: the PUBLICVIEW service that DMF's public dashboard reads)
  NC DEQ Division of Marine Fisheries, Recreational Water Quality program, ArcGIS service
  https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services/PUBLICVIEWRecreationWaterQualityDatabase/FeatureServer
  - layer 0 "Monitoring_Stations" (229 ocean and sound stations on 2026-11-21), queried as JSON with points in WGS84,
    the named fields only (FIELDS): ASN (the station code, e.g. N88), DESCRIPTIO (the site), COUNTY, TIER, LOCATION
    (ocean / sound), EPA_ID, Active, EditDate (the row's last edit) and Status, a coded value:
      No Advisory (the 2022 layer: No Alert)   no event
      Pending Swimming Advisory   one sample at or over the limit; a resample decides (15A NCAC 18A .3403(a)(1))
      Advisory          "Swimming Advisory" (15A NCAC 18A .3403(a)(2), (b)(2); .3404(b) for a wastewater spill)
      Precautionary     "Precautionary Advisory": a storm-water discharge area, including areas affected by heavy
                        rain (15A NCAC 18A .3404(c), the storm drain and pipe signs)
  - table 2 "Beach_Activity" (605 rows since 2005 on 2026-11-21): one row per advisory DMF posted (ACTIVITY_CODE
    CONTAM_ADV, 483) or pending resample (Pending, 122), with DMF's own START_DATE and END_DATE (epoch, UTC; an end
    is stamped by DMF's app when it lifts the advisory), REASON (ELEV_BACT) and INDICATOR (ENTERO), keyed to the
    station by STATE_ID (= ASN). Staff fields (Creator, Editor) are never requested.
  Until 2026-11-21 the feed read the 2022 layer RWQ_Advisory_EXTERNAL/FeatureServer/1 (OLD_LAYER), status only; on
  that day it still showed N88 as an advisory that DMF's table ended on 2026-10-31, and it lacked N14A's and N17A's
  precautionary status. No licence; credit NC DEQ Division of Marine Fisheries.

Records
  - Each Beach_Activity row is a record: source_record_id DMF's ACTIVITY_NAME ("N88_Posting2026-09-29"),
    beach_advisory, advisory_active while it has no END_DATE (raw._last_seen_in_source each read; source_updated_at
    the table's last edit, so an advisory the table has not re-confirmed for 14 days stops colouring), else
    advisory_lifted with DMF's END_DATE; time_precision minute; the station's point. An end typed before its start
    is not used (status unknown, parse_error). A row that leaves the table keeps its record with
    raw._missing_from_table_since.
  - Precautionary (a standing storm-water class with no activity row) stays a snapshot spell of the station's Status,
    as do an Advisory or a Pending status at a station with no open activity row: one record per spell, event_id
    nc-rwq-advisories:<ASN>:<status code>:<UTC stamp of its start>. Precautionary -> rain_advisory, advisory_active.
    started_at is the station row's last edit (EditDate) on the run that first saw the status, or the layer's last
    edit where the row gives none: the status was set at or before then; time_precision "poll". A station that leaves
    the status ends the spell at the layer's last edit on that run. The dates are this site's observation, not dates
    the Division publishes (raw._date_basis, raw._end_note). A blank Status leaves an open spell open.
  - The 2022 layer's records: a precautionary spell continues under its own id (the station and code are the same on
    both). An Advisory or Pending spell from the 2022 layer is duplicate_of DMF's activity row at its station of the
    same class that began on or before it (raw._superseded_by_activity) and is no longer touched by the snapshot.
  - Coordinates from the station layer; waterbody_text the station description with "ocean" or "sound";
    water_slugs empty (beach points are markers, not water fills).
  - No personal fields are requested; common.strip_personal runs regardless.

Cadence: daily is enough (the program samples weekly in season, monthly off season); runs with the refresh.
Run from pipeline/:  python -m ingest.nc_rwq_advisories [--file stations.json --meta stations-meta.json
                     [--activity activity.json --activity-meta activity-meta.json]]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import EVENTS_DIR, HEADERS, event, now_iso, path_notes_to_meta, read_json, save_raw, write_events
from common import error_detail, error_text

SOURCE_ID = "nc-rwq-advisories"
SERVICE = ("https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services/"
           "PUBLICVIEWRecreationWaterQualityDatabase/FeatureServer")
LAYER = SERVICE + "/0"
TABLE = SERVICE + "/2"
OLD_LAYER = "https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services/RWQ_Advisory_EXTERNAL/FeatureServer/1"
PAGE_URL = ("https://www.deq.nc.gov/about/divisions/marine-fisheries/shellfish-sanitation-and-recreational-water-quality/"
            "recreational-water-quality")
TZ = ZoneInfo("America/New_York")
AUTHORITY = "NC DEQ Division of Marine Fisheries, Recreational Water Quality program"
STATUS = {  # code -> (event_type, status while it holds, label, rule)
    "Advisory": ("beach_advisory", "advisory_active", "Swimming advisory",
                 "15A NCAC 18A .3403 (bacteria limits exceeded) or .3404(b) (waters impacted by a wastewater spill)"),
    "Precautionary": ("rain_advisory", "advisory_active", "Precautionary advisory (storm-water discharge area)",
                      "15A NCAC 18A .3404(c)"),
    "Pending Swimming Advisory": ("beach_advisory", "advisory_active", "Pending swimming advisory (resample pending)",
                                  "15A NCAC 18A .3403(a)(1), (b)(1)"),
}
SIGNS = {
    "Advisory": ("ATTENTION: SWIMMING IN THIS AREA IS NOT RECOMMENDED. BACTERIA TESTING INDICATES LEVELS OF "
                 "CONTAMINATION THAT MAY BE HAZARDOUS TO YOUR HEALTH. THIS ADVISORY AFFECTS WATERS WITHIN 200' OF THIS "
                 "SIGN. (15A NCAC 18A .3403(d))"),
    "Precautionary": ("WARNING! STORM WATER DISCHARGE AREA. WATERS MAY BE CONTAMINATED BY DISCHARGE FROM PIPE. "
                      "SWIMMING IS NOT RECOMMENDED WITHIN 200 YARDS OF THIS SIGN DURING ACTIVE DISCHARGE. "
                      "(15A NCAC 18A .3404(c), wet weather sign)"),
}
NO_ALERT = "No Alert"
NO_ALERT_CODES = {"No Alert", "No Advisory"}          # the 2022 layer's and PUBLICVIEW's word for no status
FIELDS = ["OBJECTID", "STATION", "COUNTY", "TIER", "LATITUDE", "LONGITUDE", "EFFECTIVE", "EPA_ID", "StationID",
          "GlobalID", "Status", "ASN", "ASN2", "DESCRIPTIO", "LOCATION", "Active", "EditDate"]
ACTIVITY_FIELDS = ["OBJECTID", "ACTIVITY_ID", "BEACH_ID", "STATE_ID", "PUBLIC_DESCRIPTION", "FIPS_COUNTY_DESC",
                   "ACTIVITY_NAME", "ACTIVITY_CODE", "START_DATE", "END_DATE", "ACTIVITY_STATION", "REASON", "INDICATOR",
                   "EditDate", "GlobalID"]
ACTIVITY_STATUS = {"CONTAM_ADV": "Advisory", "Pending": "Pending Swimming Advisory"}
REASONS = {"ELEV_BACT": "elevated bacteria"}
INDICATORS = {"ENTERO": "enterococci"}
PAGE_SIZE = 1000
MAX_ROWS = 50000
DATE_BASIS = ("Dated by this site from the map: the layer's last change on the run that first showed this status. "
              "The map gives no issue or lift dates, so this is this site's observation, not an issue date from the "
              "Division of Marine Fisheries; the advisory may have been issued earlier.")
END_NOTE = ("Dated by this site from the map: the layer's last change on the run that no longer showed this status "
            "(the Division changed it at or before then). This is this site's observation, not a lift date from "
            "the Division of Marine Fisheries.")
ACT_DATE_BASIS = ("START_DATE and END_DATE are the Division of Marine Fisheries' own dates for this advisory, from its "
                  "Beach_Activity table (the record behind its public dashboard).")
SUPERSEDED_NOTE = ("Seen on the 2022 layer (RWQ_Advisory_EXTERNAL), which shows status only; the Division's own record "
                   "of this advisory, with its dates, is the activity named in _superseded_by_activity.")


def ms_iso(v) -> str | None:
    if v in (None, ""):
        return None
    try:
        return datetime.fromtimestamp(float(v) / 1000, UTC).astimezone(TZ).isoformat(timespec="seconds")
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def stamp(t: str | None, fallback: str) -> str:
    s = t or fallback
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(UTC).strftime("%Y%m%dT%H%MZ")
    except ValueError:
        return s


def when(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def clean(v) -> str:
    return " ".join(str(v if v is not None else "").split())


def station_id(a: dict) -> str | None:
    return clean(a.get("ASN") or a.get("ASN2")) or None


def _features(js) -> list[dict]:
    if not isinstance(js, dict) or "features" not in js or js.get("error"):
        raise ValueError("the service answered no features")
    return js["features"]


def fetch(sess: requests.Session) -> tuple[list[dict], dict]:
    r = sess.get(f"{LAYER}/query", params={"where": "1=1", "outFields": ",".join(FIELDS), "outSR": 4326, "f": "json",
                                            "resultRecordCount": 2000}, timeout=(15, 90))
    r.raise_for_status()
    feats = _features(r.json())
    if r.json().get("exceededTransferLimit"):
        raise ValueError("the station layer answer was cut off at the transfer limit")
    save_raw(SOURCE_ID, r.content, "json")
    m = sess.get(LAYER, params={"f": "json"}, timeout=(15, 60))
    m.raise_for_status()
    return feats, m.json()


def fetch_activities(sess: requests.Session) -> tuple[list[dict], dict]:
    """Every Beach_Activity row (ACTIVITY_FIELDS), paged by offset in object-id order, and the table's description."""
    rows, offset = [], 0
    while True:
        r = sess.get(f"{TABLE}/query", params={"where": "1=1", "outFields": ",".join(ACTIVITY_FIELDS), "f": "json",
                                                "orderByFields": "OBJECTID", "resultOffset": offset,
                                                "resultRecordCount": PAGE_SIZE}, timeout=(15, 90))
        r.raise_for_status()
        js = r.json()
        page = [f.get("attributes") or {} for f in _features(js)]
        rows += page
        if not js.get("exceededTransferLimit") or not page:
            break
        offset += len(page)
        if offset >= MAX_ROWS:
            raise ValueError(f"the activity table did not end within {MAX_ROWS} rows")
    ids = [a.get("OBJECTID") for a in rows]
    if len(ids) != len(set(ids)):
        raise ValueError("the activity table repeated rows while it was read")
    save_raw(SOURCE_ID, json.dumps(rows).encode(), "json")
    m = sess.get(TABLE, params={"f": "json"}, timeout=(15, 60))
    m.raise_for_status()
    return rows, m.json()


def build(features: list[dict], layer_meta: dict, fetched_at: str, prev_records: list[dict],
          activities: list[dict] | None = None, table_meta: dict | None = None) -> tuple[list[dict], dict]:
    edited = ms_iso((layer_meta.get("editingInfo") or {}).get("dataLastEditDate"))
    open_by_station: dict[str, dict] = {}
    records: dict[str, dict] = {}
    for p in prev_records:
        records[p["event_id"]] = p
    act_stats = {}
    covered = set()            # stations with an open activity row: their Advisory or Pending status is that row
    if activities is not None:
        stations = {station_id((f.get("attributes") or {})): f for f in features}
        acts, act_stats = activity_records(activities, stations, table_meta or {}, fetched_at, records)
        for r in acts:
            records[r["event_id"]] = r
            if r["status"] == "advisory_active":
                covered.add((r["raw"].get("ASN"), r["raw"].get("_status_code")))
        act_stats["superseded"] = supersede_snapshots(records, acts)
    for p in records.values():
        raw = p.get("raw") or {}
        if raw.get("_kind") == "activity" or p.get("duplicate_of"):
            continue
        if p.get("ended_at") is None and p.get("status") in ("advisory_active", "unknown"):
            st = raw.get("ASN")
            if st:
                open_by_station[st] = p
    seen, tracked, odd = set(), [], Counter()
    for f in features:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        sid = station_id(a)
        if not sid or sid in seen:
            continue
        seen.add(sid)
        code = clean(a.get("Status"))
        lat = g.get("y") if g.get("y") is not None else a.get("LATITUDE")
        lon = g.get("x") if g.get("x") is not None else a.get("LONGITUDE")
        cur = open_by_station.get(sid)
        if not code and cur is not None:                  # a blank status says nothing: the spell stays open
            cur["fetched_at"] = fetched_at
            cur["raw"]["_status_blank_since"] = cur["raw"].get("_status_blank_since") or fetched_at
            continue
        if cur is not None:
            cur["raw"].pop("_status_blank_since", None)
        cur_code = ((cur or {}).get("raw") or {}).get("_status_code")
        if cur is not None and cur_code != code:          # the status this record stands for has ended
            close(cur, edited, fetched_at)
            cur = None
        if code in NO_ALERT_CODES or not code or (sid, code) in covered:
            tracked.append({"station": sid, "site": clean(a.get("DESCRIPTIO")) or None, "status": code or None,
                            "lat": lat, "lon": lon})
            continue
        if code not in STATUS:
            odd[code] += 1
        if cur is not None:                                # the same status, still in effect
            cur["source_updated_at"] = edited
            cur["fetched_at"] = fetched_at
            cur["raw"]["_last_seen_at"] = fetched_at
            cur["raw"].pop("_missing_from_layer_since", None)
            continue
        rec = open_record(a, sid, code, lat, lon, edited, fetched_at)
        records[rec["event_id"]] = rec
        open_by_station[sid] = rec
    for sid, cur in open_by_station.items():
        if sid not in seen and cur.get("ended_at") is None and cur["status"] in ("advisory_active", "unknown"):
            cur["raw"]["_missing_from_layer_since"] = cur["raw"].get("_missing_from_layer_since") or fetched_at
    out = sorted(records.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats = {"stations": len(seen), "layer_last_edit": edited,
             "status_now": dict(Counter(clean((f.get("attributes") or {}).get("Status")) for f in features)),
             "records": len(out), "open": sum(1 for r in out if r.get("ended_at") is None and not r.get("duplicate_of")
                                              and r["status"] == "advisory_active"),
             "unknown_status_codes": dict(odd), "tracked": tracked, **act_stats}
    return out, stats


def activity_records(rows: list[dict], stations: dict, table_meta: dict, fetched_at: str,
                     prev: dict) -> tuple[list[dict], dict]:
    """One record per Beach_Activity row (DMF's own advisory or pending resample, with its dates); a row that left the
    table keeps its earlier record, marked."""
    table_edit = ms_iso((table_meta.get("editingInfo") or {}).get("dataLastEditDate"))
    out, ids = [], set()
    for a in sorted(rows, key=lambda x: (x.get("START_DATE") or 0, x.get("OBJECTID") or 0)):
        a = {k: a.get(k) for k in ACTIVITY_FIELDS}
        sid = clean(a.get("STATE_ID")) or None
        code = clean(a.get("ACTIVITY_CODE"))
        st = ACTIVITY_STATUS.get(code)
        name = clean(a.get("ACTIVITY_NAME")) or f"{sid}:{code}:{a.get('START_DATE')}"
        rid, n = name, 2
        while rid in ids:
            rid, n = f"{name}~{n}", n + 1
        ids.add(rid)
        f = stations.get(sid) or {}
        sa, g = f.get("attributes") or {}, f.get("geometry") or {}
        lat = g.get("y") if g.get("y") is not None else sa.get("LATITUDE")
        lon = g.get("x") if g.get("x") is not None else sa.get("LONGITUDE")
        start, end = ms_iso(a.get("START_DATE")), ms_iso(a.get("END_DATE"))
        problem = None
        if start is None:
            problem = "no START_DATE"
        elif end and when(end) < when(start):
            problem = f"END_DATE {end} is before START_DATE {start}: the end is not used"
            end = None
        if st is None:
            problem = problem or f"activity code {code!r} is not one of the table's known codes"
        site = clean(sa.get("DESCRIPTIO")) or clean(a.get("PUBLIC_DESCRIPTION")) or sid or name
        where = clean(sa.get("LOCATION")).lower()
        et, _, label, rule = STATUS.get(st or "", ("beach_advisory", "unknown", code, None))
        status = "unknown" if problem else ("advisory_lifted" if end else "advisory_active")
        old = prev.get(f"{SOURCE_ID}:{rid}")
        raw = {**a, "ASN": sid, "_kind": "activity", "_status_code": st, "_status_label": label, "_rule": rule,
               "_reason": REASONS.get(clean(a.get("REASON")), clean(a.get("REASON")) or None),
               "_indicator": INDICATORS.get(clean(a.get("INDICATOR")), clean(a.get("INDICATOR")) or None),
               "_table": TABLE, "_date_basis": ACT_DATE_BASIS,
               "_first_seen_at": ((old or {}).get("raw") or {}).get("_first_seen_at") or fetched_at}
        if status == "advisory_active":
            raw["_last_seen_in_source"] = fetched_at
        if not f:
            raw["_station_not_on_layer"] = True
        out.append(event(
            source_id=SOURCE_ID, source_record_id=rid, event_type=et, status=status,
            waterbody_text=f"{site} ({where})" if where in ("ocean", "sound", "estuary") else site,
            water_slugs=[], water_match="none",
            lat=round(float(lat), 6) if lat is not None else None, lon=round(float(lon), 6) if lon is not None else None,
            coord_source="source" if lat is not None else None,
            started_at=start, ended_at=end, time_precision="minute",
            source_updated_at=table_edit if status == "advisory_active" else ms_iso(a.get("EditDate")),
            fetched_at=fetched_at, material=None, authority=AUTHORITY,
            advice_text=SIGNS.get(st or ""), advice_window_hours=None, advice_window_basis=rule,
            source_url=f"{TABLE}/query?where=ACTIVITY_NAME%3D%27{name}%27&outFields={','.join(ACTIVITY_FIELDS)}&f=json",
            raw=raw, parse_error=problem))
    now_ids = {r["event_id"] for r in out}
    for eid, p in prev.items():
        if (p.get("raw") or {}).get("_kind") == "activity" and eid not in now_ids:
            p["raw"]["_missing_from_table_since"] = p["raw"].get("_missing_from_table_since") or fetched_at
            out.append(p)
    stats = {"activities": len(rows), "activities_open": sum(1 for r in out if r["status"] == "advisory_active"),
             "table_last_edit": table_edit}
    return out, stats


def supersede_snapshots(records: dict, acts: list[dict]) -> int:
    """Point each Advisory or Pending snapshot spell (the 2022 layer's, or one kept for a station with no activity row)
    at DMF's activity row of the same class at its station that began on or before the spell's start, the latest
    such; returns how many are linked."""
    by_station: dict[tuple, list[dict]] = {}
    for r in acts:
        raw = r["raw"]
        if r.get("started_at") and raw.get("_status_code"):
            by_station.setdefault((raw.get("ASN"), raw["_status_code"]), []).append(r)
    n = 0
    for p in records.values():
        raw = p.get("raw") or {}
        if raw.get("_kind") == "activity" or raw.get("_status_code") not in ("Advisory", "Pending Swimming Advisory"):
            continue
        cands = [r for r in by_station.get((raw.get("ASN"), raw["_status_code"]), [])
                 if p.get("started_at") and when(r["started_at"]) <= when(p["started_at"])]
        if not cands:
            continue
        best = max(cands, key=lambda r: when(r["started_at"]))
        p["duplicate_of"] = best["event_id"]
        raw.update(_superseded_by_activity=best["source_record_id"], _superseded_note=SUPERSEDED_NOTE)
        n += 1
    return n


def open_record(a: dict, sid: str, code: str, lat, lon, edited: str | None, fetched_at: str) -> dict:
    et, status, label, rule = STATUS.get(code, ("beach_advisory", "unknown", code, None))
    row_edit = ms_iso(a.get("EditDate"))
    use_row = bool(row_edit and (not edited or when(row_edit) <= when(edited)))
    start = row_edit if use_row else (edited or fetched_at)
    site = clean(a.get("DESCRIPTIO")) or sid
    where = clean(a.get("LOCATION")).lower()
    want = {f.lower() for f in FIELDS}
    raw = {k: v for k, v in a.items() if k.lower() in want}
    raw.update({"_status_code": code, "_status_label": label, "_rule": rule, "_first_seen_at": fetched_at,
                "_last_seen_at": fetched_at, "_layer": LAYER, "_date_basis": DATE_BASIS,
                "_start_basis": (("the station row's last edit (EditDate) on the run that first saw this status: the "
                                  "status was set at or before then (the layer gives no issue time)") if use_row else
                                 ("the layer's last data edit on the run that first saw this status: the status was set "
                                  "at or before then (the layer gives no issue time)"))})
    if code not in STATUS:
        raw["_unknown_status_code"] = True
    return event(
        source_id=SOURCE_ID, source_record_id=f"{sid}:{code.lower().replace(' ', '-')}:{stamp(start, fetched_at)}",
        event_type=et, status=status,
        waterbody_text=f"{site} ({where})" if where in ("ocean", "sound", "estuary") else site,
        water_slugs=[], water_match="none",
        lat=round(float(lat), 6) if lat is not None else None, lon=round(float(lon), 6) if lon is not None else None,
        coord_source="source" if lat is not None else None,
        started_at=start, ended_at=None, time_precision="poll",
        source_updated_at=edited, fetched_at=fetched_at, material=None, authority=AUTHORITY,
        advice_text=SIGNS.get(code), advice_window_hours=None, advice_window_basis=rule,
        source_url=f"{LAYER}/query?where=ASN%3D%27{sid}%27&outFields=*&f=json", raw=raw,
        parse_error=f"status {code!r} is not one of the layer's known values" if code not in STATUS else None,
    )


def close(rec: dict, edited: str | None, fetched_at: str) -> None:
    end = edited or fetched_at
    start = rec.get("started_at")
    if start and when(end) < when(start):     # a layer edit before the start (the clock went back): use our clock
        end = fetched_at
        rec["raw"]["_end_basis"] = "fetch"
    rec["ended_at"] = end
    rec["status"] = "advisory_lifted"
    rec["fetched_at"] = fetched_at
    rec["raw"]["_lifted_seen_at"] = fetched_at
    rec["raw"]["_end_note"] = END_NOTE


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="a saved station layer query response")
    ap.add_argument("--meta", help="a saved station layer description (f=json), for its last edit time")
    ap.add_argument("--activity", help="a saved Beach_Activity query response (with --file)")
    ap.add_argument("--activity-meta", help="a saved Beach_Activity description (f=json)")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    acts, tmeta = None, None
    try:
        if args.file:
            features = json.loads(Path(args.file).read_text()).get("features") or []
            meta_js = json.loads(Path(args.meta).read_text()) if args.meta else {}
            if args.activity:
                acts = [f.get("attributes") or {} for f in json.loads(Path(args.activity).read_text())["features"]]
                tmeta = json.loads(Path(args.activity_meta).read_text()) if args.activity_meta else {}
        else:
            s = requests.Session()
            s.headers.update(HEADERS)
            features, meta_js = fetch(s)
            acts, tmeta = fetch_activities(s)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{error_text(e)}")
        print(f"{SOURCE_ID}: FAILED {error_detail(e)}", file=sys.stderr)
        return 1
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    records, stats = build(features, meta_js, fetched_at, prev, activities=acts, table_meta=tmeta)
    meta = {**stats, "layer": LAYER, "table": TABLE, "page": PAGE_URL, "credit": "NC DEQ Division of Marine Fisheries",
            "registry_ids": [SOURCE_ID]}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, meta=meta)
    print(f"{SOURCE_ID}: {stats['stations']} stations {stats['status_now']}; {stats.get('activities')} activities; "
          f"{stats['open']} open records of {stats['records']}; layer last edit {stats['layer_last_edit']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
