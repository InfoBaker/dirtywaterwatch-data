"""NEORSD CSO alerts map (Cleveland and its suburbs) -> data/build/events/oh-neorsd-cso-notification-map.json.

Source (registry oh-neorsd-cso-notification-map; research/oh/report.md section 2.3)
  The public map service behind the Northeast Ohio Regional Sewer District's "CSO Alerts: map and status of outfalls"
  page (https://www.neorsd.org/cso-alerts-map-and-status-of-outfalls/): https://utility.arcgis.com/usrsvcs/servers/
  d1477ea79422426b90560e015ce2bad9/rest/services/Public/CSONotificationApp_PROD/MapServer, no token. Layer 4
  "Monitored CSO Outfall Location" (24 outfalls NEORSD meters, EVENTMONITORING 1) and layer 5 "CSO Outfall Location"
  (88 outfalls whose overflows NEORSD's model gives) hold every outfall once; layers 0 to 3 (overflow within the
  past 24 and 72 hours) are subsets of them and are not read. The service declares its dates in America/New_York
  (dateFieldsTimeReference) and answers epoch milliseconds; they are read as UTC instants (a day-bounded record
  then runs from local midnight to local midnight, as NEORSD's CSO-002 does), and every record carries
  raw.time_zone America/New_York.

  Fields read (outFields; the safe list SAFE_FIELDS): OBJECTID, PERMITNUMBER (Ohio EPA's outfall code, 3PA00002 and
  the CSO number), CSONUMBER, LOCATION, RECIEVINGWATER [sic], WWTP (the treatment plant's service area),
  CONTROLMEASURE, EVENTMONITORING, NOMODELWWOVERFLOW (the typical-year number of wet-weather overflows),
  YEAR_COMPLETED, the last wet-weather overflow (WWOVERFLOWSTART, END, VOLUME in million gallons, DURATION in hours),
  the last dry-weather overflow (DWOVERFLOW...), the last overflow (LASTOVERFLOW..., always one of the two: read only
  as a check), PUBLICACCESSAREA, CURRENTLYOVERFLOWING ("CSO is Overflowing at Time of Data Update"),
  and the point. Excluded: LAST_EDITED_DATE (never a reliable update time: below), CREATED_USER and LAST_EDITED_USER (staff account names), PHOTO (a link
  to a photograph, not needed), LATITUDE and LONGITUDE (text copies of the point), CREATED_DATE, OVERFLOWDATE,
  WWOVERFLOW and DWOVERFLOW (2016 to 2018 dates of an older scheme, superseded by the start and end fields).

  The item is published "for display purposes only": a display term, credited and quoted in every record.

Records (a status snapshot turned into events: the layer keeps only the latest wet- and dry-weather overflow per
outfall, so each poll is compared with the archive; il_mwrd_possible_cso.py is the pattern)
  - One cso record per outfall, weather kind and start: source_record_id "<CSO number>:<wet|dry>:<start UTC>". The
    first poll records the overflows the layer shows then (back to 2013 for some dry-weather ones): they are
    NEORSD's own dated reports. A new start on a later poll opens a new record.
  - started_at the layer's start; ended_at the layer's end when it gives one (raw.ended_at_precision minute, or day
    below); status ended. The record is ongoing only while the layer gives no end for that start and marks the
    outfall overflowing at its update. A published end is never erased: a flag at a later update does not remove it,
    and an end the layer revises replaces the earlier one (raw.end_revisions keeps each). When the layer shows a newer
    start for the same outfall and kind while an earlier record still has no end (an update missed between polls),
    the earlier record ends at that newer start, at or before which it must have ended (raw.ended_at_precision bound,
    raw._end_basis says so; its volume is not known). No other end is ever invented.
  - Precision: minute. A start and end both at local midnight a day or more apart with a shorter duration, or none
    (CSO-002: 17 October 00:00 to 18 October 00:00, 0.45 hours), is a day-bounded report: started_at and ended_at
    are the dates (the end the day before the end midnight), time_precision day, raw.day_bounds says so. A
    dry-weather overflow whose start and end are the same minute and which gives no volume or duration keeps both as
    published (raw.end_note says so).
  - raw.measurement "metered by NEORSD" (layer 4) or "modelled by NEORSD" (layer 5); the authority line says which.
    A modelled overflow is read as NEORSD's own report of an overflow, labelled as modelled. estimate_flag measured
    or estimated accordingly; volume_gal from million gallons.
  - advice_text NEORSD's own words on its alerts page, quoted (the 48-hour advice of public health officials); the
    site's own notes stay in raw.
  - Place: the layer's point (coord_source source); npdes_permit OH0043991 (NEORSD's CSO permit) and outfall_id
    the CSO number, which is EPA's outfall number for the same outfall (all 112 pair; data/outfalls-oh.json);
    waterbody_text the receiving water as NEORSD names it.
  - Times: reported_at, published_at and source_updated_at null: LAST_EDITED_DATE read three hours after the fetch
    on 2026-11-08 (an editor-tracking offset), so it is never used; raw._last_seen_in_source and fetched_at the last
    poll that showed the overflow.
  Privacy: only SAFE_FIELDS are requested and only they are stored (the raw save is the filtered rows); LOCATION
  is a street description of the outfall: a house number in it ("Behind 1234 W. 114th St.") becomes
  "[house number removed]" (scrub_location); common.event runs strip_personal.

State: data/build/oh-neorsd-cso-state.json (every overflow seen): the archive, do not delete.
Failures: a failed request writes ok=False and keeps the previous records.
Run from pipeline/: python -m ingest.oh_neorsd_cso [--file layer4.json --file layer5.json --out events.json]
Cadence: hourly with the refresh (the layer is updated hourly).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from common import BUILD_DIR, HEADERS, HOUSE_NUMBER_REMOVED, event, now_iso, read_json, save_raw, write_events, write_json

SOURCE_ID = "oh-neorsd-cso-notification-map"
SERVICE = ("https://utility.arcgis.com/usrsvcs/servers/d1477ea79422426b90560e015ce2bad9/rest/services/Public/"
           "CSONotificationApp_PROD/MapServer")
PAGE_URL = "https://www.neorsd.org/cso-alerts-map-and-status-of-outfalls/"
LAYERS = {4: "metered", 5: "modelled"}
SAFE_FIELDS = ["OBJECTID", "PERMITNUMBER", "CSONUMBER", "LOCATION", "RECIEVINGWATER", "WWTP", "CONTROLMEASURE",
               "EVENTMONITORING", "NOMODELWWOVERFLOW", "YEAR_COMPLETED",
               "LASTOVERFLOWSTART", "LASTOVERFLOWEND", "LASTOVERFLOWVOLUME", "LASTOVERFLOWDURATION",
               "WWOVERFLOWSTART", "WWOVERFLOWEND", "WWOVERFLOWVOLUME", "WWOVERFLOWDURATION",
               "DWOVERFLOWSTART", "DWOVERFLOWEND", "DWOVERFLOWVOLUME", "DWOVERFLOWDURATION",
               "PUBLICACCESSAREA", "CURRENTLYOVERFLOWING"]
KINDS = {"wet": "WW", "dry": "DW"}
PERMIT = "OH0043991"
TZ_NAME = "America/New_York"
TZ = ZoneInfo(TZ_NAME)
STATE_PATH = BUILD_DIR / "oh-neorsd-cso-state.json"
CREDIT = "Northeast Ohio Regional Sewer District, CSO alerts map"
DISPLAY_TERMS = "NEORSD publishes the map's data \"for display purposes only\"; credited to NEORSD, with a link to the map."
# NEORSD's own words on its CSO alerts page (read 2026-11-08), quoted as the record's advice
ADVICE = ("When a CSO is overflowing, public health officials advise against recreational contact with water bodies for "
          "at least two days (48 hours) after a rain event.")
MATERIAL = "combined sewage and stormwater"
MATERIAL_DRY = "combined sewage (a dry-weather overflow)"
TIME_NOTE = ("the layer's epoch milliseconds read as UTC instants; the service declares its dates in America/New_York, "
             "and its day-bounded records run from local midnight to local midnight")

# a house number before a street: "Behind 1234 W. 114th St.", "Southeast of 5678 Example Rd.", "9999 Example Road".
# A number after a direction is a numbered street ("E. 81 St.", "W. 57th St.") and stays; so do distances
# ("Approx. 300 Yds") and route numbers ("I-71")
_HOUSE = re.compile(r"(?<![\w./&'-])(\d{2,6}[A-Za-z]?)(?=\s+(?:[NSEW]\.?\s*)?(?:\d+(?:st|nd|rd|th)|[A-Z][a-z]))")
_STREET_BEFORE = re.compile(r"(?:\b[NSEW]\.?|\b(?:North|South|East|West))\s*$")
_UNIT_AFTER = re.compile(r"\s+(?:yds?|yards?|ft|feet|foot|miles?|meters?)\b", re.I)


def scrub_location(v: str | None) -> str | None:
    if not v:
        return v

    def cut(m: re.Match) -> str:
        if _STREET_BEFORE.search(v[:m.start()]) or _UNIT_AFTER.match(v[m.end():]):
            return m.group(0)
        return HOUSE_NUMBER_REMOVED
    return " ".join(_HOUSE.sub(cut, v).split())


def water_name(v: str | None) -> str | None:
    s = " ".join(str(v or "").split())
    return s or None


def utc(ms) -> datetime | None:
    try:
        v = float(ms)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(v / 1000, UTC) if v > 0 else None


def iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z") if dt else None


def fetch(sess) -> dict[int, dict]:
    out = {}
    for lid in LAYERS:
        r = sess.get(f"{SERVICE}/{lid}/query", timeout=(20, 180),
                     params={"where": "1=1", "outFields": ",".join(SAFE_FIELDS), "outSR": 4326,
                             "returnGeometry": "true", "f": "json"})
        r.raise_for_status()
        doc = r.json()
        if "error" in doc:
            raise ValueError(f"layer {lid} answered an error: {doc['error']}")
        out[lid] = doc
    return out


def rows_of(doc: dict, measurement: str) -> list[dict]:
    """The safe fields of each feature, the point as _lat/_lon, and the layer's measurement kind."""
    if not isinstance(doc.get("features"), list):
        raise ValueError("no features list in the layer's answer")
    out = []
    for f in doc["features"]:
        a = {k: (f.get("attributes") or {}).get(k) for k in SAFE_FIELDS}
        a["LOCATION"] = scrub_location(a.get("LOCATION"))
        g = f.get("geometry") or {}
        a["_lat"], a["_lon"] = g.get("y"), g.get("x")
        a["_measurement"] = measurement
        out.append(a)
    return out


