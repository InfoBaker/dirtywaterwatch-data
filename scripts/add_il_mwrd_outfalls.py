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
O'Brien Lock) are on the layer but are not combined sewer outfalls. Each is an outfall row of its own (gate_rows,
2026-11-06: a reversal is a discharge of river water, with the combined sewage in it, to Lake Michigan, and every
discharge point needs a registry row and a water record before the state goes live): `structure` "lake_reversal_gate",
receiving water Lake Michigan (the shoreline model of data/rules.json reach.shoreline draws a stretch at it), the point
MWRD's layer gives, the permit and outfall id of il_mwrd.GATE_IDS (no permit lists the structures; each is filed
for want of a permit of its own under the permit of the MWRD plant whose EPA row lies nearest, which
`permit_basis` says in public words), `rain_caution` false (the rain
caution's thresholds are for combined sewer outfalls; a structure opens when the waterway itself rises, on MWRD's
decision, and the possible-CSO map and the reversal table report it). O'Brien Lock lies on the Calumet River about
11 km upstream of the river's mouth at Calumet Harbor, farther from the lake's shore than a shoreline stretch can start
(snap_km): its row carries `lake_entry`, the river's path from the lock to the mouth along the USGS NHD
high-resolution flowlines of the Calumet River (GNIS 405379; fetched, or --hr FILE), where the stretch starts
(build/reaches.py). The Chicago River Controlling Works stand beside the Chicago Harbor Lock, which NHDPlus V2.1's
Lake Michigan polygon leaves out as a hole: its lake_entry is the lake's outer shore nearest the structure
(SHORE_ENTRY), with no river path. The reversal and possible-diversion records carry the same permit and outfall id.
--gates-only FILE: the gate rows alone are rebuilt from a saved layer read of the three structures (the other rows stay).
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
            "water_matched_by", "no_water_reason", "reach_slug", "replaced_match", "receiving_water_override")
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


HR_FLOWLINES_URL = "https://hydro.nationalmap.gov/arcgis/rest/services/nhd/MapServer/6"
HR_LAKE_ENTRY = {"O'Brien Lock": {"gnis_id": "405379", "water": "Calumet River",
                                  "box": (-87.70, 41.60, -87.45, 41.80)}}
# a structure whose own point the lake record holds inside a hole (the Chicago Harbor Lock beside the Controlling
# Works: NHDPlus V2.1's Lake Michigan polygon leaves the lock chamber out as a ring of its own, so a stretch from the
# point would walk around the lock): its stretch starts on the lake's outer shore nearest the structure
SHORE_ENTRY = {"CRCW": {"lake": "lake-michigan-il", "water": "Chicago River"}}
WATERS_NHD = ROOT / "data" / "waters-nhd.json"
GATE_RAIN_NOTE = ("not read by the rain caution: its thresholds are for combined sewer outfalls, while this structure "
                  "opens when the waterway itself rises, on MWRD's decision; MWRD's possible-CSO map and its reversal "
                  "table report each opening")


def fetch_hr(spec: dict) -> list[dict]:
    """The USGS NHD high-resolution flowlines of a GNIS id inside a box (layer 6; outSR 4326)."""
    r = requests.get(HR_FLOWLINES_URL + "/query", headers=HEADERS, timeout=120, params={
        "where": f"gnis_id IN ('{spec['gnis_id'].zfill(8)}','{spec['gnis_id']}')", "geometry": ",".join(map(str, spec["box"])),
        "geometryType": "esriGeometryEnvelope", "inSR": 4326, "outSR": 4326,
        "outFields": "permanent_identifier,gnis_name,gnis_id,lengthkm", "returnGeometry": "true", "f": "json"})
    r.raise_for_status()
    return r.json().get("features") or []


