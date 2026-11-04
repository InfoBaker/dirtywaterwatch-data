"""Water records and water-name matching for the Virginia ingesters (shared helper, not a feed).

Extraction (`python -m ingest.va_waters`, run by hand when openboatlaunch's snapshot changes):
  reads ../openboatlaunch/out/water/*-va.json (records whose state is VA) and writes
  data/waters-va.json in the shape of data/waters-nj.json (slug, name, kind, state, towns, bbox,
  wikidata, charted, area_km2, launch slugs, advisories) and the VA rows of
  data/waters-mid-atlantic.csv (the other states' rows are kept as they are). Geometry stays in
  openboatlaunch's files (status.py and the export read it there).

Matching: the same conservative rules as ingest/pa_waters.py and ingest/nj_waters.py (whole-word,
accent- and punctuation-insensitive, longest names first; "Lake X" = "X Lake"; a name that runs on
into another water word, or follows "Little", "North Branch" ..., is a different water; with a
point, only a water whose box (padded ~2 km) holds it; a bare name without its generic word only
when the point lies in that water's box). Virginia specifics:
  - openboatlaunch spells the Virginia Beach river "Lynhaven River" (lynhaven-river-va); the usual
    spelling "Lynnhaven" in agency text is read as that record.
  - "Western Branch of the Elizabeth River" is openboatlaunch's "Western Branch Elizabeth River"
    (likewise Eastern and Southern Branch): the "<X> Branch of (the) <River>" form is a variant.
A wrong slug colours the wrong water, so anything uncertain stays unmatched with a note.

echo_outfalls(): the EPA National CSO Inventory rows for Virginia permits, joined to water slugs, in
data/outfalls-mid-atlantic.json (scripts/match_outfalls.py with DWW_STATES=VA).
"""
from __future__ import annotations

import csv
import glob
import io
import json
import math
import re
import sys
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path

from common import DATA_DIR, ROOT, write_json
from ingest.nh_vt_waters import FLOW_BEFORE, TRIB_BEFORE, WATER_WORD, norm

STATE = "VA"
VA_BBOX = (-83.7, 36.5, -75.2, 39.5)
OBL_WATER_DIR = ROOT.parent / "openboatlaunch" / "out" / "water"
WATERS_JSON = DATA_DIR / "waters-va.json"
MID_ATLANTIC_CSV = DATA_DIR / "waters-mid-atlantic.csv"
CSV_FIELDS = ["slug", "name", "kind", "state", "towns", "launch_count", "wikidata"]
GENERIC_LAST = {"lake", "lakes", "reservoir", "pond", "ponds", "millpond"}
NEXT_WATER = re.compile(r"\s*(brook|creek|river|stream|kill|outlet|inlet|canal|tributary|trib|run|ditch|branch)\b")
OTHER_BEFORE = re.compile(r"\b(little|north branch|south branch|east branch|west branch|middle branch|"
                          r"north fork|south fork|old|upper|lower)\s*$")
TOWN_SUFFIX = re.compile(r"\b(borough|boro|township|twp|city|town|village|county)\b")
SPELLING = {"lynnhaven": "lynhaven"}       # agency spelling -> openboatlaunch's spelling (normalised words)
BRANCH_FORM = re.compile(r"^((?:north|south|east|west|eastern|western|southern|northern) branch)(?: of)?(?: the)? (.+)$")


# ---------------------------------------------------------------- extraction

def _bbox(v):
    return [round(float(x), 5) for x in v] if isinstance(v, list) and len(v) == 4 else None


def extract(water_dir: Path = OBL_WATER_DIR) -> list[dict]:
    rows = []
    for f in sorted(glob.glob(str(water_dir / "*-va.json"))):
        d = json.loads(Path(f).read_text())
        if d.get("state") != STATE or not d.get("slug"):
            continue
        rows.append({
            "slug": d["slug"], "name": d.get("name"), "kind": d.get("kind"), "state": STATE,
            "towns": d.get("towns") or [], "bbox": _bbox(d.get("bbox")), "wikidata": d.get("wikidata"),
            "charted": d.get("charted"), "area_km2": d.get("area_km2"),
            "launches": [l.get("s") for l in d.get("launches") or [] if isinstance(l, dict) and l.get("s")],
            "advisories": d.get("advisories") or [],
        })
    return sorted(rows, key=lambda r: r["slug"])


def write_csv_rows(rows: list[dict], path: Path = MID_ATLANTIC_CSV) -> int:
    """Replace the VA rows of data/waters-mid-atlantic.csv; other states' rows stay as they are."""
    keep = []
    if path.exists():
        with path.open(newline="") as f:
            keep = [r for r in csv.DictReader(f) if r.get("state") != STATE]
    new = [{"slug": r["slug"], "name": r["name"], "kind": r["kind"], "state": STATE,
            "towns": ";".join(r["towns"]), "launch_count": len(r["launches"]), "wikidata": r["wikidata"] or ""}
           for r in rows]
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS, lineterminator="\r\n")
    w.writeheader()
    for r in keep + new:
        w.writerow({k: r.get(k, "") for k in CSV_FIELDS})
    path.write_text(buf.getvalue())
    return len(new)