def cso_number(a: dict) -> str | None:
    m = re.search(r"(\d+)", str(a.get("CSONUMBER") or ""))
    return m.group(1).zfill(3) if m else None


def _local_midnight(dt: datetime) -> bool:
    t = dt.astimezone(TZ)
    return t.hour == 0 and t.minute == 0 and t.second == 0


def times(start: datetime, end: datetime | None, dur) -> dict:
    """started_at, ended_at, precision and the day-bound note for one overflow (module docstring)."""
    if end and end > start and _local_midnight(start) and _local_midnight(end) \
            and end - start >= timedelta(days=1) and (dur is None or float(dur) < (end - start).total_seconds() / 3600):
        last_day = (end.astimezone(TZ) - timedelta(days=1)).date()
        return {"started_at": start.astimezone(TZ).date().isoformat(), "ended_at": last_day.isoformat(),
                "time_precision": "day", "ended_at_precision": "day",
                "day_bounds": ("the layer gives local midnight to local midnight and a shorter or no duration: the "
                               "overflow fell within these days, its hours not given")}
    return {"started_at": iso(start), "ended_at": iso(end) if end else None, "time_precision": "minute",
            "ended_at_precision": "minute" if end else None, "day_bounds": None}


def poll(state: dict, rows: list[dict], now: str) -> dict:
    """Open or update one record per outfall, kind and start seen in this snapshot; returns counts.

    An overflow is running only while the layer gives no end for its start and marks the outfall overflowing; a
    published end is never erased (a changed one is kept in end_revisions). When the layer shows a newer start for
    the same outfall and kind, an earlier record still without an end is closed at that start: the earlier overflow
    ended at or before it (ended_at_precision bound; a missed poll can no longer leave it running)."""
    evs = state.setdefault("events", {})
    counts = {"opened": 0, "updated": 0, "seen": 0, "bounded": 0}
    for a in rows:
        num = cso_number(a)
        if not num:
            continue
        overflowing = a.get("CURRENTLYOVERFLOWING") not in (None, 0, 0.0)
        last = utc(a.get("LASTOVERFLOWSTART"))
        for kind, p in KINDS.items():
            st = utc(a.get(f"{p}OVERFLOWSTART"))
            if st is None:
                continue
            key = f"{num}:{kind}:{iso(st)}"
            end = utc(a.get(f"{p}OVERFLOWEND"))
            running = overflowing and last == st and end is None
            cur = evs.get(key)
            if cur is None:
                cur = evs[key] = {"cso": num, "kind": kind, "start": iso(st), "first_seen_at": now, "end_revisions": []}
                counts["opened"] += 1
            else:
                counts["seen"] += 1
            new_end = iso(end)
            if new_end:
                if cur.get("end") and new_end != cur["end"]:
                    cur["end_revisions"].append({"end": cur["end"], "basis": cur.get("end_basis") or "published",
                                                 "replaced_at": now})
                    counts["updated"] += 1
                cur["end"], cur["end_basis"] = new_end, "published"
            cur.update(running=running and not cur.get("end"), volume_mg=a.get(f"{p}OVERFLOWVOLUME"),
                       duration_h=a.get(f"{p}OVERFLOWDURATION"), last_seen_at=now,
                       attributes={k: v for k, v in a.items() if not k.startswith(("WW", "DW", "LAST"))})
            for k2, ev2 in evs.items():          # an earlier overflow of this outfall and kind left without an end
                if k2 != key and ev2["cso"] == num and ev2["kind"] == kind and not ev2.get("end") \
                        and ev2["start"] < iso(st):
                    ev2.update(end=iso(st), end_basis="bound", running=False, end_bound_seen_at=now)
                    counts["bounded"] += 1
    return counts


