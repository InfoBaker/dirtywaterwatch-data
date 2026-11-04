"""Cut a state's lake records that run past its land into other states' or Canada's waters (the Great Lakes) to the
state's own waters, so that a report placed on "Lake Michigan" in Michigan colours Michigan's part of the lake and not
Wisconsin's, Illinois' and Indiana's.

Usage (from the repository root):
    pipeline/.venv/bin/python -I scripts/cut_lakes_to_state_waters.py --state MI [--dry-run]

Why: ingest/waters_from_nhd.py cuts a record to the state with the Census cartographic outlines
(cb_2023_us_state_500k), which end at the shore: water outside every outline stays, so an NHDPlus Great Lakes polygon
keeps the whole lake's United States part (Lake Michigan 57,137 km2 for Michigan) and its validation lists the record
as "outside MI bbox". The Census TIGER/Line state boundaries (tl_2023_us_state.zip, public domain) run through the
Great Lakes along the state and international lines; this script intersects each lake record (kind lake, pond or
reservoir) of the state whose geometry has more than MIN_OUTSIDE_KM2 outside the state's TIGER polygon with that
polygon, simplifies it as the builder does (~10 m), and rewrites geometry, bbox, area_km2 and the note; the towns,
slug, aliases and targets stay. The matching "outside <ST> bbox" problems in data/waters-nhd.json are dropped when the
new bounds lie inside the state's box. The zip is read from data/raw/census/ or downloaded once (about 10 MB).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pipeline"))

TIGER_NAME = "tl_2023_us_state.zip"
TIGER_URL = f"https://www2.census.gov/geo/tiger/TIGER2023/STATE/{TIGER_NAME}"
TIGER_STEM = "tl_2023_us_state"
WATERS = ROOT / "data" / "waters-nhd.json"
LAKE_KINDS = {"lake", "pond", "reservoir"}
MIN_OUTSIDE_KM2 = 1.0
NOTE = ("; cut to the state's waters along the state and international lines in the lake (Census TIGER/Line 2023 "
        "state boundary)")


def tiger_zip(download: bool = True) -> Path:
    from ingest import waters_extra as WX
    dest = WX.RAW_DIR / "census" / TIGER_NAME
    return WX.states_zip(candidates=[dest], download=download, url=TIGER_URL, dest=dest,
                         members=(f"{TIGER_STEM}.shp", f"{TIGER_STEM}.dbf"))


def cut_record(w: dict, state_shape, states_bbox) -> dict | None:
    """The record cut to state_shape, or None when it lies inside it already (less than MIN_OUTSIDE_KM2 outside)."""
    from shapely.geometry import mapping, shape
    from ingest import waters_extra as WX
    from ingest import waters_from_nhd as N
    if w.get("kind") not in LAKE_KINDS or not w.get("geometry"):
        return None
    g = shape(w["geometry"])
    if not g.is_valid:
        g = g.buffer(0)
    outside = g.difference(state_shape)
    if outside.is_empty or WX.area_km2(outside) < MIN_OUTSIDE_KM2:
        return None
    cut = WX.as_areas(g.intersection(state_shape))
    if cut is None or cut.is_empty:
        return None
    cut = WX.as_areas(WX.simplify(cut, N.SIMPLIFY_M))
    b = cut.bounds
    note = (w.get("note") or "").replace(", cut to the state, simplified", ", simplified")
    out = dict(w)
    out.update(geometry=mapping(cut), bbox=[round(b[0], 5), round(b[1], 5), round(b[2], 5), round(b[3], 5)],
               area_km2=round(WX.area_km2(cut), 3), note=note + NOTE)
    return out


def run(state: str, dry_run: bool = False, doc: dict | None = None, state_shape=None, states_bbox=None) -> dict:
    from ingest import waters_extra as WX
    from ingest import waters_from_nhd as N
    write = doc is None
    doc = doc if doc is not None else json.loads(WATERS.read_text())
    if state_shape is None:
        state_shape = N.read_state_outlines({state}, zip_path=tiger_zip(), stem=TIGER_STEM)[state]
    if states_bbox is None:                 # the state's waters' box (TIGER), not its land's (cartographic)
        states_bbox = state_shape.bounds
    changed = []
    for i, w in enumerate(doc["waters"]):
        if w.get("state") != state:
            continue
        new = cut_record(w, state_shape, states_bbox)
        if new is not None:
            changed.append((w["slug"], w.get("area_km2"), new["area_km2"], new["bbox"]))
            doc["waters"][i] = new
    done = {s for s, *_ in changed}
    tol = 0.02
    sb = states_bbox

    def inside(slug):
        w = next(x for x in doc["waters"] if x["slug"] == slug)
        b = w["bbox"]
        return b[0] >= sb[0] - tol and b[1] >= sb[1] - tol and b[2] <= sb[2] + tol and b[3] <= sb[3] + tol

    doc["problems"] = [p for p in doc.get("problems") or []
                       if not (p.split(":", 1)[0] in done and f"outside {state} bbox" in p and inside(p.split(":", 1)[0]))]
    if write and not dry_run and changed:
        WATERS.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return {"changed": changed, "problems": doc["problems"]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    rep = run(a.state.upper(), a.dry_run)
    for slug, before, after, bbox in rep["changed"]:
        print(f"{slug}: {before} km2 -> {after} km2, bbox {bbox}")
    print(f"{len(rep['changed'])} records cut; problems left: {rep['problems']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
