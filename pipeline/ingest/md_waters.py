"""Maryland water records and name matching for the Maryland ingesters (shared helper, not a feed).

- extract(): openboatlaunch's Maryland water records (../openboatlaunch/out/water/*-md.json with state
  MD) -> data/waters-md.json in the shape of data/waters-{nj,ny,pa}.json (slug, name, kind, state,
  towns, bbox, wikidata, charted, area_km2, launches as slugs, advisories), and the MD rows of
  data/waters-mid-atlantic.csv (rows of other states kept as they are). Run once per openboatlaunch
  snapshot:  python -m ingest.md_waters --extract
- match_waters(): names typed by an agency (a receiving water, an affected stretch) -> water slugs,
  with the conservative rules of ingest/nj_waters.py and ingest/pa_waters.py: whole-word, accent-
  and punctuation-insensitive, longest names first; "Lake X" = "X Lake"; a name that runs on into
  another water word, or follows "Little", "North Branch" ..., "tributary of", is a different water;
  with a point (lon, lat) only a water whose box (padded ~2 km) holds it; a name shared by several
  records needs a point or a town. A wrong slug colours the wrong water, so anything uncertain stays
  unmatched with a note.
- Maryland's name traps (research/md/report.md section 3): broad-creek-md is in Darlington (Harford),
  not the Prince George's Broad Creek; herring-creek-md is in St. Mary's, not Baltimore's Herring Run;
  back-creek-md is Annapolis; mill-creek-md is Perryville; wicomico-river-md is the St. Mary's /
  Charles river and Salisbury's is wicomico-river-mt-vernon-md. These records are used only when the
  record's county is theirs (TRAP_COUNTIES), or, with no county, when the point lies inside their box.
- County readings (COUNTY_ALIASES): in Allegany and Garrett counties "Potomac River" is the North
  Branch Potomac River (openboatlaunch's potomac-river-md begins at the confluence of the North and
  South Branches below Cumberland; its box starts at -78.587); in Prince George's County a bare
  "Western Branch" is the Western Branch Patuxent River. The point, when given, is still checked.
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import re
import sys
from functools import lru_cache
from pathlib import Path

from common import DATA_DIR, ROOT, write_json
from ingest.nh_vt_waters import FLOW_BEFORE, TRIB_BEFORE, WATER_WORD, norm

STATE = "MD"
MD_BBOX = (-79.5, 37.9, -75.0, 39.8)          # lon/lat; the check the MDE coordinates are repaired against
OBL_WATER_DIR = ROOT.parent / "openboatlaunch" / "out" / "water"
WATERS_JSON = DATA_DIR / "waters-md.json"
WATERS_CSV = DATA_DIR / "waters-mid-atlantic.csv"
GENERIC_LAST = {"lake", "lakes", "reservoir", "pond", "ponds", "millpond"}
NEXT_WATER = re.compile(r"\s*(brook|creek|river|stream|kill|outlet|inlet|canal|tributary|trib|run|ditch|branch|falls)\b")
OTHER_BEFORE = re.compile(r"\b(little|north branch|south branch|east branch|west branch|middle branch|northeast branch|"
                          r"northwest branch|old|upper|lower)\s*$")
TOWN_SUFFIX = re.compile(r"\b(borough|boro|township|twp|city|town|village)\b")
TRAP_COUNTIES = {
    "broad-creek-md": {"harford"},
    "broad-creek-st-michaels-md": {"talbot"},
    "herring-creek-md": {"st marys"},
    "back-creek-md": {"anne arundel"},
    "mill-creek-md": {"cecil"},
    "wicomico-river-md": {"st marys", "charles"},
    "wicomico-river-mt-vernon-md": {"wicomico", "somerset"},
}
# county-specific readings of a bare name (applied to the normalised text before matching)
_NB = ("north branch potomac river", "'Potomac River' in Allegany/Garrett County read as the North Branch Potomac "
       "River (potomac-river-md begins at the confluence below Cumberland)")
_WB = ("western branch patuxent river", "'Western Branch' in Prince George's County read as the Western Branch "
       "Patuxent River (WSSC's Western Branch sewershed)")
COUNTY_ALIASES = {
    "allegany": [(re.compile(r"(?<!branch )\bpotomac river\b"), *_NB)],
    "garrett": [(re.compile(r"(?<!branch )\bpotomac river\b"), *_NB)],
    "prince georges": [(re.compile(r"\bwestern branch\b(?! (?:of (?:the )?)?patuxent)"), *_WB)],
}


def norm_county(s: str | None) -> str:
    t = norm(str(s or "").replace("'", "").replace("\u2019", ""))
    t = re.sub(r"\bsaint\b", "st", t)
    t = re.sub(r"\s+county$", "", t)
    return t.strip()


def norm_town(s: str | None) -> str:
    t = norm(s)
    t = re.sub(r"^(town|city|village|borough|township) of ", "", t)
    t = TOWN_SUFFIX.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


# ---------------------------------------------------------------- extract

def water_record(d: dict) -> dict:
    """One openboatlaunch out/water/<slug>.json -> the extract's shape."""
    return {
        "slug": d["slug"], "name": d.get("name"), "kind": d.get("kind"), "state": d.get("state"),
        "towns": list(d.get("towns") or []), "bbox": d.get("bbox"), "wikidata": d.get("wikidata"),
        "charted": d.get("charted"), "area_km2": d.get("area_km2"),
        "launches": [x["s"] for x in d.get("launches") or [] if isinstance(x, dict) and x.get("s")],
        "advisories": list(d.get("advisories") or []),
    }


