"""Philadelphia Water Department CSOcast (pilot) -> data/build/events/pa-phila-csocast.json.

Source: the public ArcGIS layer behind https://water.phila.gov/maps/csocast/ (owner phillywatergis,
no licence on the item): https://services2.arcgis.com/POWz8dBwmjnei8fu/ArcGIS/rest/services/CSOCast_Layerboard/FeatureServer/0
164 CSO outfalls (Name such as D_02 / S_12A / C_FRA), Status, Status_Message, LastPoll, Latitude,
Longitude, Interceptor, Waterbody (D Delaware, S Schuylkill, C Cobbs, F Frankford, T Tacony,
P Pennypack), Street. The layer is current state only: no history, no start or end times.
Status_Message values: "Currently overflowing.", "Overflow in the past 72 hours." (the layer's
domain still says 24), "No overflow in the past 72 hours.", "Data is not currently available.".
The page calls CSOcast a pilot and says it "is not intended to be used as a water quality
notification system for recreation".

What the status is: PWD's page says CSOcast draws on its flow-monitoring network and a SWMM
watershed and wastewater conveyance model, which it calls "only an estimate of actual conditions"
(disclaimer in the page's app.js, a copy in data/raw/pa-phila-csocast/). Every record says so in
raw.status_basis: a model-and-monitor status for the outfall, not a measured or reported discharge.

Snapshot state machine (data/build/pa-phila-csocast-state.json keeps every outfall's last message
and every event; it is the archive, do not delete it). One event per overflow spell; all times are
CSOcast poll times (LastPoll), time_precision "poll":
- open: the first snapshot that says "Currently overflowing." opens a cso event (status ongoing),
  started_at = that snapshot's LastPoll (the overflow began at or before it; raw.started_after =
  the LastPoll of the last snapshot we saw clear, when there was one).
- continue: later "Currently overflowing." snapshots keep it ongoing (raw.last_overflowing_at).
- close: the first snapshot that no longer says so ("Overflow in the past 72 hours." or "No overflow
  in the past 72 hours.") ends it: ended_at = that snapshot's LastPoll (it ended at or before then;
  raw.ended_after = the last LastPoll that said overflowing).
- reappear: "Currently overflowing." after a close opens a new event.
- An outfall first seen as "Overflow in the past 72 hours." (or seen so after "No overflow ...")
  had an overflow that began and ended between our polls: an ended event with started_at null,
  ended_at = that LastPoll and raw.occurred_after = the earliest time it can have begun (the
  previous clear LastPoll, or 72 hours before). Repeats of that message add nothing.
- "Data is not currently available." is not an event: it is kept per outfall in meta.outfalls
  (state "no_data"), so the site can show "no data" as its own state. An event that was ongoing
  when its outfall went to "no data" becomes status unknown until the outfall reports again (a
  later "Currently overflowing." continues it; a clear message closes it).
- An outfall missing from the layer leaves an ongoing event unknown (raw.vanished).
Every transition is kept in raw.transitions with our fetch time and the LastPoll.
LastPoll is local wall-clock time stored as if it were UTC (its epoch equals LastPoll_DATE/TIME,
which are Eastern clock readings): it is converted from America/New_York (raw.last_poll_note);
an ambiguous fall-back hour is read as the first. A LastPoll more than 24 hours older than the fetch
marks the outfall stale in meta. A close whose LastPoll is earlier than the start (the clock went
back) uses our fetch time instead (raw.end_basis "fetch").

Places: coordinates from the layer (coord_source source). Permit and the inventory outfall come
from the nearest EPA CSO inventory outfall of PWD's three permits (data/outfalls-mid-atlantic.json;
CSOcast names are not the permit's outfall numbers) within 150 m: its water slug when it has one
(water_match outfall_registry), else the slug of the Waterbody code's water (D, S), water_match
"name". Cobbs, Frankford, Tacony and Pennypack creeks have no openboatlaunch record: no slug.
advice_window null; the page's 72-hour wording is the advice_text.

Run from pipeline/: python -m ingest.pa_phila_csocast
Cadence: hourly with the refresh (state changes are only seen if polled: a start or end is known to the
poll, and a gap longer than 72 hours can miss an overflow entirely).
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, strip_personal, write_events, write_json
from ingest import pa_waters

SOURCE_ID = "pa-phila-csocast"
LAYER = "https://services2.arcgis.com/POWz8dBwmjnei8fu/ArcGIS/rest/services/CSOCast_Layerboard/FeatureServer/0"
PAGE_URL = "https://water.phila.gov/maps/csocast/"
STATE_PATH = BUILD_DIR / "pa-phila-csocast-state.json"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "Philadelphia Water Department CSOcast (pilot)"
ADVICE = ("Waterways where a combined sewer outfall is overflowing are unsafe for any type of recreation, and may "
          "remain unsafe for recreation for a period of up to 72 hours following storm events, particularly in the "
          "Delaware and tidal Schuylkill rivers.")
DISCLAIMER = "CSOcast is not intended to be used as a water quality notification system for recreation (pilot program)."
STATUS_BASIS = ("Philadelphia Water Department's CSOcast status for this outfall. PWD says CSOcast draws on its "
                "flow-monitoring network and a SWMM watershed and wastewater conveyance model, which it calls \"only an "
                "estimate of actual conditions\". A model-and-monitor status, not a measured or reported discharge.")
TIME_BASIS = {
    "precision": ("poll: started_at and ended_at are CSOcast poll times (LastPoll) of the snapshots our hourly fetch "
                  "saw, not the overflow's own start and end"),
    "started_at": ("LastPoll of the first snapshot that said 'Currently overflowing.'; the overflow began at or before "
                   "it, after started_after when that is given"),
    "ended_at": ("LastPoll of the first snapshot that no longer said 'Currently overflowing.'; the overflow ended at or "
                 "before it, after ended_after"),
}
LAST_POLL_NOTE = ("LastPoll is Eastern wall-clock time stored as UTC (its epoch equals LastPoll_DATE/TIME); "
                  "read here as America/New_York.")
WATERBODY = {"D": "Delaware River", "S": "Schuylkill River", "C": "Cobbs Creek", "F": "Frankford Creek",
             "T": "Tacony Creek", "P": "Pennypack Creek"}
PLANTS = {
    "PA0026689": ("pa-pwd-northeast", "Philadelphia Water Department - Northeast Water Pollution Control Plant"),
    "PA0026662": ("pa-pwd-southeast", "Philadelphia Water Department - Southeast Water Pollution Control Plant"),
    "PA0026671": ("pa-pwd-southwest", "Philadelphia Water Department - Southwest Water Pollution Control Plant"),
}
REGISTRY_M = 150
STALE_H = 24


def kind_of(msg: str | None) -> str:
    m = (msg or "").strip().lower()
    if "currently overflowing" in m:
        return "overflowing"
    if m.startswith("no overflow"):
        return "none"
    if m.startswith("overflow in the past"):
        return "recent"
    if "not currently available" in m:
        return "no_data"
    return "unrecognised"


def last_poll(ms) -> datetime | None:
    """LastPoll epoch ms (local clock labelled UTC) -> aware America/New_York datetime."""
    if ms in (None, ""):
        return None
    wall = datetime.fromtimestamp(int(ms) / 1000, UTC).replace(tzinfo=None)
    return wall.replace(tzinfo=TZ)


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") if dt else None


def place(a: dict) -> dict:
    """Permit, inventory outfall and water for one CSOcast outfall (does not change between polls)."""
    lat, lon = a.get("Latitude"), a.get("Longitude")
    code = (a.get("Waterbody") or "").strip().upper()
    o, dist = pa_waters.nearest_outfall(lat, lon, set(PLANTS))
    info = {"waterbody_code": code, "waterbody_name": WATERBODY.get(code), "nearest_inventory_outfall": None}
    permit = None
    if o is not None:
        info["nearest_inventory_outfall"] = {"npdes_permit": o["npdes_permit"], "outfall": o["outfall"],
                                             "distance_m": dist, "receiving_water_echo": o.get("receiving_water_echo"),
                                             "water_slug": o.get("water_slug")}
        if dist is not None and dist <= REGISTRY_M:
            permit = o["npdes_permit"]
    slugs, how = [], "none"
    if permit and o.get("water_slug"):
        slugs, how = [o["water_slug"]], "outfall_registry"
    elif WATERBODY.get(code):
        pt = (lon, lat) if lat is not None else None
        s = pa_waters.named(WATERBODY[code], pt)
        if s:
            slugs, how = [s], "name"
    did, dname = PLANTS.get(permit, (None, None))
    info.update({"permit": permit, "discharger_id": did, "discharger_name": dname, "water_slugs": slugs, "water_match": how,
                 "inventory_outfall": o["outfall"] if permit else None})
    return info


def fetch(sess: requests.Session) -> tuple[list[dict], bytes]:
    r = sess.get(f"{LAYER}/query", params={"where": "1=1", "outFields": "*", "returnGeometry": "false",
                                           "f": "json", "resultRecordCount": 2000}, timeout=60)
    r.raise_for_status()
    js = r.json()
    if "features" not in js:
        raise ValueError(str(js)[:200])
    return [f.get("attributes") or {} for f in js["features"]], r.content


def recent_hours(msg: str | None) -> int:
    """'Overflow in the past 72 hours.' -> 72 (the layer's domain still says 24; the rows say 72)."""
    m = re.search(r"past\s+(\d+)\s+hours", msg or "", re.I)
    return int(m.group(1)) if m else 72


def _new_key(evs: dict, name: str, lp: datetime | None, now_dt: datetime) -> str:
    key = base = f"{name}-{(lp or now_dt.astimezone(TZ)):%Y%m%dT%H%M}"
    n = 2
    while key in evs:
        key, n = f"{base}-{n}", n + 1
    return key


def poll(state: dict, rows: list[dict], now: str) -> dict:
    """One snapshot of the layer into the state: outfall bookkeeping and the overflow events (module
    docstring). Returns this poll's counts."""
    outs = state.setdefault("outfalls", {})
    evs = state.setdefault("events", {})
    open_ = state.setdefault("open", {})
    now_dt = datetime.fromisoformat(now.replace("Z", "+00:00"))
    stats = Counter()
    seen = set()
    for a in rows:
        name = (a.get("Name") or "").strip()
        if not name:
            stats["unnamed"] += 1
            continue
        seen.add(name)
        msg = (a.get("Status_Message") or "").strip()
        kind = kind_of(msg)
        stats[kind] += 1
        lp = last_poll(a.get("LastPoll"))
        at = iso(lp) or now          # the source's poll time; our fetch time when the layer gives none
        prev = dict(outs.get(name) or {})   # a copy: the stored entry is updated below
        o = outs.setdefault(name, {"first_seen_at": now})
        if prev.get("status_message") != msg:
            o["changed_at"] = now
            o["changed_at_last_poll"] = iso(lp)
        o.update({"status_message": msg, "status_code": a.get("Status"), "state": kind, "last_poll": iso(lp),
                  "last_seen_at": now, "attributes": strip_personal(a)})
        o["stale"] = bool(lp and now_dt - lp.astimezone(UTC) > timedelta(hours=STALE_H))
        if kind == "no_data":
            o.setdefault("no_data_since", iso(lp) or now)
        else:
            o.pop("no_data_since", None)
        # the last state that said something about overflowing ("no data" says nothing), and the
        # last poll that said the outfall was not overflowing
        prev_known = prev.get("last_known_state", prev.get("state") if prev.get("state") != "no_data" else None)
        if kind in ("overflowing", "recent", "none"):
            o["last_known_state"] = kind
        if kind in ("recent", "none"):
            o["last_clear_poll"] = at

        key = open_.get(name)
        ev = evs.get(key) if key else None
        trans = {"fetched_at": now, "last_poll": iso(lp), "status_message": msg}
        if ev is not None and (not ev["transitions"] or ev["transitions"][-1]["status_message"] != msg):
            ev["transitions"].append(trans)
        if kind == "overflowing":
            if ev is None:                                            # open
                key = _new_key(evs, name, lp, now_dt)
                ev = evs[key] = {"outfall": name, "state": "ongoing", "started_at": at,
                                 "started_after": prev.get("last_clear_poll") if prev_known in ("none", "recent") else None,
                                 "reported_at": at, "transitions": [trans]}
                open_[name] = key
                stats["opened"] += 1
            else:                                                     # continue (also after "no data")
                if ev["state"] != "ongoing":
                    ev.setdefault("resumed", []).append({"at": at, "after": ev["state"]})
                    ev.pop("vanished", None)
                ev["state"] = "ongoing"
            ev["last_overflowing_at"] = at
        elif kind in ("recent", "none"):
            if ev is not None:                                        # close
                ev["state"] = "ended"
                if ev.get("started_at") and at < ev["started_at"]:
                    ev["ended_at"], ev["end_basis"] = iso(now_dt.astimezone(TZ)), "fetch"
                else:
                    ev["ended_at"], ev["end_basis"] = at, "last_poll"
                ev["ended_after"] = ev.get("last_overflowing_at")
                ev["closed_by"] = msg
                open_.pop(name, None)
                stats["closed"] += 1
            elif kind == "recent" and prev_known not in ("overflowing", "recent"):
                # began and ended between two polls (or before the first one we saw)
                hours = recent_hours(msg)
                floor = iso((lp or now_dt.astimezone(TZ)) - timedelta(hours=hours))
                after = prev.get("last_clear_poll") if prev_known == "none" else None
                key = _new_key(evs, name, lp, now_dt)
                ev = evs[key] = {"outfall": name, "state": "ended", "started_at": None, "ended_at": at,
                                 "end_basis": "last_poll", "reported_at": at, "first_seen_as_recent": True,
                                 "occurred_after": max(t for t in (floor, after) if t), "transitions": [trans]}
                stats["opened_recent"] += 1
        elif kind == "no_data":
            if ev is not None and ev["state"] == "ongoing":
                ev["state"] = "unknown"
                ev["no_data_since"] = at
        if ev is not None:
            ev["last_poll"] = iso(lp)
            ev["last_seen_at"] = now
    for name, key in list(open_.items()):
        if name not in seen and evs[key]["state"] == "ongoing":
            evs[key]["state"] = "unknown"
            evs[key]["vanished"] = {"last_seen_at": evs[key].get("last_seen_at"), "missing_at": now}
    state["polls"] = state.get("polls", 0) + 1
    state["last_poll_at"] = now
    return dict(stats)


def to_record(key: str, ev: dict, out: dict) -> dict:
    a = out.get("attributes") or {}
    p = out.get("place") or {}
    st = ev["state"]
    ended = ev.get("ended_at") if st == "ended" else None
    raw = {
        "outfall": a, "transitions": ev.get("transitions"),
        "status_basis": STATUS_BASIS, "time_basis": TIME_BASIS,
        "started_after": ev.get("started_after"),
        "start_basis": ("the first CSOcast snapshot whose LastPoll showed 'Currently overflowing.'; the overflow "
                        "began at or before it" if ev.get("started_at") else
                        "first seen as 'Overflow in the past 72 hours.': it began and ended between our polls; "
                        "the start was not observed (occurred_after is the earliest it can have begun)"),
        "occurred_after": ev.get("occurred_after"),
        "last_overflowing_at": ev.get("last_overflowing_at"),
        "ended_after": ev.get("ended_after") if ended else None,
        "end_basis": ({"last_poll": "the LastPoll of the first snapshot that no longer said 'Currently overflowing.'",
                       "fetch": "our fetch time of the first snapshot that no longer said 'Currently overflowing.' "
                                "(its LastPoll was earlier than the start)"}.get(ev.get("end_basis"))
                      if ended else None),
        "closed_by": ev.get("closed_by"), "resumed": ev.get("resumed"),
        "no_data_since": ev.get("no_data_since"), "vanished": ev.get("vanished"),
        "placement": {k: p.get(k) for k in ("waterbody_code", "waterbody_name", "nearest_inventory_outfall")},
        "last_poll_note": LAST_POLL_NOTE, "disclaimer": DISCLAIMER, "layer": LAYER,
    }
    stale = out.get("stale")
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="cso",
        status={"ongoing": "ongoing", "ended": "ended"}.get(st, "unknown"),
        discharger_id=p.get("discharger_id"), discharger_name=p.get("discharger_name") or "Philadelphia Water Department",
        npdes_permit=p.get("permit"), outfall_id=ev["outfall"], outfall_name=(a.get("Street") or "").strip() or None,
        waterbody_text=p.get("waterbody_name"), water_slugs=p.get("water_slugs") or [],
        water_match=p.get("water_match") or "none",
        lat=a.get("Latitude"), lon=a.get("Longitude"), coord_source="source" if a.get("Latitude") is not None else None,
        started_at=ev.get("started_at"), ended_at=ended, time_precision="poll",
        reported_at=ev.get("reported_at"), source_updated_at=ev.get("last_poll"),
        fetched_at=ev.get("last_seen_at") or now_iso(),
        material=None, volume_gal=None, volume_text=None, estimate_flag="unknown",
        authority=AUTHORITY, advice_text=ADVICE, advice_window_hours=None, advice_window_basis=None,
        source_url=PAGE_URL, raw=raw,
        parse_error=("the outfall's LastPoll is more than 24 hours old: the status may be stale" if stale and st == "ongoing" else None),
    )