def river_path(features: list[dict], lat: float, lon: float) -> tuple[list[list[float]], list[str]]:
    """([[lon, lat], ...], flowline ids): the river from the point nearest (lat, lon) to the downstream end. NHD flowlines
    are digitised in the direction of flow, so the flowlines are chained end to start, and the end that starts no
    other flowline is the mouth."""
    lines = []
    for f in features:
        for path in (f.get("geometry") or {}).get("paths") or []:
            if len(path) >= 2:
                lines.append(([[round(x, 6), round(y, 6)] for x, y in path], str((f.get("attributes") or {}).get(
                    "permanent_identifier"))))
    if not lines:
        return [], []
    starts = {tuple(c[0]): i for i, (c, _) in enumerate(lines)}
    # the line holding the vertex nearest the point, then onward along the chain
    best = min(((metres(lat, lon, y, x), i, j) for i, (c, _) in enumerate(lines) for j, (x, y) in enumerate(c)))
    _, i, j = best
    path, ids, seen = [list(p) for p in lines[i][0][j:]], [lines[i][1]], {i}
    while tuple(path[-1]) in starts and starts[tuple(path[-1])] not in seen:
        i = starts[tuple(path[-1])]
        seen.add(i)
        path += [list(p) for p in lines[i][0][1:]]
        ids.append(lines[i][1])
    return simplify(path), ids


def simplify(path: list[list[float]], tol_deg: float = 0.0001) -> list[list[float]]:
    """The path simplified to about 10 m (Douglas-Peucker, as the water records are), its ends kept."""
    from shapely.geometry import LineString
    if len(path) < 3:
        return path
    return [[round(x, 6), round(y, 6)] for x, y in LineString(path).simplify(tol_deg, preserve_topology=False).coords]


def path_km(path: list[list[float]]) -> float:
    return sum(metres(a[1], a[0], b[1], b[0]) for a, b in zip(path, path[1:])) / 1000



def lake_record_geometry(slug: str, path: Path = WATERS_NHD):
    """A water record's geometry (shapely) from data/waters-nhd.json, or None."""
    from shapely.geometry import shape
    doc = json.loads(path.read_text()) if path.exists() else {}
    w = next((x for x in doc.get("waters") or [] if x.get("slug") == slug), None)
    return shape(w["geometry"]) if w and w.get("geometry") else None


def shore_entry(lat: float, lon: float, lake) -> dict:
    """{lat, lon, outer_m, hole_m}: the point of the lake's outer shore (its polygons' exterior rings) nearest the
    structure, and how far the structure lies from it and from the nearest hole in the polygon."""
    from shapely.geometry import Point
    from shapely.ops import nearest_points
    pt = Point(lon, lat)
    polys = list(getattr(lake, "geoms", [lake]))
    ext = min((pg.exterior for pg in polys), key=lambda e: e.distance(pt))
    q = nearest_points(ext, pt)[0]
    holes = [h for pg in polys for h in pg.interiors]
    hole = min((h for h in holes), key=lambda h: h.distance(pt), default=None)
    return {"lat": round(q.y, 6), "lon": round(q.x, 6), "outer_m": round(metres(lat, lon, q.y, q.x)),
            "hole_m": round(metres(lat, lon, *reversed(nearest_points(hole, pt)[0].coords[0]))) if hole is not None else None}


def gate_permit_basis(permit: str, near: dict | None, dist_m: float | None) -> str:
    """Why a reversal structure is listed under a plant's permit, in public words (review of Illinois's gates,
    2026-11-06): the structure is MWRD's and has no permit of its own, so it is listed under the permit of MWRD's plant
    with the nearest outfall in EPA's inventory, and that permit does not name it."""
    at = (f" ({permit}: outfall {near['outfall']}" + (f", '{near['outfall_name']}'" if near.get("outfall_name") else "")
          + f", {round(dist_m):,} m away)") if near is not None and dist_m is not None else f" ({permit})"
    return ("MWRD's own structure, with no permit of its own: no NPDES permit names it as an outfall and EPA's CSO "
            "inventory lists none here. For want of one it is listed under the permit of the MWRD water reclamation "
            f"plant with the nearest outfall in EPA's inventory{at}; that permit does not name the structure, and the "
            "listing only keeps MWRD's structure with MWRD's own records")


