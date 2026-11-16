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

    pipeline/.venv/bin/python -I scripts/cut_lakes_to_state_waters.py --shared [--dry-run]

--shared (2026-11-16): a water two states share that openboatlaunch gives each state whole (one outline, a copy of the
record per state, the same water_id: Flaming Gorge Reservoir is flaming-gorge-reservoir-wy and -ut, 161.98 km2 each,
about a third of it in Utah), so a Wyoming advisory placed on the Wyoming record coloured Utah's side too. Each record
SHARED names (the openboatlaunch extract record, data/waters-<st>.json) has openboatlaunch's outline (its
out/water/<slug>.json, build/status.py OBL_WATER_DIR) cut by its state's TIGER/Line polygon as above, and the part is
written to data/water-state-parts.json with its bbox, area, the whole water's area, the records of the other states'
parts (other_parts), the extract's geometry_hash it was cut from, and the note; build/status.py load_waters applies it
(apply_state_parts). The extract files are not written (a new extract keeps the cut: it lives in the hand file), and a
part whose outline openboatlaunch later changes is listed as a build problem until this is run again.
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
STATE_PARTS = ROOT / "data" / "water-state-parts.json"
# {extract slug: {"state", "other_parts", "why"}}: the records of one water, each cut to its own state's part
SHARED = {
    "flaming-gorge-reservoir-wy": {
        "state": "WY", "other_parts": ["flaming-gorge-reservoir-ut"],
        "why": "openboatlaunch gives Wyoming the whole reservoir, about a third of it in Utah; Wyoming DEQ's bloom "
               "advisory colours Wyoming's part (owner, 2026-11-16)"},
    "flaming-gorge-reservoir-ut": {
        "state": "UT", "other_parts": ["flaming-gorge-reservoir-wy"],
        "why": "openboatlaunch gives Utah the whole reservoir, about two thirds of it in Wyoming (owner, 2026-11-16)"},
}
SHARED_NOTE = ("openboatlaunch's outline of the whole water cut to this state's part along the state line (Census "
               "TIGER/Line 2023 state boundary), simplified to ~10 m")
NOTE = ("; cut to the state's waters along the state and international lines in the lake (Census TIGER/Line 2023 "
        "state boundary)")


def tiger_zip(download: bool = True) -> Path:
    """The TIGER/Line zip, downloaded once; the download is checked for the TIGER files (states_zip checks for the
    cartographic file's members by default, which the TIGER zip does not hold)."""
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
        from common import write_rows_json      # the file's one layout (common.dumps_rows)
        write_rows_json(WATERS, doc)
    return {"changed": changed, "problems": doc["problems"]}


def extract_record(slug: str, state: str, data_dir: Path | None = None) -> dict | None:
    """The openboatlaunch extract's record of slug (data/waters-<st>.json), as on file (no part applied)."""
    p = (data_dir or ROOT / "data") / f"waters-{state.lower()}.json"
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    return next((w for w in (d.get("waters") or []) if isinstance(w, dict) and w.get("slug") == slug), None)


def obl_outline(slug: str):
    """openboatlaunch's outline of the record (out/water/<slug>.json in build/status.py OBL_WATER_DIR), or None."""
    from build import status as S
    p = S.OBL_WATER_DIR / f"{slug}.json"
    try:
        return S.outline_of(json.loads(p.read_text()))
    except (OSError, ValueError):
        return None


