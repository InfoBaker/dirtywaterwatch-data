"""Michigan's registry rows (data/dischargers.json, data/notice-channels/mi.json) and the scripts that make them
(scripts/add_mi_operators.py, scripts/add_mi_register_rows.py): no individual named, one row per permit, towns that
are towns, and the 324.3112a duty rows only for sewer systems.
Run from pipeline/: python -m pytest tests/test_mi_registry.py -q
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import Counter

import pytest

from common import DATA_DIR, ROOT
from ingest import mi_egle_mienviro as M


def load(name):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rows():
    return [r for r in json.loads((DATA_DIR / "dischargers.json").read_text()) if r.get("state") == "MI"]


@pytest.fixture(scope="module")
def register():
    return json.loads((DATA_DIR / "notice-channels" / "mi.json").read_text())["channels"]


def test_no_michigan_operator_row_names_an_individual(rows):
    for r in rows:
        for f in ("name", "short_name", "notes"):
            for seg in re.split(r"[,;()/]|\s-\s", r.get(f) or ""):
                assert not M._person(seg.strip()), (r["id"], f)
        first_two = " ".join(r["id"].split("-")[1:3]).title()             # an id made from "<given> <surname>, ..."
        assert not M._person(first_two), r["id"]


def test_a_drain_commissioners_permit_is_the_commissions():
    A = load("add_mi_operators")
    assert A.clean_name("Pat Example, Sample County Drain Commission") == "Sample County Drain Commission"
    assert A.clean_name("Sample Communities, Inc., c/o Pat Example") == "Sample Communities, Inc."
    assert A.clean_name("Sampleton, City of") == "Sampleton, City of"


def test_each_michigan_permit_is_in_one_row(rows):
    every = json.loads((DATA_DIR / "dischargers.json").read_text())
    c = Counter(p.upper() for r in every for p in {r.get("npdes_permit"), *(r.get("npdes_permits") or [])} if p)
    mine = {p.upper() for r in rows for p in r.get("npdes_permits") or []}
    assert [p for p in mine if c[p] > 1] == []
    assert any("MIG580319" in r["npdes_permits"] and r["id"] == "mi-lenawee-county-drain-commission" for r in rows)


@pytest.mark.parametrize("owner,towns", [
    ("Spring Arbor Township/Summit Township", ["Spring Arbor Township", "Summit Township"]),
    ("Charter Township of Clinton - Department of Public Services", ["Clinton"]),
    ("Charter Township of Waterford DPW", ["Waterford"]),
    ("City of Zeeland Clean Water Plant", ["Zeeland"]),
    ("Detroit Water and Sewerage Department (DWSD)", ["Detroit"]),
    ("City of Lincooln Park", ["Lincoln Park"]),
])
def test_an_owners_towns_are_towns(owner, towns):
    assert load("add_mi_operators").owner_towns(owner) == towns


def test_michigan_towns_carry_no_works_words(rows):
    bad = re.compile(r"(?i)\b(dpw|wwtp|wastewater|treatment plant|department|clean water plant)\b|/")
    assert [(r["id"], t) for r in rows for t in r.get("towns") or [] if bad.search(t)] == []


def test_the_duty_rows_go_to_sewer_systems_only(rows, register):
    named = Counter(c.get("operator_id") for c in register)
    for r in rows:
        if r["kind"] == "cso_closed_or_none" or re.search(r"\bMS4\b", r["name"]):
            assert named[r["id"]] == 0, r["id"]               # a petroleum site, a stormwater permit: no duty rows
        else:
            assert named[r["id"]] >= 3, r["id"]
    assert all(named[r["id"]] for r in rows if r["kind"] == "cso")   # the checklist's CSO one-liner


def test_an_inverted_river_name_reads_as_written():
    from ingest import waters_from_nhd as N
    assert N.gnis_display("Rouge, River") == "River Rouge" and N.gnis_display("Apopka, Lake") == "Lake Apopka"


@pytest.mark.parametrize("text,slug", [
    ("Lower Rouge River", "lower-river-rouge-mi"), ("Middle Rouge River", "middle-river-rouge-mi"),
    ("Tittabawasee River", "tittabawassee-river-mi"), ("Raisin River", "river-raisin-mi"),
])
def test_michigan_spellings_in_the_reports_reach_their_own_records(text, slug):
    """Dearborn's and Wayne County's CSO outfalls on the Lower Rouge River went to the River Rouge record 4 to 6 km
    away, and 12 reports naming the Tittabawassee with one 's' found no record; data/water-aliases.json now says."""
    from build import status as S
    R = S.Resolver(S.load_waters(), [], {}, {})
    assert R.by_name(text, "MI", None, None)[0] == [slug]


def test_a_lake_running_into_other_states_waters_is_cut_to_the_states_own():
    """scripts/cut_lakes_to_state_waters.py: a lake record with more than 1 km2 beyond the state's TIGER polygon (a
    Great Lake) keeps only the state's part; one inside it is left alone."""
    from shapely.geometry import box, mapping
    C = load("cut_lakes_to_state_waters")
    state = box(0, 0, 1, 1)                                   # about 111 km a side
    lake = {"slug": "x-lake", "kind": "lake", "state": "XX", "geometry": mapping(box(0.5, 0.2, 1.5, 0.8)),
            "bbox": [0.5, 0.2, 1.5, 0.8], "area_km2": 7400.0, "note": "NHDPlus V2.1 waterbody, cut to the state, simplified to ~10 m",
            "towns": ["A"]}
    pond = {**lake, "slug": "y-pond", "geometry": mapping(box(0.1, 0.1, 0.2, 0.2)), "bbox": [0.1, 0.1, 0.2, 0.2]}
    doc = {"waters": [lake, pond], "problems": ["x-lake: geometry (0.5, 0.2, 1.5, 0.8) outside XX bbox"]}
    rep = C.run("XX", doc=doc, state_shape=state)
    assert [c[0] for c in rep["changed"]] == ["x-lake"] and rep["problems"] == []
    got = doc["waters"][0]
    assert got["bbox"][2] <= 1.0 + 1e-6 and got["area_km2"] < 3700 and got["towns"] == ["A"]
    assert "TIGER" in got["note"] and "cut to the state," not in got["note"]
    assert doc["waters"][1] is pond


