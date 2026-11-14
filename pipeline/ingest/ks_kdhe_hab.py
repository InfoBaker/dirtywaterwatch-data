"""KDHE harmful algal bloom advisories (Kansas): the lakes KDHE's HAB status layer lists under a Hazard, Warning or
Watch, polled into dated bloom advisory records.

Source
  https://maps.kdhe.ks.gov/kdhe_doe/rest/services/HAB/HAB_County/MapServer/0 (registry: ks-kdhe-hab-status), the
  "Lake Points Statewide" layer of KDHE's HAB map: one point per listed lake with STATUS (Hazard, Warning, Watch;
  Lift for a lake just lifted), WATERBODY_ID, WATERBODY_NAME and StatusDate. Public ArcGIS map service, no key. Read
  2026-11-14: 16 points on 15 lakes (Kill Creek Park Lake has two), 8 under a Warning and 8 under a Watch, every
  StatusDate 2026-10-30 17:00 UTC: the date KDHE last updated its table (its HAB page shows the same date), not each
  advisory's start. KDHE's season runs April 1 to October 31, but an advisory can stay in effect after it, so the
  layer, not the calendar, says what is in effect. Layer 2 holds the lakes' outlines (lake zones), not read here.

Record rules (the accuracy-first clock: nothing is shown as KDHE's issue or lift time, since the layer gives neither)
  - One record per lake per spell on the list: source_record_id the WATERBODY_ID and the poll day the spell was first
    seen. event_type hab_advisory (the bloom category, plum), status advisory_active while the layer lists the lake
    under Hazard, Warning or Watch, raw.kdhe_level the current level and raw.levels each level with the poll that first
    showed it. advice_text names KDHE's level in KDHE's words ("Warning", "Watch", "Hazard").
  - started_at is the poll that first listed the lake (time_precision "poll"; raw.start_basis): on the first run that is
    every lake already listed, an advisory in effect whose issue date the layer does not give. raw.status_date is the
    layer's StatusDate, KDHE's own "as of" date for its table, kept as such.
  - Each poll that lists the lake confirms the record (raw._last_seen_in_source). The first poll that no longer lists it,
    or lists it as Lift, ends the record: status advisory_lifted, ended_at that poll, raw.ended_at_precision "poll"
    (an upper bound of KDHE's lift, which the layer does not date). A failed poll changes nothing.
  - The lake's point, kept to 0.001 degree; raw.time_zone from the point's county (pipeline/zones.py kansas_zone: the
    four western counties keep Mountain time).

Privacy: the layer holds no personal fields; only the four fields and the point are requested.
Run from pipeline/:  python -m ingest.ks_kdhe_hab [--file layer.json]
"""
from __future__ import annotations

import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import requests

import common
import zones
from common import HEADERS, event, now_iso, read_json, save_raw, write_events

SOURCE_ID = "ks-kdhe-hab-status"
LAYER = "https://maps.kdhe.ks.gov/kdhe_doe/rest/services/HAB/HAB_County/MapServer/0"
PAGE = "https://www.kdhe.ks.gov/777/Harmful-Algal-Blooms"
AUTHORITY = "Kansas Department of Health and Environment (harmful algal bloom advisory)"
LEVELS = {"hazard": "Hazard", "warning": "Warning", "watch": "Watch"}
ADVICE = {"Hazard": "KDHE lists this lake under a Hazard advisory for a harmful algal bloom.",
          "Warning": "KDHE lists this lake under a Warning for a harmful algal bloom.",
          "Watch": "KDHE lists this lake under a Watch for a harmful algal bloom."}


def lakes(doc: dict) -> dict[str, dict]:
    """{WATERBODY_ID: {name, level, status_date, lat, lon, points}} of the layer's listed lakes (not Lift)."""
    out: dict[str, dict] = {}
    for f in doc.get("features") or []:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        level = LEVELS.get(str(a.get("STATUS") or "").strip().lower())
        wid = str(a.get("WATERBODY_ID") or "").strip() or str(a.get("WATERBODY_NAME") or "").strip()
        if not level or not wid:
            continue
        sd = a.get("StatusDate")
        name = re.sub(r"\bSfl\b", "State Fishing Lake", str(a.get("WATERBODY_NAME") or "").strip().title())
        name = re.sub(r"\bCo\.\s", "County ", name)
        row = out.setdefault(wid, {"name": name, "level": level,
                                   "status_date": (datetime.fromtimestamp(sd / 1000, timezone.utc)
                                                   .strftime("%Y-%m-%dT%H:%M:%SZ") if sd else None),
                                   "lat": None, "lon": None, "points": 0})
        row["points"] += 1
        if row["lat"] is None and g.get("y") is not None:
            row["lat"], row["lon"] = round(float(g["y"]), 3), round(float(g["x"]), 3)
    return out


