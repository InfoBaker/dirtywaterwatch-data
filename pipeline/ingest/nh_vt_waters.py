"""Water-name matching for the NH and VT ingesters (shared helper, not a feed).

Matches free text typed by an operator or a state layer ("Stevens brook lake champlain",
"Otter Creek below the falls in Vergennes") to openboatlaunch water slugs in data/waters-new-england.csv,
within one state. Rules, chosen to stay conservative (a wrong slug colours the wrong water red):

- Whole-word, accent- and punctuation-insensitive match of a water's name; longest names first,
  so "Connecticut River Reservoir" never also yields "Connecticut River".
- Known misspellings in the VT DEC data are corrected first (SPELLING).
- A name directly preceded by "tributary of/to" or "branch of" is a different water: skipped.
- A name after a flow connector ("to", "into", "via", "goes into"...) that follows another named
  river/brook/creek is the downstream water, not the receiving one: skipped.
- Generic or duplicated names (two slugs share it, or it is in GUARDED) need the event's town
  to be one of the water's towns, else they stay unmatched. This is what keeps Rutland's East
  Creek off east-creek-vt (Orwell) and Springfield's Black River off black-river-vt (Coventry).
"""
from __future__ import annotations

import csv
import json
import re
import unicodedata
from functools import lru_cache

from common import DATA_DIR

# Waters that must never be placed by name alone: the event's town has to be one of theirs.
GUARDED = {
    "east-creek-vt",       # Orwell; Rutland's East Creek (most-reported VT water) has no slug
    "black-river-vt",      # Coventry/Newport; Springfield's and Ludlow's Black River have no slug
    "little-river-vt", "dead-creek-vt", "dead-creek-fairfield-vt", "east-bay-vt",
    "pond-brook-vt", "long-pond-vt", "south-pond-vt",
}

SPELLING = {  # normalised misspelling -> normalised name (VT DEC free text, 2016-2026)
    "vt": {
        "connetticut": "connecticut", "connecticutt": "connecticut", "conneticut": "connecticut",
        "conetticut": "connecticut", "conn river": "connecticut river",
        "passsumpsic": "passumpsic", "passunpsic": "passumpsic", "passumsic": "passumpsic",
        "pussumpsic": "passumpsic", "passumpsac": "passumpsic",
        "mississquoi": "missisquoi", "missiquoi": "missisquoi", "missisquio": "missisquoi",
        "missisqui": "missisquoi",
        "winooksi": "winooski", "winoski": "winooski",
        "otther creek": "otter creek", "otter creeek": "otter creek", "big otter creek": "otter creek",
        "lake champlaim": "lake champlain", "lakechamplain": "lake champlain",
        "lake memphremagog": "lac memphremagog",
        "cylde river": "clyde river",
        "steven s brook": "stevens brook", "steven brook": "stevens brook",
        "stenens brook": "stevens brook", "stevens brook lakechamplain": "stevens brook lake champlain",
        "battenkill": "batten kill",
        "harveys lake": "harvey s lake",
    },
    "nh": {},
}
# Rivers typed without "River" ("Winooski", "Passumpsic"): the bare word means the river.
BARE = {"vt": ["winooski", "passumpsic", "missisquoi", "lamoille", "connecticut", "clyde", "barton", "otter creek"],
        "nh": ["merrimack", "piscataqua", "piscataquog", "nashua", "squamscott", "androscoggin", "connecticut"]}
# Bays that are part of a water with a slug (VT): the bay name places the event on the lake.
PART_OF = {"vt": {"shelburne bay": "lake champlain", "burlington bay": "lake champlain",
                  "malletts bay": "lake champlain", "st albans bay": "lake champlain",
                  "saint albans bay": "lake champlain", "missisquoi bay": "lake champlain"},
           "nh": {}}

WATER_WORD = re.compile(r"\b(river|brook|creek|stream|kill|canal)\b")
TRIB_BEFORE = re.compile(r"(tributary( of| to)?( the)?|branch of( the)?|branch to( the)?)\s*$")
FLOW_BEFORE = re.compile(r"\b(to|into|via|in to|drains to|flows to|goes to|goes into|dumps in to|feeding into|that goes to)( the)?\s*$")


