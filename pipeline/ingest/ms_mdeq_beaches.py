"""MDEQ Beach Monitoring Program (Mississippi Gulf Coast): beach advisories, closures and coastal algal-bloom advisories
from MDEQ's beach layer, polled into dated records.

Source
  https://mgis19.mdeq.ms.gov/arcgis/rest/services/Hosted/BeachMonitoringView/FeatureServer (registry:
  ms-mdeq-beach-monitoring), the layer behind beaches.mdeq.ms.gov, public, no key. Layer 0: 21 stations (points) with
  an advisory flag (isadvisory), a closure flag (isclosure), the event type (eventtype: Enterococci, HAB, Debris Clean
  Up), MDEQ's start date (startdate), the advisory or closure text (advisorydesc, closuredesc), the BEACON id (epa) and
  the last sample date. Layer 1: the beach segment each station speaks for (lines, the same stationnumber). The layer
  shows the current state only, with no end date; MDEQ's site lists past advisories through a script page this
  module does not read. Since 2026-09-08 routine advisories go only to this layer and to beach signs (MDEQ news release
  of that day).

Why not the generic readers: an advisory and a closure are two flags, and MDEQ gives its own start date; the generic
snapshot machine reads one state field and dates by poll, and the generic layer reader keeps a lifted advisory open.

Record rules (one record per station, flag and MDEQ start date)
  - A station with either flag set opens a record: beach_closure when isclosure is 1, else beach_advisory; an
    eventtype of HAB makes it hab_advisory (the bloom category), whichever flag. status advisory_active.
    started_at is MDEQ's startdate as a date (time_precision day: the layer's start is MDEQ's own date, kept apart
    from our poll); a flag with no startdate starts at the poll that first saw it (raw.start_basis says so).
    advice_text is MDEQ's advisorydesc or closuredesc. The point is the station's own (layer 0); the segment's line
    (layer 1) is in raw.segment with its west and east ends as MDEQ names them.
  - Every poll that still shows the flag re-confirms the record (raw._last_seen_in_source = the poll's fetch time;
    fetched_at too). The layer gives no report or edit time, so reported_at and source_updated_at stay null: a poll's
    time is never published as the source's.
  - The first poll that shows both flags clear lifts it: status advisory_lifted, ended_at that poll's time (the
    advisory was lifted at or before then; raw.end_basis); a new start date or another flag or event type at the same
    station ends the old record at that poll and opens a new one.
  - A station missing from a poll changes nothing (it is not re-confirmed). A response with fewer than half the
    stations of the last good one, or none, fails the run (ok=False, previous records kept).
  - History: the previous run's records are carried; the layer keeps none.
Privacy: the layer holds stations, not people; the fields read are listed in FIELDS.
Run from pipeline/:  python -m ingest.ms_mdeq_beaches [--file layer0.json [--segments layer1.json]]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import requests

import common
from common import HEADERS, event, now_iso, read_json, save_raw, write_events

SOURCE_ID = "ms-mdeq-beach-monitoring"
LAYER = "https://mgis19.mdeq.ms.gov/arcgis/rest/services/Hosted/BeachMonitoringView/FeatureServer"
SITE = "https://beaches.mdeq.ms.gov/"
FIELDS = ["objectid", "stationnumber", "name", "location", "county", "westend", "eastend", "epa", "active",
          "latitude", "longitude", "isadvisory", "isclosure", "lastsampledate", "eventtype", "advisorydesc",
          "closuredesc", "startdate"]
AUTHORITY = "Mississippi Department of Environmental Quality, Beach Monitoring Program"
MIN_RATIO = 0.5


def query(layer: int, fields: list[str], geometry: bool) -> bytes:
    r = requests.get(f"{LAYER}/{layer}/query", headers=HEADERS, timeout=60, params={
        "where": "1=1", "outFields": ",".join(fields), "returnGeometry": "true" if geometry else "false",
        "outSR": 4326, "geometryPrecision": 5, "f": "json"})
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        raise RuntimeError(f"ArcGIS error: {d['error']}")
    return r.content


def stations(body: bytes) -> list[dict]:
    out = []
    for f in json.loads(body).get("features") or []:
        a = {k: v for k, v in (f.get("attributes") or {}).items() if k in FIELDS}
        g = f.get("geometry") or {}
        if a.get("latitude") is None and isinstance(g.get("y"), (int, float)):
            a["latitude"], a["longitude"] = g["y"], g["x"]
        out.append(a)
    return out


def segments(body: bytes | None) -> dict[str, dict]:
    out = {}
    for f in (json.loads(body).get("features") or []) if body else []:
        a = f.get("attributes") or {}
        paths = (f.get("geometry") or {}).get("paths")
        if a.get("stationnumber") and paths:
            out[str(a["stationnumber"])] = {"paths": [[[round(x, 5), round(y, 5)] for x, y in p] for p in paths]}
    return out


def start_day(v) -> str | None:
    """MDEQ's startdate as a date: text ('11/2/2026 09:12:00', '11/2/2026', ISO) or epoch milliseconds."""
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return datetime.fromtimestamp(v / 1000, UTC).date().isoformat()
    s = str(v).strip()
    for fmt in ("%m/%d/%Y %H:%M:%S", "%m/%d/%Y %H:%M", "%m/%d/%Y", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(s[:19] if "T" in s else s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def flagged(a: dict) -> bool:
    return str(a.get("isadvisory")) == "1" or str(a.get("isclosure")) == "1"


def type_of(a: dict) -> str:
    if re.search(r"\bhab\b|algal|bloom", str(a.get("eventtype") or ""), re.I):
        return "hab_advisory"
    return "beach_closure" if str(a.get("isclosure")) == "1" else "beach_advisory"


def open_record(a: dict, seg: dict | None, at: str) -> dict:
    st, et = str(a["stationnumber"]), type_of(a)
    day = start_day(a.get("startdate"))
    closure = str(a.get("isclosure")) == "1"
    raw = {"state": "MS", "station": a.get("name"), "row": a, "segment": {**(seg or {}), "west_end": a.get("westend"), "east_end": a.get("eastend")},
           "flag": "closure" if closure else "advisory", "beacon_id": a.get("epa"),
           "start_basis": ("MDEQ's start date on the layer" if day else
                           "the layer gives no start date: the poll that first showed the flag"),
           "time_basis": ("started_at: MDEQ's start date (day); ended_at: the first poll that showed both flags clear, "
                          "so the advisory was lifted at or before then"),
           "first_flagged_at": at, "_last_seen_in_source": at}
    return event(
        source_id=SOURCE_ID, source_record_id=f"{st}-{et}-{day or at[:16]}", event_type=et, status="advisory_active",
        lat=a.get("latitude"), lon=a.get("longitude"), coord_source="source" if a.get("latitude") is not None else None,
        started_at=day or at, time_precision="day" if day else "poll", fetched_at=at,
        authority=AUTHORITY, advice_text=(a.get("closuredesc") if closure else a.get("advisorydesc")) or None,
        source_url=SITE, raw=raw)


def poll_times(r: dict) -> None:
    """The layer gives no report or edit time. A record carried from before 2026-11-07 had a poll's time as
    reported_at and source_updated_at (SOL wave 2 P1-6): both become null and the later of them is the last poll that
    showed the flag (raw._last_seen_in_source)."""
    seen = [x for x in (r.get("source_updated_at"), r.get("reported_at"), r["raw"].get("_last_seen_in_source")) if x]
    if r.get("source_updated_at") or r.get("reported_at"):
        r["raw"]["_last_seen_in_source"] = max(seen)
        r["reported_at"] = r["source_updated_at"] = None


def run(rows: list[dict], segs: dict[str, dict], prev: list[dict], at: str) -> tuple[list[dict], dict]:
    recs = {r["event_id"]: r for r in prev}
    for r in recs.values():
        poll_times(r)
    open_by = {r["raw"]["row"]["stationnumber"]: r for r in recs.values() if r["status"] == "advisory_active"}
    stats = {"stations": len(rows), "flagged": 0, "opened": 0, "lifted": 0, "replaced": 0}
    for a in rows:
        st = str(a.get("stationnumber") or "")
        if not st:
            continue
        cur = open_by.get(st)
        if flagged(a):
            stats["flagged"] += 1
            new = open_record(a, segs.get(st), at)
            same = cur and (cur["event_id"] == new["event_id"] or (
                cur["event_type"] == new["event_type"] and not start_day(a.get("startdate"))
                and not start_day(cur["raw"]["row"].get("startdate"))))     # no MDEQ date: the poll's key stays
            if same:
                cur["fetched_at"] = at
                cur["raw"]["_last_seen_in_source"] = at
                cur["raw"]["row"] = a
                continue
            if cur:                                     # another start date, flag or type at the station
                cur["status"], cur["ended_at"] = "advisory_lifted", at
                cur["raw"]["ended_at_precision"] = "poll"   # an end seen by a poll is exact: never rounded to the day's end (SOL wave2 P1-2)
                cur["raw"]["end_basis"] = f"replaced at this poll by {new['event_id']}"
                stats["replaced"] += 1
            if new["event_id"] in recs:                 # a closed record whose flag came back: the same advisory
                old = recs[new["event_id"]]
                old.update(status="advisory_active", ended_at=None, fetched_at=at)
                old["raw"]["_last_seen_in_source"] = at
                old["raw"].setdefault("reopened_at", []).append(at)
                continue
            recs[new["event_id"]] = new
            stats["opened"] += 1
        elif cur:
            cur["status"], cur["ended_at"], cur["fetched_at"] = "advisory_lifted", at, at
            cur["raw"]["ended_at_precision"] = "poll"       # exact at the poll that first showed the flags clear
            cur["raw"]["end_basis"] = "the first poll that showed both flags clear: lifted at or before then"
            stats["lifted"] += 1
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats["open"] = sum(1 for r in out if r["status"] == "advisory_active")
    return out, stats


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev_doc = read_json(path, {}) or {}
    prev = prev_doc.get("records") or []
    try:
        if "--file" in argv:
            body = Path(argv[argv.index("--file") + 1]).read_bytes()
            seg = Path(argv[argv.index("--segments") + 1]).read_bytes() if "--segments" in argv else None
        else:
            body = query(0, FIELDS, True)
            save_raw(SOURCE_ID, body, "json")
            try:
                seg = query(1, ["stationnumber", "name"], True)
            except (requests.RequestException, RuntimeError, ValueError):
                seg = None                                  # the segments are context; the stations decide
        rows = stations(body)
        last = (prev_doc.get("meta") or {}).get("stations")
        if not rows or (isinstance(last, int) and len(rows) < last * MIN_RATIO):
            raise RuntimeError(f"{len(rows)} stations in the layer (the last good run had {last})")
    except (requests.RequestException, RuntimeError, ValueError, OSError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    recs, stats = run(rows, segments(seg), prev, now_iso())
    out = write_events(SOURCE_ID, recs, meta={"registry_ids": [SOURCE_ID, "ms-hab"], "url": LAYER, **stats,
                                              "cadence": "every refresh (hourly); MDEQ posts advisories here first"})
    print(f"{SOURCE_ID}: {len(recs)} records ({stats['open']} in effect, {stats['stations']} stations) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
