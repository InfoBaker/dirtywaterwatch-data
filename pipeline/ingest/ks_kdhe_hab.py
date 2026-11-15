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
  - One record per lake per spell on the list: source_record_id the WATERBODY_ID and the poll time the spell was
    first seen (to the second, so a lake lifted and listed again the same day is a new spell).
    event_type hab_advisory (the bloom category, plum), status advisory_active while the layer lists the lake
    under Hazard, Warning or Watch, raw.kdhe_level the current level and raw.levels each level with the poll that first
    showed it. advice_text names KDHE's level in KDHE's words ("Warning", "Watch", "Hazard").
  - started_at is the poll that first listed the lake (time_precision "poll"; raw.start_basis): on the first run that is
    every lake already listed, an advisory in effect whose issue date the layer does not give. raw.status_date is the
    layer's StatusDate, KDHE's own "as of" date for its table, kept as such.
  - Each poll that lists the lake confirms the record (raw._last_seen_in_source). The first poll that no longer lists it,
    or lists it as Lift, ends the record: status advisory_lifted, ended_at that poll, raw.ended_at_precision "poll"
    (an upper bound of KDHE's lift, which the layer does not date). A failed poll changes nothing: an answer with no features list, an error, a truncation or a status
    word KDHE does not use is a failed poll (check), never a lift of every lake.
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
from ingest import poll_periods
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
        if row["level"] != level:
            # two rows for one lake under different levels: the more severe stands (err on the side of safety), and
            # the record says the layer disagreed with itself (re-review P1-1)
            row.setdefault("conflicting_levels", sorted({row["level"]}))
            row["conflicting_levels"] = sorted({*row["conflicting_levels"], level})
            if SEVERITY[level] > SEVERITY[row["level"]]:
                row["level"] = level
        if row["lat"] is None and g.get("y") is not None:
            row["lat"], row["lon"] = round(float(g["y"]), 3), round(float(g["x"]), 3)
    return out


# Kansas's bounding box, a little wide: a listed lake's point outside it is not a usable point
KS_BOX = (36.9, 40.1, -102.1, -94.5)
SEVERITY = {"Hazard": 3, "Warning": 2, "Watch": 1}


def check(doc) -> None:
    """A layer answer good enough to say which lakes are listed: anything else is a failed read, never a lift of every
    advisory (Astra 2026-11-14 P1-1, re-review P1-1). A valid answer has a features list (possibly empty), no error and
    no truncation; every row is a dict with attributes, KDHE's STATUS word and the lake's identity (WATERBODY_ID or,
    failing that, its name); and every listed row (Hazard, Warning, Watch) has a numeric point inside Kansas. A row
    that would be silently dropped would lift that lake, so it fails the whole read instead."""
    if not isinstance(doc, dict) or "error" in doc or not isinstance(doc.get("features"), list):
        raise ValueError("the HAB layer's answer has no features list")
    if doc.get("exceededTransferLimit"):
        raise ValueError("the HAB layer's answer is truncated")
    for f in doc["features"]:
        if not isinstance(f, dict) or not isinstance(f.get("attributes"), dict):
            raise ValueError("a HAB layer row has no attributes")
        a = f["attributes"]
        st = str(a.get("STATUS") or "").strip().lower()
        if st not in (*LEVELS, "lift"):
            raise ValueError(f"unexpected HAB status {st!r}")
        if not (str(a.get("WATERBODY_ID") or "").strip() or str(a.get("WATERBODY_NAME") or "").strip()):
            raise ValueError("a HAB layer row has no lake identity")
        if st == "lift":
            continue
        g = f.get("geometry")
        try:
            y, x = float(g["y"]), float(g["x"])
        except (TypeError, KeyError, ValueError):
            raise ValueError("a listed HAB lake has no usable point") from None
        if not (KS_BOX[0] <= y <= KS_BOX[1] and KS_BOX[2] <= x <= KS_BOX[3]):
            raise ValueError("a listed HAB lake's point is outside Kansas")


def rounded(doc: dict) -> dict:
    """The answer with every point kept to 0.001 degree, as saved in data/raw."""
    out = {k: v for k, v in doc.items() if k != "features"}
    out["features"] = [{"attributes": f.get("attributes"),
                        "geometry": {k: round(float(v), 3) for k, v in (f.get("geometry") or {}).items()
                                     if k in ("x", "y") and v is not None}} for f in doc.get("features") or []]
    return out


def run(doc: dict, prev: list[dict], at: str) -> tuple[list[dict], dict]:
    check(doc)
    recs = {r["event_id"]: r for r in prev}
    open_by = {r["raw"].get("waterbody_id"): r for r in recs.values() if r["status"] == "advisory_active"}
    now = lakes(doc)
    stats = {"listed": len(now), "opened": 0, "confirmed": 0, "lifted": 0}
    for wid, x in now.items():
        r = open_by.get(wid)
        if r is None:
            tz = zones.kansas_zone(lat=x["lat"], lon=x["lon"])
            r = event(source_id=SOURCE_ID, source_record_id=f"{wid}-{re.sub(r'[^0-9]', '', at)[:14]}", event_type="hab_advisory",
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
            if poll_periods.revise_place(r, at, name=x["name"], lat=x["lat"], lon=x["lon"]):
                r["raw"]["time_zone"] = zones.kansas_zone(lat=x["lat"], lon=x["lon"])
        poll_periods.seen(r, at)
        if x.get("conflicting_levels"):
            r["raw"]["conflicting_levels"] = x["conflicting_levels"]
    for wid, r in open_by.items():
        if wid not in now:
            r.update(status="advisory_lifted", ended_at=at)
            r["raw"].update(ended_at_precision="poll", _unlisted_since=at,
                            end_basis="the first poll at which KDHE's layer no longer listed the lake; not KDHE's lift time")
            stats["lifted"] += 1
    for r in recs.values():
        r["fetched_at"] = at
        # the colour ages out CONFIRM_DAYS after the last poll that listed the lake, and a lift seen after a long
        # outage never colours the unread gap (build/status.py, keyed on this flag; re-review P1-2). Set on every
        # record, earlier saves included, so the rule applies to them at the next read
        r["raw"]["_poll_confirmed"] = True
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
            check(doc)
            save_raw(SOURCE_ID, json.dumps(rounded(doc)), "json")
        recs, stats = run(doc, prev, now_iso())
    except (requests.RequestException, OSError, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=str(e))
        print(f"{SOURCE_ID}: {e}", file=sys.stderr)
        return 1
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
