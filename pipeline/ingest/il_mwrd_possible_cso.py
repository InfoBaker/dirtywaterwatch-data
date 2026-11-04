"""MWRD "Possible CSO Events" map layer (Cook County) -> data/build/events/il-mwrd-possible-cso-events-layer.json.

Source
  The public layer behind MWRD's CSO notification map (registry il-mwrd-possible-cso-events-layer; research/il/
  report.md section 2.3): https://utility.arcgis.com/usrsvcs/servers/addf95280b254c1e8fe64dc8e35dfedc/rest/services/
  CSO/CSO_PossibleEvents/MapServer/0. No token. Fields: OBJECTID, OWNER, OUTFALL_CITY, WATERWAY_REACH, LOCATION,
  last_edited_date, GlobalID and the point. The service says: "This is the master CSO layer. Updates to CSO_EVENT are
  copied to an Archive layer nightly and the layer's fields are reset." MWRD's app says the map is "updated daily and
  reflects unconfirmed CSO and diversion activity", that "Not all CSO outfalls are equipped with monitoring
  equipment. Therefore, other CSOs may have occurred that are not reflected on the above map", and that the
  waterways "may contain disease-causing bacteria at any time". The archive is not public. The layer is empty on a day
  with no activity (it was empty when the research and this module were written, 2026-11-03 and -04).

  MWRD's own record of each event, per outfall with tide-gate open and close times (the CSO Event Synopsis Report,
  apps.mwrd.org/csoreports), is a form-and-session report server: by the owner's standing rule it is not worked
  around; the state text and the register name the request for an export or a feed. This layer is the part MWRD
  publishes openly.

Records (a status snapshot turned into events; pa_phila_csocast.py is the model)
  - One record per outfall per day of activity: an outfall that appears on the layer opens a cso record keyed by the
    outfall (owner, location and reach) and the Central-time day of its edit time. status "unknown": the layer marks
    possible, unconfirmed activity and gives neither a start nor an end. started_at is the layer's edit time for the
    outfall when it gives one (the time MWRD's system marked it: an observation time, not the overflow's start, which
    the map never gives; the overflow began at or before it), else the time this module first saw it; time_precision
    "poll"; raw.start_basis says so on every record. ended_at stays null: the nightly reset is not the end of a discharge,
    and the layer never says when one ended (the status build then applies its rule for a record with no end).
    raw.edits keeps every edit time seen, raw.first_seen_at and raw.last_seen_at our poll times, and raw.left_layer_at
    the first poll it was gone. A later day's appearance opens a new record.
  - A location at a reversal structure (the Wilmette gate, the Chicago River Controlling Works, O'Brien Lock) is a
    diversion of the waterway into Lake Michigan: waterbody_text "Lake Michigan", raw.diversion the structure.
  - Place: the point MWRD gives (outSR 4326; coord_source source); the nearest registry row of data/outfalls-il.json
    within PAIR_M gives the permit, the outfall id and the receiving water; else the owner's permit (il_mwrd).
  - Edit times are read as epoch milliseconds in UTC (ArcGIS editor tracking); raw.edit_time_note says so.
  Privacy: only the fields above are requested (outFields); none names a person; common.event runs strip_personal.

Failures: a request that fails or answers an error writes ok=False and keeps the previous records; the state file
(data/build/il-mwrd-possible-cso-state.json) is the archive of every appearance: do not delete it.

Run from pipeline/: python -m ingest.il_mwrd_possible_cso [--file saved.json --out events.json]
Cadence: hourly with the refresh (an appearance shorter than the gap between polls can be missed).
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, DATA_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json
from ingest import il_mwrd as M

SOURCE_ID = "il-mwrd-possible-cso-events-layer"
LAYER = ("https://utility.arcgis.com/usrsvcs/servers/addf95280b254c1e8fe64dc8e35dfedc/rest/services/CSO/"
         "CSO_PossibleEvents/MapServer/0")
APP_URL = ("https://mwrdgc.maps.arcgis.com/apps/instant/sidebar/index.html?appid=1a2bc307bc404d9e927528fd215da022")
FIELDS = ["OBJECTID", "OWNER", "OUTFALL_CITY", "WATERWAY_REACH", "LOCATION", "last_edited_date"]
STATE_PATH = BUILD_DIR / "il-mwrd-possible-cso-state.json"
TZ = ZoneInfo("America/Chicago")
PAIR_M = 150
AUTHORITY = "Metropolitan Water Reclamation District of Greater Chicago (Possible CSO Events map, unconfirmed)"
ADVICE = ("MWRD: the map \"reflects unconfirmed CSO and diversion activity\"; \"Not all CSO outfalls are equipped with "
          "monitoring equipment. Therefore, other CSOs may have occurred that are not reflected on the above map. "
          "Regardless of CSO activity, the Chicago Area Waterways may contain disease-causing bacteria at any time.\"")
EDIT_NOTE = "last_edited_date read as epoch milliseconds in UTC (ArcGIS editor tracking)"
MATERIAL = "combined sewage and stormwater"
MATERIAL_DIVERSION = "waterway water with combined sewage and stormwater, let back into Lake Michigan"


def unit_key(a: dict) -> str:
    s = "|".join(str(a.get(k) or "") for k in ("OWNER", "LOCATION", "WATERWAY_REACH")).lower()
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s)).strip("-") or f"objectid-{a.get('OBJECTID')}"


def edit_time(ms) -> datetime | None:
    try:
        v = float(ms)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    return datetime.fromtimestamp(v / 1000, UTC)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z") if dt else None


def fetch() -> tuple[dict, bytes]:
    r = requests.get(LAYER + "/query", headers=HEADERS, timeout=60,
                     params={"where": "1=1", "outFields": ",".join(FIELDS), "outSR": 4326, "returnGeometry": "true",
                             "f": "json"})
    r.raise_for_status()
    doc = r.json()
    if "error" in doc:
        raise ValueError(f"layer answered an error: {doc['error']}")
    return doc, r.content


def rows_of(doc: dict) -> list[dict]:
    if not isinstance(doc.get("features"), list):
        raise ValueError("no features list in the layer's answer")
    out = []
    for f in doc["features"]:
        a = {k: (f.get("attributes") or {}).get(k) for k in FIELDS}      # the safe fields only
        g = f.get("geometry") or {}
        a["_lat"], a["_lon"] = g.get("y"), g.get("x")
        out.append(a)
    return out


def _metres(lat1, lon1, lat2, lon2) -> float:
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return 6371000 * math.hypot(x, math.radians(lat2 - lat1))


def registry_rows() -> list[dict]:
    return (read_json(DATA_DIR / "outfalls-il.json", {}) or {}).get("outfalls", [])


def place(a: dict, reg: list[dict]) -> dict:
    """Permit, outfall, water and diversion for one layer row (module docstring)."""
    div = M.diversion(a.get("LOCATION"))
    out = {"permit": None, "outfall": None, "outfall_name": a.get("LOCATION"), "water": M.reach_water(a.get("WATERWAY_REACH")),
           "water_slug": None, "diversion": div[1] if div else None, "pair": None}
    if div:
        out["water"] = M.LAKE
        return out
    lat, lon = a.get("_lat"), a.get("_lon")
    best = None
    if lat is not None and lon is not None:
        for r in reg:
            if r.get("lat") is None:
                continue
            d = _metres(lat, lon, r["lat"], r["lon"])
            if d <= PAIR_M and (best is None or d < best[0]):
                best = (d, r)
    if best:
        r = best[1]
        out.update(permit=r["npdes_permit"], outfall=str(r["outfall"]), water=r.get("receiving_water_echo") or out["water"],
                   water_slug=r.get("water_slug"), pair=f"registry row {round(best[0])} m from the layer's point")
    else:
        perms = M.owner_permits(a.get("OWNER"))
        out["permit"] = perms[0] if len(perms) == 1 else None
    return out


def poll(state: dict, rows: list[dict], now: str) -> dict:
    """Open, continue and close the records of one snapshot; returns counts."""
    evs, open_ = state.setdefault("events", {}), state.setdefault("open", {})
    seen, counts = set(), {"opened": 0, "continued": 0, "left": 0}
    for a in rows:
        u = unit_key(a)
        seen.add(u)
        et = edit_time(a.get("last_edited_date"))
        day = (et or datetime.fromisoformat(now.replace("Z", "+00:00"))).astimezone(TZ).date().isoformat()
        cur = open_.get(u)
        if cur and evs[cur]["day"] != day:
            evs[cur].setdefault("left_layer_at", now)
            cur = None
        if cur is None:
            cur = f"{u}:{day}"
            if cur in evs:              # back on the same day after leaving: the same record
                evs[cur].pop("left_layer_at", None)
                evs[cur].setdefault("returns", []).append(now)
            else:
                evs[cur] = {"unit": u, "day": day, "first_seen_at": now, "edits": [], "attributes": {}}
                counts["opened"] += 1
            open_[u] = cur
        else:
            counts["continued"] += 1
        ev = evs[cur]
        ev["last_seen_at"] = now
        ev["attributes"] = {k: v for k, v in a.items()}
        if et and iso(et) not in ev["edits"]:
            ev["edits"].append(iso(et))
            ev["edits"].sort()
    for u in list(open_):
        if u not in seen:
            evs[open_[u]].setdefault("left_layer_at", now)
            del open_[u]
            counts["left"] += 1
    return counts


def to_record(key: str, ev: dict, reg: list[dict]) -> dict:
    a = ev["attributes"]
    p = place(a, reg)
    start = ev["edits"][0] if ev["edits"] else ev["first_seen_at"]
    raw = {"layer": {k: v for k, v in a.items() if not k.startswith("_")}, "first_seen_at": ev["first_seen_at"],
           "last_seen_at": ev["last_seen_at"], "edits": ev["edits"], "day": ev["day"],
           "start_basis": ("the time MWRD's map marked the outfall (the layer's edit time): when the activity was "
                           "observed, not when the overflow began, which the map does not give; it began at or before "
                           "this time" if ev["edits"]
                           else "the first poll that saw the outfall on the layer: when the activity was observed, not "
                                "when the overflow began, which the map does not give; it began at or before this time"),
           "end_note": "the layer gives no end; leaving it at the nightly reset is not the end of a discharge",
           "edit_time_note": EDIT_NOTE, "status_basis": "possible, unconfirmed activity (MWRD's map)"}
    if ev.get("left_layer_at"):
        raw["left_layer_at"] = ev["left_layer_at"]
    if ev.get("returns"):
        raw["returns"] = ev["returns"]
    if p["diversion"]:
        raw["diversion"] = p["diversion"]
    if p["pair"]:
        raw["registry_pair"] = p["pair"]
    lat, lon = a.get("_lat"), a.get("_lon")
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="cso", status="unknown",
        npdes_permit=p["permit"], outfall_id=p["outfall"], outfall_name=p["outfall_name"],
        waterbody_text=p["water"], water_slugs=[p["water_slug"]] if p["water_slug"] else [],
        water_match="outfall_registry" if p["water_slug"] else "none",
        lat=lat, lon=lon, coord_source="source" if lat is not None else None,
        started_at=start, ended_at=None, time_precision="poll",
        source_updated_at=ev["edits"][-1] if ev["edits"] else None,
        material=MATERIAL_DIVERSION if p["diversion"] else MATERIAL, authority=AUTHORITY, advice_text=ADVICE,
        source_url=APP_URL, raw=raw)


def run(doc: dict, now: str, state_path: Path, out: Path | None = None) -> tuple[list[dict], dict]:
    state = read_json(state_path, {}) or {}
    rows = rows_of(doc)
    counts = poll(state, rows, now)
    state["last_poll"] = {"at": now, "features": len(rows), **counts}
    write_json(state_path, state)
    reg = registry_rows()
    recs = [to_record(k, ev, reg) for k, ev in state["events"].items()]
    recs.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "layer": LAYER, "features_now": len(rows), "poll": state["last_poll"],
            "empty_note": ("An empty layer means MWRD's map shows no possible CSO activity at this poll; it is reset "
                           "nightly, and not every outfall is monitored."),
            "credit": M.CREDIT, "disclaimer": ADVICE}
    return recs, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="a saved layer answer (needs --out; its state is kept next to that file)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    now = now_iso()
    if a.file:
        if not a.out:
            ap.error("--file needs --out (only live polls reach the archive)")
        out = Path(a.out)
        recs, meta = run(json.loads(Path(a.file).read_text()), now, out.with_suffix(".state.json"))
        write_events(SOURCE_ID, recs, meta=meta, path=out)
        print(f"{SOURCE_ID}: {len(recs)} records (file) -> {out}")
        return 0
    try:
        doc, content = fetch()
        rows_of(doc)
    except (requests.RequestException, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"layer: {type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    if doc.get("features"):
        save_raw(SOURCE_ID, content, "json")
    recs, meta = run(doc, now, STATE_PATH)
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(recs)} records, {meta['features_now']} on the layer now -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