def to_record(key: str, ev: dict) -> dict:
    a = ev["attributes"]
    st = datetime.fromisoformat(ev["start"].replace("Z", "+00:00"))
    end = datetime.fromisoformat(ev["end"].replace("Z", "+00:00")) if ev.get("end") else None
    bound = ev.get("end_basis") == "bound"
    t = times(st, end, None if bound else ev.get("duration_h"))
    measured = a.get("_measurement") == "metered"
    raw = {"layer": {k: v for k, v in a.items() if not k.startswith("_")}, "time_zone": TZ_NAME,
           "weather": "wet weather" if ev["kind"] == "wet" else "dry weather",
           "measurement": "metered by NEORSD" if measured else "modelled by NEORSD",
           "volume_mg": ev.get("volume_mg"), "duration_h": ev.get("duration_h"),
           "_first_seen_at": ev["first_seen_at"], "_last_seen_in_source": ev["last_seen_at"],
           "time_note": TIME_NOTE, "display_terms": DISPLAY_TERMS, "state": "OH",
           "update_time_note": ("the layer's LAST_EDITED_DATE is not used as the source's update time: it reads hours "
                                "after the polls that read it")}
    if t["ended_at_precision"]:
        raw["ended_at_precision"] = "bound" if bound else t["ended_at_precision"]
    if bound:
        raw["_end_basis"] = (f"NEORSD's map later showed a newer overflow at this outfall, starting {ev['end']}; this "
                             "one ended at or before then (its own end was not seen)")
    if t["day_bounds"]:
        raw["day_bounds"] = t["day_bounds"]
    if ev.get("end_revisions"):
        raw["end_revisions"] = ev["end_revisions"]
    if end is not None and end == st and ev.get("volume_mg") is None:
        raw["end_note"] = "the layer gives the same minute for start and end and no volume or duration"
    if ev.get("running"):
        raw["end_note"] = "NEORSD's layer marked the outfall overflowing at its update; no end is given yet"
    vol = ev.get("volume_mg")
    gal = int(round(float(vol) * 1_000_000)) if isinstance(vol, (int, float)) and vol > 0 and not bound else None
    status = "ongoing" if ev.get("running") else ("ended" if t["ended_at"] else "unknown")
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type="cso", status=status,
        discharger_name="Northeast Ohio Regional Sewer District", npdes_permit=PERMIT, outfall_id=ev["cso"],
        outfall_name=" ".join(x for x in (a.get("CSONUMBER"), a.get("LOCATION")) if x) or None,
        waterbody_text=water_name(a.get("RECIEVINGWATER")),
        lat=a.get("_lat"), lon=a.get("_lon"), coord_source="source" if a.get("_lat") is not None else None,
        started_at=t["started_at"], ended_at=t["ended_at"], time_precision=t["time_precision"],
        reported_at=None, published_at=None, source_updated_at=None, fetched_at=ev["last_seen_at"],
        material=MATERIAL if ev["kind"] == "wet" else MATERIAL_DRY,
        volume_gal=gal, volume_text=f"{vol} million gallons" if vol is not None and not bound else None,
        estimate_flag=("measured" if measured else "estimated") if gal else "unknown",
        authority=f"{CREDIT} ({'metered' if measured else 'modelled'} by NEORSD)", advice_text=ADVICE,
        source_url=PAGE_URL, raw=raw)


