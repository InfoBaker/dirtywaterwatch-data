"""NYC DEP Waterbody Advisory System (New York City) -> data/build/events/nyc-dep-advisories.json

Source
  DEP's model-driven advisories for 45 harbor waterbodies (https://www.nyc.gov/site/dep/water/
  waterbody-advisories.page), served by the dashboard https://nycwaterbodyadvisory.azurewebsites.net/
  over an open JSON API: /api/advisory?advisoryType=WQ (and CSO) returns one row per waterbody,
  {occurredOn, waterbody {id, name, class, rainGauge}, duration, message, volume}. The dashboard
  (main-*.js) marks a waterbody "On Advisory" when duration > 0 and shows "on advisory until"
  occurredOn + duration hours. DEP: the system uses "10-years of hourly modeled bacterial data to
  project when and for how long a waterbody is likely to exceed its bacterial limit", driven by
  the rain gauges at the 14 WRRFs. These are official advisories from a model, not discharge
  reports; under 6 NYCRR 750-2.7(b)(2)(iii) they stand in for per-outfall CSO notices.
  The ArcGIS layers the dashboard names in /api/profile give each waterbody's polygon and
  attributes: waterbody_wq_advisory_staging (the WQ layer, live despite the name) and
  waterbody_csov2_advisory_staging (CSO layer; its Advisory flag is 1 on most waterbodies in dry
  weather, so it is recorded, not used). Credit: "NYC DEP Waterbody Advisory System".

Records
  - One record per advisory episode per waterbody, event_type "cso" (DEP's CSO advisories),
    status advisory_active while the API shows duration > 0, advisory_lifted afterwards;
    authority "NYC DEP Waterbody Advisory System"; advice_text = the API's message.
  - started_at = occurredOn of the first poll that showed the advisory (the model run hour, New York
    local time; the API gives no offset); ended_at = the "until" time (occurredOn + duration) while
    active. When a later poll shows "No Advisory", ended_at = the earlier of the last until and the
    occurredOn of that model run (raw._ended_at_basis); an advisory whose until passed while the
    module was not polling is closed at its until.
  - The API keeps no history (occurredOn is ignored as a parameter): data/build/
    nyc-dep-advisories-state.json is the archive of episodes. Do not delete it. Poll hourly.
  - Water slugs by name within New York (qualifiers such as "(Manhattan)", ", Lower" removed),
    checked against the polygon's centroid; lat/lon = the polygon's centroid, coord_precision_m =
    half its bounding-box diagonal. Polygons are cached in data/build/nyc-dep-waterbodies.json
    (refreshed every 7 days). The layer's WBID is not the API id: the two join by name.
  - advisoryType=CSO is fetched as well; it has matched WQ so far, and any difference is counted
    in meta.cso_type_differs (not turned into records).
  - volume (0 so far, unit not stated) stays in raw.
  - Raw API and layer responses are saved to data/raw/nyc-dep-advisories/ when they change.

Run (from pipeline/): python -m ingest.nyc_dep_advisories
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json
from ingest import ny_waters

SOURCE_ID = "nyc-dep-advisories"
API = "https://nycwaterbodyadvisory.azurewebsites.net/api/"
DASHBOARD = "https://nycwaterbodyadvisory.azurewebsites.net/"
PAGE = "https://www.nyc.gov/site/dep/water/waterbody-advisories.page"
LAYERS = {
    "wq": "https://services.arcgis.com/at3rDjch5X7i9Bag/arcgis/rest/services/waterbody_wq_advisory_staging/FeatureServer/0",
    "csov2": "https://services.arcgis.com/at3rDjch5X7i9Bag/arcgis/rest/services/waterbody_csov2_advisory_staging/FeatureServer/0",
}
STATE_PATH = BUILD_DIR / "nyc-dep-advisories-state.json"
GEOM_CACHE = BUILD_DIR / "nyc-dep-waterbodies.json"
TZ = ZoneInfo("America/New_York")
AUTHORITY = "NYC DEP Waterbody Advisory System"
LAYER_FIELDS = ["Advisory", "Expires", "Hours", "Class", "Activity2", "Indicator_", "Rain_Gauge", "Prim_RainG",
                "Sec_RainG", "Tri_RainG", "Rainfall_T", "peak_inten", "manual_ove", "WBID", "MapID", "Volume"]
TIME_NOTE = "occurredOn has no offset; read as New York local time (the dashboard shows it as local time)"


def norm_name(s: str | None) -> str:
    return " ".join(str(s or "").replace("\xa0", " ").split()).strip().lower()


def water_query(name: str) -> str:
    """'Hudson River (Manhattan)' -> 'Hudson River'; 'East River, Lower' -> 'East River'."""
    s = re.sub(r"\([^)]*\)", " ", name.replace("\xa0", " "))
    s = re.sub(r",\s*(upper|lower|inner|outer)\b", " ", s, flags=re.I)
    return " ".join(s.split())


def parse_local(s: str | None) -> datetime | None:
    if not s:
        return None
    dt = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    return dt.astimezone(TZ) if dt.tzinfo else dt.replace(tzinfo=TZ)


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(TZ).isoformat(timespec="seconds") if dt else None


# ---------------------------------------------------------------- fetch

def get_json(sess: requests.Session, url: str, params=None):
    r = sess.get(url, params=params, timeout=60)
    r.raise_for_status()
    return r.json(), r.content


def save_if_changed(state: dict, name: str, content: bytes) -> None:
    h = hashlib.sha256(content).hexdigest()
    if state.setdefault("raw_hashes", {}).get(name) != h:
        save_raw(SOURCE_ID, content, f"{name}.json")
        state["raw_hashes"][name] = h


def layer_attrs(sess, key: str, state: dict) -> dict:
    """normalised name -> attributes of the layer (no geometry)."""
    data, content = get_json(sess, LAYERS[key] + "/query", {"where": "1=1", "outFields": "*", "returnGeometry": "false",
                                                           "f": "json"})
    if "features" not in data:
        raise ValueError(f"{key} layer: {str(data)[:200]}")
    out = {}
    for f in data["features"]:
        a = f.get("attributes") or {}
        nm = norm_name(a.get("Waterbod_1"))
        if nm:
            out[nm] = {k: a.get(k) for k in LAYER_FIELDS if k in a}
    # saved without Creator_1 / Editor_1 (staff user names) and the other unlisted fields
    save_if_changed(state, f"layer-{key}", json.dumps(out, sort_keys=True).encode())
    return out


def geometries(sess) -> dict:
    """normalised name -> {centroid [lon, lat], bbox, radius_m} from the WQ layer, cached 7 days."""
    cache = read_json(GEOM_CACHE)
    if cache and datetime.now(UTC) - datetime.fromisoformat(cache["fetched_at"].replace("Z", "+00:00")) < timedelta(days=7):
        return cache["waterbodies"]
    try:
        from shapely.geometry import Polygon, MultiPolygon
        data, _ = get_json(sess, LAYERS["wq"] + "/query", {"where": "1=1", "outFields": "Waterbod_1,WBID",
                                                           "returnGeometry": "true", "outSR": "4326", "f": "json"})
        out = {}
        for f in data.get("features", []):
            rings = (f.get("geometry") or {}).get("rings") or []
            polys = [Polygon(r) for r in rings if len(r) >= 4]
            if not polys:
                continue
            g = MultiPolygon(polys).buffer(0) if len(polys) > 1 else polys[0].buffer(0)
            c = g.representative_point()   # inside the water, unlike a centroid of a curved river
            b = g.bounds
            radius = int(((b[2] - b[0]) * 84000) ** 2 + ((b[3] - b[1]) * 111000) ** 2) ** 0.5 / 2
            out[norm_name(f["attributes"].get("Waterbod_1"))] = {
                "point": [round(c.x, 6), round(c.y, 6)], "bbox": [round(x, 6) for x in b], "radius_m": int(radius)}
        write_json(GEOM_CACHE, {"fetched_at": now_iso(), "url": LAYERS["wq"], "waterbodies": out})
        return out
    except Exception as e:  # noqa: BLE001 - placement only; never fatal
        print(f"nyc-dep-advisories: polygons unavailable ({e})", file=sys.stderr)
        return (cache or {}).get("waterbodies", {})


# ---------------------------------------------------------------- episodes

def poll(state: dict, rows: list[dict], now: datetime, layer_wq: dict, layer_cso: dict) -> dict:
    eps = state.setdefault("episodes", {})
    active = state.setdefault("active", {})
    seen, stats = set(), {"rows": len(rows), "active_now": 0, "opened": 0, "lifted": 0}
    for row in rows:
        wb = row.get("waterbody") or {}
        wid = str(wb.get("id"))
        seen.add(wid)
        occ = parse_local(row.get("occurredOn"))
        dur = float(row.get("duration") or 0)
        nm = norm_name(wb.get("name"))
        snap = {"occurredOn": row.get("occurredOn"), "duration": row.get("duration"), "message": row.get("message"),
                "volume": row.get("volume"), "seen_at": iso(now)}
        cur = eps.get(active.get(wid)) if active.get(wid) else None
        if dur > 0 and occ is not None:
            until = occ + timedelta(hours=dur)
            stats["active_now"] += 1
            if cur and occ > parse_local(cur["until"]):
                close(cur, parse_local(cur["until"]), "the advisory's until passed before the next activation was seen", now)
                active.pop(wid, None)
                stats["lifted"] += 1
                cur = None
            if cur is None:
                rid = f"WQ-{wid}-{occ:%Y%m%dT%H%M}"
                cur = eps.setdefault(rid, {"rid": rid, "waterbody_id": wid, "name": wb.get("name"), "class": wb.get("class"),
                                           "rain_gauge": wb.get("rainGauge"), "started_at": iso(occ),
                                           "first_seen_at": iso(now), "history": [], "state": "active"})
                active[wid] = rid
                stats["opened"] += 1
            if not cur["history"] or {k: cur["history"][-1].get(k) for k in ("occurredOn", "duration", "message")} != \
                    {k: snap[k] for k in ("occurredOn", "duration", "message")}:
                cur["history"].append(snap)
            cur.update({"until": iso(until), "last_seen_at": iso(now), "message": row.get("message"),
                        "volume": row.get("volume"), "model_run": iso(occ),
                        "layer_wq": layer_wq.get(nm), "layer_csov2": layer_cso.get(nm)})
        elif cur:
            until = parse_local(cur["until"])
            end = min(until, occ) if occ else until
            cur["history"].append(snap)
            close(cur, end, ("the earlier of the last until and the model run that showed 'No Advisory' "
                             f"(occurredOn {row.get('occurredOn')})"), now)
            active.pop(wid, None)
            stats["lifted"] += 1
    for wid, rid in list(active.items()):      # an active waterbody the API no longer lists
        cur = eps.get(rid)
        if wid not in seen and cur and parse_local(cur["until"]) <= now:
            close(cur, parse_local(cur["until"]), "the waterbody left the API after its until passed", now)
            active.pop(wid, None)
            stats["lifted"] += 1
    return stats


def close(ep: dict, end: datetime, basis: str, now: datetime) -> None:
    ep.update({"state": "lifted", "ended_at": iso(end), "ended_at_basis": basis, "lifted_seen_at": iso(now)})


def to_record(ep: dict, geo: dict, fetched_at: str) -> dict:
    nm = norm_name(ep.get("name"))
    g = geo.get(nm) or {}
    pt = g.get("point")
    q = water_query(ep.get("name") or "")
    slugs, notes = ny_waters.match_waters(q, ["New York"], tuple(pt) if pt else None)
    raw = {k: ep.get(k) for k in ("waterbody_id", "name", "class", "rain_gauge", "first_seen_at", "last_seen_at",
                                  "lifted_seen_at", "until", "model_run", "volume", "history", "layer_wq", "layer_csov2")
           if ep.get(k) is not None}
    raw["_time_basis"] = TIME_NOTE
    raw["_started_at_basis"] = "occurredOn (model run hour) of the first poll that showed the advisory"
    if ep.get("ended_at_basis"):
        raw["_ended_at_basis"] = ep["ended_at_basis"]
    raw["_water"] = {"query": q, "via": "waterbody name within New York, checked against the polygon" if slugs else None,
                     "notes": notes or None}
    if g:
        raw["polygon_bbox"] = g.get("bbox")
    active = ep.get("state") == "active"
    return event(
        source_id=SOURCE_ID, source_record_id=ep["rid"], event_type="cso",
        status="advisory_active" if active else "advisory_lifted",
        discharger_id="ny-nyc-dep", discharger_name="New York City Department of Environmental Protection",
        waterbody_text=ep.get("name"), water_slugs=slugs, water_match="name" if slugs else "none",
        lat=pt[1] if pt else None, lon=pt[0] if pt else None, coord_source="source" if pt else None,
        coord_precision_m=g.get("radius_m") if pt else None,
        started_at=ep.get("started_at"), ended_at=ep.get("until") if active else ep.get("ended_at"),
        time_precision="hour", reported_at=None, published_at=None, source_updated_at=ep.get("model_run"),
        fetched_at=fetched_at, material=None, volume_gal=None, volume_text=None, estimate_flag="unknown",
        authority=AUTHORITY, advice_text=ep.get("message"), advice_window_hours=None, advice_window_basis=None,
        source_url=DASHBOARD, raw=raw,
    )


# ---------------------------------------------------------------- main

def main(argv=None) -> int:
    state = read_json(STATE_PATH, {}) or {}
    sess = requests.Session()
    sess.headers.update(HEADERS)
    now = datetime.now(UTC)
    try:
        wq, wq_bytes = get_json(sess, API + "advisory", {"advisoryType": "WQ"})
        if not isinstance(wq, list):          # an empty list is a valid answer: no advisory in effect
            raise ValueError(f"advisory API answered {str(wq)[:200]}")
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"nyc-dep-advisories: FAILED {e}", file=sys.stderr)
        return 1
    save_if_changed(state, "advisory-WQ", wq_bytes)
    errors, cso_differs = [], None
    try:
        cso, cso_bytes = get_json(sess, API + "advisory", {"advisoryType": "CSO"})
        save_if_changed(state, "advisory-CSO", cso_bytes)
        key = lambda r: (str((r.get("waterbody") or {}).get("id")), r.get("duration"), r.get("message"))  # noqa: E731
        cso_differs = len({key(r) for r in cso} ^ {key(r) for r in wq})
    except Exception as e:  # noqa: BLE001
        errors.append(f"advisoryType=CSO: {e}")
    layers = {}
    for k in LAYERS:
        try:
            layers[k] = layer_attrs(sess, k, state)
        except Exception as e:  # noqa: BLE001
            layers[k] = {}
            errors.append(f"layer {k}: {e}")
    try:
        sensors, s_bytes = get_json(sess, API + "sensors")
        save_if_changed(state, "sensors", s_bytes)
        state["sensors_last"] = [{k: s.get(k) for k in ("id", "name", "accumulatedLast24Hours", "active")} for s in sensors]
    except Exception as e:  # noqa: BLE001
        errors.append(f"sensors: {e}")
    stats = poll(state, wq, now, layers["wq"], layers["csov2"])
    state["last_poll_at"] = iso(now)
    state["polls"] = state.get("polls", 0) + 1
    write_json(STATE_PATH, state)

    geo = geometries(sess)
    fetched = now.isoformat(timespec="seconds").replace("+00:00", "Z")
    records = sorted((to_record(ep, geo, fetched) for ep in state["episodes"].values()),
                     key=lambda r: r["started_at"] or "", reverse=True)
    # the 45 waterbodies' placement, so a quiet day still shows the match rate
    placement = {}
    for row in wq:
        nm = (row.get("waterbody") or {}).get("name") or ""
        g = geo.get(norm_name(nm)) or {}
        slugs, _ = ny_waters.match_waters(water_query(nm), ["New York"], tuple(g["point"]) if g.get("point") else None)
        placement[nm.replace("\xa0", " ").strip()] = slugs
    wq_layer_on = sorted(n for n, a in layers["wq"].items() if a.get("Advisory"))
    meta = {**stats, "polls_total": state["polls"], "episodes": len(state["episodes"]),
            "model_run": (wq[0] if wq else {}).get("occurredOn"), "cso_type_differs": cso_differs,
            "wq_layer_advisory_on": wq_layer_on,
            "csov2_layer_advisory_flag_on": sum(1 for a in layers["csov2"].values() if a.get("Advisory")),
            "waterbodies": len(placement), "waterbodies_with_slug": sum(1 for v in placement.values() if v),
            "placement": placement, "rain_24h_in": {s["id"]: s["accumulatedLast24Hours"] for s in state.get("sensors_last", [])},
            "time_note": TIME_NOTE,
            "credit": "NYC DEP Waterbody Advisory System (model-based advisories, not discharge reports)"}
    write_events(SOURCE_ID, records, ok=True, error="; ".join(errors) or None, meta=meta)
    print(f"nyc-dep-advisories: {stats['rows']} waterbodies, {stats['active_now']} on advisory "
          f"(model run {meta['model_run']}); {len(records)} episodes kept; {meta['waterbodies_with_slug']} of "
          f"{meta['waterbodies']} waterbodies have a water slug" + (f"; errors: {errors}" if errors else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