def gate_rows(points: list[dict], epa_rows: list[dict], hr: dict | None = None, previous: dict | None = None,
              lakes: dict | None = None) -> list[dict]:
    """The reversal structures' outfall rows (module docstring). points: the layer's rows for the structures; hr:
    {reversal column: NHD high-resolution flowline features} for the structures in HR_LAKE_ENTRY (fetched when None);
    lakes: {slug: geometry} for SHORE_ENTRY (read from data/waters-nhd.json when None)."""
    prev = {(r["npdes_permit"], str(r["outfall"])): r for r in (previous or {}).get("outfalls", [])}
    by_permit: dict[str, list[dict]] = defaultdict(list)
    for o in epa_rows:
        if o.get("npdes_permit") in M.MWRD_PERMITS and o.get("lat") is not None:
            by_permit[o["npdes_permit"]].append(o)
    rows = []
    for p in sorted(points, key=lambda p: p["OBJECTID"]):
        col, name = M.diversion(p["TARP_CONNECTION"], p["LOCATION"])
        permit, outfall = M.gate_ids(col)
        near = min(((metres(p["lat"], p["lon"], o["lat"], o["lon"]), o) for o in by_permit.get(permit, [])),
                   key=lambda t: t[0], default=(None, None))
        nearest_all = min(((metres(p["lat"], p["lon"], o["lat"], o["lon"]), o) for ps in by_permit.values() for o in ps),
                          key=lambda t: t[0], default=(None, None))
        if near[1] is not None and nearest_all[1] is not None and nearest_all[1]["npdes_permit"] != permit:
            raise ValueError(f"{name}: the nearest MWRD plant row is {nearest_all[1]['npdes_permit']}, not {permit} "
                             "(il_mwrd.GATE_IDS)")
        basis = gate_permit_basis(permit, near[1], near[0])
        row = {"npdes_permit": permit, "permittee": (near[1] or {}).get("permittee") or "MWRD", "state": "IL",
               "city": p["OUTFALL_CITY"], "outfall": outfall, "outfall_name": name, "outfall_status": "CSO",
               "receiving_water_echo": M.LAKE, "mwrd_reach": p["WATERWAY_REACH"], "mwrd_owner": p["OWNER"],
               "tarp_connection": p["TARP_CONNECTION"],
               "monitored": {"Monitored": True, "Unmonitored": False}.get(p["M_OR_U"]),
               "lat": p["lat"], "lon": p["lon"], "coords_from": "il-mwrd-cso-points",
               "outfall_kind": "cso", "structure": "lake_reversal_gate", "structure_note": M.GATE_NOTE,
               "reversal_column": col, "from_waterway": M.DIVERSION_WATERWAYS[col],
               "receiving_water_basis": ("MWRD's table of reversals to Lake Michigan gives this structure's column; "
                                         "a reversal lets the waterway into the lake here"),
               "permit_basis": basis, "rain_caution": False, "rain_caution_note": GATE_RAIN_NOTE,
               "country": "US", "source_id": "il-mwrd-cso-points",
               "source_url": f"{M.CSO_POINTS_URL}/query?where=OBJECTID%3D{p['OBJECTID']}&outFields=*&f=json",
               "source_record_id": p["OBJECTID"], "epa_row": None}
        if col in HR_LAKE_ENTRY:
            spec = HR_LAKE_ENTRY[col]
            feats = (hr or {}).get(col)
            if feats is None:
                feats = fetch_hr(spec)
            path, ids = river_path(feats, p["lat"], p["lon"])
            km = path_km(path)     # the drawn (simplified) path's length
            if len(path) < 2:
                raise ValueError(f"{name}: no NHD high-resolution flowline of GNIS {spec['gnis_id']} to the lake")
            row["lake_entry"] = {
                "lat": path[-1][1], "lon": path[-1][0], "water": spec["water"],
                "path": path, "path_km": round(km, 2),
                "source": (f"USGS NHD high-resolution flowlines (The National Map NHD MapServer, layer 6 'Flowline - "
                           f"Large Scale') of the {spec['water']}, GNIS {spec['gnis_id']}: {', '.join(ids)}, from the "
                           "vertex nearest the structure to the downstream end of the last, the river's mouth"),
                "source_url": HR_FLOWLINES_URL,
                "basis": (f"the structure lies on the {spec['water']}, {round(km, 1)} km up the river from its "
                          "mouth; in a reversal the river runs to the lake through that mouth, so the shoreline stretch "
                          "starts there and the river's path from the structure to it is drawn with it")}
        if col in SHORE_ENTRY:
            spec = SHORE_ENTRY[col]
            lake = (lakes or {}).get(spec["lake"]) if lakes is not None else lake_record_geometry(spec["lake"])
            if lake is None:
                raise ValueError(f"{name}: no geometry for {spec['lake']}")
            e = shore_entry(p["lat"], p["lon"], lake)
            row["lake_entry"] = {
                "lat": e["lat"], "lon": e["lon"], "water": spec["water"], "path": [], "path_km": 0.0,
                "source": (f"the point of the outer shore of the water record {spec['lake']} (NHDPlus V2.1, cut to the "
                           "state; data/waters-nhd.json) nearest MWRD's point for the structure"),
                "basis": (f"the lake record leaves a hole in its polygon {e['hole_m']} m from the structure, at the lock "
                          f"beside it, which a stretch from the structure's own point would walk around; the stretch "
                          f"starts on the lake's shore {e['outer_m']} m away instead")}
        old = prev.get((permit, outfall))
        if old and old.get("lat") == row["lat"] and old.get("lon") == row["lon"] and \
                old.get("receiving_water_echo") == row["receiving_water_echo"]:
            row.update({k: old[k] for k in TIE_KEYS if k in old})
        rows.append(row)
    return rows