def run(docs: dict[int, dict], now: str, state_path: Path) -> tuple[list[dict], dict]:
    state = read_json(state_path, {}) or {}
    rows = [r for lid, doc in docs.items() for r in rows_of(doc, LAYERS[lid])]
    counts = poll(state, rows, now)
    state["last_poll"] = {"at": now, "outfalls": len(rows), **counts}
    write_json(state_path, state)
    recs = [to_record(k, ev) for k, ev in state["events"].items()]
    recs.sort(key=lambda r: (r["started_at"] or "", r["event_id"]), reverse=True)
    meta = {"registry_ids": [SOURCE_ID], "service": SERVICE, "layers": {str(k): v for k, v in LAYERS.items()},
            "poll": state["last_poll"], "credit": CREDIT, "display_terms": DISPLAY_TERMS, "time_note": TIME_NOTE}
    return recs, meta


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", action="append", help="saved layer answers, layer 4 first, then layer 5 (needs --out)")
    ap.add_argument("--out")
    a = ap.parse_args(argv)
    now = now_iso()
    if a.file:
        if not a.out or len(a.file) != 2:
            ap.error("--file twice (layer 4, layer 5) and --out (only live polls reach the archive)")
        out = Path(a.out)
        docs = {lid: json.loads(Path(f).read_text()) for lid, f in zip(LAYERS, a.file)}
        recs, meta = run(docs, now, out.with_suffix(".state.json"))
        write_events(SOURCE_ID, recs, meta=meta, path=out)
        print(f"{SOURCE_ID}: {len(recs)} records (file) -> {out}")
        return 0
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        docs = fetch(sess)
        rows = [r for lid, doc in docs.items() for r in rows_of(doc, LAYERS[lid])]
    except (requests.RequestException, ValueError) as e:
        write_events(SOURCE_ID, [], ok=False, error=f"layers: {type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    save_raw(SOURCE_ID, json.dumps(rows), "json")          # the filtered safe-field rows only
    recs, meta = run(docs, now, STATE_PATH)
    path = write_events(SOURCE_ID, recs, meta=meta)
    print(f"{SOURCE_ID}: {len(recs)} records from {meta['poll']['outfalls']} outfalls -> {path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
