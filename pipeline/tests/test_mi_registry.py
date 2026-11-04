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
    """The NHD Great Lakes records were cut to Michigan's waters; the tidy (MI audit P1-3) then dropped them for
    openboatlaunch's whole-lake records, which carry the wikidata ids the shoreline rule keys on. Any NHD record
    of these slugs left must still be Michigan's part only."""
    from build import status as S
    w = {x["slug"]: x for x in json.loads((DATA_DIR / "waters-nhd.json").read_text())["waters"]}
    box_mi = (-90.42, 41.69, -82.12, 48.31)                   # Michigan's TIGER box, waters included
    public = S.load_waters()
    for slug, most, qid in (("lake-michigan-mi", 40000, "Q1169"), ("lake-superior-mi", 30000, "Q1066"),
                            ("lake-huron-mi", 25000, "Q1383"), ("lake-erie-mi", 1000, "Q5492")):
        assert public[slug].get("wikidata") == qid, slug
        if slug in w:
            b = w[slug]["bbox"]
            assert b[0] >= box_mi[0] - 0.01 and b[1] >= box_mi[1] - 0.01 and b[2] <= box_mi[2] + 0.01 and b[3] <= box_mi[3] + 0.01, slug
            assert w[slug]["area_km2"] < most, slug           # not the whole lake (Michigan 57,137 km2 before)
    assert not [p for p in json.loads((DATA_DIR / "waters-nhd.json").read_text())["problems"] if "outside MI" in p]


def test_the_tidy_left_no_michigan_nhd_record_shadowed_but_the_kept_one():
    """MI audit P1-3: 82 NHD records shared an openboatlaunch slug and were shadowed (status.load_waters keeps the
    first record of a slug); after `waters_from_nhd --state MI --tidy` only KEEP_NHD_RECORD's are."""
    from ingest import waters_from_nhd as N
    obl = {x["slug"] for x in json.loads((DATA_DIR / "waters-mi.json").read_text())["waters"]}
    nhd = [x for x in json.loads((DATA_DIR / "waters-nhd.json").read_text())["waters"] if x.get("state") == "MI"]
    assert sorted(x["slug"] for x in nhd if x["slug"] in obl) == sorted(s for s in N.KEEP_NHD_RECORD if s.endswith("-mi"))
    aliases = json.loads((DATA_DIR / "water-aliases.json").read_text())
    assert not [a for a in aliases.get("huron-river-mi", []) if "," in a]          # a list of streams (P3-2)


@pytest.mark.parametrize("old,new", [
    ("black-river-mi", "black-river-port-huron-mi"), ("paint-river-mi", "paint-river-iron-river-mi"),
    ("pine-river-mi", "pine-river-alma-mi"), ("torch-lake-mi", "torch-lake-hubbell-mi"),
])
def test_the_target_rows_of_a_shadowed_record_of_another_water_follow_it(old, new):
    """The NHD records of these slugs were other waters than openboatlaunch's records of the slug (Croswell's
    Black River resolved to Alpena's); after the tidy no Michigan target row names the old slug."""
    from build import status as S
    rows = [t for t in json.loads((DATA_DIR / "waters-nhd.json").read_text())["targets"] if t.get("state") == "MI"]
    assert not [t["name"] for t in rows if old in (t.get("slugs") or []) or old in (t.get("reach_slugs") or {}).values()]
    assert new in S.load_waters()


def outfall(f, permit, oid):
    rows = json.loads((DATA_DIR / f).read_text())["outfalls"]
    return next(r for r in rows if r["npdes_permit"] == permit and r["outfall"] == oid)


