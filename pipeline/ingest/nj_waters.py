"""Water-name matching for the New Jersey ingesters (shared helper, not a feed).

Matches names typed by an agency (a beach name, a HAB waterbody name, a receiving water) to the
openboatlaunch water slugs for New Jersey in data/waters-mid-atlantic.csv, with the bounding boxes in
data/waters-nj.json. Conservative, like ingest/ny_waters.py (a wrong slug colours the wrong water):

- Whole-word, accent- and punctuation-insensitive match of a water's name, longest names first;
  a name followed by another water word ("Cedar Lake Brook") or preceded by "Little", "North
  Branch" ..., "tributary of" is a different water and is not used.
- "Lake X" and "X Lake" are the same name; a bare name that is a water's name without its generic
  word ("Spruce Run" for Spruce Run Reservoir, "Hopatcong State Park" for Lake Hopatcong) counts
  only when nothing else matched, it has 5 letters or more, and the point lies inside that water's
  box (padded ~300 m).
- With a point (lon, lat) a name only matches a water whose box, padded by ~2 km, holds the point;
  several records sharing the name are settled by the unpadded box, then the smallest box. Without
  a point, a name shared by several records needs one of the water's towns.
- by_town(): the one water of the right kind whose towns include the municipality and whose box
  holds the point (water_match 'inferred'); never for the ocean.
"""
from __future__ import annotations

import csv
import json
import re
from functools import lru_cache

from common import DATA_DIR
from ingest.nh_vt_waters import FLOW_BEFORE, TRIB_BEFORE, WATER_WORD, norm

STATE = "NJ"
NJ_BBOX = (-75.6, 38.9, -73.88, 41.36)
GENERIC_LAST = {"lake", "lakes", "reservoir", "pond", "ponds", "millpond"}
NEXT_WATER = re.compile(r"\s*(brook|creek|river|stream|kill|outlet|inlet|canal|tributary|trib|run|ditch|branch)\b")
OTHER_BEFORE = re.compile(r"\b(little|north branch|south branch|east branch|west branch|middle branch|old|upper|lower)\s*$")
TOWN_SUFFIX = re.compile(r"\b(borough|boro|township|twp|city|town|village)\b")
KINDS = {  # beach location type -> water kinds it can be on
    "lake": {"lake", "pond", "reservoir"},
    "river": {"river", "stream", "canal"},
    "bay": {"bay"},
}


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
    p = DATA_DIR / "waters-nj.json"
    if p.exists():
        for w in json.loads(p.read_text()).get("waters", []):
            b = w.get("bbox")
            out[w["slug"]] = {**w, "bbox": [float(x) for x in b] if isinstance(b, list) and len(b) == 4 else None}
    return out


def _variants(name_n: str) -> set[str]:
    """'lake hopatcong' -> {'lake hopatcong', 'hopatcong lake'}; 'cedar lake' -> {.., 'lake cedar'}."""
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
    for row in _rows():
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


def bbox(slug: str):
    return (_records().get(slug) or {}).get("bbox")


def name_of(slug: str) -> str | None:
    r = _records().get(slug)
    if r:
        return r.get("name")
    return next((row["name"] for row in _rows() if row["slug"] == slug), None)


def kind_of(slug: str) -> str | None:
    r = _records().get(slug)
    if r:
        return r.get("kind")
    return next((row["kind"] for row in _rows() if row["slug"] == slug), None)


def in_nj(lon, lat) -> bool:
    return lon is not None and lat is not None and NJ_BBOX[0] <= lon <= NJ_BBOX[2] and NJ_BBOX[1] <= lat <= NJ_BBOX[3]


def _holds(slug: str, lon: float, lat: float, pad: float) -> bool | None:
    b = bbox(slug)
    if not b:
        return None
    return b[0] - pad <= lon <= b[2] + pad and b[1] - pad <= lat <= b[3] + pad


def _area(slug: str) -> float:
    b = bbox(slug) or [0, 0, 360, 180]
    return (b[2] - b[0]) * (b[3] - b[1])


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
        notes.append(f"'{name}': the point is not near any of the {len(cands)} New Jersey waters with this name: not used")
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
    """(slugs, notes) for free text within New Jersey. point is (lon, lat)."""
    t = norm(text)
    if not t:
        return [], []
    if point is not None and not in_nj(*point):
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


def by_town(town: str | None, location_type: str | None, point: tuple[float, float] | None,
            pad: float = 0.01) -> tuple[list[str], str | None]:
    """(slug list, note): the one water of a kind fitting the location type ('Lake', 'River', 'Bay')
    whose towns include the municipality and whose box (padded ~1 km) holds the point."""
    kinds = KINDS.get(norm(location_type))
    nt = norm_town(town)
    if not kinds or not nt or point is None or not in_nj(*point):
        return [], None
    cands = []
    for row in _rows():
        if row["kind"] not in kinds:
            continue
        towns = {norm_town(x) for x in (row.get("towns") or "").split(";") if x.strip()}
        if nt in towns and _holds(row["slug"], point[0], point[1], pad):
            cands.append(row["slug"])
    if len(cands) > 1:   # several boxes near the point: the one that holds it unpadded
        cands = [s for s in cands if _holds(s, point[0], point[1], 0)] or cands
    if len(cands) == 1:
        return cands, f"the one {location_type.lower()} water listing {town} whose box holds the station point"
    return [], (f"{len(cands)} waters fit town {town!r}: not used" if cands else None)
