"""Water names and outfalls for the Pennsylvania ingesters (shared helper, not a feed).

- Water records: openboatlaunch's Pennsylvania waters (data/waters-mid-atlantic.csv rows with state
  PA, bounding boxes from data/waters-pa.json). Same conservative rules as ingest/nj_waters.py
  (whole-word, accent- and punctuation-insensitive, longest names first; "Lake X" = "X Lake"; a
  name that runs on into another water word, or follows "Little", "North Branch" ..., is a
  different water; with a point, only a water whose box (padded ~2 km) holds it; a bare name
  without its generic word only when the point lies in that water's box). A wrong slug colours
  the wrong water, so anything uncertain stays unmatched with a note.
- named(): one water by its exact name near a point (the fixed waters a source names: the three
  rivers at Pittsburgh, Lake Erie at Erie, the Delaware and Schuylkill at Philadelphia).
- echo_outfalls(): the EPA National CSO Inventory rows for Pennsylvania permits, joined to water
  slugs, in data/outfalls-mid-atlantic.json; nearest_outfall() finds the inventory outfall nearest a
  point (the CSOcast layer numbers outfalls its own way, so permit + outfall are found by place).
"""
from __future__ import annotations

import csv
import json
import math
import re
from functools import lru_cache

from common import DATA_DIR
from ingest.nh_vt_waters import FLOW_BEFORE, TRIB_BEFORE, WATER_WORD, norm

STATE = "PA"
PA_BBOX = (-80.53, 39.71, -74.68, 42.54)   # with Lake Erie's PA shore
GENERIC_LAST = {"lake", "lakes", "reservoir", "pond", "ponds", "millpond"}
NEXT_WATER = re.compile(r"\s*(brook|creek|river|stream|kill|outlet|inlet|canal|tributary|trib|run|ditch|branch)\b")
OTHER_BEFORE = re.compile(r"\b(little|north branch|south branch|east branch|west branch|middle branch|old|upper|lower)\s*$")
TOWN_SUFFIX = re.compile(r"\b(borough|boro|township|twp|city|town|village)\b")


def norm_town(s: str | None) -> str:
    t = norm(s)
    t = re.sub(r"^(town|city|village|borough|township) of ", "", t)
    t = TOWN_SUFFIX.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


@lru_cache(maxsize=None)
def _rows() -> list[dict]:
    with open(DATA_DIR / "waters-mid-atlantic.csv", newline="") as f:
        return [r for r in csv.DictReader(f) if r["state"] == STATE]


@lru_cache(maxsize=None)
def _records() -> dict[str, dict]:
    out = {}
    p = DATA_DIR / "waters-pa.json"
    if p.exists():
        for w in json.loads(p.read_text()).get("waters", []):
            b = w.get("bbox")
            out[w["slug"]] = {**w, "bbox": [float(x) for x in b] if isinstance(b, list) and len(b) == 4 else None}
    return out


def _variants(name_n: str) -> set[str]:
    out = {name_n}
    w = name_n.split()
    if len(w) >= 2 and w[0] == "lake":
        out.add(" ".join(w[1:] + ["lake"]))
    elif len(w) >= 2 and w[-1] == "lake":
        out.add(" ".join(["lake"] + w[:-1]))
    return out


@lru_cache(maxsize=None)
def _index():
    by_name: dict[str, list[tuple[str, set[str]]]] = {}
    bare: dict[str, list[str]] = {}
    rows = _rows() or [{"slug": s, "name": r["name"], "towns": ";".join(r.get("towns") or [])}
                       for s, r in _records().items()]
    for row in rows:
        towns = {norm_town(t) for t in (row.get("towns") or "").split(";") if t.strip()}
        n = norm(row["name"])
        for v in _variants(n):
            by_name.setdefault(v, []).append((row["slug"], towns))
        w = n.split()
        if len(w) >= 2 and w[-1] in GENERIC_LAST:
            bare.setdefault(" ".join(w[:-1]), []).append(row["slug"])
        elif len(w) >= 2 and w[0] == "lake":
            bare.setdefault(" ".join(w[1:]), []).append(row["slug"])
    return by_name, sorted(by_name, key=len, reverse=True), bare


def exists(slug: str) -> bool:
    return slug in _records() or any(r["slug"] == slug for r in _rows())


def bbox(slug: str):
    return (_records().get(slug) or {}).get("bbox")


def name_of(slug: str) -> str | None:
    r = _records().get(slug)
    if r:
        return r.get("name")
    return next((row["name"] for row in _rows() if row["slug"] == slug), None)


def in_pa(lon, lat) -> bool:
    return lon is not None and lat is not None and PA_BBOX[0] <= lon <= PA_BBOX[2] and PA_BBOX[1] <= lat <= PA_BBOX[3]


def _holds(slug: str, lon: float, lat: float, pad: float) -> bool | None:
    b = bbox(slug)
    if not b:
        return None
    return b[0] - pad <= lon <= b[2] + pad and b[1] - pad <= lat <= b[3] + pad


def _area(slug: str) -> float:
    b = bbox(slug) or [0, 0, 360, 180]
    return (b[2] - b[0]) * (b[3] - b[1])


