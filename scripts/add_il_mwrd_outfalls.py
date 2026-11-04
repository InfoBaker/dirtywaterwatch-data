"""Cook County's combined sewer outfalls from MWRD's CSO Points layer -> data/outfalls-il.json (the registry row shape
of data/outfalls-mid-atlantic.json, one row per outfall, each citing the layer).

Usage: pipeline/.venv/bin/python -I scripts/add_il_mwrd_outfalls.py [--file saved-layer.json] [--dry-run]

Source: MWRD's public CSO Points layer (pipeline/ingest/il_mwrd.py CSO_POINTS_URL; registry il-mwrd-cso-points): 441
outfalls of 51 owners with MWRD's own coordinates, waterway reach, TARP drop-shaft key, location and whether MWRD
monitors the outfall. EPA's CSO inventory (data/outfalls-us.json) holds 186 rows for Chicago's permit alone, 151 of the
Cook County rows on a point shared with the facility's, and no reach or monitoring flag.

Each point is given its owner's permit (il_mwrd.owner_permits) and, where it can be told, the permit's outfall number in
EPA's inventory:
  1. distance: the nearest open or closed EPA row of the owner's permits within MATCH_M (400 m), one to one, nearest
     pairs first;
  2. name: for the points and EPA rows still unpaired, the street and the side ("Touhy Ave (E)" and "CSO - TOUHY
     AVENUE EAST"), when exactly one of each carries it; then the street alone when exactly one of each carries it
     and they do not name opposite sides.
A paired point takes EPA's permit and outfall number, so in the registry (common.load_outfall_registry: a state file
outranks the national one) this row replaces EPA's for the same outfall; `epa_row` records the EPA row it replaces and
how they were paired, and EPA's row stays in data/outfalls-us.json unchanged. An unpaired point keeps the TARP key as
its outfall id ("DS-M99"; MWRD's synopsis report uses the same key; "DS-M99#12", the layer's object id added,
when several unpaired outfalls share one drop shaft) under its owner's first permit, with
`epa_row` null. A point whose owner has no combined sewer permit in EPA's inventory (Robbins, Forest View, a
campground) is listed under `without_permit` with the reason, not as an outfall row.
receiving_water_echo is the water MWRD's reach label names (il_mwrd.REACH_WATERS: MWRD's own assignment of the outfall
to a waterway), else EPA's text for a paired row (kept in epa_row.receiving_water_echo; EPA's inventory gives texts
such as 'SUBURBAN CHICAGO AREAS' for Cook County outfalls); reach labels are kept in mwrd_reach. The three reversal structures (Wilmette gate, Chicago River Controlling Works,
O'Brien Lock) are on the layer but are not combined sewer outfalls: they are listed under `diversion_points` and not as
outfall rows (their discharges are the Lake Michigan reversals, il-mwrd-lake-michigan-reversals).
Water ties are added afterwards by `python -m ingest.outfall_waters --state IL`; a rerun keeps a row's ties when its
point and receiving water are unchanged.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))
from common import HEADERS  # noqa: E402
from ingest import il_mwrd as M  # noqa: E402

OUT = ROOT / "data" / "outfalls-il.json"
US = ROOT / "data" / "outfalls-us.json"
MATCH_M = 400
TIE_KEYS = ("water_slug", "water_name", "water_kind", "distance_m", "alternatives", "match", "water_match",
            "water_matched_by", "no_water_reason", "reach_slug", "replaced_match")
STREET = re.compile(r"\b(ave|avenue|av|st|street|rd|road|blvd|boulevard|dr|drive|pkwy|parkway|ext|extension|ct|court|"
                    r"pl|place|ln|lane|hwy|highway|cso|csos|outfall|no|and|the|of|at)\b")
SIDE = {"e": "E", "east": "E", "w": "W", "west": "W", "n": "N", "north": "N", "s": "S", "south": "S"}


def fetch() -> list[dict]:
    r = requests.get(M.CSO_POINTS_URL + "/query", headers=HEADERS, timeout=120,
                     params={"where": "1=1", "outFields": ",".join(M.CSO_POINTS_FIELDS), "outSR": 4326,
                             "returnGeometry": "true", "orderByFields": "OBJECTID", "f": "json"})
    r.raise_for_status()
    return r.json().get("features") or []


def metres(lat1, lon1, lat2, lon2) -> float:
    x = math.radians(lon2 - lon1) * math.cos(math.radians((lat1 + lat2) / 2))
    return 6371000 * math.hypot(x, math.radians(lat2 - lat1))


def loc_key(t: str | None) -> tuple[str | None, str | None]:
    """'Touhy Ave (E)' -> ('touhy', 'E'); the first word of the street and the side MWRD gives in brackets."""
    t = t or ""
    m = re.search(r"\(([EWNS])\)", t)
    base = STREET.sub(" ", re.sub(r"[^a-z0-9 ]", " ", re.sub(r"\([^)]*\)", " ", t).lower()))
    w = base.split()
    return (w[0] if w else None, m.group(1) if m else None)


def epa_key(t: str | None) -> tuple[str | None, str | None]:
    """'CSO - TOUHY AVENUE EAST' -> ('touhy', 'E')."""
    t = re.sub(r"^\s*cso\s*[-#:]*\s*", "", (t or "").lower()).strip()
    side = None
    m = re.search(r"\b(east|west|north|south|e|w|n|s)\s*$", t)
    if m:
        side, t = SIDE[m.group(1)], t[:m.start()]
    w = STREET.sub(" ", re.sub(r"[^a-z0-9 ]", " ", t)).split()
    return (w[0] if w else None, side)


def pair(points: list[dict], epa: list[dict]) -> dict[int, tuple[dict, str]]:
    """{OBJECTID: (EPA row, how)} for the points that can be told apart (module docstring)."""
    out: dict[int, tuple[dict, str]] = {}
    used: set[tuple[str, str]] = set()
    cand = []
    for p in points:
        perms = M.owner_permits(p["OWNER"])
        for o in epa:
            if o["npdes_permit"] in perms and o.get("lat") is not None:
                d = metres(p["lat"], p["lon"], o["lat"], o["lon"])
                if d <= MATCH_M:
                    cand.append((d, p["OBJECTID"], o))
    for d, pid, o in sorted(cand, key=lambda c: (c[0], c[1], c[2]["outfall"])):
        k = (o["npdes_permit"], o["outfall"])
        if pid in out or k in used:
            continue
        out[pid] = (o, f"distance: EPA's point lies {round(d)} m from MWRD's")
        used.add(k)
    for use_side in (True, False):
        groups: dict[tuple, tuple[list, list]] = defaultdict(lambda: ([], []))
        for p in points:
            if p["OBJECTID"] in out:
                continue
            k = loc_key(p["LOCATION"])
            groups[(tuple(M.owner_permits(p["OWNER"])), k if use_side else (k[0], None))][0].append(p)
        for o in epa:
            if (o["npdes_permit"], o["outfall"]) in used:
                continue
            k = epa_key(o.get("outfall_name"))
            for perms_k in {g[0] for g in groups}:
                if o["npdes_permit"] in perms_k:
                    groups[(perms_k, k if use_side else (k[0], None))][1].append(o)
        for (_, k), (ps, os_) in groups.items():
            if k[0] and len(ps) == 1 and len(os_) == 1:
                o = os_[0]
                sides = (loc_key(ps[0]["LOCATION"])[1], epa_key(o.get("outfall_name"))[1])
                if not use_side and None not in sides and sides[0] != sides[1]:
                    continue                    # the same street on the other bank is another outfall
                out[ps[0]["OBJECTID"]] = (o, "name: MWRD's location and EPA's outfall name give the same street"
                                          + (" and side" if use_side else ""))
                used.add((o["npdes_permit"], o["outfall"]))
    return out


def build(features: list[dict], epa_rows: list[dict], previous: dict | None = None) -> dict:
    points = []
    for f in features:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        if g.get("x") is None or g.get("y") is None:
            continue
        points.append({k: (a.get(k).strip() if isinstance(a.get(k), str) else a.get(k)) for k in M.CSO_POINTS_FIELDS}
                      | {"lat": round(g["y"], 6), "lon": round(g["x"], 6)})
    epa = [o for o in epa_rows if str(o.get("npdes_permit") or "").startswith("IL")]
    div, rest = [], []
    for p in points:
        d = M.diversion(p["TARP_CONNECTION"], p["LOCATION"])
        (div if d and "P.S." not in (p["LOCATION"] or "") else rest).append(p)
    no_permit = [p for p in rest if not M.owner_permits(p["OWNER"])]
    rest = [p for p in rest if M.owner_permits(p["OWNER"])]
    pairs = pair(rest, epa)
    prev = {(r["npdes_permit"], str(r["outfall"])): r for r in (previous or {}).get("outfalls", [])}
    rows = []
    tarp_count = Counter(p["TARP_CONNECTION"] for p in rest if p["OBJECTID"] not in pairs)
    for p in sorted(rest, key=lambda p: p["OBJECTID"]):
        o, how = pairs.get(p["OBJECTID"], (None, None))
        permit = o["npdes_permit"] if o else M.owner_permits(p["OWNER"])[0]
        outfall = o["outfall"] if o else (p["TARP_CONNECTION"] if p["TARP_CONNECTION"] not in (None, "", "None")
                                         else f"MWRD-{p['OBJECTID']}")
        if not o and tarp_count[p["TARP_CONNECTION"]] > 1:
            outfall = f"{outfall}#{p['OBJECTID']}"     # several outfalls at one drop shaft: the layer's id tells them apart
        water = M.reach_water(p["WATERWAY_REACH"]) or (o or {}).get("receiving_water_echo")
        row = {"npdes_permit": permit, "permittee": (o or {}).get("permittee") or p["OWNER"], "state": "IL",
               "city": p["OUTFALL_CITY"], "outfall": outfall, "outfall_name": p["LOCATION"],
               "outfall_status": "CSO", "receiving_water_echo": water, "mwrd_reach": p["WATERWAY_REACH"],
               "mwrd_owner": p["OWNER"], "tarp_connection": p["TARP_CONNECTION"],
               "monitored": {"Monitored": True, "Unmonitored": False}.get(p["M_OR_U"]),
               "lat": p["lat"], "lon": p["lon"], "coords_from": "il-mwrd-cso-points",
               "outfall_kind": "cso", "country": "US", "source_id": "il-mwrd-cso-points",
               "source_url": f"{M.CSO_POINTS_URL}/query?where=OBJECTID%3D{p['OBJECTID']}&outFields=*&f=json",
               "source_record_id": p["OBJECTID"],
               "epa_row": ({"file": "data/outfalls-us.json", "npdes_permit": o["npdes_permit"], "outfall": o["outfall"],
                            "outfall_name": o.get("outfall_name"), "receiving_water_echo": o.get("receiving_water_echo"),
                            "paired_by": how} if o else None)}
        if len(M.owners(p["OWNER"])) > 1:
            row["owner_note"] = (f"MWRD's layer names more than one owner ({p['OWNER']}); filed under the first "
                                 "owner's permit")
        old = prev.get((permit, str(outfall)))
        if old and old.get("lat") == row["lat"] and old.get("lon") == row["lon"] and \
                old.get("receiving_water_echo") == row["receiving_water_echo"]:
            row.update({k: old[k] for k in TIE_KEYS if k in old})
        rows.append(row)
    return {
        "source": ("MWRD CSO Points layer (il-mwrd-cso-points), fetched by scripts/add_il_mwrd_outfalls.py; EPA's "
                   "national CSO inventory (data/outfalls-us.json) for permits and outfall numbers"),
        "source_url": M.CSO_POINTS_URL,
        "rule": ("one row per MWRD outfall point; the owner's combined sewer permit; EPA's outfall number when the point "
                 "pairs with an EPA row of that permit (nearest within 400 m one to one, then the same street and "
                 "side), else MWRD's TARP key as the outfall id"),
        "generated": date.today().isoformat(),
        "count": len(rows),
        "paired_with_epa": sum(1 for r in rows if r["epa_row"]),
        "outfalls": rows,
        "diversion_points": [{"name": M.diversion(p["TARP_CONNECTION"], p["LOCATION"])[1], "location": p["LOCATION"],
                              "lat": p["lat"], "lon": p["lon"], "water": M.LAKE,
                              "note": "a structure that lets the waterway back into Lake Michigan in severe storms, "
                                      "not a combined sewer outfall"} for p in div],
        "without_permit": [{"owner": p["OWNER"], "location": p["LOCATION"], "lat": p["lat"], "lon": p["lon"],
                            "mwrd_reach": p["WATERWAY_REACH"], "tarp_connection": p["TARP_CONNECTION"],
                            "reason": "EPA's CSO inventory holds no combined sewer permit for this owner"}
                           for p in no_permit],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    feats = json.loads(Path(a.file).read_text())["features"] if a.file else fetch()
    prev = json.loads(OUT.read_text()) if OUT.exists() else None
    doc = build(feats, json.loads(US.read_text())["outfalls"], prev)
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in doc.items() if k not in ("rule", "source")},
                     indent=1))
    if not a.dry_run:
        OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