@pytest.mark.parametrize("f,permit,oid,slug", [
    # Croswell's plant is on the Black River at Port Huron, not Alpena's (185,770 m before the tidy)
    ("outfalls-plants-us.json", "MI0021083", "SLD", "black-river-port-huron-mi"),
    # Standish's point lies on Arenac County's Pine River (openboatlaunch's pine-river-mi), not Alma's
    ("outfalls-plants-us.json", "MI0024139", "003", "pine-river-mi"),
    # the Saint Joseph River's plants on their own EPA reach: the river's NHD record, not the mouth (P2-5)
    *[("outfalls-plants-us.json", p, "SLD", "saint-joseph-river-jonesville-mi")
      for p in ("MI0020109", "MI0020991", "MI0022136", "MI0060273", "MIG570204", "MIG580404", "MIG580409", "MIG580415")],
    # Benton Harbor-St Joseph lies at the mouth, on openboatlaunch's polygon (5 m)
    # the sludge outfall: the outline ties run of 2026-11-04 matched it by its own EPA reach to the river's NHD line
    # (saint-joseph-river-jonesville-mi, 1.4 km), the plant's 001 by name to the openboatlaunch mouth record (5 m);
    # both are the Saint Joseph River
    ("outfalls-plants-us.json", "MI0022322", "SLD", ("saint-joseph-river-mi", "saint-joseph-river-jonesville-mi")),
    # the Upper River Rouge (NHD's name; EPA's 'Upper Rouge River'): Redford-Livonia's outfalls; the four whose EPA
    # point lies on Bell Branch, its tributary, by the point rule (receiving_water_override, the basis on the row)
    ("outfalls-us.json", "MI0051535", "001", "upper-river-rouge-mi"),
    ("outfalls-us.json", "MI0051535", "0U3", "upper-river-rouge-mi"),
    *[("outfalls-us.json", "MI0051535", o, "bell-branch-mi") for o in ("0U5", "0U9", "U10", "U11")],
    # the point on Ashcroft-Sherwood Drain, which does not reach the Upper River Rouge in NHDPlus: name and point
    # disagree, no record
    ("outfalls-us.json", "MI0051535", "0U2", None),
    # Grosse Pointe Shores: 'COMBINED SEWAGE TO LK.ST.CLAIR ONLY'
    *[("outfalls-us.json", "MI0026085", o, "lake-saint-clair-mi") for o in ("001", "002", "003", "004")],
    # Yale: the permit number typed as the water; EPA's discharge points give MIG580325 (Yale WWSL) Mill Creek
    *[("outfalls-us.json", "MI0021270", o, "mill-creek-kenockee-mi") for o in ("002", "004", "005", "006", "007")],
    # Capac's Lemon Drain: the unnamed NHDPlus flowline of EPA's reach 04090001000512
    *[("outfalls-us.json", "MI0021733", o, "unnamed-tributary-to-belle-river-mi") for o in ("002", "003", "004")],
    # the plant's general permit, outfall 001, named Lemon Drain by EPA: tied by the outline ties run, cited the same way
    ("outfalls-plants-us.json", "MIG580271", "001", "unnamed-tributary-to-belle-river-mi"),
    # GLWA's Rouge outfalls: Hubbell-Southfield and Baby Creek on the main River Rouge, Oakwood at the Detroit record
    ("outfalls-us.json", "MI0022802", "101", "river-rouge-mi"), ("outfalls-us.json", "MI0022802", "107", "river-rouge-mi"),
    ("outfalls-us.json", "MI0022802", "109", "river-rouge-detroit-mi"),
    # Conner Creek (buried): no record of it, and no source names the water it reaches
    ("outfalls-us.json", "MI0022802", "104", None),
])
def test_michigan_outfalls_after_the_tidy(f, permit, oid, slug):
    r = outfall(f, permit, oid)
    assert r["water_slug"] in slug if isinstance(slug, tuple) else r["water_slug"] == slug
    assert r.get("no_water_reason") if slug is None else r.get("water_match")
    if r.get("receiving_water_override"):
        assert "MI go-live audit 2026-11-04" in r["receiving_water_override"]["basis"]


