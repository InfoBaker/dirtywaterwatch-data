"""Illinois's go-live gates (2026-11-06): the three lake reversal structures registered as MWRD outfall rows
(scripts/add_il_mwrd_outfalls.py gate_rows, data/outfalls-il.json), the reversal and possible-diversion records tied to
them, the stretch at a structure up a river from the lake (build/reaches.py lake_entry), the structures kept out of the
rain caution, the Chicago Sanitary and Ship Canal record cut to the canal (ingest/waters_from_nhd.py clip_within) and an
override's water read as a name (ingest/outfall_waters.py). Street names in the fixtures are placeholders.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from shapely.geometry import LineString, box, shape

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
from build import rain_likely as RL  # noqa: E402
from build import reaches as R  # noqa: E402
from build import shoreline as SH  # noqa: E402
from build import status as S  # noqa: E402
from ingest import il_mwrd as M  # noqa: E402
from ingest import outfall_waters as OW  # noqa: E402
from ingest import waters_from_nhd as N  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
SHORE = SH.rule(json.loads((ROOT / "data" / "rules.json").read_text()))


def _script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def _il():
    return json.loads((ROOT / "data" / "outfalls-il.json").read_text())


# ---------------------------------------------------------------- the registry rows

def test_the_three_reversal_structures_are_mwrd_outfall_rows_on_lake_michigan():
    doc = _il()
    gates = {r["reversal_column"]: r for r in doc["outfalls"] if r.get("structure") == "lake_reversal_gate"}
    assert set(gates) == set(M.GATE_IDS) and doc["reversal_gates"] == 3 and "diversion_points" not in doc
    assert doc["count"] == len(doc["outfalls"])
    for col, r in gates.items():
        assert (r["npdes_permit"], r["outfall"]) == M.GATE_IDS[col]
        assert (r["lat"], r["lon"]) == M.DIVERSION_POINTS[col]                 # MWRD's own point, never a guess
        assert r["coords_from"] == "il-mwrd-cso-points" and r["source_url"].startswith(M.CSO_POINTS_URL)
        assert r["outfall_kind"] == "cso" and r["receiving_water_echo"] == "Lake Michigan"
        assert r["water_slug"] == "lake-michigan-il" and not r.get("coords_problem")
        assert r["rain_caution"] is False and "rain caution" in r["rain_caution_note"]
        assert "discharge of river water" in r["structure_note"] and "nearest" in r["permit_basis"]
    # O'Brien Lock lies up the Calumet River: the river's path to its mouth, from the USGS NHD high-resolution flowlines
    le = gates["O'Brien Lock"]["lake_entry"]
    lat, lon = M.DIVERSION_POINTS["O'Brien Lock"]
    assert R.seg_km([[lon, lat], le["path"][0]]) < 0.1 and le["path"][-1] == [le["lon"], le["lat"]]
    assert le["lat"] > 41.73 and 10 < le["path_km"] < 12 and "GNIS 405379" in le["source"]
    assert "lake_entry" not in gates["Wilmette"] and "lake_entry" not in gates["CRCW"]
    reg = {(r["npdes_permit"], str(r["outfall"])): r for r in common.load_outfall_registry(provisional=False)}
    assert all(reg[ids]["_file"] == "data/outfalls-il.json" for ids in M.GATE_IDS.values())


def test_gate_rows_take_the_nearest_mwrd_plant_permit_and_build_the_lake_entry():
    A = _script("add_il_mwrd_outfalls")
    pts = [{"OBJECTID": 395, "OWNER": "MWRD", "OUTFALL_CITY": "Chicago", "WATERWAY_REACH": "Cal R",
            "TARP_CONNECTION": "OBrien Lock and Dam", "LOCATION": "OBrien Lock and Dam", "M_OR_U": "Monitored",
            "lat": 41.65, "lon": -87.57}]
    epa = [{"npdes_permit": "IL0028061", "outfall": "152", "outfall_name": "CSO - SAMPLE PUMP STATION", "lat": 41.66,
            "lon": -87.57, "permittee": "SAMPLE WRP"},
           {"npdes_permit": "IL0028053", "outfall": "142", "outfall_name": "", "lat": 41.70, "lon": -87.57,
            "permittee": "OTHER WRP"}]
    river = [{"attributes": {"permanent_identifier": "b"}, "geometry": {"paths": [[[-87.57, 41.66], [-87.56, 41.70]]]}},
             {"attributes": {"permanent_identifier": "a"}, "geometry": {"paths": [[[-87.57, 41.64], [-87.57, 41.65],
                                                                                  [-87.57, 41.66]]]}}]
    rows = A.gate_rows(pts, epa, {"O'Brien Lock": river})
    r = rows[0]
    assert (r["npdes_permit"], r["outfall"]) == M.GATE_IDS["O'Brien Lock"] and r["permittee"] == "SAMPLE WRP"
    assert "IL0028061 outfall 152, 'CSO - SAMPLE PUMP STATION', 1,112 m away" in r["permit_basis"]
    assert r["lake_entry"]["path"] == [[-87.57, 41.65], [-87.57, 41.66], [-87.56, 41.7]]   # from the structure on
    assert (r["lake_entry"]["lat"], r["lake_entry"]["lon"]) == (41.7, -87.56) and "a, b" in r["lake_entry"]["source"]
    # the table's permit must be the nearest plant row's: a structure nearer another plant's rows stops the build
    with pytest.raises(ValueError):
        A.gate_rows(pts, [dict(epa[0], lat=41.75), dict(epa[1], lat=41.651)], {"O'Brien Lock": river})


def test_a_rebuild_of_the_gate_rows_keeps_every_other_row_and_its_ties():
    A = _script("add_il_mwrd_outfalls")
    doc = _il()
    feats = [{"attributes": {"OBJECTID": r["source_record_id"], "OWNER": r["mwrd_owner"], "OUTFALL_CITY": r["city"],
                             "WATERWAY_REACH": r["mwrd_reach"], "TARP_CONNECTION": r["tarp_connection"],
                             "LOCATION": r["tarp_connection"], "M_OR_U": "Monitored"},
              "geometry": {"x": r["lon"], "y": r["lat"]}} for r in doc["outfalls"] if r.get("structure")]
    path = next(r for r in doc["outfalls"] if r.get("lake_entry"))["lake_entry"]["path"]
    hr = {"O'Brien Lock": [{"attributes": {"permanent_identifier": "x"}, "geometry": {"paths": [path]}}]}
    us = json.loads((ROOT / "data" / "outfalls-us.json").read_text())["outfalls"]
    out = A.replace_gates(doc, feats, us, hr)
    assert [r for r in out["outfalls"] if not r.get("structure")] == [r for r in doc["outfalls"] if not r.get("structure")]
    gates = [r for r in out["outfalls"] if r.get("structure")]
    assert len(gates) == 3 and all(r["water_slug"] == "lake-michigan-il" for r in gates)   # the ties are kept


# ---------------------------------------------------------------- the records carry their structure's row

def test_reversal_records_and_possible_diversions_carry_their_structures_registry_ids():
    from ingest import il_mwrd_lake_reversals as REV
    recs, _ = REV.build((FIX / "il_mwrd_lake_reversals.txt").read_text(), None)
    for r in recs:
        assert (r["npdes_permit"], r["outfall_id"]) == M.GATE_IDS[r["raw"]["structure_column"]]
    from ingest import il_mwrd_possible_cso as P
    feats = json.loads((FIX / "il_mwrd_possible_cso.json").read_text())["features"]
    a = next(f["attributes"] for f in feats if f["attributes"]["LOCATION"] == "Wilmette Gate")
    p = P.place(a, [])
    assert (p["permit"], p["outfall"]) == M.GATE_IDS["Wilmette"] and p["water"] == "Lake Michigan"


def test_a_reversal_record_finds_the_stretch_built_at_its_structure():
    from ingest import il_mwrd_lake_reversals as REV
    recs, _ = REV.build((FIX / "il_mwrd_lake_reversals.txt").read_text(), None)
    obrien = next(r for r in recs if r["raw"]["structure_column"] == "O'Brien Lock")
    permit, outfall = M.GATE_IDS["O'Brien Lock"]
    reach = {"key": R.reach_key(permit, outfall), "permit": permit, "outfall": outfall, "model": SH.MODEL,
             "segments": [{"coords": [[0, 0], [1, 1]]}], "cut_reason": SH.MODEL}
    found = S.event_reaches(obrien, {}, S.index_reaches({reach["key"]: reach}))
    assert found == [(reach, None)]


# ---------------------------------------------------------------- the stretch from a structure up a river

LAKE = {"type": "Polygon", "coordinates": [[[-87.60, 41.70]] + [[round(-87.60 + i / 100, 4), 41.70] for i in range(1, 21)]
                                           + [[-87.40, 41.90], [-87.60, 41.90], [-87.60, 41.70]]]}
LAND = {"IL": box(-88.0, 41.4, -87.40, 41.70)}
WATERS = {"lake-michigan-il": {"slug": "lake-michigan-il", "name": "Lake Michigan", "kind": "lake", "state": "IL",
                               "bbox": list(shape(LAKE).bounds), "geometry": LAKE, "area_km2": 4055.318,
                               "gnis_id": "1623080"}}
GATE = (41.60, -87.52)                       # about 11 km inland, farther than snap_km from the shore
MOUTH = [-87.50, 41.70]
PATH = [[-87.52, 41.60], [-87.51, 41.65], MOUTH]


def _cand(**kw):
    S._GEOM_CACHE.clear()
    return {"key": "IL0028061-OBrienLockandDam", "permit": "IL0028061", "outfall": "OBrien Lock and Dam",
            "water_slug": "lake-michigan-il", "lat": GATE[0], "lon": GATE[1], "name": None, "sources": ["echo"],
            "state": "IL", "outfall_kind": "cso", "model": SH.MODEL, **kw}


def test_a_structure_up_a_river_gets_its_stretch_at_the_mouth_with_the_river_drawn_to_it():
    far = R.shoreline_record(_cand(), WATERS, SHORE, LAND)
    assert far["segments"] == [] and far["cut_reason"] == "no_trace"          # from the structure itself: no shore
    km = R.seg_km(PATH)
    entry = {"lat": MOUTH[1], "lon": MOUTH[0], "water": "Calumet River", "path": PATH, "path_km": km}
    rec = R.shoreline_record(_cand(lake_entry=entry), WATERS, SHORE, LAND)
    assert rec["cut_reason"] == SH.MODEL and rec["error"] is None
    river, *shore = rec["segments"]
    assert river["path"] == "river_to_lake" and river["gnis_name"] == "Calumet River" and river["coords"] == PATH
    assert (river["km_start"], river["km_end"]) == (0.0, round(km, 3))
    assert shore and all(s["km_start"] == round(km, 3) and s["coords"][0] == pytest.approx(MOUTH, abs=1e-3)
                         for s in shore)
    assert all(e["km_from_outfall"] > km for e in rec["stops"])
    assert rec["length_km"] == pytest.approx(sum(s["km_end"] - s["km_start"] for s in rec["segments"]), abs=0.01)
    assert (rec["lat"], rec["lon"]) == GATE and rec["waters"] == ["lake-michigan-il"]   # cached at the structure


def test_candidates_carry_the_lake_entry_and_the_rain_flag_and_a_new_entry_rebuilds_the_stretch(tmp_path, monkeypatch):
    entry = {"lat": MOUTH[1], "lon": MOUTH[0], "water": "Calumet River", "path": PATH, "path_km": R.seg_km(PATH)}
    row = {"npdes_permit": "IL0028061", "outfall": "OBrien Lock and Dam", "state": "IL", "water_slug": "lake-michigan-il",
           "lat": GATE[0], "lon": GATE[1], "outfall_kind": "cso", "rain_caution": False, "lake_entry": entry,
           "_file": "data/outfalls-il.json"}
    c = R.candidate_outfalls(WATERS, [row], {"IL"}, {}, set(), plants=False, shore=SHORE)
    assert len(c) == 1 and c[0]["model"] == SH.MODEL and c[0]["lake_entry"] == entry and c[0]["rain_caution"] is False
    monkeypatch.setattr(R, "REACH_DIR", tmp_path)
    monkeypatch.setattr(R, "load_reaches", lambda: {p.stem: json.loads(p.read_text()) for p in tmp_path.glob("*.json")})
    assert R.run_shorelines(c, WATERS, SHORE, land=LAND, log=lambda *_: None)["built"] == 1
    assert R.run_shorelines(c, WATERS, SHORE, land=LAND, log=lambda *_: None)["due"] == 0
    moved = [{**c[0], "lake_entry": {**entry, "path": PATH[1:], "path_km": R.seg_km(PATH[1:])}}]
    assert R.run_shorelines(moved, WATERS, SHORE, land=LAND, log=lambda *_: None)["due"] == 1


# ---------------------------------------------------------------- the rain caution

def test_a_reversal_structure_never_drives_the_rain_caution(monkeypatch):
    gate = {"npdes_permit": "IL0028088", "outfall": "Wilmette Gate", "outfall_kind": "cso", "outfall_status": "CSO",
            "rain_caution": False, "state": "IL", "lat": 42.07, "lon": -87.68, "water_slug": "lake-michigan-il"}
    cso = dict(gate, outfall="101", rain_caution=None, water_slug="north-shore-channel-il")
    assert RL.cso_open(cso) and not RL.cso_open(gate)
    stretch = {"key": "g", "permit": "IL0028088", "model": SH.MODEL, "rain_caution": False, "segments": [{"coords": []}],
               "water_slug": "lake-michigan-il", "cut_reason": SH.MODEL, "waters": ["lake-michigan-il"]}
    waters = {"lake-michigan-il": WATERS["lake-michigan-il"],
              "north-shore-channel-il": {"name": "North Shore Channel", "kind": "stream"}}
    keys, tags, _, _ = RL.targets("IL0028088", waters, [gate, cso], [], {"g": stretch}, S.reach_waters)
    assert keys == [] and "lake-michigan-il" not in tags and tags == {"north-shore-channel-il": "unmodeled"}
    from ingest import rainfall as RF
    monkeypatch.setattr(RF, "load_outfall_registry", lambda *_a, **_k: [gate, cso])
    monkeypatch.setattr(RF, "radar_states", lambda live=None: {"IL"})
    assert [o["outfall"] for o in RF.cso_outfalls({"IL"})] == ["101"]


# ---------------------------------------------------------------- the canal records

def test_a_hand_record_cut_to_its_box_keeps_the_canal_and_drops_the_branches():
    canal = LineString([(-88.0, 41.6), (-87.7, 41.8404)])
    branch = LineString([(-87.7, 41.8404), (-87.68, 41.95)])          # the id runs on north of the canal's head
    rec = {"_geom": canal.union(branch), "bbox": None, "length_km": 0, "comids": [1, 2], "note": "NHDPlus V2.1"}
    fs = [{"comid": 1, "_geom": canal}, {"comid": 2, "_geom": branch}]
    spec = {"name": "Sample Canal", "state": "IL", "gnis_id": "1", "within": (-88.2, 41.5, -87.66, 41.8404),
            "within_why": "north of it the id is on the branches"}
    out, kept, problem = N.clip_within(rec, fs, spec)
    assert problem == "" and out["comids"] == [1] and [f["comid"] for f in kept] == [1]
    assert out["bbox"][3] <= 41.8404 and out["length_km"] < N.WX.length_km(canal.union(branch))
    assert "north of it the id is on the branches" in out["note"]
    none, _, why = N.clip_within(dict(rec, _geom=branch), fs, {**spec, "within": (-89, 40, -88.9, 40.1)})
    assert none is None and "nothing of GNIS 1" in why


def test_the_ship_canal_record_is_the_canal_and_mwrds_canal_outfalls_are_tied_to_it():
    spec = next(h for h in N.HAND if h["name"] == "Chicago Sanitary and Ship Canal")
    assert spec["supersede"] and spec["gnis_id"] == "421744" and spec["within"][3] == 41.8404
    waters = {w["slug"]: w for w in json.loads((ROOT / "data" / "waters-nhd.json").read_text())["waters"]}
    c = waters["chicago-sanitary-and-ship-canal-il"]
    assert c["hand"] and c["bbox"][3] <= 41.8404 and 40 < c["length_km"] < 55       # not the North Shore Channel
    assert waters["illinois-and-michigan-canal-il"]["hand"] and waters["lake-michigan-il"]["area_km2"] < 5000
    rows = [r for r in _il()["outfalls"] if r.get("mwrd_reach", "").startswith("CSSC")]
    assert len(rows) == 51 and all(r["water_slug"] == "chicago-sanitary-and-ship-canal-il" for r in rows)


def test_mwrds_hand_ties_cite_their_evidence():
    ov = {(r["npdes_permit"], r["outfall"]): r for r in _il()["outfalls"] if r.get("receiving_water_override")}
    assert set(ov) == {("IL0045012", "178"), ("ILM580011", "CDS-39"), ("ILM580028", "001")}
    for r in ov.values():
        assert "IL go-live gates, 2026-11-06" in r["receiving_water_override"]["basis"]
        assert "MWRD's CSO Points layer" in r["receiving_water_override"]["basis"]
    assert ov[("IL0045012", "178")]["water_slug"] == "chicago-sanitary-and-ship-canal-il"
    assert ov[("ILM580011", "CDS-39")]["water_slug"] == "east-arm-little-calumet-river-il"


class _Steps(OW.Matcher):
    """Matcher.match with its steps stubbed: what the name step is asked."""

    def __init__(self):
        self.asked, self.waters = [], {"ditch": {"name": "Sample Union Drainage Ditch"}}

    def clear_row(self):
        pass

    def by_name(self, o, text):
        self.asked.append(text)
        return "ditch", "by name"

    def usable(self, s, o, step):
        return True


def test_an_overrides_water_is_a_name_even_where_the_text_rules_read_a_ditch():
    row = {"receiving_water_echo": "Sample Union Drainage Ditch", "lat": None, "lon": None, "state": "IL"}
    assert OW.why_not_a_name("Sample Union Drainage Ditch")             # the text alone reads as a street ditch
    mt = _Steps()
    hand = dict(row, receiving_water_override={"water": "Sample Union Drainage Ditch", "basis": "two agencies name it"})
    assert mt.match(hand) == {"slug": "ditch", "how": "by name", "step": "name"}
    assert mt.asked == ["Sample Union Drainage Ditch"]
