"""Water-name matching for the New York ingesters (shared helper, not a feed).

Matches free text typed by a notifier or an agency ("Hudson River", "2 Mile Creek", "Tributary of
Longhouse creek", "Lake Champlain - Cumberland Bay") to openboatlaunch water slugs for New York in
data/waters-mid-atlantic.csv, with the bounding boxes in data/waters-ny.json. The rules follow
ingest/nh_vt_waters.py and stay conservative (a wrong slug colours the wrong water red):

- Whole-word, accent- and punctuation-insensitive match of a water's name, longest names first.
- A name directly preceded by "tributary of/to" or "branch of" is a different water: skipped, as is
  a name that runs on into another water word ("White Lake Brook" is not White Lake) or follows
  "Little" or "North Branch" ("Little Niagara" is not the Niagara River). A
  name after a flow connector ("to", "into", "via" ...) that follows another named stream is the
  downstream water: skipped.
- With a point (lon, lat) a name only matches a water whose bounding box, padded by ~2 km, holds
  the point. Several records sharing the name (the Mohawk River and its Colonie pool, the Niagara
  River and its channels) are settled by the unpadded box, then by the smallest box that holds the
  point (the most local record); the choice is noted. Without a point, a name shared by several
  records, or in GUARDED, needs one of the water's towns.
- New York's Newtown Creek record is the stream near Elmira, not the Brooklyn-Queens creek; the
  point (or the town) is what keeps NYC's Newtown Creek off it.
"""
from __future__ import annotations

import csv
import json
import re
from functools import lru_cache

from common import DATA_DIR
from ingest.nh_vt_waters import FLOW_BEFORE, TRIB_BEFORE, WATER_WORD, norm, norm_town

# "White Lake Brook" is not White Lake; "Little Niagara" is not the Niagara River.
NEXT_WATER = re.compile(r"\s*(brook|creek|river|stream|kill|outlet|inlet|canal|tributary|trib|run|ditch|drain|branch)\b")
OTHER_BEFORE = re.compile(r"\b(little|north branch|south branch|east branch|west branch|middle branch|old)\s*$")

STATE = "NY"
# NY bounding box (lon/lat), padded a little: points outside are not New York geocodes.
NY_BBOX = (-79.9, 40.45, -71.8, 45.1)

GUARDED = {"newtown-creek-ny", "black-river-ny", "east-river-ny"}

SPELLING = {
    "hudson ruver": "hudson river", "genesse river": "genesee river", "geneese river": "genesee river",
    "2 mile creek": "two mile creek", "niagra river": "niagara river", "niagara rive": "niagara river",
    "susquehana": "susquehanna", "susquehanna river river": "susquehanna river",
    "mohawk rive": "mohawk river", "lake champlian": "lake champlain", "lake champlin": "lake champlain",
    "long island sound lis": "long island sound", "lis": "long island sound",
    "saint lawrence": "st lawrence river", "st lawrence": "st lawrence river",
    "barge canal": "erie canal", "nys barge canal": "erie canal",
    "lake chautauqua": "chautauqua lake", "thompson s lake": "thompsons lake",
}
# Rivers typed without "River" ("Hudson", "Mohawk"): the bare word means the river.
BARE = ["hudson", "mohawk", "niagara", "genesee", "susquehanna", "chenango", "oswego", "chemung",
        "saranac", "seneca", "oswegatchie", "raquette", "grasse", "bronx", "harlem", "wallkill"]
# Parts of a water with a record: the part's name places the event on the water.
PART_OF = {
    "cumberland bay": "lake champlain", "willsboro bay": "lake champlain", "bulwagga bay": "lake champlain",
    "western long island sound": "long island sound", "upper east river": "east river",
    "lower east river": "east river",
}


@lru_cache(maxsize=None)
def _rows() -> list[dict]:
    with open(DATA_DIR / "waters-mid-atlantic.csv", newline="") as f:
        return [r for r in csv.DictReader(f) if r["state"] == STATE]


