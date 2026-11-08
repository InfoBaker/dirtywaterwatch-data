"""Oregon DEQ: spills reported to the Oregon Emergency Response System (OERS) and verified by DEQ, 2013 to 2025-03-27,
the sewage rows, as a frozen archive -> data/build/events/or-deq-oers-spills-2013-2025.json

Source
  https://services.arcgis.com/uUvqNMGPm7axC2dD/arcgis/rest/services/all_spills_Aug1_2013_Mar27_2025_pts/FeatureServer/1
  (registry: or-deq-oers-spills-2013-2025), a hosted layer in the State of Oregon's ArcGIS Online organisation: "All
  spills reported to OERS and verified by DEQ between August 1, 2013 and March 27, 2025" (its service name; the layer
  is named all_spills_Jul1_2013_Mar27_2025_pts and its first row is dated 2013-07-24). hasStaticData true; last edited
  2025-04-01 (editingInfo.lastEditDate 1743526797067). 2,844 rows of the material category "Sewage, Stormwater,
  Wastewater, Floodwater, & Biological", 2,371 of them Material "Sewage", read 2026-11-07. No successor and no DEQ
  public list of newer reports was found: Oregon's newer sewage reports are in DEQ's files (OERS takes them by telephone,
  1-800-452-0311; OAR 340-142-0040; permit Schedule F).

What is read (privacy)
  SAFE_FIELDS only, requested by name (outFields). Never requested: Situation (the call narrative: it names callers,
  residents and contractors), Name (the incident's title, often a street address or a business or person's name),
  Address (the street address, often a private home: the point and the city carry the place), Latitude and Longitude
  (text copies of Lat_DD and Lon_DD). data/raw keeps only the requested fields of the rows read, as the layer gave
  them (save_safe), never another field. common.event runs common.strip_personal on raw.

Record rules (rules only; no model, no geocoding)
  - Rows: Material "Sewage" (2,371). The category's other materials (Wastewater (Non-Sewage) 266, Biological Material
    78, Food Waste 47, Animal Waste 44, Milk 31, Floodwater 6, Medical Waste 1) are not sewage reports: counted in
    meta.not_sewage, not kept.
  - Key: OERS_No (the OERS incident number); a number on two rows (2 numbers) keeps the first as OERS_No and the other
    as "<OERS_No>-r<Release_Num>" (or "-o<OBJECTID>").
  - Times: Date2 (a date) and Time (HH:MM:SS) are the date and time of the report to OERS, in Oregon's own clock: Pacific,
    or Mountain in Malheur County north of township 35 South (zones.oregon_zone from the row's County and point;
    raw.time_zone). DEQ's layer gives no separate start and no end: started_at is the report time (raw.start_basis: the
    spill began at or before it), reported_at the same; a row with no time is precision day. ended_at stays null and
    status "unknown": the layer never says when a spill stopped, so the status build treats each as a report with no
    end. published_at and source_updated_at are null (the layer gives no per-row publication or edit time); the
    layer's last edit is meta.layer_last_edit.
  - Type (Source, the layer's own category): Sewer, Storm Drain or Outfall, Pipeline -> sso; Wastewater Treatment
    Plant -> bypass (a release at a treatment plant); every other source (a private residence 77, a vehicle, a septic
    tank 24, a business, Other, Unknown: 297 rows) -> sso as well, since DEQ's material is "Sewage": a sewage report
    with its caution and in the counts, raw._source_type the layer's word and raw._type_basis saying the source is not
    a public sewer. These are DEQ-verified OERS reports, not the public's own, so no citizen_caution applies (the layer
    names no reporter).
  - Place: Lat_DD and Lon_DD are DEQ's point (coord_source "source"); a point outside Oregon's box is not used
    (raw._coords_rejected). Affected_Waterway is the water text: a placeholder (NULL, None, Unknown, N/A) is no water;
    "Columbia River, Astoria" is the water "Columbia River" and the place "Astoria" (raw.waterway_place; TOWN_NAMES:
    "Hood River" after a comma is the town); two waters ("Evans Creek and the Rogue River") are both kept, joined by
    "; "; a text that names no water ("Possible impact to creek") is none; a name typed in lower or upper case is title
    cased. The status build places a report by the water it names (county-aware through its point and county) or by
    its point.
  - Reached water: MediaAffected lists what the spill reached. When it lists only Soil, Pavement, Building or Facility,
    Sanitary Sewer, Air or Groundwater and the row names no water, raw.reached_water is false with the media as
    raw._no_water_reason (kept, listed, placed on no water). Surface Water, Marine Water, Sediment, a storm drain or a
    catch basin, or a blank, NULL or "None" list, leaves the question open (err on safety).
  - Volume: Q_released_gal when Quantity_Unknown is not "Yes" (DEQ's figure in gallons; estimate_flag estimated);
    the figure in another unit (cubic yards, cups) is kept as volume_text too.
  - Operator: the layer names none. discharger_id stays null; City and County are kept in raw.
  - authority: "Oregon Department of Environmental Quality (OERS spill reports verified by DEQ)".
  - The archive is frozen: meta.frozen true, so the status build never calls it stale for its age.

Cadence
  Each run reads the layer's metadata only (one small request). The rows are read again only when the events file is
  missing, or the layer's last edit has changed (DEQ refreshed it: the records are rebuilt and meta.frozen says
  whether it is still the 2025 archive), or with --backfill. A failed read keeps the previous records (ok false).

Run from pipeline/:  python -m ingest.or_deq_oers_spills [--backfill] [--file saved.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

import zones
from common import EVENTS_DIR, HEADERS, event, now_iso, read_json, save_raw, write_events

SOURCE_ID = "or-deq-oers-spills-2013-2025"
LAYER = ("https://services.arcgis.com/uUvqNMGPm7axC2dD/arcgis/rest/services/all_spills_Aug1_2013_Mar27_2025_pts/"
         "FeatureServer/1")
ITEM_URL = LAYER
AUTHORITY = "Oregon Department of Environmental Quality (OERS spill reports verified by DEQ)"
FROZEN_EDIT_MS = 1743526797067          # editingInfo.lastEditDate read 2026-11-07 (2025-04-01)
SAFE_FIELDS = ("OBJECTID", "OERS_No", "Quantity_Unknown", "Quantity_Released", "UOM", "Q_released_gal", "Date", "Date2",
               "Time", "Affected_Waterway", "Report_Required", "City", "County", "Region", "State", "Release_Num",
               "Source", "SourceCategory", "Material", "MaterialCategory", "MediaAffected", "Cause", "Activity",
               "Lat_DD", "Lon_DD")
NEVER_READ = ("Situation", "Name", "Address", "Latitude", "Longitude")
WHERE = "MaterialCategory LIKE 'Sewage%'"
PAGE = 2000
TIMEOUT = (60, 900)
SAFE_FORMAT = "dww-safe-rows/1"
BOUNDS = (-124.8, 41.9, -116.4, 46.35)   # Oregon (west, south, east, north)
PLACEHOLDER = re.compile(r"^\s*(?:null|none|unknown|n/?a|na|-+|\?|not known|unk)\s*(?:,.*)?$", re.I)
WATER_WORD = re.compile(r"\b(?:river|creek|slough|lake|bay|ocean|reservoir|pond|channel|estuary|harbor|harbour|"
                        r"canal|ditch|fork|run|branch|wetlands?|marsh|sound|inlet|lagoon|spring|brook|stream)\b", re.I)
DRY_MEDIA = {"soil", "pavement", "building or facility", "sanitary sewer", "air", "groundwater"}
TYPES = {"sewer": "sso", "storm drain or outfall": "sso", "pipeline": "sso", "wastewater treatment plant": "bypass"}


def clean(v) -> str:
    s = "" if v is None else str(v).strip()
    return "" if s.upper() == "NULL" else s


def zone_of(a: dict) -> str:
    return zones.oregon_zone(a.get("Lat_DD"), a.get("Lon_DD"), clean(a.get("County")) or None)


def times(a: dict, tz: ZoneInfo) -> tuple[str | None, str | None]:
    """(started_at, precision): Date2 (YYYY-MM-DD, or epoch ms on an older service) and Time (HH:MM:SS) in tz."""
    d = a.get("Date2")
    day = None
    if isinstance(d, (int, float)):
        day = datetime.utcfromtimestamp(d / 1000).date()
    elif isinstance(d, str) and re.match(r"\d{4}-\d{2}-\d{2}", d):
        day = datetime.strptime(d[:10], "%Y-%m-%d").date()
    if day is None:
        return None, None
    m = re.match(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$", clean(a.get("Time")))
    if m and int(m.group(1)) < 24:
        return datetime(day.year, day.month, day.day, int(m.group(1)), int(m.group(2)), tzinfo=tz).isoformat(), \
            "minute"
    return datetime(day.year, day.month, day.day, tzinfo=tz).isoformat(), "day"


# towns whose names read as waters: after a comma they are the place ("Columbia River, Hood River": the Columbia at the
# town of Hood River, reported from Cascade Locks and Mosier)
TOWN_NAMES = {"hood river", "coos bay", "lake oswego", "rogue river", "myrtle creek", "grand ronde", "warm springs",
              "astoria", "portland", "madras"}
RIVER_STEMS = {"willamette", "columbia", "umpqua", "south umpqua", "north umpqua", "rogue", "santiam", "clackamas",
               "tualatin", "deschutes", "snake", "john day", "coquille", "siuslaw", "mckenzie", "yamhill", "sandy",
               "nehalem", "siletz", "yaquina", "alsea", "chetco", "klamath", "malheur", "owyhee", "grande ronde"}
NOT_A_NAME = re.compile(r"\b(?:possible|possibly|impact|unnamed|unknown|nearby|local|potential)\b", re.I)


def tidy(name: str) -> str:
    n = re.sub(r"\s+", " ", name).strip(" .;:-")
    n = re.sub(r"\s+(?:affected|impacted)$", "", n, flags=re.I)
    n = re.sub(r"\s+via\b.*$", "", n, flags=re.I)              # "McKenzie River via outfall to creek"
    return n.title() if (n.islower() or n.isupper()) else n


def waterway(text: str) -> tuple[list[str], str | None]:
    """(waters, place) of Affected_Waterway (rules only): a placeholder is no water ("NULL", "None", "Unknown, Madras");
    "Columbia River, Astoria" and "Columbia River, Hood River" are the water and its town (TOWN_NAMES, or a part with no
    water word); "Ames Creek, South Santiam River affected" and "Evans Creek and the Rogue River" are two waters; a
    text that is no water's name ("Possible impact to creek") is none."""
    t = clean(text)
    if not t or PLACEHOLDER.match(t):
        return [], None
    # (text, follows a comma?) parts: a town can follow a comma only
    pieces = re.split(r"(\s*,\s*|\s+and\s+(?:the\s+)?(?=[A-Z]))", t)
    parts = [(pieces[0], False)] + [(pieces[i + 1], "," in pieces[i]) for i in range(1, len(pieces) - 1, 2)]
    waters, place = [], None
    for i, (x, after_comma) in enumerate(parts):
        x = tidy(x)
        if not x:
            continue
        if x.lower() in RIVER_STEMS:
            x = f"{x} River"                                     # "Willamette, Oak Lodge": the Willamette River
        if i and after_comma and (x.lower() in TOWN_NAMES or not WATER_WORD.search(x)):
            place = ", ".join(y for y in (place, x) if y)
            continue
        if NOT_A_NAME.search(x) or not WATER_WORD.search(x) or not x[:1].isupper():
            continue
        if x not in waters:
            waters.append(x)
    return waters, place


