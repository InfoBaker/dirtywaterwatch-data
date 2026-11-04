"""AlexRenew CSO status layer (Alexandria, Virginia) -> data/build/events/va-alexrenew-cso.json.

Source
  AlexRenew's public ArcGIS view "Outfall Overflow Status" (the Public Notification System for
  Alexandria's combined sewer outfalls): https://services8.arcgis.com/gPxDs3sbKpglnSk7/arcgis/rest/
  services/Outfall_Overflow_Status_view/FeatureServer/0 . Four points (CSO 019 Potomac River /
  Oronoco Bay, CSO 020 Hunting Creek, CSO 021 and 022 Hooffs Run), each holding only its latest
  overflow: status (0 normal / 1 overflowing), status_text, timestamp_start and timestamp_end
  ("Last Overflow Start / End", true UTC epoch milliseconds). Web map description: "If an overflow
  event occurred in past 24 hours, the outfall indicator will turn red, otherwise it will remain
  green." Licence (item): provided as a public resource, no warranties.

Record rules
  - The layer is a snapshot, so this module keeps data/build/va-alexrenew-cso-state.json (do not
    delete it: it is the archive). One cso event per outfall and overflow start (source_record_id
    "019-20260101T1413"): an outfall turning red, or a new "Last Overflow Start", is a new event;
    started_at = timestamp_start, ended_at = timestamp_end when it is not before the start; status
    ongoing while the layer says overflowing with no end, else ended. Every poll's status is kept in
    raw.status_log only when it changes. An overflow already in the layer at the first poll is kept
    with raw.first_seen_already_in_layer (it was not seen turning red).
  - A last overflow of 60 s or less starting exactly on the hour at the same instant on several
    outfalls (CSO 021 and 022: 2026-01-01 06:00:00-06:01:00 UTC) is the layer's initial value, not
    an observed overflow: kept as event_type unknown with a note (it colours nothing).
  - Discharger va-alexrenew (VPDES VA0025160); outfall number from CSO_Name; coordinates from the
    layer (outSR 4326); receiving water from the name ("Potomac River") and the ECHO inventory row
    (data/outfalls-mid-atlantic.json, water_match outfall_registry when it has a slug).
  - advice_window_hours 24 (the map's red window; data/rules.json has the same by discharger).

Run from pipeline/: python -m ingest.va_alexrenew_cso
Cadence: every 15 minutes (the red window is 24 hours; a gap longer than that can miss an overflow
only when a second one replaces the first within the gap).
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
from ingest import va_waters

SOURCE_ID = "va-alexrenew-cso"
LAYER = ("https://services8.arcgis.com/gPxDs3sbKpglnSk7/arcgis/rest/services/"
         "Outfall_Overflow_Status_view/FeatureServer/0")
MAP_PAGE = "https://www.alexrenew.com/combined-sewer-overflow-status"
STATE_PATH = BUILD_DIR / "va-alexrenew-cso-state.json"
TZ = ZoneInfo("America/New_York")
PERMIT = "VA0025160"
DISCHARGER = {"discharger_id": "va-alexrenew",
              "discharger_name": "Alexandria Renew Enterprises (AlexRenew WRRF and Alexandria combined sewer outfalls)",
              "npdes_permit": PERMIT}
AUTHORITY = "AlexRenew Public Notification System (Outfall Overflow Status map)"
ADVICE = ("AlexRenew: if an overflow event occurred in the past 24 hours, the outfall indicator turns red, "
          "otherwise it remains green.")


def utc_ms(ms) -> datetime | None:
    """timestamp_start/_end: true UTC epoch milliseconds -> aware datetime in America/New_York."""
    if ms in (None, ""):
        return None
    return datetime.fromtimestamp(int(ms) / 1000, UTC).astimezone(TZ)


def outfall_of(name: str | None) -> str | None:
    m = re.match(r"\s*CSO\s*0*(\d{1,3})", name or "", re.I)
    return f"{int(m.group(1)):03d}" if m else None


def water_of(name: str | None) -> str | None:
    m = re.match(r"\s*CSO\s*\d+\s*[-–]\s*(.+)$", name or "")
    return m.group(1).strip() if m else None


def placeholder(rows: list[dict]) -> set[str]:
    """Outfalls whose last overflow looks like the layer's initial value: <= 60 s, starting on the
    hour, the same start on two or more outfalls."""
    starts: dict[int, list[str]] = {}
    for a in rows:
        s, e = a.get("timestamp_start"), a.get("timestamp_end")
        if s is None or e is None:
            continue
        if 0 <= int(e) - int(s) <= 60_000 and int(s) % 3_600_000 == 0:
            starts.setdefault(int(s), []).append(outfall_of(a.get("CSO_Name")) or str(a.get("OBJECTID")))
    return {o for v in starts.values() if len(v) >= 2 for o in v}


def poll(state: dict, feats: list[dict], now: str) -> dict:
    """Fold one layer snapshot into the state: returns counts."""
    evs = state.setdefault("events", {})
    outs = state.setdefault("outfalls", {})
    first_poll = not state.get("polls")
    attrs = [f.get("attributes") or {} for f in feats]
    ph = placeholder(attrs)
    stats = {"features": len(feats), "red": 0, "new_events": 0}
    for f in feats:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        of = outfall_of(a.get("CSO_Name")) or f"OID{a.get('OBJECTID')}"
        red = a.get("status") == 1 or (a.get("status_text") or "").lower().startswith("overflow")
        stats["red"] += int(red)
        prev = outs.get(of) or {}
        cur = {"status": a.get("status"), "status_text": a.get("status_text"), "start": a.get("timestamp_start"),
               "end": a.get("timestamp_end"), "name": a.get("CSO_Name"), "lat": g.get("y"), "lon": g.get("x"),
               "seen_at": now}
        changed = (prev.get("status"), prev.get("start"), prev.get("end")) != (cur["status"], cur["start"], cur["end"])
        outs[of] = cur
        start = utc_ms(a.get("timestamp_start"))
        if start is None:
            continue
        key = f"{of}-{start.astimezone(UTC):%Y%m%dT%H%M}"
        ev = evs.get(key)
        if ev is None:
            ev = evs[key] = {"outfall": of, "first_seen_at": now, "status_log": [],
                             "first_seen_already_in_layer": first_poll or not red,
                             "placeholder": of in ph}
            stats["new_events"] += 1
        if changed or not ev["status_log"]:
            ev["status_log"].append({"at": now, "status": a.get("status"), "status_text": a.get("status_text"),
                                     "timestamp_end": a.get("timestamp_end")})
        ev.update({"name": a.get("CSO_Name"), "start_ms": a.get("timestamp_start"), "end_ms": a.get("timestamp_end"),
                   "red_now": red, "last_seen_at": now, "lat": g.get("y"), "lon": g.get("x"),
                   "attributes": {k: v for k, v in a.items() if k not in ("Picture",)}})
        if red:
            ev["seen_red"] = True
    state["polls"] = state.get("polls", 0) + 1
    state["last_poll_at"] = now
    return stats


def to_record(key: str, ev: dict) -> dict:
    start, end = utc_ms(ev.get("start_ms")), utc_ms(ev.get("end_ms"))
    problems = []
    if end is not None and start is not None and end < start:
        problems.append("layer end before start (end left out)")
        end = None
    if ev.get("red_now") and end is None:
        status = "ongoing"
    elif end is not None or not ev.get("red_now"):
        status = "ended"
    else:
        status = "unknown"
    name = ev.get("name")
    of = ev.get("outfall")
    eo = va_waters.echo_outfall(PERMIT, of)
    water = water_of(name)
    slugs, wnotes = va_waters.match_waters(water, ["Alexandria"], (ev["lon"], ev["lat"]) if ev.get("lat") is not None else None)
    how = "name" if slugs else "none"
    if eo and eo.get("water_slug") and eo.get("match") in ("geometry+name", "geometry", "name_only"):
        if eo["water_slug"] not in slugs:
            slugs = [eo["water_slug"]] + slugs
        how = "outfall_registry"
    etype = "cso"
    if ev.get("placeholder"):
        etype = "unknown"
        problems.append("the layer's initial value (60 s or less, on the hour, same start on several outfalls), "
                        "not an observed overflow")
    raw = {"layer_attributes": ev.get("attributes"), "status_log": ev.get("status_log"),
           "first_seen_at": ev.get("first_seen_at"), "last_seen_at": ev.get("last_seen_at"),
           "seen_red": bool(ev.get("seen_red")), "first_seen_already_in_layer": ev.get("first_seen_already_in_layer"),
           "echo_outfall": {k: eo.get(k) for k in ("outfall", "receiving_water_echo", "water_slug", "match")} if eo else None,
           "water_placement": {"name": water, "notes": wnotes or None},
           "_time_basis": "timestamp_start/_end are UTC epoch milliseconds (shown in America/New_York)",
           "layer": LAYER}
    lat, lon = ev.get("lat"), ev.get("lon")
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type=etype, status=status, **DISCHARGER,
        outfall_id=of, outfall_name=name, waterbody_text=(eo or {}).get("receiving_water_echo") or water,
        water_slugs=slugs, water_match=how,
        lat=lat, lon=lon, coord_source="source" if lat is not None else None,
        started_at=start.isoformat(timespec="seconds") if start else None,
        ended_at=end.isoformat(timespec="seconds") if end else None, time_precision="minute",
        reported_at=None, published_at=None, source_updated_at=ev.get("layer_edit"), fetched_at=ev.get("last_seen_at") or now_iso(),
        material="combined sewage and stormwater", volume_gal=None, volume_text=None, estimate_flag="unknown",
        authority=AUTHORITY, advice_text=ADVICE, advice_window_hours=24,
        advice_window_basis="AlexRenew CSO status web map description (red for 24 hours after an overflow)",
        source_url=MAP_PAGE, raw=raw, parse_error="; ".join(problems) or None,
    )


def main(argv=None) -> int:
    state = read_json(STATE_PATH, {}) or {}
    now = now_iso()
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        r = sess.get(LAYER + "/query", params={"where": "1=1", "outFields": "*", "outSR": 4326, "f": "json"}, timeout=60)
        r.raise_for_status()
        d = r.json()
        if "error" in d or "features" not in d:
            raise ValueError(str(d)[:200])
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    h = hashlib.sha256(json.dumps(d.get("features"), sort_keys=True).encode()).hexdigest()
    if state.get("raw_hash") != h:
        save_raw(SOURCE_ID, r.content, "status.json")
        state["raw_hash"] = h
    edit = None
    try:
        info = sess.get(LAYER, params={"f": "json"}, timeout=30).json()
        ms = (info.get("editingInfo") or {}).get("dataLastEditDate")
        edit = datetime.fromtimestamp(ms / 1000, UTC).astimezone(TZ).isoformat(timespec="seconds") if ms else None
    except Exception:  # noqa: BLE001
        pass
    stats = poll(state, d["features"], now)
    for ev in state["events"].values():
        if ev.get("last_seen_at") == now:
            ev["layer_edit"] = edit
    write_json(STATE_PATH, state)
    records = sorted((to_record(k, ev) for k, ev in state["events"].items()),
                     key=lambda x: x["started_at"] or "", reverse=True)
    meta = {**stats, "polls_total": state["polls"], "layer": LAYER, "layer_data_last_edit": edit,
            "registry_ids": ["va-alexrenew-cso-status-layer"], "covers_permits": [PERMIT], "statewide": False,
            "timezone_note": "timestamps are UTC epoch milliseconds; shown in America/New_York",
            "license": "AlexRenew: provided as a public resource; no warranties (ArcGIS item licence)"}
    path = write_events(SOURCE_ID, records, ok=True, meta=meta)
    print(f"{SOURCE_ID}: {stats['features']} outfalls, {stats['red']} red now; {len(records)} events -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