@lru_cache(maxsize=None)
def _index():
    by_name: dict[str, list[tuple[str, set[str]]]] = {}
    for row in _rows():
        towns = {norm_town(t) for t in (row.get("towns") or "").split(";") if t.strip()}
        by_name.setdefault(norm(row["name"]), []).append((row["slug"], towns))
    return by_name, sorted(by_name, key=len, reverse=True)


@lru_cache(maxsize=None)
def _records() -> dict[str, dict]:
    p = DATA_DIR / "waters-ny.json"
    out = {}
    if p.exists():
        for w in json.loads(p.read_text()).get("waters", []):
            b = w.get("bbox")
            if isinstance(b, str):
                try:
                    b = json.loads(b)
                except ValueError:
                    b = None
            out[w["slug"]] = {**w, "bbox": [float(x) for x in b] if isinstance(b, list) and len(b) == 4 else None}
    return out


def name_of(slug: str) -> str | None:
    r = _records().get(slug)
    if r:
        return r.get("name")
    return next((row["name"] for row in _rows() if row["slug"] == slug), None)


def kind_of(slug: str) -> str | None:
    return (_records().get(slug) or {}).get("kind")


def bbox(slug: str) -> list[float] | None:
    return (_records().get(slug) or {}).get("bbox")


def in_ny(lon, lat) -> bool:
    return lon is not None and lat is not None and NY_BBOX[0] <= lon <= NY_BBOX[2] and NY_BBOX[1] <= lat <= NY_BBOX[3]


def _holds(slug: str, lon: float, lat: float, pad: float) -> bool | None:
    b = bbox(slug)
    if not b:
        return None
    return b[0] - pad <= lon <= b[2] + pad and b[1] - pad <= lat <= b[3] + pad


def _area(slug: str) -> float:
    b = bbox(slug) or [0, 0, 360, 180]
    return (b[2] - b[0]) * (b[3] - b[1])


def prepare(text: str | None) -> str:
    t = norm(text)
    for bad, good in sorted({**SPELLING, **PART_OF}.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{re.escape(norm(bad))}\b", norm(good), t)
    for bare in BARE:
        t = re.sub(rf"\b{bare}\b(?! river| reservoir| lake| pond| bay| brook| creek| kill| canal| harbor)", f"{bare} river", t)
    return re.sub(r"\b(river )+river\b", "river", t)


def match_waters(text: str | None, towns: list[str] | None = None,
                 point: tuple[float, float] | None = None, pad: float = 0.02) -> tuple[list[str], list[str]]:
    """(slugs, notes) for free text within New York. point is (lon, lat)."""
    t = prepare(text)
    if not t:
        return [], []
    by_name, names = _index()
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
            if NEXT_WATER.match(t[m.end():]) and not WATER_WORD.search(name.split()[-1]):
                notes.append(f"'{name}' runs on into another water's name ('{name} {NEXT_WATER.match(t[m.end():]).group(1)}'): not used")
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
            cands = by_name[name]
            pick = None
            if point is not None:
                ok = [s for s, _ in cands if _holds(s, point[0], point[1], pad)]
                if not ok and len(cands) == 1 and cands[0][0] not in GUARDED and bbox(cands[0][0]) is None:
                    ok = [cands[0][0]]   # no box to check (st-lawrence-river-ny): a unique name stands
                    notes.append(f"'{name}': the water record has no bounding box, so the point could not be checked")
                if len(ok) > 1:
                    tight = [s for s in ok if _holds(s, point[0], point[1], 0)]
                    ok = tight or ok
                if len(ok) > 1:
                    ok = sorted(ok, key=_area)[:1]
                    notes.append(f"'{name}': the point lies in {len(cands)} records' boxes; the most local one ({ok[0]}) used")
                if ok:
                    pick = ok[0]
                else:
                    notes.append(f"'{name}': the point is not near any of the {len(cands)} New York waters with this name: not used")
            elif len(cands) == 1 and cands[0][0] not in GUARDED:
                pick = cands[0][0]
            else:
                hits = [s for s, tw in cands if town_set & tw]
                if len(hits) == 1:
                    pick = hits[0]
                else:
                    notes.append(f"'{name}' is generic or shared by {len(cands)} waters and no point or town settles it: not used")
            if pick and pick not in slugs:
                slugs.append(pick)
    return slugs, notes