def run(doc: dict, prev: list[dict], at: str) -> tuple[list[dict], dict]:
    recs = {r["event_id"]: r for r in prev}
    open_by = {r["raw"].get("waterbody_id"): r for r in recs.values() if r["status"] == "advisory_active"}
    now = lakes(doc)
    stats = {"listed": len(now), "opened": 0, "confirmed": 0, "lifted": 0}
    for wid, x in now.items():
        r = open_by.get(wid)
        if r is None:
            tz = zones.kansas_zone(lat=x["lat"], lon=x["lon"])
            r = event(source_id=SOURCE_ID, source_record_id=f"{wid}-{at[:10]}", event_type="hab_advisory",
                      status="advisory_active", waterbody_text=x["name"], lat=x["lat"], lon=x["lon"],
                      coord_source="source", coord_precision_m=100, started_at=at, time_precision="poll",
                      authority=AUTHORITY, advice_text=ADVICE[x["level"]], source_url=PAGE,
                      raw={"state": "KS", "time_zone": tz, "waterbody_id": wid, "kdhe_level": x["level"],
                           "levels": [{"level": x["level"], "first_seen": at}], "status_date": x["status_date"],
                           "points_on_layer": x["points"], "layer": LAYER,
                           "start_basis": ("the first poll of KDHE's HAB layer that listed this lake; KDHE's issue "
                                           "date is not in the layer"),
                           "status_date_basis": "KDHE's date for its whole status table, not this advisory's start"})
            recs[r["event_id"]] = r
            stats["opened"] += 1
        else:
            stats["confirmed"] += 1
            if r["raw"].get("kdhe_level") != x["level"]:
                r["raw"]["levels"].append({"level": x["level"], "first_seen": at})
                r["raw"]["kdhe_level"] = x["level"]
                r["advice_text"] = ADVICE[x["level"]]
            r["raw"]["status_date"] = x["status_date"]
        r["raw"]["_last_seen_in_source"] = at
    for wid, r in open_by.items():
        if wid not in now:
            r.update(status="advisory_lifted", ended_at=at)
            r["raw"].update(ended_at_precision="poll", _unlisted_since=at,
                            end_basis="the first poll at which KDHE's layer no longer listed the lake; not KDHE's lift time")
            stats["lifted"] += 1
    for r in recs.values():
        r["fetched_at"] = at
    out = sorted(recs.values(), key=lambda r: (r.get("started_at") or "", r["event_id"]), reverse=True)
    stats["open"] = sum(1 for r in out if r["status"] == "advisory_active")
    return out, stats


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = common.EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = (read_json(path, {}) or {}).get("records") or []
    try:
        if "--file" in argv:
            doc = json.loads(Path(argv[argv.index("--file") + 1]).read_text())
        else:
            r = requests.get(f"{LAYER}/query", headers=HEADERS, timeout=(20, 120), params={
                "where": "1=1", "outFields": "STATUS,WATERBODY_ID,WATERBODY_NAME,StatusDate", "outSR": 4326,
                "f": "json", "returnGeometry": "true"})
            r.raise_for_status()
            doc = r.json()
            if "error" in doc:
                raise ValueError(str(doc["error"]))
            save_raw(SOURCE_ID, json.dumps(doc), "json")
    except (requests.RequestException, OSError, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
    recs, stats = run(doc, prev, now_iso())
    out = write_events(SOURCE_ID, recs, meta={
        "registry_ids": [SOURCE_ID], "url": LAYER, "page": PAGE, **stats,
        "credit": "Kansas Department of Health and Environment, Harmful Algal Blooms",
        "caveat": ("KDHE's map of lakes under a bloom Hazard, Warning or Watch. The map gives no date for each advisory: "
                   "each is dated to the first time this site read it listed and ends at the first read that no longer "
                   "lists it."),
        "cadence": "every refresh"})
    print(f"{SOURCE_ID}: {len(recs)} records ({stats}) -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
