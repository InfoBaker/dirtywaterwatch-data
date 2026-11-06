"""California's go-live gates (2026-11-06): the receiving waters of the big coastal plants' outfalls from their permits.

Usage: pipeline/.venv/bin/python -I scripts/ca_gate_ties.py [--check]
  --check: change nothing; exit 1 when a row is not as the table says (after a rebuild of the registry files or a
           ties run: a row the ties pass tied keeps its tie, which must then be the table's record).

Why: EPA's inventory gives San Francisco's 29 Bayside combined sewer discharge outfalls (NPDES CA0037664) the receiving
water 'Pacific Ocean' or a sewer drainage basin's name, but they lie on San Francisco Bay's waterfront, east of the
Golden Gate: once openboatlaunch's Pacific Ocean record is on file, the ocean rule would tie them to the ocean. The
permit names each one's water:
  - Order R2-2013-0029 (NPDES CA0037664: Southeast plant, North Point Wet Weather Facility, Bayside Wet Weather
    Facilities and collection system; adopted 2013-08-14, in force until reissued), Table 2, Discharge Locations:
    each discharge point's receiving water and point;
  - the San Francisco Bay Regional Water Board's 2021 stipulation for a cleanup and abatement order (agenda of
    November 2021, item 5): "the Bayside system has 29 combined sewer discharge outfalls to San Francisco Bay", and
    the Bayside system "discharges to San Francisco Bay pursuant to NPDES Permit CA0037664 (Order R2-2013-0029)".
The permit's names for the shore are places on the bay (Marina Beach, Yacht Harbor #2, Piers 3 to 39, Central Basin,
India Basin, South Basin, Candlestick Cove, and Yosemite Creek, the tidal slough at the bay's South Basin): their water
record is San Francisco Bay. Mission Creek and Islais Creek are the tidal channels openboatlaunch keeps as Mission Creek
and Islais Creek Channel. EPA's 'Central San Francisco Bay' and 'Lower San Francisco Bay' (East Bay MUD's outfalls,
CA0037702, and the Southeast plant's) are the San Francisco Bay Basin Plan's segments of the bay.
The deep ocean outfalls whose point EPA gives without the longitude's minus sign (a point across the Pacific, which the
plants build set aside with coords_problem and kept as echo_lat/echo_lon) take their permits' points (never a model's):
Orange County Sanitation District's 120-inch and 78-inch outfalls (Order R8-2021-0010, NPDES CA0110604, Table 2) and
Hyperion's 5-mile outfall (Order R4-2023-0033, NPDES CA0109991, Table 2); their water stays EPA's 'Pacific Ocean'. The
permit's point replaces the flagged one, so the row's coords_problem is cleared (reaches and placement skip a row that
carries one: the 78-inch outfall, 1.5 miles out, gets its shoreline stretch); EPA's figures stay in epa_lat/epa_lon and
echo_lat/echo_lon (review of 2026-11-06). The Bayside points follow one rule, the cited point nearest the shore at
the named street, and each row's coords_note says which point it keeps and why (NOTE for the rows not moved).
Laguna Street (011), whose point in EPA's inventory lies about 4.6 km east, off the wrong shore, takes Table 2's
(review of 2026-11-06, P3-4), about 290 m off the shore; the 2008 tentative order's point, about 70 m inland at
Marina Boulevard, is the nearer one by that rule, and the note says so (the adopted order's point is kept). Brannan Street (019) keeps EPA's point (37.785278,
-122.39, at the shore by Pier 32): it is the point of the Regional Water Board's revised tentative order of January
2008 for the same permit (37 47 7 N, 122 23 24 W), while Table 2 of the 2013 order prints 122.373333 W (122 22 24),
about 1.1 km out in the bay, which looks like a slip of one minute. Sunnydale Avenue (043, Candlestick Cove) keeps
EPA's point: Table 2 prints Quint Street's point for it (37.747222, -122.386944), the 2008 tentative order the same
(37 44 50 N, 122 23 13 W), and no public record found gives its own (docs/checklists/2026-11-06-ca-bays.md in the
site repository).

Each row gets receiving_water_override {water, basis}: the name the record carries, so `python -m ingest.outfall_waters
--state CA` finds that record by name once openboatlaunch's California extract is on file (the state batch's `extract`
step; the records are not in this repository yet). Until then a row with no record says so in no_water_reason. No tie
is written here to a record that is not on file, so the share of outfalls tied counts only real records.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "pipeline"))

BY = "scripts/ca_gate_ties.py (CA go-live gates, 2026-11-06)"
TAG = " (CA go-live gates 2026-11-06)"
BAYSIDE = "Order R2-2013-0029 (NPDES CA0037664), Table 2"
STIP = ("the Regional Water Board's 2021 stipulation (cleanup and abatement order, November 2021) gives the Bayside "
        "system's 29 combined sewer discharge outfalls to San Francisco Bay")
OCSD = "Order R8-2021-0010 (NPDES CA0110604, Orange County Sanitation District), Table 2"
ORDER_2008 = ("San Francisco Bay Regional Water Board's revised tentative order of January 2008 for the same permit "
              "(R2-2008-00XX, agenda of January 2008, item 13)")
POINT_RULE = "the cited point nearest the shore at the named street"     # the rule the Bayside point calls follow
HYPERION = "Order R4-2023-0033 (NPDES CA0109991, Hyperion Water Reclamation Plant), Table 2"
SFB, SFB_SLUG = "San Francisco Bay", "san-francisco-bay-ca"
MISSION, MISSION_SLUG = "Mission Creek", "mission-creek-ca"
ISLAIS, ISLAIS_SLUG = "Islais Creek Channel", "islais-creek-channel-ca"
PACIFIC, PACIFIC_SLUG = "Pacific Ocean", "pacific-ocean-ca"

FILES = {"us": "outfalls-us.json", "plants": "outfalls-plants-us.json"}


def bay(dp, name, said, what="a place on San Francisco Bay's waterfront"):
    return (f"{BAYSIDE} gives discharge point {dp} ({name}) the receiving water '{said}', {what}; {STIP}; EPA's "
            f"inventory text is not the bay")


def creek(dp, name, said, rec):
    return (f"{BAYSIDE} gives discharge point {dp} ({name}) the receiving water '{said}', the tidal channel that "
            f"openboatlaunch's record names {rec}, at the bay's shore; {STIP}")


# (file, permit, outfall): (expected record slug, the override's water, basis)
TABLE = {
    ("us", "CA0037664", "009"): (SFB_SLUG, SFB, bay("009", "Baker Street Outfall", "Marina Beach")),
    ("us", "CA0037664", "010"): (SFB_SLUG, SFB, bay("010", "Pierce Street Outfall", "Marina Beach")),
    ("us", "CA0037664", "011"): (SFB_SLUG, SFB, bay("011", "Laguna Street Outfall", "Yacht Harbor #2")),
    ("us", "CA0037664", "013"): (SFB_SLUG, SFB, bay("013", "Beach Street Outfall", "Pier 39")),
    ("us", "CA0037664", "015"): (SFB_SLUG, SFB, bay("015", "Sansome Street Outfall", "Pier 31")),
    ("us", "CA0037664", "017"): (SFB_SLUG, SFB, bay("017", "Jackson Street Outfall", "Pier 3")),
    ("us", "CA0037664", "018"): (SFB_SLUG, SFB, bay("018", "Howard Street Outfall", "Pier 14")),
    ("us", "CA0037664", "019"): (SFB_SLUG, SFB, bay("019", "Brannan Street Outfall", "Pier 32")),
    ("us", "CA0037664", "022"): (MISSION_SLUG, MISSION, creek("022", "Third Street Outfall", "Mission Creek", MISSION)),
    ("us", "CA0037664", "023"): (MISSION_SLUG, MISSION, creek("023", "Fourth Street North Outfall", "Mission Creek", MISSION)),
    ("us", "CA0037664", "024"): (MISSION_SLUG, MISSION, creek("024", "Fifth Street North Outfall", "Mission Creek", MISSION)),
    ("us", "CA0037664", "025"): (MISSION_SLUG, MISSION, creek("025", "Sixth Street North Outfall", "Mission Creek", MISSION)),
    ("us", "CA0037664", "026"): (MISSION_SLUG, MISSION, creek("026", "Division Street Outfall", "Mission Creek", MISSION)),
    ("us", "CA0037664", "027"): (MISSION_SLUG, MISSION, creek("027", "Sixth Street South Outfall", "Mission Creek", MISSION)),
    ("us", "CA0037664", "028"): (MISSION_SLUG, MISSION, creek("028", "Fourth Street South Outfall", "Mission Creek", MISSION)),
    ("us", "CA0037664", "029"): (SFB_SLUG, SFB, bay("029", "Mariposa Street Outfall", "Central Basin", "a basin of San Francisco Bay")),
    ("us", "CA0037664", "030"): (SFB_SLUG, SFB, bay("030", "20th Street Outfall", "Central Basin", "a basin of San Francisco Bay")),
    ("us", "CA0037664", "030A"): (SFB_SLUG, SFB, bay("030A", "22nd Street Outfall", "Central Basin", "a basin of San Francisco Bay")),
    ("us", "CA0037664", "031"): (ISLAIS_SLUG, ISLAIS, creek("031", "Third Street North Outfall", "Islais Creek", ISLAIS)),
    ("us", "CA0037664", "031A"): (ISLAIS_SLUG, ISLAIS, creek("031A", "Islais Creek North Outfall", "Islais Creek", ISLAIS)),
    ("us", "CA0037664", "032"): (ISLAIS_SLUG, ISLAIS, creek("032", "Marin Street Outfall", "Islais Creek", ISLAIS)),
    ("us", "CA0037664", "033"): (ISLAIS_SLUG, ISLAIS, creek("033", "Selby Street Outfall", "Islais Creek", ISLAIS)),
    ("us", "CA0037664", "035"): (ISLAIS_SLUG, ISLAIS, creek("035", "Third Street South Outfall", "Islais Creek", ISLAIS)),
    ("us", "CA0037664", "037"): (SFB_SLUG, SFB, bay("037", "Evans Avenue Outfall", "India Basin", "a basin of San Francisco Bay")),
    ("us", "CA0037664", "038"): (SFB_SLUG, SFB, bay("038", "Hudson Avenue Outfall", "India Basin", "a basin of San Francisco Bay")),
    ("us", "CA0037664", "040"): (SFB_SLUG, SFB, bay("040", "Griffith Street South Outfall", "Yosemite Creek",
                                                   "the tidal slough at San Francisco Bay's South Basin")),
    ("us", "CA0037664", "041"): (SFB_SLUG, SFB, bay("041", "Yosemite Avenue Outfall", "Yosemite Creek",
                                                   "the tidal slough at San Francisco Bay's South Basin")),
    ("us", "CA0037664", "042"): (SFB_SLUG, SFB, bay("042", "Fitch Street Outfall", "South Basin", "a basin of San Francisco Bay")),
    ("us", "CA0037664", "043"): (SFB_SLUG, SFB, bay("043", "Sunnydale Avenue Outfall", "Candlestick Cove", "a cove of San Francisco Bay")),
    # the Southeast plant's and North Point's own outfalls (plant rows)
    ("plants", "CA0037664", "001"): (SFB_SLUG, SFB, f"{BAYSIDE} gives discharge point 001 (Pier 80 Outfall) the "
                                     "receiving water 'Lower San Francisco Bay', the Basin Plan's segment of San "
                                     "Francisco Bay; the Regional Water Board's 2021 stipulation says the Bayside system discharges to San "
                                     "Francisco Bay under this permit"),
    ("plants", "CA0037664", "002"): (ISLAIS_SLUG, ISLAIS, creek("002", "Quint Street Outfall", "Islais Creek", ISLAIS)),
    ("plants", "CA0037664", "003"): (SFB_SLUG, SFB, f"{BAYSIDE} gives discharge points 003 and 004 (Pier 33 Outfall) the "
                                     "receiving water 'Central San Francisco Bay', the Basin Plan's segment of San "
                                     "Francisco Bay"),
    # East Bay Municipal Utility District's main plant
    ("plants", "CA0037702", "EFF1"): (SFB_SLUG, SFB, "EPA's inventory gives the receiving water 'Central San "
                                      "Francisco Bay', the San Francisco Bay Basin Plan's name for the bay's central segment"),
    ("plants", "CA0037702", "EFFB"): (SFB_SLUG, SFB, "EPA's inventory gives the receiving water 'Central San "
                                      "Francisco Bay', the San Francisco Bay Basin Plan's name for the bay's central segment"),
    ("plants", "CA0037702", "EFFD"): (SFB_SLUG, SFB, "EPA's inventory gives the receiving water 'Central San "
                                      "Francisco Bay', the San Francisco Bay Basin Plan's name for the bay's central segment"),
    # the deep ocean outfalls whose point EPA gives with the longitude's sign dropped: the permit's point (MOVE) and
    # the permit's water
    ("plants", "CA0110604", "001"): (PACIFIC_SLUG, PACIFIC, f"{OCSD} gives discharge point 001 (the 120-inch outfall) "
                                     "the receiving water 'Pacific Ocean (4.5 miles offshore)' at 33 34 36 N, 118 00 36 W"),
    ("plants", "CA0110604", "002"): (PACIFIC_SLUG, PACIFIC, f"{OCSD} gives discharge point 002 (the 78-inch outfall) "
                                     "the receiving water 'Pacific Ocean (1.5 miles offshore)' at 33 36 56 N, 117 58 13 W"),
    ("plants", "CA0109991", "002"): (PACIFIC_SLUG, PACIFIC, f"{HYPERION} gives discharge point 002 (the 5-mile outfall, "
                                     "Y-shaped diffuser) the receiving water 'Pacific Ocean' at 33.91197 N, 118.52145 W"),
}

# the permits' own points for the outfalls whose point EPA's inventory gives with the longitude's sign dropped (degrees,
# minutes and seconds converted)
MOVE = {
    ("plants", "CA0110604", "001"): (33.576667, -118.01, f"{OCSD}: 33 34 36 N, 118 00 36 W (the 120-inch outfall, "
                                     "4.5 miles offshore); EPA's inventory gives the same figures without the longitude's minus sign"),
    ("plants", "CA0110604", "002"): (33.615556, -117.970278, f"{OCSD}: 33 36 56 N, 117 58 13 W (the 78-inch outfall, "
                                     "1.5 miles offshore); EPA's inventory gives the same figures without the longitude's minus sign"),
    ("plants", "CA0109991", "002"): (33.91197, -118.52145, f"{HYPERION}: 33.91197 N, 118.52145 W (the 5-mile "
                                     "outfall's Y-shaped diffuser); EPA's inventory gives the same figures without the longitude's minus "
                                     "sign"),
    # a Bayside combined sewer discharge outfall whose point in EPA's inventory is not the permit's (review of
    # 2026-11-06, P3-4): Table 2's point, as printed
    ("us", "CA0037664", "011"): (37.811667, -122.43189, f"{BAYSIDE}: 37.811667 N, 122.43189 W (discharge point 011, "
                                 "Laguna Street Outfall, Yacht Harbor #2), the adopted order's point, about 290 m off "
                                 "the shore outside the Marina harbor (Census TIGER/Line water). EPA's inventory gives "
                                 "37.80611, -122.38, about 4.6 km east, off the wrong shore. The rule for the Bayside points "
                                 f"is {POINT_RULE}; the {ORDER_2008} gave 37 48 22 N, 122 25 53 W, about 0.6 km south and "
                                 "about 70 m inland of the shoreline at Marina Boulevard, which by that rule is the "
                                 "nearer point; Table 2's is kept as the adopted order's"),
}

# the Bayside outfalls whose point is kept, with why (review of 2026-11-06, P3-4 of the CA gates and P3-4 of the CA
# bays review): the note is set on the row, the point and coords_from are left as they are
NOTE = {
    ("us", "CA0037664", "019"): (f"EPA's point (37.785278, -122.39, Brannan Street Outfall, Pier 32) is the one the "
                                 f"{ORDER_2008} gives (37 47 7 N, 122 23 24 W), about 210 m inland of the shoreline at Pier "
                                 f"30-32 as the Census draws it; {BAYSIDE} prints 122.373333 W (122 22 24), about 970 m "
                                 "out in the open bay, read as a slip of one minute. Rule applied: "
                                 f"{POINT_RULE}, so EPA's point is kept"),
    ("us", "CA0037664", "043"): (f"{BAYSIDE} gives discharge point 043 (Sunnydale Avenue Outfall, Candlestick Cove) "
                                 "Quint Street's point (37.747222, -122.386944, at Islais Creek, about 4 km north of "
                                 f"Candlestick Cove), and the {ORDER_2008} the same (37 44 50 N, 122 23 13 W); EPA's "
                                 f"inventory copies it. Rule applied: {POINT_RULE}; no public record found gives this "
                                 "outfall's own point, so EPA's is kept"),
}


def waters() -> dict:
    from build import status as S
    return S.load_waters()


def override(o: dict, entry: tuple, wat: dict) -> str | None:
    """The table's override on row o; a row with no record on file says why. Returns a problem, or None."""
    slug, water, basis = entry
    o["receiving_water_override"] = {"water": water, "basis": basis + TAG}
    if o.get("water_slug"):
        # tied (by the ties pass after openboatlaunch's extract): it must be the table's record
        return None if o["water_slug"] == slug else f"tied to {o['water_slug']}, not {slug}"
    reason = (f"the permit's water '{water}' (openboatlaunch's {slug}) is not among the water records on file: the "
              f"state batch's extract brings openboatlaunch's California records and its ties step ties this row by "
              f"that name")
    if slug in wat:
        reason = (f"the permit's water '{water}' ({slug}) is on file; the next ties run "
                  f"(python -m ingest.outfall_waters --state CA) ties this row by that name")
    o.update(water_slug=None, water_name=None, water_kind=None, distance_m=None, match="none",
             no_water_reason=reason, water_match="none: " + reason, water_matched_by=BY)
    return None