def record(a: dict, key: str, fetched_at: str) -> dict:
    zone = zone_of(a)
    tz = ZoneInfo(zone)
    start, prec = times(a, tz)
    src = clean(a.get("Source"))
    et = TYPES.get(src.lower(), "sso")
    waters, place = waterway(a.get("Affected_Waterway"))
    water = "; ".join(waters) or None
    lat, lon = a.get("Lat_DD"), a.get("Lon_DD")
    raw = {"state": "OR", "time_zone": zone,
           "timezone_note": ("Mountain time: Malheur County north of township 35 South (49 CFR 71.9)"
                             if zone == zones.MOUNTAIN else "Pacific time"),
           "oers_no": clean(a.get("OERS_No")), "city": clean(a.get("City")) or None,
           "county": clean(a.get("County")) or None, "region": clean(a.get("Region")) or None,
           "source": src or None, "source_category": clean(a.get("SourceCategory")) or None,
           "cause": clean(a.get("Cause")) or None, "activity": clean(a.get("Activity")) or None,
           "media_affected": clean(a.get("MediaAffected")) or None,
           "affected_waterway": clean(a.get("Affected_Waterway")) or None,
           "start_basis": ("the date and time of the report to OERS (DEQ's layer gives no separate start): the spill "
                           "began at or before it" if prec == "minute" else
                           "the date of the report to OERS, with no time (DEQ's layer gives no separate start)"),
           "end_basis": "DEQ's layer gives no end for any spill",
           "_withheld": "the call narrative, the incident title and the street address are not read (they name people "
                        "and private homes)"}
    if src.lower() not in TYPES:
        raw["_source_type"] = src or None
        raw["_type_basis"] = (f"DEQ's material is Sewage; the source is not a public sewer or plant ({src or 'not '
                              'given'}): kept as a sewage report")
    if place:
        raw["waterway_place"] = place
    if not (isinstance(lat, (int, float)) and isinstance(lon, (int, float))
            and BOUNDS[0] <= lon <= BOUNDS[2] and BOUNDS[1] <= lat <= BOUNDS[3]):
        if lat is not None or lon is not None:
            raw["_coords_rejected"] = [lat, lon]
        lat = lon = None
    media = [m.strip().lower() for m in clean(a.get("MediaAffected")).split(",") if m.strip()]
    if not water and media and all(m in DRY_MEDIA for m in media):
        raw["reached_water"] = False
        raw["_no_water_reason"] = (f"DEQ's record lists the media affected as {clean(a.get('MediaAffected'))} and "
                                   "names no water")
    vol, vtext = None, None
    q, unit = a.get("Q_released_gal"), clean(a.get("UOM"))
    if clean(a.get("Quantity_Unknown")).lower() != "yes" and isinstance(q, (int, float)) and q > 0:
        vol = int(round(q)) if q >= 1 else None
        if vol is None:
            vtext = f"{q:g} gallons"                 # under a gallon: kept as text, never rounded to 0
    if isinstance(a.get("Quantity_Released"), (int, float)) and unit and unit.lower() not in ("gallons", "none"):
        vtext = f"{a['Quantity_Released']:g} {unit}"
    return event(
        source_id=SOURCE_ID, source_record_id=key, event_type=et, status="unknown",
        waterbody_text=water, water_match="name" if water else "none",
        lat=lat, lon=lon, coord_source="source" if lat is not None else None,
        started_at=start, time_precision=prec, reported_at=start, published_at=None, source_updated_at=None,
        fetched_at=fetched_at, material="sewage", volume_gal=vol, volume_text=vtext,
        estimate_flag="estimated" if vol is not None else "unknown", authority=AUTHORITY, source_url=ITEM_URL,
        raw=raw, parse_error=None if start else "no report date")