def norm(s: str | None) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("+", " and ")
    s = re.sub(r"[^a-z0-9]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def norm_town(s: str | None) -> str:
    t = norm(s)
    t = re.sub(r"^(town|city|village) of ", "", t)
    t = re.sub(r"\bst\b", "saint", t)
    return re.sub(r"\s+", " ", t).strip()


def facility_town(name: str | None) -> str:
    """'Burlington Main' -> 'burlington', 'Lunenburg FD2' -> 'lunenburg', 'Hartford - WRJ' -> 'hartford'."""
    t = norm_town(name)
    t = re.sub(r"\b(fd ?\d*|wwtf|wwtp|wrj|main|north|east|river|plant|wastewater|quechee)\b", " ", t)
    return re.sub(r"\s+", " ", t).strip()


@lru_cache(maxsize=None)
def _index(state: str):
    st = state.upper()
    by_name: dict[str, list[tuple[str, set[str]]]] = {}
    with open(DATA_DIR / "waters-new-england.csv", newline="") as f:
        for row in csv.DictReader(f):
            if row["state"] != st:
                continue
            towns = {norm_town(t) for t in (row.get("towns") or "").split(";") if t.strip()}
            by_name.setdefault(norm(row["name"]), []).append((row["slug"], towns))
    names = sorted(by_name, key=len, reverse=True)
    return by_name, names


@lru_cache(maxsize=None)
def _bboxes(state: str) -> dict[str, list[float]]:
    """slug -> [w, s, e, n] from data/waters-<st>.json (openboatlaunch extract), if present."""
    p = DATA_DIR / f"waters-{state.lower()}.json"
    out = {}
    if p.exists():
        for w in json.loads(p.read_text()).get("waters", []):
            b = w.get("bbox")
            if isinstance(b, str):
                try:
                    b = json.loads(b)
                except ValueError:
                    b = None
            if isinstance(b, list) and len(b) == 4:
                out[w["slug"]] = [float(x) for x in b]
    return out


def near(slug: str, state: str, lon: float, lat: float, pad: float = 0.02) -> bool | None:
    """Is the point inside the water's bounding box padded by ~2 km? None if no bbox."""
    b = _bboxes(state).get(slug)
    if not b:
        return None
    return b[0] - pad <= lon <= b[2] + pad and b[1] - pad <= lat <= b[3] + pad


def _apply_spelling(t: str, state: str) -> str:
    for bad, good in sorted({**SPELLING.get(state, {}), **PART_OF.get(state, {})}.items(), key=lambda kv: -len(kv[0])):
        t = re.sub(rf"\b{re.escape(bad)}\b", good, t)
    for bare in BARE.get(state, []):
        if " " not in bare:
            t = re.sub(rf"\b{bare}\b(?! river| reservoir| lake| pond| bay| brook)", f"{bare} river", t)
    return t


def match_waters(text: str | None, state: str, towns: list[str] | None = None,
                 point: tuple[float, float] | None = None) -> tuple[list[str], list[str]]:
    """Return (slugs, notes). Notes say why a named water was not used. With a point (lon, lat),
    a name only matches a water whose padded bounding box holds the point, which also settles
    generic and shared names."""
    state = state.lower()
    t = _apply_spelling(norm(text), state)
    if not t:
        return [], []
    by_name, names = _index(state)
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
                ok = [sl for sl, _tw in cands if near(sl, state, point[0], point[1])]
                if len(ok) == 1:
                    if ok[0] not in slugs:
                        slugs.append(ok[0])
                else:
                    notes.append(f"'{name}': the point is near {len(ok)} of the {len(cands)} waters with this name: not used")
                continue
            if len(cands) == 1 and cands[0][0] not in GUARDED:
                pick = cands[0][0]
            else:
                hits = [s for s, tw in cands if town_set & tw]
                if len(hits) == 1:
                    pick = hits[0]
                else:
                    notes.append(f"'{name}' is generic or shared by {len(cands)} waters and the town does not settle it: not used")
            if pick and pick not in slugs:
                slugs.append(pick)
    return slugs, notes