@pytest.mark.parametrize("text,slug", [
    ("Upper Rouge River", "upper-river-rouge-mi"), ("Upper River Rouge", "upper-river-rouge-mi"),
    ("Lemon Drain", "unnamed-tributary-to-belle-river-mi"),
])
def test_michigan_names_the_operators_type_reach_their_records(mi_resolver, text, slug):
    assert mi_resolver.by_name(text, "MI", None, None, {})[0] == [slug]


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


@pytest.fixture
def mi_resolver(monkeypatch):
    from build import status as S
    monkeypatch.setattr(S, "_STATES", set(S.rules_live_states(S.load_rules()) or []) | {"MI"})
    return S.make_resolver()


def test_rouge_river_as_the_operators_type_it_finds_both_river_rouge_records(mi_resolver):
    """GLWA and Dearborn type "Rouge River" (and "Main Rouge River"); the records are "River Rouge" (the audit's
    P1-2: the resolver found no water)."""
    from build import status as S
    for text in ("Rouge River", "Main Rouge River"):
        key = ("MI", S.norm_name(text))
        found = set(mi_resolver.names.get(key, [])) | set(mi_resolver.exact.get(key, []))
        assert found == {"river-rouge-mi", "river-rouge-detroit-mi"}, text


@pytest.mark.parametrize("ev,slug", [
    # GLWA's report names no outfall in the registry: Detroit, its town, holds only the Detroit record
    ({"npdes_permit": "MI0022802", "discharger_id": "mi-glwa-wrrf-mi0022802", "outfall_id": "063"},
     "river-rouge-detroit-mi"),
    # Dearborn's outfall 013 lies on the River Rouge record (registry, 16 m)
    ({"npdes_permit": "MI0025542", "discharger_id": "mi-dearborn-cso-mi0025542", "outfall_id": "013"},
     "river-rouge-mi"),
])
def test_the_operator_chooses_which_river_rouge_a_rouge_river_report_reaches(mi_resolver, ev, slug):
    ev = {"event_id": "mi-egle-mienviro-cso-sso-list:x", "source_id": M.SOURCE_ID, "event_type": "cso",
          "waterbody_text": "Rouge River", **ev}
    assert mi_resolver.resolve(ev)["water_slugs"] == [slug]


def test_a_rouge_river_report_whose_town_holds_neither_record_is_not_guessed(mi_resolver):
    ev = {"event_id": "mi-egle-mienviro-cso-sso-list:y", "source_id": M.SOURCE_ID, "event_type": "cso",
          "waterbody_text": "Main Rouge River", "npdes_permit": "MI0051489",
          "discharger_id": "mi-wayne-co-dearborn-heights-cso-mi0051489"}
    r = mi_resolver.resolve(ev)
    assert r["water_slugs"] == [] and r.get("unplaced_reason") == "ambiguous name"


def test_a_name_given_to_an_unnamed_record_is_cited_on_the_rows_it_ties():
    """A hand alias that names an unnamed NHDPlus record ('Lemon Drain' on unnamed-tributary-to-belle-river-mi) is
    the permit's name for EPA's own reach: each outfall row it ties says so in receiving_water_override's basis,
    with the reach, so the tie is not read as a name match alone (MI go-live review 2026-11-04)."""
    aliases = json.loads((DATA_DIR / "water-aliases.json").read_text())
    named = {s: {a.lower() for a in v} for s, v in aliases.items() if s.startswith("unnamed-") and s.endswith("-mi")}
    rows = [r for f in ("outfalls-us.json", "outfalls-plants-us.json")
            for r in json.loads((DATA_DIR / f).read_text())["outfalls"] if r.get("water_slug") in named
            and str(r.get("receiving_water_echo") or "").lower() in named[r["water_slug"]]]
    assert len(rows) == 4
    for r in rows:
        basis = (r.get("receiving_water_override") or {}).get("basis") or ""
        reach = r.get("reach_id") or "04090001000512"      # MIG580271 001 has no reach of its own: the SLD outfall's is cited
        assert reach in basis and "COMID" in basis, (r["npdes_permit"], r["outfall"])