def build(features: list[dict], epa_rows: list[dict], previous: dict | None = None, hr: dict | None = None) -> dict:
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
    gates = gate_rows(div, epa_rows, hr, previous)
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
        "count": len(rows) + len(gates),
        "paired_with_epa": sum(1 for r in rows if r["epa_row"]),
        "reversal_gates": len(gates),
        "outfalls": rows + gates,
        "without_permit": [{"owner": p["OWNER"], "location": p["LOCATION"], "lat": p["lat"], "lon": p["lon"],
                            "mwrd_reach": p["WATERWAY_REACH"], "tarp_connection": p["TARP_CONNECTION"],
                            "reason": "EPA's CSO inventory holds no combined sewer permit for this owner"}
                           for p in no_permit],
    }


def layer_points(features: list[dict]) -> list[dict]:
    """The layer's features as points: the safe fields, stripped, with lat and lon."""
    out = []
    for f in features:
        a, g = f.get("attributes") or {}, f.get("geometry") or {}
        if g.get("x") is None or g.get("y") is None:
            continue
        out.append({k: (a.get(k).strip() if isinstance(a.get(k), str) else a.get(k)) for k in M.CSO_POINTS_FIELDS}
                   | {"lat": round(g["y"], 6), "lon": round(g["x"], 6)})
    return out


def replace_gates(doc: dict, features: list[dict], epa_rows: list[dict], hr: dict | None = None,
                  lakes: dict | None = None) -> dict:
    """The file with its gate rows rebuilt from a layer read of the structures (--gates-only); every other row stays."""
    div = [p for p in layer_points(features)
           if M.diversion(p["TARP_CONNECTION"], p["LOCATION"]) and "P.S." not in (p["LOCATION"] or "")]
    gates = gate_rows(div, epa_rows, hr, doc, lakes)
    if len(gates) != len(M.GATE_IDS):
        raise ValueError(f"{len(gates)} structures in the layer read, not {len(M.GATE_IDS)}")
    rows = [r for r in doc["outfalls"] if r.get("structure") != "lake_reversal_gate"]
    out = {k: v for k, v in doc.items() if k != "diversion_points"}
    out.update(count=len(rows) + len(gates), reversal_gates=len(gates), outfalls=rows + gates)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--gates-only", metavar="FILE", help="a saved layer read of the three structures: rebuild their rows only")
    ap.add_argument("--hr", metavar="FILE", help="a saved NHD high-resolution read of the Calumet River (O'Brien Lock)")
    a = ap.parse_args(argv)
    hr = {"O'Brien Lock": json.loads(Path(a.hr).read_text())["features"]} if a.hr else None
    if a.gates_only:
        prev = json.loads(OUT.read_text())
        doc = replace_gates(prev, json.loads(Path(a.gates_only).read_text())["features"],
                            json.loads(US.read_text())["outfalls"], hr)
        print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in doc.items() if k not in ("rule", "source")},
                         indent=1))
        if not a.dry_run:
            OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=True) + "\n")
        return 0
    feats = json.loads(Path(a.file).read_text())["features"] if a.file else fetch()
    prev = json.loads(OUT.read_text()) if OUT.exists() else None
    doc = build(feats, json.loads(US.read_text())["outfalls"], prev, hr)
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in doc.items() if k not in ("rule", "source")},
                     indent=1))
    if not a.dry_run:
        OUT.write_text(json.dumps(doc, indent=1, ensure_ascii=True) + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