def test_michigans_great_lakes_records_hold_michigans_waters_only():
    w = {x["slug"]: x for x in json.loads((DATA_DIR / "waters-nhd.json").read_text())["waters"]}
    box_mi = (-90.42, 41.69, -82.12, 48.31)                   # Michigan's TIGER box, waters included
    for slug, most in (("lake-michigan-mi", 40000), ("lake-superior-mi", 30000), ("lake-huron-mi", 25000),
                       ("lake-erie-mi", 1000)):
        b = w[slug]["bbox"]
        assert b[0] >= box_mi[0] - 0.01 and b[1] >= box_mi[1] - 0.01 and b[2] <= box_mi[2] + 0.01 and b[3] <= box_mi[3] + 0.01, slug
        assert w[slug]["area_km2"] < most, slug               # not the whole lake (Michigan 57,137 km2 before)
    assert not [p for p in json.loads((DATA_DIR / "waters-nhd.json").read_text())["problems"] if "outside MI" in p]


def test_the_petroleum_general_permits_outfalls_drive_no_sewage_caution():
    """EPA's CSO inventory lists four Michigan petroleum and remediation general permits (MIG08...); their 13 outfall
    rows are outfall_kind "other" with the reason, so the rain-likely caution and the map never read them as combined
    sewer outfalls (the Kalamazoo River at Marshall, the Chippewa and Clinton Rivers)."""
    from common import load_outfall_registry
    from ingest import rainfall
    rows = [r for r in load_outfall_registry(DATA_DIR) if str(r.get("npdes_permit")).startswith("MIG0811")]
    assert len(rows) == 13 and all(r["outfall_kind"] == "other" and "petroleum" in r["kind_note"] for r in rows)
    assert not [o for o in rainfall.cso_outfalls({"MI"}) if str(o["permit"]).startswith("MIG0811")]


def test_egles_statewide_list_credits_every_michigan_operator_online():
    """MCL 324.3112a(2): EGLE posts every operator's notice, so /reporting/ credits each Michigan operator with
    online notice (the go-live audit's P1-1: without the marker only GLWA, 1 of 565, was credited)."""
    from export import coverage as C
    reg = C.load_register()
    mi = C.notice_reach(reg, frozenset({M.SOURCE_ID}))["MI"]["told_online"]
    assert mi["operators"] == 565
    assert mi["online"] == 565