def extract(obl_dir: Path = OBL_WATER_DIR, out_json: Path = WATERS_JSON, out_csv: Path | None = WATERS_CSV,
            snapshot: str | None = None) -> dict:
    """Write data/waters-md.json (and the MD rows of data/waters-mid-atlantic.csv)."""
    waters = []
    for p in sorted(Path(obl_dir).glob("*-md.json")):
        try:
            d = json.loads(p.read_text())
        except Exception:  # noqa: BLE001 - a half-written file in the snapshot is skipped, not fatal
            continue
        if d.get("state") != STATE or not d.get("slug"):
            continue
        waters.append(water_record(d))
    waters.sort(key=lambda w: w["slug"])
    snap = snapshot
    if snap is None:
        meta = Path(obl_dir).parent / "meta.json"
        try:
            m = json.loads(meta.read_text())
            snap = str(m.get("built") or m.get("generated") or m.get("updated") or "")[:10] or None
        except Exception:  # noqa: BLE001
            snap = None
    out = {"state": STATE, "source": f"openboatlaunch out/water snapshot {snap or 'unknown date'}",
           "count": len(waters), "waters": waters}
    write_json(out_json, out)
    if out_csv is not None:
        _write_csv_rows(out_csv, waters)
    _records.cache_clear()
    _index.cache_clear()
    return out


def _write_csv_rows(path: Path, waters: list[dict]) -> None:
    head = ["slug", "name", "kind", "state", "towns", "launch_count", "wikidata"]
    rows = []
    if path.exists():
        with open(path, newline="") as f:
            rows = [r for r in csv.DictReader(f) if r.get("state") != STATE]
    rows += [{"slug": w["slug"], "name": w["name"], "kind": w["kind"], "state": STATE,
              "towns": "; ".join(w["towns"]), "launch_count": len(w["launches"]), "wikidata": w["wikidata"] or ""}
             for w in waters]
    buf = io.StringIO()
    wr = csv.DictWriter(buf, fieldnames=head)
    wr.writeheader()
    for r in rows:
        wr.writerow({k: r.get(k, "") for k in head})
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(buf.getvalue())
    tmp.replace(path)


# ---------------------------------------------------------------- lookup

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
    return out


@lru_cache(maxsize=None)
def _index():
    by_name: dict[str, list[tuple[str, set[str]]]] = {}
    bare: dict[str, list[str]] = {}
    for slug, r in _records().items():
        towns = {norm_town(t) for t in r.get("towns") or [] if str(t).strip()}
        n = norm(r.get("name"))
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


def kind_of(slug: str) -> str | None:
    return (_records().get(slug) or {}).get("kind")


def in_md(lon, lat) -> bool:
    return (isinstance(lon, (int, float)) and isinstance(lat, (int, float))
            and MD_BBOX[0] <= lon <= MD_BBOX[2] and MD_BBOX[1] <= lat <= MD_BBOX[3])


def _holds(slug: str, lon: float, lat: float, pad: float) -> bool | None:
    b = bbox(slug)
    if not b:
        return None
    return b[0] - pad <= lon <= b[2] + pad and b[1] - pad <= lat <= b[3] + pad


def _area(slug: str) -> float:
    b = bbox(slug) or [0, 0, 360, 180]
    return (b[2] - b[0]) * (b[3] - b[1])


