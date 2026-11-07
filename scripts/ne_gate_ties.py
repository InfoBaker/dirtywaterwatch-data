"""Nebraska's go-live gates (2026-11-07): Omaha's four combined sewer outfalls on an outfall channel to the Missouri River.

Usage: pipeline/.venv/bin/python -I scripts/ne_gate_ties.py [--check]
  --check: change nothing; exit 1 when a row of the table is not as the table says (after an offline ties run, or a
           cloud ties run that reads the rows another way, rerun this script).

Why: Omaha's combined sewer permit NE0133680 has 25 open outfalls in EPA's CSO inventory (data/outfalls-us.json). Nine
give the receiving water as 'Outfall channel to Missouri River' (EPA's receiving-water text, from the state). The tie of
2026-11-01 (scripts/match_outfalls.py) put all nine on the Missouri River; the cloud ties of 2026-11-07
(ingest.outfall_waters) kept five (111, 112, 114, 115, 117: within 400 m of openboatlaunch's Missouri River line) and
undid four (105 Minne Lusa Avenue, 106, 107, 108) as "no record named 'Outfall channel' in NE", reading the channel as
the water. The text names the Missouri River as the water the channel carries the overflow to, so each of the four gets
receiving_water_override {water: "Missouri River", basis} (a later `python -m ingest.outfall_waters --state NE` then
finds the same record by name) and the tie fields, with the distance measured on 2026-11-07 from the row's own point
to openboatlaunch's Missouri River line as its water page publishes it (a centre line: the river's bank is nearer).
Outfall 205R (the city's retention treatment basin at 64th and Dupont) has no point in EPA's inventory: its row carries
the facility's point (coords_from 'facility'), the same point as outfall 107 on the Missouri riverfront, 10.9 km from
Little Papillion Creek, the water EPA's text names for it. POINT_NOT_USED keeps that point as published in
echo_lat/echo_lon and leaves lat/lon empty with coords_problem saying why (the way ingest.outfall_waters sets aside a
point that cannot be the outfall's), so placement, reaches and the rain check do not use it; the row stays tied to
Little Papillion Creek by EPA's receiving-water text. No point is invented.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "pipeline"))

BY = "scripts/ne_gate_ties.py (NE go-live gates, 2026-11-07)"
OBL = "openboatlaunch record; distance to its line as published on its water page, 2026-11-07"
FILE = "outfalls-us.json"
TEXT = "Outfall channel to Missouri River"


def epa(outfall: str) -> str:
    return (f"EPA's CSO inventory gives outfall {outfall} of permit NE0133680 (Omaha's combined sewer system) the "
            f"receiving water '{TEXT}': the channel carries the overflow to the Missouri River")


# (permit, outfall): (slug, the override's water, metres from the row's point, how measured, basis)
TABLE = {
    ("NE0133680", "105"): ("missouri-river-ne", "Missouri River", 946, OBL, epa("105")),
    ("NE0133680", "106"): ("missouri-river-ne", "Missouri River", 999, OBL, epa("106")),
    ("NE0133680", "107"): ("missouri-river-ne", "Missouri River", 1052, OBL, epa("107")),
    ("NE0133680", "108"): ("missouri-river-ne", "Missouri River", 547, OBL, epa("108")),
}


# (permit, outfall): (slug, EPA's receiving-water text, why the point is not the outfall's)
POINT_NOT_USED = {
    ("NE0133680", "205R"): ("little-papillion-creek-ne", "Little Papillion Creek",
                            "EPA's inventory gives no point for outfall 205R (City of Omaha Retention Treatment Basin, "
                            "64th and Dupont); the row's point was the facility's, shared with outfall 107 on the "
                            "Missouri riverfront and 10.9 km from Little Papillion Creek, so it is not this outfall's "
                            "place and is not used"),
}


def set_point_aside(o: dict, entry: tuple, w: dict) -> None:
    slug, text, why = entry
    if o.get("lat") is not None or o.get("lon") is not None:
        o["echo_lat"], o["echo_lon"] = o.get("lat"), o.get("lon")
    o["lat"] = o["lon"] = None
    o["coords_problem"] = why
    o.update(water_slug=slug, water_name=w.get("name"), water_kind=w.get("kind"), distance_m=None, match="name_only")
    o["water_match"] = (f"receiving water: EPA's CSO inventory gives outfall {o.get('outfall')} the receiving water "
                        f"'{text}'; {w.get('name')} ({slug}, NHDPlus V2.1 record), by name; the row has no point of "
                        f"its own (coords_problem)")
    o["water_matched_by"] = BY
    o.pop("no_water_reason", None)
    o.pop("replaced_match", None)


def waters() -> dict:
    from build import status as S
    return S.load_waters()


def tie(o: dict, entry: tuple, w: dict) -> None:
    slug, water, d, how, basis = entry
    o["receiving_water_override"] = {"water": water, "basis": basis + " (NE go-live gates 2026-11-07)"}
    named = water.lower() in [str(x).lower() for x in [w.get("name")] + list(w.get("aliases") or [])]
    o.update(water_slug=slug, water_name=w.get("name"), water_kind=w.get("kind"), distance_m=d,
             match="geometry+name" if named and d <= 400 else "geometry" if d <= 400 else "name_only")
    o["water_match"] = f"receiving water: {basis}; {w.get('name')} ({slug}, {how}), {d} m from the point"
    o["water_matched_by"] = BY
    o.pop("no_water_reason", None)
    o.pop("replaced_match", None)


def apply(doc: dict, wat: dict) -> list[str]:
    """Write the table into the loaded file; returns the keys not found."""
    idx = {(o.get("npdes_permit"), str(o.get("outfall"))): o for o in doc["outfalls"]}
    missing = []
    for key, entry in TABLE.items():
        o = idx.get(key)
        if o is None or entry[0] not in wat or o.get("receiving_water_echo") != TEXT:
            missing.append("/".join(key))
            continue
        tie(o, entry, wat[entry[0]])
    for key, entry in POINT_NOT_USED.items():
        o = idx.get(key)
        if o is None or entry[0] not in wat or o.get("receiving_water_echo") != entry[1] \
                or o.get("coords_from") != "facility":
            missing.append("/".join(key))
            continue
        set_point_aside(o, entry, wat[entry[0]])
    return missing


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    path = DATA / FILE
    old = path.read_text()
    doc = json.loads(old)
    before = json.dumps(doc, sort_keys=True)
    missing = apply(doc, waters())
    if missing:
        print("not found: " + ", ".join(missing))
        return 1
    changed = json.dumps(doc, sort_keys=True) != before
    if "--check" in argv:
        print("as the table says" if not changed else "rows differ from the table: rerun without --check")
        return 1 if changed else 0
    # the file keeps its own format: indent 1, its non-ASCII text as written
    new = json.dumps(doc, indent=1, ensure_ascii=json.dumps(json.loads(old), indent=1) == old)
    if new != old:
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(new)
        tmp.replace(path)
    print(f"data/{FILE}: {'written' if path.read_text() != old else 'unchanged'}")
    print(f"{len(TABLE)} rows tied, {len(POINT_NOT_USED)} row's point set aside")
    return 0


if __name__ == "__main__":
    sys.exit(main())