def build(rows: list[dict], fetched_at: str) -> tuple[list[dict], dict]:
    sewage = [a for a in rows if clean(a.get("Material")) == "Sewage"]
    other = Counter(clean(a.get("Material")) or "(blank)" for a in rows if clean(a.get("Material")) != "Sewage")
    seen: Counter = Counter()
    recs = []
    for a in sorted(sewage, key=lambda x: x.get("OBJECTID") or 0):
        no = clean(a.get("OERS_No")) or f"o{a.get('OBJECTID')}"
        seen[no] += 1
        key = no if seen[no] == 1 else (f"{no}-r{a['Release_Num']}" if a.get("Release_Num") not in (None, "")
                                        else f"{no}-o{a.get('OBJECTID')}")
        recs.append(record(a, key, fetched_at))
    years = Counter((r["started_at"] or "")[:4] for r in recs)
    stats = {"rows_read": len(rows), "records": len(recs), "not_sewage": dict(other.most_common()),
             "by_type": dict(Counter(r["event_type"] for r in recs)),
             "by_year": dict(sorted(years.items())),
             "water_named": sum(1 for r in recs if r["waterbody_text"]),
             "reached_no_water": sum(1 for r in recs if (r["raw"] or {}).get("reached_water") is False),
             "with_point": sum(1 for r in recs if r["lat"] is not None),
             "mountain_time": sum(1 for r in recs if r["raw"]["time_zone"] == zones.MOUNTAIN),
             "first": min((r["started_at"] for r in recs if r["started_at"]), default=None),
             "last": max((r["started_at"] for r in recs if r["started_at"]), default=None)}
    return recs, stats