def trap_ok(slug: str, county: str | None, point) -> tuple[bool, str | None]:
    """A name-trap record is used only in its own county (or, with no county, when the point lies in
    its box). Other records pass."""
    allowed = TRAP_COUNTIES.get(slug)
    if not allowed:
        return True, None
    c = norm_county(county) if county else ""
    if c:
        if c in allowed:
            return True, None
        return False, (f"{slug} is the {name_of(slug)} in {'/'.join(sorted(allowed))} county; this record is in "
                       f"{county}: not used (name trap)")
    if point is not None and _holds(slug, point[0], point[1], 0.003):
        return True, None
    return False, f"{slug} is a name trap (several Maryland waters share the name) and no county or point confirms it: not used"


def _pick(name: str, cands: list[tuple[str, set[str]]], point, town_set: set[str], county: str | None, pad: float,
          notes: list[str]) -> str | None:
    kept = []
    for s, tw in cands:
        ok, why = trap_ok(s, county, point)
        if ok:
            kept.append((s, tw))
        elif why:
            notes.append(why)
    cands = kept
    if not cands:
        return None
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
        notes.append(f"'{name}': the point is not near any of the {len(cands)} Maryland waters with this name: not used")
        return None
    if len(cands) == 1:
        return cands[0][0]
    hits = [s for s, tw in cands if town_set & tw]
    if len(hits) == 1:
        return hits[0]
    notes.append(f"'{name}' is shared by {len(cands)} waters and no point or town settles it: not used")
    return None


def named(name: str, point: tuple[float, float] | None = None, county: str | None = None,
          pad: float = 0.02) -> str | None:
    """The one Maryland water called exactly `name` (point = (lon, lat): its box, padded, must hold
    the point; name traps need their county). None when there is none or the name is ambiguous."""
    by_name, _, _ = _index()
    cands = [s for s, _ in by_name.get(norm(name), []) if trap_ok(s, county, point)[0]]
    if point is not None:
        cands = [s for s in cands if _holds(s, point[0], point[1], pad) is not False]
    if len(cands) > 1 and point is not None:
        cands = sorted(cands, key=_area)[:1]
    return cands[0] if len(cands) == 1 else None


def match_waters(text: str | None, towns: list[str] | None = None, point: tuple[float, float] | None = None,
                 county: str | None = None, pad: float = 0.02) -> tuple[list[str], list[str]]:
    """(slugs, notes) for free text within Maryland. point is (lon, lat); county is the source's
    county name ("Allegany", "Prince George's", "Baltimore City" ...)."""
    t = norm(text)
    if not t:
        return [], []
    notes: list[str] = []
    if point is not None and not in_md(*point):
        point = None
    for rx, repl, why in COUNTY_ALIASES.get(norm_county(county), []):
        if rx.search(t):
            t = rx.sub(repl, t)
            notes.append(why)
    by_name, names, bare = _index()
    town_set = {norm_town(x) for x in (towns or []) if x and norm_town(x)}
    taken = [False] * len(t)
    slugs: list[str] = []
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
            pick = _pick(name, by_name[name], point, town_set, county, pad, notes)
            if pick and pick not in slugs:
                slugs.append(pick)
    if not slugs and point is not None:
        for b in sorted(bare, key=len, reverse=True):
            m = re.search(rf"\b{re.escape(b)}\b", t)
            if len(b.replace(" ", "")) < 5 or not m or NEXT_WATER.match(t[m.end():]) or OTHER_BEFORE.search(t[:m.start()]):
                continue
            ok = [s for s in bare[b] if _holds(s, point[0], point[1], 0.003) and trap_ok(s, county, point)[0]]
            if len(ok) == 1:
                slugs.append(ok[0])
                notes.append(f"'{b}' read as {ok[0]} (the name without its generic word; the point lies in its box)")
                break
    return slugs, notes


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Extract openboatlaunch's Maryland water records (not a feed)")
    ap.add_argument("--extract", action="store_true", help="write data/waters-md.json and the MD rows of the CSV")
    ap.add_argument("--obl-dir", default=str(OBL_WATER_DIR))
    ap.add_argument("--snapshot", help="snapshot date for the 'source' line (default: openboatlaunch out/meta.json)")
    args = ap.parse_args(argv)
    if not args.extract:
        ap.print_help()
        return 0
    out = extract(Path(args.obl_dir), snapshot=args.snapshot)
    kinds = {}
    for w in out["waters"]:
        kinds[w["kind"]] = kinds.get(w["kind"], 0) + 1
    print(f"md_waters: {out['count']} Maryland waters -> {WATERS_JSON} ({kinds})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
