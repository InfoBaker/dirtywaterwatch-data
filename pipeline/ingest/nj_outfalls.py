"""NJDEP CSO outfall points -> data/build/nj-cso-outfalls.json (an outfall registry, not a feed: it
writes no events file).

Source
  NJDEP 'NJPDES Combined Sewer Overflow (CSO)' points, Utilities MapServer layer 0 (NJGIN
  Util_NJPDES_CSO; registry row nj-njdep-cso-outfalls-arcgis): 211 outfalls of 21 permittees
  (207 Active, 4 Sealed), last edited 2022-2023. Plain GET, no key, one request
  (maxRecordCount 2000). The raw response is kept under data/raw/nj-cso-outfalls/.
  Terms: the NJDEP Data Distribution Agreement (keep the metadata with the data; credit NJDEP GIS),
  so the output names the layer and its metadata page.

Output
  One row per outfall: outfall_id (CSO_ID, 'NJ0108880-030A'), npdes_permit, permittee, outfall (the
  layer's DSN, '030A'), outfall_name (OUTFALL_ALT, a street or place name), receiving_water, lat,
  lon, status (CSO_STAT), last_edit; joined to data/outfalls-mid-atlantic.json (EPA ECHO inventory
  matched to openboatlaunch waters) by permit + outfall number: the DSN as given, else its number
  without the letter suffix ('030A' -> '030'); a combined DSN ('011A/013A') tries each part.
  water_slug comes from that row (water_match 'outfall_registry'); where it has none, the layer's
  receiving water, when it names one water only, is matched by name to a New Jersey water near the
  point (ingest/nj_waters.py, water_match 'name'); else null.

Cadence
  The layer is static (last edits 2022-2023): a run refetches only when the file is older than 7
  days (--force refetches now), so `make ingest` can run it before the New Jersey feeds.

Failures
  An HTTP or JSON error, or a response with fewer than half the previous file's outfalls, leaves the
  previous file in place and exits 1.

Run from pipeline/:  python -m ingest.nj_outfalls [--force]
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from collections import Counter
from datetime import UTC, datetime, timedelta

import requests

from common import BUILD_DIR, DATA_DIR, HEADERS, now_iso, read_json, save_raw, write_json
from ingest import nj_waters

SOURCE_ID = "nj-cso-outfalls"
LAYER = "https://mapsdep.nj.gov/arcgis/rest/services/Features/Utilities/MapServer/0"
METADATA_URL = "https://www.nj.gov/dep/gis/digidownload/metadata/html/Util_NJPDES_CSO.html"
OUT = BUILD_DIR / "nj-cso-outfalls.json"
MAX_AGE = timedelta(days=7)


def dsn_keys(dsn: str | None) -> list[str]:
    """'030A' -> ['030A', '030']; '011A/013A' -> ['011A', '011', '013A', '013']; '01A' stays."""
    out: list[str] = []
    for part in re.split(r"[/,;&]| and ", (dsn or "").upper()):
        p = part.strip()
        if not p:
            continue
        out.append(p)
        m = re.fullmatch(r"(\d{1,3})[A-Z]", p)
        if m:
            out.append(m.group(1).zfill(3))
    return list(dict.fromkeys(out))


def echo_index() -> dict[tuple[str, str], dict]:
    reg = read_json(DATA_DIR / "outfalls-mid-atlantic.json", {}) or {}
    return {(o["npdes_permit"], str(o["outfall"]).upper()): o for o in reg.get("outfalls", [])
            if str(o.get("npdes_permit", "")).startswith("NJ")}


def ms_date(v) -> str | None:
    try:
        return datetime.fromtimestamp(int(v) / 1000, UTC).date().isoformat() if v not in (None, "") else None
    except (TypeError, ValueError, OverflowError):
        return None


def clean(v):
    if isinstance(v, str):
        v = v.strip()
        return v or None
    return v


def build_rows(features: list[dict], echo: dict) -> tuple[list[dict], dict]:
    rows, stats = [], Counter()
    for f in features:
        a = f.get("attributes") or {}
        permit, dsn = clean(a.get("NJPDES_NO")), clean(a.get("DSN"))
        lat, lon = a.get("LATITUDE"), a.get("LONGITUDE")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)) or not nj_waters.in_nj(lon, lat):
            lat = lon = None
        e = None
        for k in dsn_keys(dsn):
            e = echo.get((permit, k))
            if e:
                break
        row = {"outfall_id": clean(a.get("CSO_ID")), "npdes_permit": permit, "permittee": clean(a.get("PERMITTEE")),
               "outfall": dsn, "outfall_name": clean(a.get("OUTFALL_ALT")), "receiving_water": clean(a.get("RECV_WATER")),
               "lat": round(lat, 7) if lat is not None else None, "lon": round(lon, 7) if lon is not None else None,
               "status": clean(a.get("CSO_STAT")), "last_edit": ms_date(a.get("LAST_EDIT")),
               "echo_outfall": e["outfall"] if e else None, "water_slug": None, "water_name": None,
               "water_match": "none", "water_match_note": None}
        stats["echo_joined" if e else "echo_not_joined"] += 1
        if e and e.get("water_slug"):
            row.update(water_slug=e["water_slug"], water_name=e.get("water_name"), water_match="outfall_registry",
                       water_match_note=f"ECHO inventory row {permit} {e['outfall']} ({e.get('match')})")
        elif row["receiving_water"] and not re.search(r"/|;|,|\band\b", row["receiving_water"]):
            # one named water only: 'Delaware River/Newton Creek' is the creek first, so it stays unplaced
            pt = (lon, lat) if lat is not None else None
            slugs, notes = nj_waters.match_waters(row["receiving_water"], None, pt)
            if len(slugs) == 1:
                row.update(water_slug=slugs[0], water_name=nj_waters.name_of(slugs[0]), water_match="name",
                           water_match_note="; ".join(notes) or "receiving water name, point within ~2 km of the water")
        stats[f"water_{row['water_match']}"] += 1
        rows.append(row)
    rows.sort(key=lambda r: (r["npdes_permit"] or "", r["outfall"] or ""))
    return rows, dict(stats)


def fetch() -> tuple[dict | None, str | None]:
    params = {"where": "1=1", "outFields": "*", "returnGeometry": "false", "f": "json"}
    err = None
    for i in range(3):
        try:
            r = requests.get(LAYER + "/query", params=params, headers=HEADERS, timeout=120)
            r.raise_for_status()
            js = r.json()
            if not isinstance(js.get("features"), list):
                raise ValueError(f"no features: {str(js)[:200]}")
            save_raw(SOURCE_ID, r.content, "json")
            return js, None
        except (requests.RequestException, ValueError) as e:
            err = f"{type(e).__name__}: {e}"
            time.sleep(3 * (i + 1))
    return None, err


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--force", action="store_true", help="refetch even when the file is less than 7 days old")
    args = ap.parse_args(argv)
    prev = read_json(OUT, {}) or {}
    try:
        age = datetime.now(UTC) - datetime.fromisoformat(str(prev.get("fetched_at")).replace("Z", "+00:00"))
    except ValueError:
        age = None
    if not args.force and age is not None and age < MAX_AGE and prev.get("outfalls"):
        print(f"{SOURCE_ID}: {prev.get('count')} outfalls, fetched {prev['fetched_at']} (under 7 days): not refetched")
        return 0
    js, err = fetch()
    if js is not None and prev.get("count") and len(js["features"]) < prev["count"] / 2:
        err = f"incomplete response: {len(js['features'])} outfalls against {prev['count']} before"
    if err:
        print(f"{SOURCE_ID}: fetch failed, previous file kept: {err}", file=sys.stderr)
        return 1
    rows, stats = build_rows(js["features"], echo_index())
    out = {"source": "NJDEP NJPDES Combined Sewer Overflow (CSO) outfall points (Util_NJPDES_CSO)",
           "layer_url": LAYER, "metadata_url": METADATA_URL,
           "credit": "NJDEP Geographic Information System (NJDEP Data Distribution Agreement)",
           "registry_ids": ["nj-njdep-cso-outfalls-arcgis"], "fetched_at": now_iso(),
           "join": "data/outfalls-mid-atlantic.json by permit + outfall number (DSN, then DSN without its letter)",
           "stats": stats, "count": len(rows),
           "statuses": dict(Counter(r["status"] for r in rows)), "outfalls": rows}
    write_json(OUT, out)
    print(f"{SOURCE_ID}: {len(rows)} outfalls ({stats}) -> {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
