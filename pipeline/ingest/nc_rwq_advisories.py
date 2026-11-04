"""NC DEQ Division of Marine Fisheries coastal swimming advisories -> data/build/events/nc-rwq-advisories.json

Source
  NC DEQ Division of Marine Fisheries, Recreational Water Quality program: the public station layer
  https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services/RWQ_Advisory_EXTERNAL/FeatureServer/1
  ("Monitoring_Stations"; 225 ocean and sound stations on 2026-11-04), queried as JSON with points in
  WGS84. Each station has ASN (its station code, e.g. N88), DESCRIPTIO (the site), COUNTY, TIER (1 daily-use,
  2 less used), LOCATION (ocean / sound), EPA_ID and Status, a coded value:
    No Alert          "No Pending Swimming Advisory/Swimming Advisory"
    Pending Swimming Advisory   one sample at or over the limit; a resample decides (15A NCAC 18A .3403(a)(1))
    Advisory          "Swimming Advisory" (15A NCAC 18A .3403(a)(2), (b)(2); .3404(b) for a wastewater spill)
    Precautionary     "Precautionary Advisory": a storm-water discharge area, including areas affected by heavy
                      rain (15A NCAC 18A .3404(c), the storm drain and pipe signs)
  The layer is the current state only: no dates, no history. The station's "Data" link (a sample-results page
  on xapps.ncdenr.org) answered 404 on 2026-11-04 and is kept in raw only. No licence; credit NC DEQ Division
  of Marine Fisheries.

Snapshot rules (the previous events file is the state)
  - One record per spell of one Status at one station: event_id nc-rwq-advisories:<ASN>:<status code>:<UTC
    stamp of the layer edit that opened it>. Advisory -> beach_advisory, advisory_active (the authority's own
    advisory); Precautionary -> rain_advisory, advisory_active (the storm-water discharge sign); Pending Swimming
    Advisory -> beach_advisory, status unknown (a sample over the limit awaiting a resample; the status build
    shows it as an unconfirmed advisory). No Alert is no event: the stations are listed in meta.tracked.
  - started_at is the layer's last data edit (editingInfo.dataLastEditDate) on the run that first saw the
    status: the status was set at or before that edit and has held since; time_precision "poll". When a
    station leaves that status, the record is advisory_lifted with ended_at the
    layer's last edit on that run, which is when DEQ changed it or earlier. A status changed to another opens a
    new record. source_updated_at is the layer's last edit on every run, so an advisory the layer has not
    re-confirmed for 14 days stops colouring (docs/plan.md §2, re-confirmation).
  - A station missing from the layer leaves an open record open but says so (raw._missing_from_layer_since).
  - Coordinates from the layer (the station point); waterbody_text is the station description with "ocean" or
    "sound"; water_slugs empty (beach points are markers, not water fills).
  - No personal fields in this layer; common.strip_personal runs regardless.

Cadence: daily is enough (the program samples weekly in season, monthly off season); runs with the refresh.
Run from pipeline/:  python -m ingest.nc_rwq_advisories [--file layer.json --meta layer-meta.json]
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

SOURCE_ID = "nc-rwq-advisories"
LAYER = "https://services2.arcgis.com/kCu40SDxsCGcuUWO/arcgis/rest/services/RWQ_Advisory_EXTERNAL/FeatureServer/1"
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


def fetch(sess: requests.Session) -> tuple[list[dict], dict]:
    r = sess.get(f"{LAYER}/query", params={"where": "1=1", "outFields": "*", "outSR": 4326, "f": "json",
                                            "resultRecordCount": 2000}, timeout=(15, 90))
    r.raise_for_status()
    js = r.json()
    if "features" not in js:
        raise ValueError(f"no features: {str(js)[:200]}")
    save_raw(SOURCE_ID, r.content, "json")
    m = sess.get(LAYER, params={"f": "json"}, timeout=(15, 60))
    m.raise_for_status()
    return js["features"], m.json()


def build(features: list[dict], layer_meta: dict, fetched_at: str, prev_records: list[dict]) -> tuple[list[dict], dict]:
    edited = ms_iso((layer_meta.get("editingInfo") or {}).get("dataLastEditDate"))
    open_by_station: dict[str, dict] = {}
    records: dict[str, dict] = {}
    for p in prev_records:
        records[p["event_id"]] = p
        if p.get("ended_at") is None and p.get("status") in ("advisory_active", "unknown"):
            st = (p.get("raw") or {}).get("ASN")
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
        cur_code = ((cur or {}).get("raw") or {}).get("_status_code")
        if cur is not None and cur_code != code:          # the status this record stands for has ended
            close(cur, edited, fetched_at)
            cur = None
        if code == NO_ALERT or not code:
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
    for sid, cur in open_by_station.items():
        if sid not in seen and cur.get("ended_at") is None and cur["status"] in ("advisory_active", "unknown"):
            cur["raw"]["_missing_from_layer_since"] = cur["raw"].get("_missing_from_layer_since") or fetched_at
    out = sorted(records.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats = {"stations": len(seen), "layer_last_edit": edited,
             "status_now": dict(Counter(clean((f.get("attributes") or {}).get("Status")) for f in features)),
             "records": len(out), "open": sum(1 for r in out if r.get("ended_at") is None and
                                              r["status"] in ("advisory_active", "unknown")),
             "unknown_status_codes": dict(odd), "tracked": tracked}
    return out, stats


def open_record(a: dict, sid: str, code: str, lat, lon, edited: str | None, fetched_at: str) -> dict:
    et, status, label, rule = STATUS.get(code, ("beach_advisory", "unknown", code, None))
    site = clean(a.get("DESCRIPTIO")) or sid
    where = clean(a.get("LOCATION")).lower()
    raw = {k: v for k, v in a.items() if k not in ("GlobalID_2", "GlobalID_3")}
    raw.update({"_status_code": code, "_status_label": label, "_rule": rule, "_first_seen_at": fetched_at,
                "_last_seen_at": fetched_at, "_layer": LAYER,
                "_start_basis": ("the layer's last data edit on the run that first saw this status: the status was set "
                                 "at or before then (the layer gives no issue time)")})
    if code not in STATUS:
        raw["_unknown_status_code"] = True
    return event(
        source_id=SOURCE_ID, source_record_id=f"{sid}:{code.lower().replace(' ', '-')}:{stamp(edited, fetched_at)}",
        event_type=et, status=status,
        waterbody_text=f"{site} ({where})" if where in ("ocean", "sound") else site,
        water_slugs=[], water_match="none",
        lat=round(float(lat), 6) if lat is not None else None, lon=round(float(lon), 6) if lon is not None else None,
        coord_source="source" if lat is not None else None,
        started_at=edited or fetched_at, ended_at=None, time_precision="poll",
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
    rec["raw"]["_end_note"] = ("the layer's last data edit on the run that no longer showed this status: DEQ changed it "
                               "at or before then")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--file", help="a saved layer query response")
    ap.add_argument("--meta", help="a saved layer description (f=json), for its last edit time")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    try:
        if args.file:
            features = json.loads(Path(args.file).read_text()).get("features") or []
            meta_js = json.loads(Path(args.meta).read_text()) if args.meta else {}
        else:
            s = requests.Session()
            s.headers.update(HEADERS)
            features, meta_js = fetch(s)
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    prev = (read_json(EVENTS_DIR / f"{SOURCE_ID}.json", {}) or {}).get("records", [])
    records, stats = build(features, meta_js, fetched_at, prev)
    meta = {**stats, "layer": LAYER, "page": PAGE_URL, "credit": "NC DEQ Division of Marine Fisheries",
            "registry_ids": [SOURCE_ID]}
    path_notes_to_meta(records, meta)
    path = write_events(SOURCE_ID, records, ok=True, meta=meta)
    print(f"{SOURCE_ID}: {stats['stations']} stations {stats['status_now']}; {stats['open']} open records of "
          f"{stats['records']}; layer last edit {stats['layer_last_edit']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
