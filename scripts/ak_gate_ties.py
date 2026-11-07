"""Alaska's go-live gates (2026-11-07): Juneau's four outfalls tied to Gastineau Channel by the permit's text, five plant
outfalls tied by EPA's own limit-set names, the pipeline's 'CSO' feature held back, one borrowed point set aside, and
the reasons of the untied rows made to say why the NHD step could not place them.

Usage: pipeline/.venv/bin/python -I scripts/ak_gate_ties.py [--check]
  --check: change nothing; exit 1 when a row is not as this script leaves it (after a cloud ties run or a rebuild of
           data/outfalls-plants-us.json, rerun this script).

Why: the Alaska water batch of 2026-11-07 (pull request 14) tied 30 of Alaska's 110 open outfalls. NHDPlus V2.1, the
network NLDI and EPA's NHDPlus service read, has no data for Alaska, so 79 of the batch's 90 targets failed there.
  - TABLE: two rows whose receiving water EPA names as a cove of a water that has a record. EPA's own limit-set names
    (limit_set_names in the row, from ICIS-NPDES) name the larger water, and the Census TIGER/Line area water of the
    cove's name (TIGERweb Hydro layer 1) holds EPA's point and adjoins the Census polygon of that larger water:
      AKG572007 001 (Bartlett Cove, Glacier Bay National Park): "Discahrge into Bartlett Cove, Glacier Bay" (EPA's
        spelling); Census "Bartlett Cv" (OID 11059306807) holds the point; 96 percent of it lies inside
        openboatlaunch's Glacier Bay outline, which holds the point (0 m).
      AKG572111 001 (the Steelhead barge's plant): "DISCHARGE TO SHOAL COVE IN CARROLL INLET"; EPA's receiving water
        is "Shelter Cove"; Census "Shelter Cv" (OID 11051343660) holds the point and adjoins Census "Carroll Inlt";
        openboatlaunch's Carroll Inlet outline lies 104 m from the point.
    And three sewage lagoons whose inventory row gives no receiving water but whose limit sets name a river that has
    a record: AKG573010 (Naknek) and AKG573029 (King Salmon) to the Naknek River, 267 and 479 m from its outline;
    AKG573002 outfall 002 (Chuathbaluk) to the Kuskokwim River, 526 m. The tie step does not read limit-set names.
    Each gets receiving_water_override {water, basis} (so a later `python -m ingest.outfall_waters --state AK` finds
    the same record by name) and the tie fields; the distance was measured on 2026-11-07 from the row's point to the
    outline as openboatlaunch's water page publishes it.
  - Juneau (TABLE, JUNEAU): permit AK0023213 names Gastineau Channel as the receiving water of the plant (001) and of
    the outfalls Table I.D.1 lists, the combined sewer outfalls N-11, N11.2 and N-15.1 (002, 003, 004 in EPA's CSO
    inventory, which gives the same water). They go to the channel's hand record (Census TIGER/Line OID 11050889607,
    ingest/waters_from_nhd.py HAND, built by a --hand-only run); 004 leaves Douglas Boat Harbor, which the outline
    rule had given it at 174 m, for the channel the permit names (52 m).
  - NOT_SEWER: AKG320002, the Trans-Alaska Pipeline's general permit, whose one row in EPA's CSO inventory (08AA, a
    pump station's tank utilidor at Prudhoe Bay, 'CSO|DEW') is no combined sewer outfall by EPA's own record: listed
    in data/outfalls-us.json's excluded_not_sewage, so the registry, the rain watch and the counts leave it out.
  - POINT_NOT_USED: AKG570023 (City of Koyuk) has no outfall point in ICIS; its row carried the facility geocode
    (coords_from 'facility'), which lies in Nome (Census place 'Nome city'), 209 km from Koyuk (Census place 'Koyuk
    city', interior point 64.94128, -161.14514). The point is kept as published in echo_lat/echo_lon and not used;
    the row stays untied (no record of Koyuk Inlet or Norton Sound). No point is invented.
  - NHDPLUS_TEXT: the reasons of the untied Alaska rows said "no NHD flowline or waterbody of that name within 2 km
    (no named NHD water nearby); no NHD flowline or waterbody of that name in the state". That was the NHDPlus V2.1
    steps answering for a state they hold no data for; the text now says so. The rows with no receiving-water text
    were each sent to NLDI, which snaps no Alaska point: their reason says that too.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
sys.path.insert(0, str(ROOT / "pipeline"))

BY = "scripts/ak_gate_ties.py (AK go-live gates, 2026-11-07)"
OBL = "openboatlaunch record; distance to its outline as published on its water page, 2026-11-07"
FILES = {"us": "outfalls-us.json", "plants": "outfalls-plants-us.json"}
GAP = "NHDPlus V2.1, which this step reads, has no data for Alaska"

# (file, permit, outfall): (slug, the override's water, metres from the row's point, how measured, EPA's text, basis)
TABLE = {
    ("plants", "AKG572007", "001"): (
        "glacier-bay-ak", "Glacier Bay", 0, OBL, "Bartlett Cove",
        "EPA's limit set for permit AKG572007 (Bartlett Cove plant, Glacier Bay National Park) reads 'Discahrge into "
        "Bartlett Cove, Glacier Bay'; EPA's receiving water is Bartlett Cove, a cove of Glacier Bay: the Census "
        "TIGER/Line area water 'Bartlett Cv' (OID 11059306807) holds the point and adjoins the Census's Glacier Bay"),
    ("plants", "AKG572111", "001"): (
        "carroll-inlet-ak", "Carroll Inlet", 104, OBL, "Shelter Cove",
        "EPA's limit set for permit AKG572111 (the Steelhead barge's plant) reads 'DISCHARGE TO SHOAL COVE IN CARROLL "
        "INLET'; EPA's receiving water is Shelter Cove: the Census TIGER/Line area water 'Shelter Cv' (OID "
        "11051343660) holds the point and adjoins the Census's Carroll Inlet ('Carroll Inlt')"),
    ("plants", "AKG573010", "001"): (
        "naknek-river-ak", "Naknek River", 267, OBL, None,
        "EPA's limit sets for permit AKG573010 (Naknek sewage lagoon) read 'DISCHARGE TO NAKNEK RIVER' and "
        "'Unscheduled Discharge from Naknek Lagoon into Naknek River'; EPA's inventory gives no receiving water"),
    ("plants", "AKG573029", "001"): (
        "naknek-river-ak", "Naknek River", 479, OBL, None,
        "EPA's limit sets for permit AKG573029 (King Salmon sewage lagoon) read 'DISCHARGE TO NAKNEK RIVER' and "
        "'Discharge from lagoon to Naknek River'; EPA's inventory gives no receiving water"),
    ("plants", "AKG573002", "002"): (
        "kuskokwim-river-ak", "Kuskokwim River", 526, OBL, None,
        "EPA's limit sets for outfall 002 of permit AKG573002 (Chuathbaluk sewage lagoon) read 'DISCHARGE TO "
        "KUSKOKWIM RIVER' and 'Seasonal discharge from lagoon to Kuskokwim River'; EPA's inventory gives no receiving "
        "water (outfall 001's limit sets name wetlands, and it stays untied)"),
}

JUNEAU = ("EPA permit AK0023213 (City and Borough of Juneau, Juneau-Douglas plant, effective 2001-12-27, the copy the "
          "City and Borough publishes) authorizes discharge 'to receiving waters named the Gastineau Channel' (cover "
          "page, outfall 001) and 'from the outfalls specified herein to the Gastineau Channel' (Part I); Table I.D.1 "
          "lists the combined sewer outfalls N-11, N11.2 and N-15.1 (Douglas)")
HAND = "Census TIGER/Line hand record, data/waters-nhd.json; distance to its polygon"
for _o, _d in (("001", 0), ("002", 143), ("003", 80), ("004", 52)):
    TABLE[("plants" if _o == "001" else "us", "AK0023213", _o)] = (
        "gastineau-channel-ak", "Gastineau Channel", _d, HAND, "Gastineau Channel",
        JUNEAU + f"; EPA's {'discharge points' if _o == '001' else 'CSO inventory'} give outfall {_o} the receiving "
                 f"water 'Gastineau Channel'")

# permits held back from data/outfalls-us.json's combined sewer rows by EPA's own record (the excluded_not_sewage
# section common.load_outfall_registry reads in every outfall file, as the plants file holds Arizona's and
# California's): the row stays as EPA lists it and no reader of the registry sees it
NOT_SEWER = {
    "AKG320002": {
        "npdes_permit": "AKG320002", "permittee": "APSC - TRANS-ALASKA PIPELINE SYSTEM", "state": "AK",
        "city": "NORTH POLE", "sic_codes": ["1382", "4612", "4922"], "naics_codes": ["213112", "486110", "486210"],
        "external_outfalls": 1, "reason": "not_a_combined_sewer",
        "why": ("EPA's own record shows a crude-oil pipeline, not a combined sewer system: the CSO inventory's one "
                "feature of the permit is a pump station's tank utilidor"),
        "basis": ("ECHO (dfr_rest_services.get_dfr and eff_rest_services.download_effluent_chart for AKG320002, read "
                  "2026-11-07): facility 'APSC - TRANS-ALASKA PIPELINE SYSTEM', SIC 1382 (Oil and Gas Exploration "
                  "Services), 4612 (Crude Petroleum Pipelines), 4922 (Natural Gas Transmission), NAICS 213112, 486110, "
                  "486210; EPA's CSO inventory lists one feature, 08AA 'PS01 TK110/TK110 Utilidors' at Pump Station 1, "
                  "Prudhoe Bay, status 'CSO|DEW', with no limit or report 2023-2026 (the permit's limits are at pump "
                  "stations 3 to 6); not a combined sewer outfall (Alaska final audit 2026-11-07)"),
    },
}


# (file, permit, outfall): (EPA's receiving-water text, why the point is not the outfall's)
POINT_NOT_USED = {
    ("plants", "AKG570023", "None"): (
        "KOYUK INLET OF NORTON SOUND",
        "ICIS gives no outfall point for permit AKG570023 (City of Koyuk); the row's point was the facility geocode, "
        "which lies in Nome (Census place 'Nome city'), 209 km from Koyuk (Census place 'Koyuk city', interior point "
        "64.94128, -161.14514), so it is not this outfall's place and is not used"),
}

# the NHDPlus V2.1 steps' answers in a state they hold no data for, as the batch of 2026-11-07 wrote them
NHDPLUS_TEXT = [
    ("NHD builder: no NHD flowline or waterbody of that name within 2 km (no named NHD water nearby); no NHD flowline or "
     "waterbody of that name in the state", f"NHD builder: {GAP}"),
    ("NHD builder: no NHD flowline or waterbody of that name within 2 km (no named NHD water nearby)",
     f"NHD builder: {GAP}"),
]
NO_TEXT = "no receiving-water text in EPA's inventory; no water record within 150 m of the point"
NO_TEXT_NHD = f"; NHD builder: {GAP} (NLDI snaps no point there)"


def waters() -> dict:
    from build import status as S
    return S.load_waters()


def tie(o: dict, entry: tuple, w: dict) -> None:
    slug, water, d, how, _text, basis = entry
    o["receiving_water_override"] = {"water": water, "basis": basis + " (AK go-live gates 2026-11-07)"}
    o.update(water_slug=slug, water_name=w.get("name"), water_kind=w.get("kind"), distance_m=d,
             match="geometry+name" if d <= 400 else "name_only")
    o["water_match"] = f"receiving water: {basis}; {w.get('name')} ({slug}, {how}), {d} m from the point"
    o["water_matched_by"] = BY
    o.pop("no_water_reason", None)
    o.pop("replaced_match", None)


def set_point_aside(o: dict, entry: tuple) -> None:
    _text, why = entry
    if o.get("lat") is not None or o.get("lon") is not None:
        o["echo_lat"], o["echo_lon"] = o.get("lat"), o.get("lon")
    o["lat"] = o["lon"] = None
    o["coords_problem"] = why


def reword(o: dict) -> None:
    """The NHDPlus V2.1 steps' reason, in an untied Alaska row, said as what it is."""
    if o.get("state") != "AK" or o.get("water_slug"):
        return
    for key in ("water_match", "no_water_reason"):
        t = o.get(key)
        if not isinstance(t, str):
            continue
        for old, new in NHDPLUS_TEXT:
            if old in t:
                t = t.replace(old, new)
                break
        if t.endswith(NO_TEXT) and o.get("lat") is not None:
            t += NO_TEXT_NHD
        o[key] = t