def main(argv=None) -> int:
    if not OBL_WATER_DIR.is_dir():
        print(f"va-waters: {OBL_WATER_DIR} not found (openboatlaunch snapshot missing)", file=sys.stderr)
        return 1
    rows = extract()
    snap = datetime.fromtimestamp(max(Path(p).stat().st_mtime for p in glob.glob(str(OBL_WATER_DIR / "*-va.json"))), UTC)
    write_json(WATERS_JSON, {"state": STATE, "source": f"openboatlaunch out/water snapshot {snap:%Y-%m-%d}",
                             "count": len(rows), "waters": rows})
    n = write_csv_rows(rows)
    print(f"va-waters: {len(rows)} Virginia waters -> {WATERS_JSON} and {n} rows in {MID_ATLANTIC_CSV.name}")
    return 0


# ---------------------------------------------------------------- matching

def norm_town(s: str | None) -> str:
    t = norm(s)
    t = re.sub(r"^(town|city|village|county) of ", "", t)
    t = TOWN_SUFFIX.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def norm_text(s: str | None) -> str:
    t = norm(s)
    for a, b in SPELLING.items():
        t = re.sub(rf"\b{a}\b", b, t)
    return t


@lru_cache(maxsize=None)
def _records() -> dict[str, dict]:
    out = {}
    if WATERS_JSON.exists():
        for w in json.loads(WATERS_JSON.read_text()).get("waters", []):
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
    m = BRANCH_FORM.match(name_n)
    if m:
        out |= {f"{m.group(1)} {m.group(2)}", f"{m.group(1)} of {m.group(2)}", f"{m.group(1)} of the {m.group(2)}"}
    return out


@lru_cache(maxsize=None)
def _index():
    by_name: dict[str, list[tuple[str, set[str]]]] = {}
    bare: dict[str, list[str]] = {}
    for slug, row in _records().items():
        towns = {norm_town(t) for t in row.get("towns") or [] if t}
        n = norm(row.get("name"))
        if not n:
            continue
        for v in _variants(n):
            by_name.setdefault(v, []).append((slug, towns))
        w = n.split()
        if len(w) >= 2 and w[-1] in GENERIC_LAST:
            bare.setdefault(" ".join(w[:-1]), []).append(slug)
        elif len(w) >= 2 and w[0] == "lake":
            bare.setdefault(" ".join(w[1:]), []).append(slug)
    return by_name, sorted(by_name, key=len, reverse=True), bare


def exists(slug: str) -> bool:
    return slug in _records()


def bbox(slug: str):
    return (_records().get(slug) or {}).get("bbox")


def name_of(slug: str) -> str | None:
    return (_records().get(slug) or {}).get("name")


def in_va(lon, lat) -> bool:
    return lon is not None and lat is not None and VA_BBOX[0] <= lon <= VA_BBOX[2] and VA_BBOX[1] <= lat <= VA_BBOX[3]


def _holds(slug: str, lon: float, lat: float, pad: float) -> bool | None:
    b = bbox(slug)
    if not b:
        return None
    return b[0] - pad <= lon <= b[2] + pad and b[1] - pad <= lat <= b[3] + pad


def _area(slug: str) -> float:
    b = bbox(slug) or [0, 0, 360, 180]
    return (b[2] - b[0]) * (b[3] - b[1])


def named(name: str, point: tuple[float, float] | None = None, pad: float = 0.02) -> str | None:
    """The one Virginia water called exactly `name` (point = (lon, lat): its box, padded, must hold
    the point). None when there is no such record or the name is ambiguous."""
    by_name, _, _ = _index()
    cands = [s for s, _ in by_name.get(norm_text(name), [])]
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
        notes.append(f"'{name}': the point is not near any of the {len(cands)} Virginia waters with this name: not used")
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
    """(slugs, notes) for free text within Virginia. point is (lon, lat)."""
    t = norm_text(text)
    if not t:
        return [], []
    if point is not None and not in_va(*point):
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
    return tuple(o for o in rows if str(o.get("npdes_permit", "")).startswith("VA"))


def echo_outfalls(permits: set[str] | None = None) -> list[dict]:
    return [o for o in _echo() if permits is None or o["npdes_permit"] in permits]


def echo_outfall(permit: str, number: str | None) -> dict | None:
    """The inventory row for permit + outfall number ('6', '06', '006' are the same outfall)."""
    if not number:
        return None
    m = re.fullmatch(r"0*(\d+)([A-Z]?)", str(number).strip().upper())
    if not m:
        return None
    want = f"{int(m.group(1)):03d}{m.group(2)}"
    for o in echo_outfalls({permit}):
        if str(o.get("outfall") or "").upper() == want:
            return o
    return None


def metres(lat1, lon1, lat2, lon2) -> float:
    my = 111_320.0
    mx = my * math.cos(math.radians((lat1 + lat2) / 2))
    return math.hypot((lat1 - lat2) * my, (lon1 - lon2) * mx)


if __name__ == "__main__":
    sys.exit(main())
