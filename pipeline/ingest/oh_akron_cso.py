"""City of Akron CSO overflow-status map -> data/build/events/oh-akron-cso-notifications.json.

Source (registry oh-akron-cso-notifications; research/oh/report.md section 2.3)
  The layer behind Akron Waterways Renewed's overflow status page (https://www.akronwaterwaysrenewed.com/
  overflow-status): https://agis.akronohio.gov/server/rest/services/City_of_Akron_CSO_Notifications/MapServer/0,
  no token. One row per site (28 on 2026-11-08: racks, storage basins, tunnels): name, point (lat, long and the
  geometry), status ("0" or "1"), icon (a marker colour), note ("The receiving water for this overflow is the Little
  Cuyahoga River."), updatetime (local wall-clock text, "2026-11-07 19:04:00", read in America/New_York), URL1 (the
  site's own PDF of overflow history) and URL2 (a daily-totals PDF). Akron's page says the real-time data "has not
  yet been reviewed for accuracy"; every record quotes it.
  Fields read: ESRI_OID, name, status, note, updatetime, URL1, URL2 and the point. Excluded: icon (a marker colour:
  status 0 is a green dot on Akron's map, which is never shown green here; a status-0 site is "no report", grey),
  lat and long (text copies of the point). No field names a person.

Records (a status snapshot turned into events; il_mwrd_possible_cso.py is the pattern)
  - A site whose status is "1" opens a cso record (status ongoing) keyed "<site>:<start>", started_at the row's
    updatetime at the first poll that showed it (the time Akron's system marked the overflow: it began at or before
    it), time_precision poll, raw.start_basis says so. When a later poll shows the site at "0", the record ends at
    that row's updatetime (raw.ended_at_precision poll; raw.end_bounds the last update at "1" and the first at "0":
    the overflow ended between them), status ended. No end is invented: a site that leaves the layer keeps its
    record open, with raw.left_layer_at.
  - Any other status value opens the same record with raw.code_undecoded (Akron does not publish what it means), so
    the status build gives it the site's caution only, never red.
  - Status "0" makes no record: no current report, grey. The PDFs (URL1, URL2) are linked in raw, not parsed.
  - Place: the layer's point (coord_source source); npdes_permit OH0023833 (Akron's CSO permit); outfall_id null
    (the site names do not map to the permit's outfall numbers in any public table); waterbody_text from the note.
  - Times: raw.time_zone America/New_York; reported_at and published_at null; source_updated_at the row's
    updatetime; fetched_at and raw._last_seen_in_source the poll.
  Privacy: only the fields above are requested and the raw save holds only them; common.event runs strip_personal.

State: data/build/oh-akron-cso-state.json (every overflow seen): the archive, do not delete.
Failures: a failed request writes ok=False and keeps the previous records.
Run from pipeline/: python -m ingest.oh_akron_cso [--file saved.json --out events.json]
Cadence: hourly with the refresh (an overflow shorter than the gap between polls can be missed).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "oh-akron-cso-notifications"
LAYER = "https://agis.akronohio.gov/server/rest/services/City_of_Akron_CSO_Notifications/MapServer/0"
PAGE_URL = "https://www.akronwaterwaysrenewed.com/overflow-status"
SAFE_FIELDS = ["ESRI_OID", "name", "status", "note", "updatetime", "URL1", "URL2"]
PERMIT = "OH0023833"
TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
STATE_PATH = BUILD_DIR / "oh-akron-cso-state.json"
CREDIT = "City of Akron, Akron Waterways Renewed overflow status map"
# Akron's own words on its overflow status page (read 2026-11-08), quoted as the record's advice
ADVICE = ("While this is the most current information available, the real-time data has not yet been reviewed for "
          "accuracy.")
CAVEAT = "Akron: the real-time data \"has not yet been reviewed for accuracy\"."
MATERIAL = "combined sewage and stormwater"
ACTIVE = "1"
QUIET = "0"


def site_key(a: dict) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", str(a.get("name") or "").lower()).strip("-")
    return s or f"oid-{a.get('ESRI_OID')}"


def local_time(v) -> str | None:
    """'2026-11-07 19:04:00' (Akron's wall clock) -> ISO with the Eastern offset; None when unreadable."""
    try:
        dt = datetime.strptime(str(v or "").strip(), "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None
    return dt.replace(tzinfo=TZ).isoformat()


def water_of(note: str | None) -> str | None:
    m = re.search(r"receiving water for this overflow is (?:the )?(.+?)\.?\s*$", str(note or ""), re.I)
    return m.group(1).strip() if m else None


def fetch(sess) -> dict:
    r = sess.get(LAYER + "/query", timeout=(20, 120),
                 params={"where": "1=1", "outFields": ",".join(SAFE_FIELDS), "outSR": 4326, "returnGeometry": "true",
                         "f": "json"})
    r.raise_for_status()
    doc = r.json()
    if "error" in doc:
        raise ValueError(f"layer answered an error: {doc['error']}")
    return doc


def rows_of(doc: dict) -> list[dict]:
    if not isinstance(doc.get("features"), list):
        raise ValueError("no features list in the layer's answer")
    out = []
    for f in doc["features"]:
        a = {k: (f.get("attributes") or {}).get(k) for k in SAFE_FIELDS}
        g = f.get("geometry") or {}
        a["_lat"], a["_lon"] = g.get("y"), g.get("x")
        out.append(a)
    return out


def poll(state: dict, rows: list[dict], now: str) -> dict:
    evs, open_ = state.setdefault("events", {}), state.setdefault("open", {})
    counts = {"opened": 0, "continued": 0, "ended": 0}
    seen = set()
    for a in rows:
        u = site_key(a)
        seen.add(u)
        st = str(a.get("status") if a.get("status") is not None else "").strip()
        upd = local_time(a.get("updatetime"))
        cur = open_.get(u)
        if st in ("", QUIET):
            if cur and st == QUIET:
                ev = evs[cur]
                ev.update(end=upd or now, end_basis="updatetime" if upd else "poll", end_seen_at=now)
                ev["end_bounds"] = [ev.get("last_active_update") or ev["start"], upd or now]
                del open_[u]
                counts["ended"] += 1
            continue
        if cur is None:
            start = upd or now
            cur = f"{u}:{re.sub(r'[^0-9T]', '', start[:16])}"
            evs[cur] = {"site": u, "start": start, "start_basis": "updatetime" if upd else "poll",
                        "first_seen_at": now, "statuses": []}
            open_[u] = cur
            counts["opened"] += 1
        else:
            counts["continued"] += 1
        ev = evs[cur]
        ev.pop("left_layer_at", None)
        ev.update(attributes=a, last_seen_at=now, last_active_update=upd or ev.get("last_active_update"))
        if st not in ev["statuses"]:
            ev["statuses"].append(st)
    for u in list(open_):
        if u not in seen:
            evs[open_[u]].setdefault("left_layer_at", now)
    return counts


def to_record(key: str, ev: dict) -> dict:
    a = ev["attributes"]
    ended = ev.get("end")
    raw = {"layer": {k: v for k, v in a.items() if not k.startswith("_")}, "time_zone": TZ_NAME, "state": "OH",
           "statuses_seen": ev["statuses"], "_first_seen_at": ev["first_seen_at"],
           "_last_seen_in_source": ev["last_seen_at"], "caveat": CAVEAT,
           "start_basis": ("the row's update time at the first poll that showed the site overflowing: when Akron's "
                           "system marked it, not when the overflow began, which the layer does not give; it began at "
                           "or before this time" if ev["start_basis"] == "updatetime" else
                           "the first poll that showed the site overflowing (the row gave no update time)"),
           "pdfs": [x for x in (a.get("URL1"), a.get("URL2")) if x]}
    if ended:
        raw.update(ended_at_precision="poll", end_bounds=ev.get("end_bounds"),
                   end_basis="the first update showing the site back at status 0; the overflow ended between the "
                             "last update at 1 and this one")
    if ev.get("left_layer_at"):
        raw["left_layer_at"] = ev["left_layer_at"]
    odd = [s for s in ev["statuses"] if s != ACTIVE]
    if odd:
        raw["code_undecoded"] = (f"Akron's layer gave status {', '.join(odd)}, whose meaning Akron does not publish "
                                 "(0 no overflow, 1 overflowing are the map's own legend)")
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="cso", status="ended" if ended else "ongoing",
        discharger_name="City of Akron", npdes_permit=PERMIT, outfall_id=None, outfall_name=a.get("name"),
        waterbody_text=water_of(a.get("note")),
        lat=a.get("_lat"), lon=a.get("_lon"), coord_source="source" if a.get("_lat") is not None else None,
        started_at=ev["start"], ended_at=ended, time_precision="poll",
        reported_at=None, published_at=None, source_updated_at=local_time(a.get("updatetime")),
        fetched_at=ev["last_seen_at"], material=MATERIAL, authority=CREDIT, advice_text=ADVICE,
        source_url=PAGE_URL, raw=raw)


def run(doc: dict, now: str, state_path: Path) -> tuple[list[dict], dict]:
    state = read_json(state_path, {}) or {}
    rows = rows_of(doc)
    counts = poll(state, rows, now)
    state["last_poll"] = {"at": now, "sites": len(rows),
                          "overflowing": sum(1 for r in rows if str(r.get("status") or "").strip() not in ("", QUIET)),
                          **counts}
    write_json(state_path, state)
    recs = [to_record(k, ev) for k, ev in state["events"].items()]
    recs.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "layer": LAYER, "poll": state["last_poll"], "credit": CREDIT,
            "caveat": CAVEAT,
            "empty_note": "No record means no site showed an overflow at any poll; status 0 is no report, never clean."}
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
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        doc = fetch(sess)
        rows = rows_of(doc)
    except (requests.RequestException, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"layer: {type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    save_raw(SOURCE_ID, json.dumps(rows), "json")
    recs, meta = run(doc, now, STATE_PATH)
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(recs)} records, {meta['poll']['overflowing']} of {len(rows)} sites overflowing now -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