def main() -> int:
    state = read_json(STATE_PATH, {}) or {}
    now = now_iso()
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        rows, content = fetch(sess)
        prev_n = len(state.get("outfalls") or {})
        if not rows or (prev_n and len(rows) < prev_n / 2):
            raise ValueError(f"{len(rows)} outfalls in the layer (previous poll {prev_n})")
    except Exception as e:
        write_events(SOURCE_ID, [], ok=False, error=f"layer: {e}")
        print(f"pa-phila-csocast: FAILED {e}", file=sys.stderr)
        return 1
    h = hashlib.sha256(json.dumps(sorted(rows, key=lambda a: str(a.get("Name"))), sort_keys=True).encode()).hexdigest()
    if state.get("raw_hash") != h:
        save_raw(SOURCE_ID, content, "json")
        state["raw_hash"] = h
    stats = poll(state, rows, now)
    for name, o in state["outfalls"].items():
        if "place" not in o or o.get("place_for") != [o["attributes"].get("Latitude"), o["attributes"].get("Longitude")]:
            o["place"] = place(o["attributes"])
            o["place_for"] = [o["attributes"].get("Latitude"), o["attributes"].get("Longitude")]
    write_json(STATE_PATH, state)

    records = [to_record(k, ev, state["outfalls"].get(ev["outfall"], {})) for k, ev in state["events"].items()]
    records.sort(key=lambda r: r["reported_at"] or "", reverse=True)
    outfalls_meta = {}
    for name, o in sorted(state["outfalls"].items()):
        p = o.get("place") or {}
        outfalls_meta[name] = {
            "state": o.get("state"), "status_message": o.get("status_message"), "last_poll": o.get("last_poll"),
            "stale": o.get("stale"), "no_data_since": o.get("no_data_since"), "changed_at": o.get("changed_at"),
            "present_in_layer": o.get("last_seen_at") == now,
            "lat": o["attributes"].get("Latitude"), "lon": o["attributes"].get("Longitude"),
            "street": o["attributes"].get("Street"), "waterbody_code": p.get("waterbody_code"),
            "npdes_permit": p.get("permit"), "discharger_id": p.get("discharger_id"),
            "water_slugs": p.get("water_slugs"), "water_match": p.get("water_match"),
            "open_event_id": f"{SOURCE_ID}:{state['open'][name]}" if name in state.get("open", {}) else None,
        }
    present = [m for m in outfalls_meta.values() if m["present_in_layer"]]
    meta = {
        "outfalls_in_layer": len(rows), "by_state": dict(Counter(m["state"] for m in present)),
        "stale_last_poll": sum(1 for m in present if m["stale"]),
        "with_water_slug": sum(1 for m in present if m["water_slugs"]),
        "water_match": dict(Counter(m["water_match"] for m in present)),
        "with_permit": sum(1 for m in present if m["npdes_permit"]),
        "poll": stats, "polls_total": state["polls"], "events_open": len(state.get("open", {})),
        "outfalls": outfalls_meta, "no_data_note": ("'Data is not currently available.' is kept per outfall here "
                                                   "(state no_data), not as an event."),
        "last_poll_note": LAST_POLL_NOTE, "disclaimer": DISCLAIMER, "layer": LAYER,
        "status_basis": STATUS_BASIS, "time_basis": TIME_BASIS, "time_precision": "poll",
        "covers_permits": sorted(PLANTS), "statewide": False,
    }
    path = write_events(SOURCE_ID, records, ok=True, meta=meta)
    print(f"pa-phila-csocast: {len(rows)} outfalls {meta['by_state']}, {meta['stale_last_poll']} stale; "
          f"{len(records)} events ({meta['events_open']} open); slug for {meta['with_water_slug']} -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