def apply(docs: dict, wat: dict) -> list[str]:
    """Write the tables into the loaded files; returns the keys not found."""
    idx = {(k, o.get("npdes_permit"), str(o.get("outfall"))): o for k, d in docs.items() for o in d["outfalls"]}
    missing = []
    for key, entry in TABLE.items():
        o = idx.get(key)
        if o is None or entry[0] not in wat or o.get("receiving_water_echo") != entry[4] \
                or o.get("coords_from") != "permitted_feature":
            missing.append("/".join(key[1:]))
            continue
        tie(o, entry, wat[entry[0]])
    for key, entry in POINT_NOT_USED.items():
        o = idx.get(key)
        if o is None or o.get("receiving_water_echo") != entry[0] or o.get("coords_from") != "facility":
            missing.append("/".join(key[1:]))
            continue
        set_point_aside(o, entry)
    held = docs["us"].setdefault("excluded_not_sewage", [])
    for p, entry in NOT_SEWER.items():
        if not any(o.get("npdes_permit") == p for o in docs["us"]["outfalls"]):
            missing.append(f"{p} (excluded_not_sewage)")
            continue
        held[:] = [x for x in held if x.get("npdes_permit") != p] + [entry]
    held.sort(key=lambda x: x["npdes_permit"])
    for d in docs.values():
        for o in d["outfalls"]:
            reword(o)
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
            # outfalls-us.json keeps its own format: indent 1, its non-ASCII text as written
            new = json.dumps(docs[k], indent=1, ensure_ascii=json.dumps(json.loads(old), indent=1) == old)
            if new != old:
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(new)
                tmp.replace(path)
        print(f"data/{n}: {'written' if path.read_text() != old else 'unchanged'}")
    print(f"{len(TABLE)} rows tied, {len(POINT_NOT_USED)} row's point set aside, {len(NOT_SEWER)} permit held back")
    return 0


if __name__ == "__main__":
    sys.exit(main())