def query(sess: requests.Session) -> list[dict]:
    rows, off = [], 0
    while True:
        r = sess.get(f"{LAYER}/query", headers=HEADERS, timeout=TIMEOUT, params={
            "where": WHERE, "outFields": ",".join(SAFE_FIELDS), "orderByFields": "OBJECTID", "returnGeometry": "false",
            "resultOffset": off, "resultRecordCount": PAGE, "f": "json"})
        r.raise_for_status()
        d = r.json()
        if "error" in d:
            raise RuntimeError(f"layer error: {d['error']}")
        feats = d.get("features") or []
        rows += [{k: (f.get("attributes") or {}).get(k) for k in SAFE_FIELDS} for f in feats]
        if not d.get("exceededTransferLimit") or not feats:
            return rows
        off += len(feats)


def metadata(sess: requests.Session) -> dict:
    r = sess.get(LAYER, headers=HEADERS, timeout=TIMEOUT, params={"f": "json"})
    r.raise_for_status()
    d = r.json()
    return {"name": d.get("name"), "hasStaticData": d.get("hasStaticData"),
            "lastEditDate": (d.get("editingInfo") or {}).get("lastEditDate")}


def load_file(path: str) -> tuple[list[dict], dict]:
    d = json.loads(Path(path).read_text())
    if d.get("format") != SAFE_FORMAT:
        raise ValueError(f"not a {SAFE_FORMAT} document")
    return [{k: r.get(k) for k in SAFE_FIELDS} for r in d.get("rows") or []], d.get("meta") or {}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--file", help="a saved safe document (data/raw/or-deq-oers-spills-2013-2025/*.json)")
    ap.add_argument("--backfill", action="store_true", help="read the rows even when the layer has not changed")
    args = ap.parse_args(argv)
    fetched_at = now_iso()
    path = EVENTS_DIR / f"{SOURCE_ID}.json"
    prev = read_json(path, {}) or {}
    try:
        if args.file:
            rows, lmeta = load_file(args.file)
        else:
            sess = requests.Session()
            lmeta = metadata(sess)
            same = (prev.get("records") and (prev.get("meta") or {}).get("layer_last_edit_ms") == lmeta["lastEditDate"])
            if same and not args.backfill:
                if not prev.get("ok"):
                    # a failed read since the last good one: the layer answers again and is unchanged, so the archive's
                    # records and meta are good as they are; the file is marked ok again (review 2026-11-08 P2-5)
                    write_events(SOURCE_ID, prev["records"], ok=True, error=None, meta=prev.get("meta") or {})
                print(f"{SOURCE_ID}: layer unchanged since {lmeta['lastEditDate']}; {len(prev['records'])} records kept")
                return 0
            rows = query(sess)
            save_raw(SOURCE_ID, json.dumps({"format": SAFE_FORMAT, "layer": LAYER, "fields": list(SAFE_FIELDS),
                                            "meta": lmeta, "rows": rows}, ensure_ascii=False), "json")
    except Exception as e:  # noqa: BLE001
        write_events(SOURCE_ID, [], ok=False, error=f"{type(e).__name__}: {e}")
        print(f"{SOURCE_ID}: FAILED {e}", file=sys.stderr)
        return 1
    recs, stats = build(rows, fetched_at)
    edit = lmeta.get("lastEditDate")
    meta = {**stats, "layer": LAYER, "registry_ids": [SOURCE_ID], "frozen": edit in (None, FROZEN_EDIT_MS),
            "layer_last_edit_ms": edit,
            "layer_last_edit": datetime.utcfromtimestamp(edit / 1000).strftime("%Y-%m-%dT%H:%M:%SZ") if edit else None,
            "credit": "Oregon Department of Environmental Quality, spills reported to OERS and verified by DEQ, "
                      "2013 to March 27, 2025",
            "caveat": ("A closed archive: DEQ's layer stops at March 27, 2025 and gives the date and time of each "
                       "report, not the spill's start or end."),
            "time_basis": ("Date2 and Time are the date and time of the report to OERS, read in Pacific time (Mountain "
                           "in Malheur County north of township 35 South)"),
            "timezone": "America/Los_Angeles"}
    out = write_events(SOURCE_ID, recs, ok=True, error=None, meta=meta)
    print(f"{SOURCE_ID}: {json.dumps(stats)} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