def shared_part(slug: str, spec: dict, rec: dict, outline, state_shape, when: str) -> tuple[dict | None, str]:
    """(the record's part in its state, why not): openboatlaunch's whole outline cut by the state's TIGER polygon and
    simplified as cut_record does, with its bbox, area, the whole area, other_parts, the hash it was cut from."""
    from shapely.geometry import mapping
    from ingest import waters_extra as WX
    from ingest import waters_from_nhd as N
    if rec is None:
        return None, "no record of this slug in the state's openboatlaunch extract"
    if rec.get("kind") not in LAKE_KINDS:
        return None, f"kind {rec.get('kind')!r} is not a lake, pond or reservoir"
    if outline is None or outline.is_empty:
        return None, "openboatlaunch's outline is not on this machine (OBL_WATER_DIR)"
    g = outline if outline.is_valid else outline.buffer(0)
    whole = WX.area_km2(g)
    cut = WX.as_areas(g.intersection(state_shape))
    if cut is None or cut.is_empty:
        return None, "no part of the outline lies in the state"
    if whole - WX.area_km2(cut) < MIN_OUTSIDE_KM2:
        return None, f"less than {MIN_OUTSIDE_KM2} km2 of the outline lies outside the state: nothing to cut"
    cut = WX.as_areas(WX.simplify(cut, N.SIMPLIFY_M))
    b = cut.bounds
    # as the file holds it (lists, not tuples), so an unchanged cut compares equal on a rerun (review 2026-11-16 P3)
    return {"geometry": json.loads(json.dumps(mapping(cut))), "bbox": [round(b[0], 5), round(b[1], 5), round(b[2], 5), round(b[3], 5)],
            "area_km2": round(WX.area_km2(cut), 3), "whole_area_km2": round(whole, 3),
            "other_parts": list(spec["other_parts"]), "cut_from_geometry_hash": rec.get("geometry_hash"),
            "cut": when, "note": SHARED_NOTE, "why": spec["why"]}, ""


def run_shared(dry_run: bool = False, shared: dict | None = None, shapes: dict | None = None, records=None,
               outlines=None, path: Path | None = None, when: str | None = None) -> dict:
    """--shared: every SHARED record cut to its state's part, written to data/water-state-parts.json (sorted by slug;
    the file's other entries kept). records(slug, state) and outlines(slug) default to the extract and
    openboatlaunch's folder; shapes {state: polygon} to the TIGER/Line file. A record that cannot be cut here keeps
    the part on file and says why."""
    from datetime import datetime, timezone
    from common import write_json
    from ingest import waters_from_nhd as N
    shared = SHARED if shared is None else shared
    path = path or STATE_PARTS
    when = when or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    records = records or extract_record
    outlines = outlines or obl_outline
    if shapes is None:
        shapes = N.read_state_outlines({v["state"] for v in shared.values()}, zip_path=tiger_zip(), stem=TIGER_STEM)
    try:
        doc = json.loads(path.read_text())
    except (OSError, ValueError):
        doc = {}
    changed, kept = [], []
    for slug, spec in sorted(shared.items()):
        part, why = shared_part(slug, spec, records(slug, spec["state"]), outlines(slug), shapes[spec["state"]], when)
        if part is None:
            kept.append((slug, why))
            continue
        old = doc.get(slug)
        if old and {k: v for k, v in old.items() if k != "cut"} == {k: v for k, v in part.items() if k != "cut"}:
            continue                        # the same part: the date of the first cut stays
        doc[slug] = part
        changed.append((slug, part["whole_area_km2"], part["area_km2"], part["bbox"]))
    doc = dict(sorted(doc.items()))
    if changed and not dry_run:
        write_json(path, doc)
    return {"changed": changed, "kept": kept, "doc": doc}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--state")
    ap.add_argument("--shared", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    if a.shared:
        rep = run_shared(a.dry_run)
        for slug, before, after, bbox in rep["changed"]:
            print(f"{slug}: {before} km2 -> {after} km2, bbox {bbox}")
        for slug, why in rep["kept"]:
            print(f"{slug}: not cut ({why})")
        print(f"{len(rep['changed'])} shared records cut{' (dry run)' if a.dry_run else ''}")
        return 0
    if not a.state:
        ap.error("--state or --shared is required")
    rep = run(a.state.upper(), a.dry_run)
    for slug, before, after, bbox in rep["changed"]:
        print(f"{slug}: {before} km2 -> {after} km2, bbox {bbox}")
    print(f"{len(rep['changed'])} records cut; problems left: {rep['problems']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
