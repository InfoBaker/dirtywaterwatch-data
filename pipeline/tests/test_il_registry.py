"""Illinois registry: MWRD's outfall points against EPA's inventory (scripts/add_il_mwrd_outfalls.py), the operator rows
(scripts/add_il_operators.py) and the register rows (scripts/add_il_register_rows.py). Street names are placeholders."""
import importlib.util
import json
import sys
from pathlib import Path

import common
from ingest import il_mwrd as M

ROOT = Path(__file__).resolve().parents[2]


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def _feat(oid, owner, loc, lat, lon, tarp="DS-X1", reach="NSC Lower (NSWRP)"):
    return {"attributes": {"OBJECTID": oid, "OWNER": owner, "OUTFALL_CITY": owner, "WATERWAY_REACH": reach,
                           "TARP_CONNECTION": tarp, "LOCATION": loc, "M_OR_U": "Monitored"},
            "geometry": {"x": lon, "y": lat}}


def _epa(permit, outfall, name, lat, lon):
    return {"npdes_permit": permit, "outfall": outfall, "outfall_name": name, "lat": lat, "lon": lon,
            "permittee": "SAMPLE CSO, CITY OF", "receiving_water_echo": "NORTH SHORE CHANNEL"}


def test_reach_labels_and_reversal_structures():
    assert M.reach_water("NSC Lower (NSWRP)") == "North Shore Channel"
    assert M.reach_water("Little Cal R (South)") == "Little Calumet River"
    assert M.reach_water("Cal Sag Ch") == "Calumet-Sag Channel"
    assert M.reach_water("I & M Canal") == "Illinois and Michigan Canal"
    assert M.reach_water("Nowhere Cr") is None
    assert M.diversion("OBrien Lock and Dam")[0] == "O'Brien Lock"
    assert M.diversion("Chicago River Controlling Works")[0] == "CRCW"
    assert M.diversion("Wilmette Gate")[0] == "Wilmette" and M.diversion("Sample Ave (E)") is None
    assert M.owner_permits("Chicago / Calumet Park") == ["IL0045012"] and M.owner_permits("Mt. Prospect") == ["IL0052400"]
    assert M.owner_permits("Sample Campground") == []


def test_points_pair_with_epa_rows_by_distance_then_street_and_side():
    S = _script("add_il_mwrd_outfalls")
    feats = [_feat(1, "Chicago", "Sample Ave (E)", 42.0000, -87.7000),
             _feat(2, "Chicago", "Example St (W)", 42.0300, -87.7300, tarp="DS-X2"),
             _feat(3, "Chicago", "Other Ave (W)", 42.0500, -87.7500, tarp="DS-X3"),
             _feat(4, "Chicago", "Third Ave (N)", 42.0600, -87.7600, tarp="DS-X4"),
             _feat(5, "Chicago", "Third Ave (S)", 42.0610, -87.7610, tarp="DS-X4"),
             _feat(6, "Chicago River Controlling Works", "Chicago River Controlling Works", 41.88, -87.60,
                   tarp="Chicago River Controlling Works", reach="Chicago R"),
             _feat(7, "Sample Campground", "Sample Rd (E)", 42.03, -87.87)]
    epa = [_epa("IL0045012", "001", "CSO - SAMPLE AVENUE EAST", 42.0001, -87.7001),      # 15 m away
           _epa("IL0045012", "002", "CSO - EXAMPLE STREET WEST", 41.90, -87.65),          # the facility's point
           _epa("IL0045012", "003", "CSO - OTHER AVENUE EAST", 41.90, -87.65)]            # the other bank
    doc = S.build(feats, epa)
    by = {r["source_record_id"]: r for r in doc["outfalls"]}
    assert by[1]["outfall"] == "001" and by[1]["epa_row"]["paired_by"].startswith("distance")
    assert by[2]["outfall"] == "002" and "street and side" in by[2]["epa_row"]["paired_by"]
    assert by[3]["epa_row"] is None and by[3]["outfall"] == "DS-X3"                      # sides differ: not paired
    assert {by[4]["outfall"], by[5]["outfall"]} == {"DS-X4#4", "DS-X4#5"}                 # one drop shaft, two outfalls
    assert by[3]["receiving_water_echo"] == "North Shore Channel" and by[1]["receiving_water_echo"] == "NORTH SHORE CHANNEL"
    assert 6 not in by and doc["diversion_points"][0]["water"] == "Lake Michigan"
    assert 7 not in by and doc["without_permit"][0]["owner"] == "Sample Campground"


def test_the_illinois_outfall_file_outranks_epas_rows_for_the_same_outfall():
    doc = json.loads((ROOT / "data" / "outfalls-il.json").read_text())
    keys = [common.outfall_key(r["npdes_permit"], r["outfall"]) for r in doc["outfalls"]]
    assert len(keys) == len(set(keys)) and doc["count"] == len(keys) > 400
    reg = {common.outfall_key(r["npdes_permit"], r["outfall"]): r for r in common.load_outfall_registry(provisional=False)
           if r.get("state") == "IL"}
    paired = [r for r in doc["outfalls"] if r["epa_row"]]
    assert paired and all(reg[common.outfall_key(r["npdes_permit"], r["outfall"])]["_file"] == "data/outfalls-il.json"
                          for r in paired)
    assert all(r["coords_from"] == "il-mwrd-cso-points" and r["source_url"].startswith(M.CSO_POINTS_URL)
               for r in doc["outfalls"])
