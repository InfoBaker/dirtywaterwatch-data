"""Coastal Alabama Beach Monitoring Program (ADEM with the Alabama Department of Public Health): beach advisories from
ADEM's beach monitoring layer, polled into dated records -> data/build/events/al-adem-beach-monitoring.json

Source
  https://gis.adem.alabama.gov/arcgis/rest/services/BeachMonitoring_New/MapServer/15 (registry al-adem-beach-monitoring),
  the stations layer behind ADEM's beach monitoring map (https://adem.alabama.gov/coastal/ademadph-coastal-alabama-beach-monitoring-program),
  public, no key, no licence or terms shown. 25 stations on 2026-11-07 (Gulf of Mexico, Mobile Bay, Perdido, Arnica,
  Wolf and Weeks bays, Perdido Pass, Dog and Fowl rivers), each with its BEACON id (ID), its name (Descriptio), the
  water (WaterbodyN), its point (Latitude, Longitude), the results PDF (URL), the last sample date (Date, "11/03/26")
  and an advisory code (Advisory, a small integer). The program samples under the federal BEACH Act; the Alabama
  Department of Public Health issues the swim advisories (news releases) and lifts them when enterococci fall below
  104 per 100 mL.

The advisory code
  ADEM does not publish what the codes mean: the layer's renderer is one symbol, and the legend's "Beach Monitoring
  Sites" layer (classes Green, Yellow, Red, keyed on a text value) no longer answers (checked 2026-11-07). Every station
  showed 11 on 2026-11-07, when no Alabama swim advisory was reported in effect (the last reported, Wolf Bay at Orange
  Beach Waterfront Park, was lifted in September 2026). So 11 is read as "no advisory" (BASELINE) and any other code
  opens a record, on the side of caution, shown only as the site's caution; the record quotes the code and says its
  meaning is not published (an owner question: ask ADEM for the code list). The legend's
  green is never shown by this site.

Record rules (one record per station and advisory spell)
  - A station whose code is not BASELINE (and not empty) opens a beach_advisory record, status advisory_active, at the
    station's point, dated by the poll that first saw it (time_precision poll; the layer gives no advisory date, only
    the last sample date, kept in raw.last_sample_date). The water is ADEM's WaterbodyN (waterbody_text).
  - The layer gives no advisory, report or edit time, so reported_at and source_updated_at stay null; every poll that
    still shows the code re-confirms it (raw._last_seen_in_source and fetched_at are that poll's time; the first poll
    is raw._first_seen_at). A change to another non-baseline code is kept in raw.codes_seen, not a new record.
  - Never the health department's advisory: until ADEM publishes what its codes mean, every record carries
    raw.code_undecoded (the reason) and the status build shows it as the site's caution (rule code_caution), never red.
  - The first poll that shows BASELINE lifts it: status advisory_lifted, ended_at that poll's time (lifted at or before
    then; raw.end_basis).
  - A station missing from a poll changes nothing. A response with fewer than half the stations of the last good one,
    or none, fails the run (ok false, previous records kept).
  - meta.stations lists every station with its code and last sample date (the snapshot), so the state page can say
    when each was last sampled.
Privacy: the layer holds stations, not people; the fields read are FIELDS.
Run from pipeline/:  python -m ingest.al_adem_beaches [--file layer15.json]
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import requests

import common
from common import HEADERS, event, now_iso, read_json, save_raw, write_events

SOURCE_ID = "al-adem-beach-monitoring"
LAYER = "https://gis.adem.alabama.gov/arcgis/rest/services/BeachMonitoring_New/MapServer/15"
SITE = "https://adem.alabama.gov/coastal/ademadph-coastal-alabama-beach-monitoring-program"
FIELDS = ["OBJECTID", "ID", "Name", "Descriptio", "WaterbodyN", "Latitude", "Longitude", "File", "URL", "Date",
          "Advisory"]
AUTHORITY = ("Alabama Department of Public Health and Alabama Department of Environmental Management, Coastal Alabama "
             "Beach Monitoring Program")
BASELINE = {11}
MIN_RATIO = 0.5
CODE_NOTE = ("ADEM's layer gives the station advisory code {code}; ADEM does not publish what its codes mean. Every "
             "station showed 11 on 2026-11-07, when no swim advisory was reported in effect, so 11 is read as no "
             "advisory and any other code is shown as this site's caution, not as an advisory.")


def query() -> bytes:
    r = requests.get(f"{LAYER}/query", headers=HEADERS, timeout=(20, 300), params={
        "where": "1=1", "outFields": ",".join(FIELDS), "returnGeometry": "false", "orderByFields": "OBJECTID",
        "f": "json"})
    r.raise_for_status()
    d = r.json()
    if "error" in d:
        raise RuntimeError(f"ArcGIS error: {d['error']}")
    return r.content


def stations(body: bytes) -> list[dict]:
    return [{k: v for k, v in (f.get("attributes") or {}).items() if k in FIELDS}
            for f in json.loads(body).get("features") or []]


def sample_day(v) -> str | None:
    """The layer's Date ('11/03/26') as an ISO date."""
    s = str(v or "").strip()
    for fmt in ("%m/%d/%y", "%m/%d/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def code_of(a: dict) -> int | None:
    try:
        return int(a.get("Advisory"))
    except (TypeError, ValueError):
        return None


def flagged(a: dict) -> bool:
    c = code_of(a)
    return c is not None and c not in BASELINE


def name_of(a: dict) -> str:
    return " ".join(str(a.get("Descriptio") or a.get("Name") or a.get("ID") or "").split())


def open_record(a: dict, at: str) -> dict:
    st, code = str(a["ID"]), code_of(a)
    raw = {"state": "AL", "station": name_of(a), "beacon_id": st, "row": a, "code": code,
           "code_note": CODE_NOTE.format(code=code), "codes_seen": [{"code": code, "first_seen_at": at}],
           "last_sample_date": sample_day(a.get("Date")), "results_pdf": a.get("URL") or None,
           "start_basis": "the layer gives no advisory date: the poll that first showed the code",
           "code_undecoded": CODE_NOTE.format(code=code), "_first_seen_at": at, "_last_seen_in_source": at,
           "time_basis": ("started_at: the first poll that showed a code other than 11; ended_at: the first poll that "
                          "showed 11 again, so the advisory was lifted at or before then")}
    return event(
        source_id=SOURCE_ID, source_record_id=f"{st}-{at[:16]}", event_type="beach_advisory",
        status="advisory_active", waterbody_text=(a.get("WaterbodyN") or "").strip() or None,
        outfall_name=name_of(a) or None,
        lat=a.get("Latitude"), lon=a.get("Longitude"), coord_source="source" if a.get("Latitude") is not None else None,
        started_at=at, time_precision="poll", reported_at=None, source_updated_at=None, fetched_at=at,
        authority=AUTHORITY, advice_text=None, source_url=SITE, raw=raw)


def run(rows: list[dict], prev: list[dict], at: str) -> tuple[list[dict], dict]:
    recs = {r["event_id"]: r for r in prev}
    open_by = {r["raw"]["beacon_id"]: r for r in recs.values() if r["status"] == "advisory_active"}
    stats = {"stations": len(rows), "flagged": 0, "opened": 0, "lifted": 0}
    for a in rows:
        st = str(a.get("ID") or "")
        if not st:
            continue
        cur = open_by.get(st)
        if flagged(a):
            stats["flagged"] += 1
            if cur:
                cur["fetched_at"] = at
                cur["raw"]["_last_seen_in_source"] = at
                cur["raw"]["row"] = a
                cur["raw"]["last_sample_date"] = sample_day(a.get("Date"))
                if cur["raw"]["codes_seen"][-1]["code"] != code_of(a):
                    cur["raw"]["codes_seen"].append({"code": code_of(a), "first_seen_at": at})
                continue
            new = open_record(a, at)
            recs[new["event_id"]] = new
            stats["opened"] += 1
        elif cur and code_of(a) in BASELINE:
            cur["status"], cur["ended_at"], cur["fetched_at"] = "advisory_lifted", at, at
            cur["raw"]["end_basis"] = "the first poll that showed code 11 again: lifted at or before then"
            stats["lifted"] += 1
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats["open"] = sum(1 for r in out if r["status"] == "advisory_active")
    stats["codes"] = sorted({c for c in (code_of(a) for a in rows) if c is not None})
    return out, stats


def snapshot(rows: list[dict]) -> list[dict]:
    return [{"id": a.get("ID"), "name": name_of(a), "water": a.get("WaterbodyN"), "code": code_of(a),
             "lat": a.get("Latitude"), "lon": a.get("Longitude"),
             "last_sample_date": sample_day(a.get("Date")), "results_pdf": a.get("URL")} for a in rows]


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev_doc = read_json(path, {}) or {}
    prev = prev_doc.get("records") or []
    try:
        if "--file" in argv:
            body = Path(argv[argv.index("--file") + 1]).read_bytes()
        else:
            body = query()
            save_raw(SOURCE_ID, body, "json")
        rows = stations(body)
        last = (prev_doc.get("meta") or {}).get("stations")
        if not rows or (isinstance(last, int) and len(rows) < last * MIN_RATIO):
            raise RuntimeError(f"{len(rows)} stations in the layer (the last good run had {last})")
    except (requests.RequestException, RuntimeError, ValueError, OSError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    recs, stats = run(rows, prev, now_iso())
    out = write_events(SOURCE_ID, recs, meta={"registry_ids": [SOURCE_ID], "url": LAYER, "site": SITE, **stats,
                                              "station_list": snapshot(rows), "code_rule": CODE_NOTE.format(code="N"),
                                              "cadence": "every refresh (hourly); sampled weekly in season"})
    print(f"{SOURCE_ID}: {len(recs)} records ({stats['open']} in effect, {stats['stations']} stations, codes "
          f"{stats['codes']}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
