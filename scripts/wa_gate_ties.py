"""Washington's go-live gates (2026-11-06): King County's and Seattle's outfalls tied by the operators' own lists.

Usage: pipeline/.venv/bin/python -I scripts/wa_gate_ties.py [--check]
  --check: change nothing; exit 1 when a row of the table is not as the table says (after a rebuild of
           data/outfalls-wa.json by scripts/build_wa_outfalls.py, or an offline ties run, rerun this script).

Why: after the openboatlaunch outline ties of 2026-11-04 (812 of 951 Washington rows tied), 41 rows of King County's
and Seattle's permits (WA0029181, WA0031682, WA0029581) had no water record, and 19 more were tied to the wrong water
by EPA's permit-level text or a misplaced point: King County's rows in EPA's file on the Duwamish Waterway, Pipers
Creek or Lake Washington 1.2 to 10.5 km away (Canal Street, 3rd Ave W, Ballard and Henderson among them); Seattle's
outfall 170 on Blackjack Creek in Kitsap County; two South plant outfalls on the Black River near Olympia.
The operators' lists name every one of these outfalls' waters:
  - Ecology's permit WA0029181 (King County West Point and its CSO outfalls, effective 2024-06-01), table 1 (the
    treatment plants' outfalls) and table 32 (each CSO outfall's receiving water and point);
  - Ecology's permit WA0031682 (Seattle's combined sewer system, effective 2025-12-01), table 2 (each outfall's
    receiving water and point), which Seattle Public Utilities' CSO basin layer repeats (ArcGIS item
    1dd13c8a00ae4ff187cef29d208a5ada, CSOB_REC_WTR_BDY_NAME, with Ecology's water body ids);
  - Ecology's permit WA0029581 (King County South plant, effective 2015-07-01), S1.A and its fact sheet.
Each row of TABLE gets receiving_water_override {water, basis} (the operator's water as the record names it, so a
later `python -m ingest.outfall_waters --state WA` with the outlines finds the same record by name) and the tie
fields, with the distance measured on 2026-11-06 from the row's own point: to openboatlaunch's outline as its water
page publishes it (the cloud runs' outlines; none is on file here), or to the record's own geometry (Census TIGER/Line
and NHD records, data/waters-nhd.json). Nothing here moves a point except the South plant's marine outfall, whose EPA
point is the plant in Renton, 15 km from the diffuser the permit locates; EPA's point is kept in epa_lat/epa_lon.
Rows the operators name a water for that has no record (Seattle's three Longfellow Creek outfalls: NHDPlus V2.1, the
NHD high-resolution flowlines and the Census hydrography carry no Longfellow Creek; OpenStreetMap does, and its
Overpass service did not answer from here) get the override and a reason, no tie.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "pipeline"))

BY = "scripts/wa_gate_ties.py (WA go-live gates, 2026-11-06)"
KC = "Ecology's permit WA0029181 (King County West Point, effective 2024-06-01)"
SEA = ("Ecology's permit WA0031682 (City of Seattle combined sewer system, effective 2025-12-01), table 2, and Seattle "
       "Public Utilities' CSO basin layer")
SOUTH = "Ecology's permit WA0029581 (King County South plant, effective 2015-07-01)"
OBL = "openboatlaunch record; distance to its outline as published on its water page, 2026-11-06"
CENSUS = "Census TIGER/Line record (data/waters-nhd.json)"
NHD = "NHDPlus V2.1 record (data/waters-nhd.json)"

FILES = {"wa": "outfalls-wa.json", "us": "outfalls-us.json", "plants": "outfalls-plants-us.json"}


def kc(dsn, name, said):
    return f"{KC}, table 32, gives outfall {dsn} ({name}) the receiving water '{said}'"


def sea(dsn, said, wbid):
    return f"{SEA} give outfall {dsn} the receiving water '{said}' (Ecology water body {wbid})"


# (file, permit, outfall): (slug, the override's water, metres from the row's point, how measured, basis)
TABLE = {
    ("wa", "WA0029181", "007"): ("lake-washington-ship-canal-wa", "Lake Washington Ship Canal", 258, OBL,
                                 kc("007", "Canal Street Overflow", "Lake Washington Ship Canal")),
    ("wa", "WA0029181", "008"): ("lake-washington-ship-canal-wa", "Lake Washington Ship Canal", 126, OBL,
                                 kc("008", "3rd Avenue West Overflow", "Lake Washington Ship Canal")),
    ("wa", "WA0029181", "014"): ("montlake-cut-wa", "Montlake Cut", 0, CENSUS,
                                 kc("014", "Montlake Overflow", "Lake Washington Ship Canal")
                                 + "; the point lies on the Montlake Cut, the canal's stretch between Union Bay and "
                                   "Portage Bay (USGS GNIS 1534602), which openboatlaunch's Ship Canal record does "
                                   "not cover"),
    ("wa", "WA0029181", "030"): ("east-waterway-wa", "East Waterway", 0, CENSUS,
                                 kc("030", "Lander Street Regulator", "Duwamish River - East Waterway")),
    ("wa", "WA0029181", "032"): ("east-waterway-wa", "East Waterway", 18, CENSUS,
                                 kc("032", "Hanford #2 Regulator", "Duwamish River - East Waterway")),
    ("wa", "WA0029181", "057"): ("puget-sound-wa", "Puget Sound", 293, OBL,
                                 kc("057", "Barton St PS Emergency Overflow", "Puget Sound")),
    ("wa", "WA0031682", "019"): ("lake-washington-wa", "Lake Washington", 286, OBL,
                                 sea("019", "Union Bay", "WA-08-9350, Lake Washington") + "; Union Bay is the bay of "
                                 "Lake Washington at the Montlake Cut, inside openboatlaunch's Lake Washington record"),
    ("wa", "WA0031682", "059"): ("salmon-bay-waterway-wa", "Salmon Bay", 0, CENSUS,
                                 sea("059", "Salmon Bay", "WA-08-9340") + "; below the locks, on the Census polygon "
                                 "named Salmon Bay Waterway"),
    ("wa", "WA0031682", "060"): ("salmon-bay-waterway-wa", "Salmon Bay", 0, CENSUS,
                                 sea("060", "Salmon Bay", "WA-08-9340") + "; below the locks, on the Census polygon "
                                 "named Salmon Bay Waterway"),
    ("wa", "WA0031682", "091"): ("puget-sound-wa", "Puget Sound", 372, OBL,
                                 sea("091", "Puget Sound - Central", "WA-PS-0270")),
    ("wa", "WA0031682", "094"): ("puget-sound-wa", "Puget Sound", 326, OBL,
                                 sea("094", "Puget Sound - Central", "WA-PS-0270")),
    ("wa", "WA0031682", "095"): ("puget-sound-wa", "Puget Sound", 284, OBL,
                                 sea("095", "Puget Sound - Central", "WA-PS-0270")),
    ("wa", "WA0031682", "107"): ("east-waterway-wa", "East Waterway", 0, CENSUS,
                                 sea("107", "East Waterway - Duwamish River", "WA-09-1010")),
    ("wa", "WA0031682", "161"): ("lake-washington-wa", "Lake Washington", 469, OBL,
                                 sea("161", "Lake Washington", "WA-08-9350") + "; the permit's own point for it "
                                 "(47.67713, -122.24909) lies on the lake's outline"),
    ("wa", "WA0031682", "174"): ("lake-washington-ship-canal-wa", "Lake Washington Ship Canal", 83, OBL,
                                 sea("174", "Lake Washington - Ship Canal", "WA-08-9340")),
    # EPA's rows of the same permits (data/outfalls-us.json; the status file's rows above outrank them where both exist)
    ("us", "WA0029181", "007"): ("lake-washington-ship-canal-wa", "Lake Washington Ship Canal", 242, OBL,
                                 kc("007", "Canal Street Overflow", "Lake Washington Ship Canal")
                                 + "; EPA's text 'Duwamish Waterway' is the permit's label, 7.4 km away"),
    ("us", "WA0029181", "008"): ("lake-washington-ship-canal-wa", "Lake Washington Ship Canal", 126, OBL,
                                 kc("008", "3rd Avenue West Overflow", "Lake Washington Ship Canal")
                                 + "; EPA's text 'Pipers Creek' is another outfall's water, 5.4 km away"),
    ("us", "WA0029181", "012"): ("lake-washington-wa", "Lake Washington", 0, OBL,
                                 kc("012", "Belvoir PS Emergency Overflow", "Lake Washington (Union Bay)")
                                 + "; EPA's text 'Boeing Creek' is another outfall's water, 13 km away"),
    ("us", "WA0029181", "014"): ("montlake-cut-wa", "Montlake Cut", 0, CENSUS,
                                 kc("014", "Montlake Overflow", "Lake Washington Ship Canal")
                                 + "; the point lies on the Montlake Cut (USGS GNIS 1534602)"),
    ("us", "WA0029181", "027B"): ("elliott-bay-wa", "Elliott Bay", 0, OBL,
                                  f"{KC}, table 1, gives the Elliott West CSO Treatment Plant (027b) the receiving "
                                  "water 'Elliott Bay' (EPA writes 'Elliot Bay/Puget Sound')"),
    ("us", "WA0029181", "030"): ("east-waterway-wa", "East Waterway", 0, CENSUS,
                                 kc("030", "Lander Street Regulator", "Duwamish River - East Waterway")),
    ("us", "WA0029181", "032"): ("east-waterway-wa", "East Waterway", 18, CENSUS,
                                 kc("032", "Hanford #2 Regulator", "Duwamish River - East Waterway")
                                 + "; EPA's text 'Duwamish Waterway' is the permit's label"),
    ("us", "WA0029181", "034"): ("duwamish-river-wa", "Duwamish River", 0, OBL,
                                 kc("034", "E. Duwamish Siphon/Duwamish PS Emergency Overflow", "Duwamish River")),
    ("us", "WA0029181", "044"): ("duwamish-river-wa", "Duwamish River", 0, OBL,
                                 f"{KC}, table 1, gives the Henderson/MLK CSO Treatment Plant (044) the receiving water "
                                 "'Duwamish Waterway', and table 32 gives the Norfolk Street Regulator (044a) at the "
                                 "same point 'Duwamish River'; the point lies on openboatlaunch's Duwamish River record"),
    ("us", "WA0029181", "044A"): ("duwamish-river-wa", "Duwamish River", 0, OBL,
                                  kc("044a", "Norfolk Street Regulator", "Duwamish River")),
    ("us", "WA0029181", "057"): ("puget-sound-wa", "Puget Sound", 293, OBL,
                                 kc("057", "Barton St PS Emergency Overflow", "Puget Sound")),
    ("us", "WA0031682", "019"): ("lake-washington-wa", "Lake Washington", 286, OBL,
                                 sea("019", "Union Bay", "WA-08-9350, Lake Washington")),
    ("us", "WA0031682", "059"): ("salmon-bay-waterway-wa", "Salmon Bay", 0, CENSUS,
                                 sea("059", "Salmon Bay", "WA-08-9340")),
    ("us", "WA0031682", "060"): ("salmon-bay-waterway-wa", "Salmon Bay", 0, CENSUS,
                                 sea("060", "Salmon Bay", "WA-08-9340")),
    ("us", "WA0031682", "070"): ("elliott-bay-wa", "Elliott Bay", 16, OBL,
                                 "EPA's inventory gives the receiving water 'Elliot Bay' (Elliott Bay misspelt); the "
                                 "outfall is closed and not in the 2025 permit"),
    ("us", "WA0031682", "071"): ("elliott-bay-wa", "Elliott Bay", 33, OBL,
                                 sea("071", "Elliott Bay", "WA-09-0010")),
    ("us", "WA0031682", "072"): ("elliott-bay-wa", "Elliott Bay", 1, OBL,
                                 "EPA's inventory gives the receiving water 'Elliot Bay' (Elliott Bay misspelt); the "
                                 "outfall is closed and not in the 2025 permit"),
    ("us", "WA0031682", "091"): ("puget-sound-wa", "Puget Sound", 384, OBL,
                                 sea("091", "Puget Sound - Central", "WA-PS-0270")),
    ("us", "WA0031682", "094"): ("puget-sound-wa", "Puget Sound", 266, OBL,
                                 sea("094", "Puget Sound - Central", "WA-PS-0270")),
    ("us", "WA0031682", "095"): ("puget-sound-wa", "Puget Sound", 294, OBL,
                                 sea("095", "Puget Sound - Central", "WA-PS-0270")),
    ("us", "WA0031682", "107"): ("east-waterway-wa", "East Waterway", 24, CENSUS,
                                 sea("107", "East Waterway - Duwamish River", "WA-09-1010")),
    ("us", "WA0031682", "150"): ("salmon-bay-waterway-wa", "Salmon Bay Waterway", 0, CENSUS,
                                 "EPA's inventory gives the receiving water 'Salmon Bay Waterway', the Census polygon "
                                 "of that name; the outfall is closed and not in the 2025 permit"),
    ("us", "WA0031682", "174"): ("lake-washington-ship-canal-wa", "Lake Washington Ship Canal", 81, OBL,
                                 sea("174", "Lake Washington - Ship Canal", "WA-08-9340")),
    # EPA's other King County rows, tied by the outline ties of 2026-11-04 through EPA's permit-level text (review
    # 2026-11-04 P1-1) to waters 1.5 to 10.5 km away; the status file's rows outrank these, and the permit names each
    ("us", "WA0029181", "003"): ("lake-washington-ship-canal-wa", "Lake Washington Ship Canal", 7, OBL,
                                 kc("003", "Ballard Siphon Regulator", "Lake Washington Ship Canal")
                                 + "; EPA's text 'Duwamish Waterway' is the permit's label, 9.1 km away"),
    ("us", "WA0029181", "004"): ("lake-washington-ship-canal-wa", "Lake Washington Ship Canal", 0, OBL,
                                 kc("004", "11th Avenue NW (East Ballard Overflow)", "Lake Washington Ship Canal")),
    ("us", "WA0029181", "006"): ("elliott-bay-wa", "Elliott Bay", 0, OBL,
                                 kc("006", "Magnolia South Overflow", "Elliott Bay/Puget Sound")),
    ("us", "WA0029181", "009"): ("lake-union-wa", "Lake Union", 0, OBL,
                                 kc("009", "Dexter Avenue Regulator", "Lake Union")),
    ("us", "WA0029181", "028"): ("elliott-bay-wa", "Elliott Bay", 38, OBL,
                                 kc("028", "King Street Regulator", "Elliott Bay/Puget Sound")),
    ("us", "WA0029181", "029"): ("elliott-bay-wa", "Elliott Bay", 21, OBL,
                                 kc("029", "Kingdome (Connecticut St Regulator)", "Elliott Bay/Puget Sound")),
    ("us", "WA0029181", "031"): ("duwamish-river-wa", "Duwamish River", 1776, OBL,
                                 kc("031a,b,c", "Hanford #1 Regulator", "Duwamish River")
                                 + "; EPA's point lies 1.8 km west of the permit's (47.5631, -122.34531), which lies "
                                   "on the record (review 2026-11-04: EPA's point in error)"),
    ("us", "WA0029181", "035"): ("duwamish-river-wa", "Duwamish River", 0, OBL,
                                 kc("035", "W. Duwamish Siphon/Duwamish PS Emergency Overflow", "Duwamish River")),
    ("us", "WA0029181", "040"): ("duwamish-river-wa", "Duwamish River", 0, OBL,
                                 kc("040", "8th Avenue South Regulator", "Duwamish River")),
    ("us", "WA0029181", "041"): ("duwamish-river-wa", "Duwamish River", 25, OBL,
                                 kc("041", "Brandon Street Regulator", "Duwamish River")),
    ("us", "WA0029181", "042"): ("duwamish-river-wa", "Duwamish River", 0, OBL,
                                 kc("042", "Michigan W. Regulator", "Duwamish River")),
    ("us", "WA0029181", "043"): ("duwamish-river-wa", "Duwamish River", 10, OBL,
                                 kc("043", "East Marginal Way PS Emergency Overflow", "Duwamish River")),
    ("us", "WA0029181", "045"): ("lake-washington-wa", "Lake Washington", 0, OBL,
                                 kc("045", "Henderson Street PS Emergency Overflow", "Lake Washington")
                                 + "; EPA's text 'Duwamish Waterway' is the permit's label, 10.5 km away"),
    # King County's South plant (plant rows: ingest.outfall_waters reads EPA's text and reach for these, not the
    # override, so the override records the evidence)
    ("plants", "WA0029581", "001"): ("puget-sound-wa", "Puget Sound", 0, OBL,
                                     f"{SOUTH}, S1.A, gives outfall 001 to Puget Sound with its north diffuser at "
                                     "47.602778, -122.429 (the south at 47.599722, -122.429028), off Duwamish Head; "
                                     "EPA's text is 'Puget Sound (Central)' and EPA's point is the plant in Renton"),
    ("plants", "WA0029581", "001A"): ("puget-sound-wa", "Puget Sound", 0, OBL,
                                      f"{SOUTH}, S1.A: outfall 001's effluent to Puget Sound (north diffuser 47.602778, "
                                      "-122.429); EPA's point is the plant in Renton"),
    ("plants", "WA0029581", "002A"): ("black-river-renton-wa", "Black River", 168, NHD,
                                      f"{SOUTH} calls outfall 002 the Green River outfall (maintenance and emergency "
                                      "only); EPA's point lies 168 m from the Black River at Renton, where EPA's "
                                      "catchment index puts it (reach GNIS name Black River), and 641 m from the "
                                      "Green River record, which ends where the Black River joins it to form the "
                                      "Duwamish; was tied to the Black River near Olympia, 99 km away"),
    ("plants", "WAR002511", "0P1"): ("black-river-renton-wa", "Black River", 287, NHD,
                                     "EPA's inventory gives the receiving water 'Black River' for the South plant's "
                                     "stormwater outfall and its reach is the Black River's; was tied to the Black "
                                     "River near Olympia, 99 km away"),
}

# the permit's own point for the South plant's marine outfall (north diffuser), replacing EPA's plant point
MOVE = {("plants", "WA0029581", "001"): (47.602778, -122.429), ("plants", "WA0029581", "001A"): (47.602778, -122.429)}

# operators' waters with no record yet: (file, permit, outfall): (water, basis, reason)
LONGFELLOW = ("Seattle's permit names Longfellow Creek; NHDPlus V2.1, the NHD high-resolution flowlines and the "
              "Census hydrography carry no Longfellow Creek (a stream largely in pipes); OpenStreetMap does, and a "
              "record from it waits for a run that reaches OpenStreetMap's Overpass service")
NO_RECORD = {
    ("wa", "WA0031682", "168"): ("Longfellow Creek", sea("168", "Longfellow Creek", "WA-09-1000")),
    ("wa", "WA0031682", "169"): ("Longfellow Creek", sea("169", "Longfellow Creek", "WA-09-1000")),
    ("wa", "WA0031682", "170"): ("Longfellow Creek", sea("170", "Longfellow Creek", "WA-09-1000")),
    ("us", "WA0031682", "168"): ("Longfellow Creek", sea("168", "Longfellow Creek", "WA-09-1000")),
    ("us", "WA0031682", "169"): ("Longfellow Creek", sea("169", "Longfellow Creek", "WA-09-1000")),
    ("us", "WA0031682", "170"): ("Longfellow Creek", sea("170", "Longfellow Creek", "WA-09-1000")
                                 + "; EPA's point for this outfall lies 20 km away in Kitsap County (review "
                                   "2026-11-04), where it was tied to Blackjack Creek"),
}

SOURCES = {OBL: "openboatlaunch", CENSUS: "Census TIGER/Line", NHD: "NHDPlus V2.1"}


def waters() -> dict:
    from build import status as S
    return S.load_waters()


def tie(o: dict, entry: tuple, w: dict) -> None:
    slug, water, d, how, basis = entry
    o["receiving_water_override"] = {"water": water, "basis": basis + " (WA go-live gates 2026-11-06)"}
    named = water.lower() in [str(x).lower() for x in [w.get("name")] + list(w.get("aliases") or [])]
    o.update(water_slug=slug, water_name=w.get("name"), water_kind=w.get("kind"), distance_m=d,
             match="geometry+name" if named and d <= 400 else "geometry" if d <= 400 else "name_only")
    o["water_match"] = (f"operator's list: {basis}; {w.get('name')} ({slug}, {how}), {d} m from the point")
    o["water_matched_by"] = BY
    o.pop("no_water_reason", None)
    o.pop("replaced_match", None)


def untie(o: dict, water: str, basis: str) -> None:
    o["receiving_water_override"] = {"water": water, "basis": basis + " (WA go-live gates 2026-11-06)"}
    o.update(water_slug=None, water_name=None, water_kind=None, distance_m=None, match="none")
    o["no_water_reason"] = f"{basis}; {LONGFELLOW}"
    o["water_match"] = "none: " + o["no_water_reason"]
    o["water_matched_by"] = BY


def move(o: dict, lat: float, lon: float) -> None:
    if o.get("coords_from") != "permit":
        o["epa_lat"], o["epa_lon"] = o.get("lat"), o.get("lon")
    o["lat"], o["lon"] = lat, lon
    o["coords_from"] = "permit"
    o["coords_note"] = (f"{SOUTH}, S1.A, locates outfall 001's north diffuser at 47.602778, -122.429 (the south at "
                        f"47.599722, -122.429028); EPA's point (epa_lat, epa_lon) is the plant in Renton, 15 km away")


def apply(docs: dict, wat: dict) -> list[str]:
    """Write the table into the loaded files; returns the keys not found."""
    idx = {(k, o.get("npdes_permit"), str(o.get("outfall"))): o for k, d in docs.items() for o in d["outfalls"]}
    missing = []
    for key, entry in TABLE.items():
        o = idx.get(key)
        if o is None or entry[0] not in wat:
            missing.append("/".join(key))
            continue
        if key in MOVE:
            move(o, *MOVE[key])
        tie(o, entry, wat[entry[0]])
    for key, (water, basis) in NO_RECORD.items():
        o = idx.get(key)
        if o is None:
            missing.append("/".join(key))
            continue
        untie(o, water, basis)
    return missing


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from ingest.outfall_waters import write_plants
    docs = {k: json.loads((DATA / n).read_text()) for k, n in FILES.items()}
    before = json.dumps(docs, sort_keys=True)
    missing = apply(docs, waters())
    if missing:
        print("not found: " + ", ".join(missing))
        return 1
    changed = json.dumps(docs, sort_keys=True) != before
    if "--check" in argv:
        print("as the table says" if not changed else "rows differ from the table: rerun without --check")
        return 1 if changed else 0
    for k, n in FILES.items():
        path = DATA / n
        old = path.read_text()
        if k == "plants":
            write_plants(path, docs[k])
        else:
            # each file keeps its own format: indent 1, outfalls-us.json with its non-ASCII text as written
            new = json.dumps(docs[k], indent=1, ensure_ascii=json.dumps(json.loads(old), indent=1) == old)
            if new != old:
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(new)
                tmp.replace(path)
        print(f"data/{n}: {'written' if path.read_text() != old else 'unchanged'}")
    print(f"{len(TABLE)} rows tied, {len(NO_RECORD)} given the operator's water and a reason")
    return 0


if __name__ == "__main__":
    sys.exit(main())