def move(o: dict, lat: float, lon: float, note: str) -> None:
    """The permit's point on row o. EPA's own point is kept in epa_lat/epa_lon (the flagged one the plants build set
    aside in echo_lat/echo_lon when the row has none), and the flag on it is cleared: the row's point is now the
    permit's (reaches and placement skip a row with coords_problem)."""
    if o.get("coords_from") != "permit":
        o["epa_lat"], o["epa_lon"] = o.get("lat"), o.get("lon")
    if o.get("epa_lat") is None and o.get("echo_lat") is not None:
        o["epa_lat"], o["epa_lon"] = o["echo_lat"], o["echo_lon"]
    o["lat"], o["lon"] = lat, lon
    o["coords_from"] = "permit"
    o["coords_note"] = note
    o.pop("coords_problem", None)


def apply(docs: dict, wat: dict) -> list[str]:
    """Write the table into the loaded files; returns the problems (a key not found, a tie to another record)."""
    idx = {(k, o.get("npdes_permit"), str(o.get("outfall"))): o for k, d in docs.items() for o in d["outfalls"]}
    problems = []
    for key, entry in TABLE.items():
        o = idx.get(key)
        if o is None:
            problems.append("not found: " + "/".join(key))
            continue
        if key in MOVE:
            move(o, *MOVE[key])
        if key in NOTE:
            o["coords_note"] = NOTE[key]
        p = override(o, entry, wat)
        if p:
            problems.append("/".join(key) + ": " + p)
    return problems


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    from ingest.outfall_waters import write_plants
    docs = {k: json.loads((DATA / n).read_text()) for k, n in FILES.items()}
    before = json.dumps(docs, sort_keys=True)
    problems = apply(docs, waters())
    if problems:
        print("\n".join(problems))
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
            new = json.dumps(docs[k], indent=1, ensure_ascii=json.dumps(json.loads(old), indent=1) == old)
            if new != old:
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(new)
                tmp.replace(path)
        print(f"data/{n}: {'written' if path.read_text() != old else 'unchanged'}")
    print(f"{len(TABLE)} rows given the permit's water ({len(MOVE)} with the permit's point)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