def named(name: str, point: tuple[float, float] | None = None, pad: float = 0.02) -> str | None:
    """The one Pennsylvania water called exactly `name` (point = (lon, lat): its box, padded, must
    hold the point). None when there is no such record or the name is ambiguous."""
    by_name, _, _ = _index()
    cands = [s for s, _ in by_name.get(norm(name), [])]
    if point is not None:
        cands = [s for s in cands if _holds(s, point[0], point[1], pad)]
    if len(cands) > 1 and point is not None:
        cands = sorted(cands, key=_area)[:1]
    return cands[0] if len(cands) == 1 else None


def _pick(name: str, cands: list[tuple[str, set[str]]], point, town_set: set[str], pad: float,
          notes: list[str]) -> str | None:
    if point is not None:
        ok = [s for s, _ in cands if _holds(s, point[0], point[1], pad)]
        if not ok and len(cands) == 1 and bbox(cands[0][0]) is None:
            notes.append(f"'{name}': the water record has no bounding box, so the point could not be checked")
            return cands[0][0]
        if len(ok) > 1:
            ok = [s for s in ok if _holds(s, point[0], point[1], 0)] or ok
        if len(ok) > 1:
            ok = sorted(ok, key=_area)[:1]
            notes.append(f"'{name}': the point lies in several records' boxes; the most local one ({ok[0]}) used")
        if ok:
            return ok[0]
        notes.append(f"'{name}': the point is not near any of the {len(cands)} Pennsylvania waters with this name: not used")
        return None
    if len(cands) == 1:
        return cands[0][0]
    hits = [s for s, tw in cands if town_set & tw]
    if len(hits) == 1:
        return hits[0]
    notes.append(f"'{name}' is shared by {len(cands)} waters and no point or town settles it: not used")
    return None


def match_waters(text: str | None, towns: list[str] | None = None,
                 point: tuple[float, float] | None = None, pad: float = 0.02) -> tuple[list[str], list[str]]:
    """(slugs, notes) for free text within Pennsylvania. point is (lon, lat)."""
    t = norm(text)
    if not t:
        return [], []
    if point is not None and not in_pa(*point):
        point = None
    by_name, names, bare = _index()
    town_set = {norm_town(x) for x in (towns or []) if x and norm_town(x)}
    taken = [False] * len(t)
    slugs: list[str] = []
    notes: list[str] = []
    for name in names:
        for m in re.finditer(rf"\b{re.escape(name)}\b", t):
            if any(taken[m.start():m.end()]):
                continue
            for i in range(m.start(), m.end()):
                taken[i] = True
            before = t[:m.start()]
            nxt = NEXT_WATER.match(t[m.end():])
            if nxt and not WATER_WORD.search(name.split()[-1]):
                notes.append(f"'{name}' runs on into another water's name ('{name} {nxt.group(1)}'): not used")
                continue
            if OTHER_BEFORE.search(before):
                notes.append(f"'{name}' preceded by '{OTHER_BEFORE.search(before).group(1)}': a different water, not used")
                continue
            if TRIB_BEFORE.search(before):
                notes.append(f"'{name}' named as the water a tributary/branch joins: not used")
                continue
            fb = FLOW_BEFORE.search(before)
            if fb and WATER_WORD.search(before[:fb.start()]):
                notes.append(f"'{name}' named as the downstream water: not used")
                continue
            pick = _pick(name, by_name[name], point, town_set, pad, notes)
            if pick and pick not in slugs:
                slugs.append(pick)
    if not slugs and point is not None:
        for b in sorted(bare, key=len, reverse=True):
            m = re.search(rf"\b{re.escape(b)}\b", t)
            if len(b.replace(" ", "")) < 5 or not m or NEXT_WATER.match(t[m.end():]) or OTHER_BEFORE.search(t[:m.start()]):
                continue
            ok = [s for s in bare[b] if _holds(s, point[0], point[1], 0.003)]
            if len(ok) == 1:
                slugs.append(ok[0])
                notes.append(f"'{b}' read as {ok[0]} (the name without its generic word; the point lies in its box)")
                break
    return slugs, notes


# ---------------------------------------------------------------- outfall inventory

@lru_cache(maxsize=None)
def _echo() -> tuple:
    p = DATA_DIR / "outfalls-mid-atlantic.json"
    rows = json.loads(p.read_text()).get("outfalls", []) if p.exists() else []
    return tuple(o for o in rows if str(o.get("npdes_permit", "")).startswith("PA"))


def echo_outfalls(permits: set[str] | None = None) -> list[dict]:
    return [o for o in _echo() if permits is None or o["npdes_permit"] in permits]


def metres(lat1, lon1, lat2, lon2) -> float:
    my = 111_320.0
    mx = my * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat1 - lat2) * my, (lon1 - lon2) * mx)


def nearest_outfall(lat, lon, permits: set[str]) -> tuple[dict | None, float | None]:
    """(inventory row, distance in metres) of the nearest outfall of these permits to the point."""
    if lat is None or lon is None:
        return None, None
    best, dist = None, None
    for o in echo_outfalls(permits):
        if o.get("lat") is None or o.get("lon") is None:
            continue
        d = metres(lat, lon, o["lat"], o["lon"])
        if dist is None or d < dist:
            best, dist = o, d
    return best, (round(dist) if dist is not None else None)
