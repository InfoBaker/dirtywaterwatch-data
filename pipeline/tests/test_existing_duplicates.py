"""NHD records that duplicate an openboatlaunch record now on file (ingest.waters_from_nhd.resolve_existing_duplicates,
--tidy), and the outfall steps on a record whose outline is not on this machine (ingest.outfall_waters,
2026-11-04: the NC, GA and FL openboatlaunch extracts arrived without their out/water files in cloud sessions).
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Polygon, box, mapping

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from ingest import outfall_waters as OW  # noqa: E402
from ingest import waters_from_nhd as N  # noqa: E402


@pytest.fixture(autouse=True)
def no_geometry_cache():
    S._GEOM_CACHE.clear()
    yield
    S._GEOM_CACHE.clear()


def nhd_rec(slug, name, line, towns, aliases=()):
    g = LineString(line)
    return {"slug": slug, "name": name, "kind": "river", "state": "NC", "towns": list(towns), "aliases": list(aliases),
            "bbox": list(g.bounds), "gnis_id": slug, "source": "nhd", "geometry": mapping(g)}


def obl_rec(slug, name, bbox, towns, kind="river"):
    # an openboatlaunch extract row: no geometry inline, and no out/water file on this machine
    return {"slug": slug, "name": name, "kind": kind, "state": "NC", "towns": list(towns), "bbox": bbox}


@pytest.fixture
def fixture_doc(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path / "no-snapshot")
    existing = {
        # the same Neuse River as the NHD record below (its box holds the NHD feature)
        "neuse-river-nc": obl_rec("neuse-river-nc", "Neuse River", [-78.6, 35.0, -77.0, 35.8], ["Goldsboro", "Kinston"]),
        # openboatlaunch's Little River is the one at Candor, 125 km from the NHD builder's at Goldsboro
        "little-river-nc": obl_rec("little-river-nc", "Little River", [-79.9, 35.2, -79.8, 35.3], ["Candor"]),
        # openboatlaunch's Tar River under a town slug: the NHD record of the same water at Greenville is a duplicate
        "tar-river-greenville-nc": obl_rec("tar-river-greenville-nc", "Tar River", [-77.6, 35.5, -77.2, 35.7], ["Greenville"]),
    }
    doc = {"stats": {}, "targets": [
        {"state": "NC", "name": "NEUSE RIVER", "slugs": ["neuse-river-nc"], "towns": ["Goldsboro"],
         "reach_slugs": {"03020201000171": "neuse-river-nc"}},
        {"state": "NC", "name": "Little River", "slugs": ["little-river-nc"], "towns": ["Goldsboro"],
         "reach_slugs": {"03020201000999": "little-river-nc"}},
        {"state": "NC", "name": "Tar River", "slugs": ["tar-river-nc"], "towns": ["Greenville"]},
        {"state": "VA", "name": "James River", "slugs": ["james-river-va"]},
    ], "waters": [
        nhd_rec("neuse-river-nc", "Neuse River", [(-78.3, 35.3), (-77.9, 35.38), (-77.6, 35.25)], ["Goldsboro"],
                aliases=["NEUSE RV", "NEUSE RV/PAMLICO SOUND"]),
        nhd_rec("little-river-nc", "Little River", [(-78.1, 35.45), (-78.0, 35.4)], ["Goldsboro", "Kenly"]),
        nhd_rec("tar-river-nc", "Tar River", [(-77.5, 35.6), (-77.3, 35.62)], ["Greenville"]),
        nhd_rec("mill-creek-nc", "Mill Creek", [(-78.0, 35.0), (-78.01, 35.01)], ["Dunn"]),
        {**nhd_rec("james-river-va", "James River", [(-77.4, 37.5), (-77.3, 37.5)], ["Richmond"]), "state": "VA"},
    ]}
    return doc, existing


def test_an_nhd_record_of_an_openboatlaunch_water_is_dropped_and_its_rows_point_there(fixture_doc):
    doc, existing = fixture_doc
    new, actions, aliases = N.resolve_existing_duplicates(json.loads(json.dumps(doc)), existing, ["NC"], when="2026-11-04")
    slugs = [w["slug"] for w in new["waters"]]
    assert "neuse-river-nc" not in slugs and "tar-river-nc" not in slugs          # openboatlaunch's are the public ones
    assert "mill-creek-nc" in slugs and "james-river-va" in slugs                  # no duplicate, another state: kept
    acts = {a["slug"]: a for a in actions}
    assert acts["neuse-river-nc"]["action"] == "dropped" and acts["neuse-river-nc"]["to"] == "neuse-river-nc"
    assert acts["tar-river-nc"]["to"] == "tar-river-greenville-nc"
    rows = {t["name"]: t for t in new["targets"]}
    assert rows["Tar River"]["slugs"] == ["tar-river-greenville-nc"]
    assert any("the NHD record tar-river-nc was dropped: openboatlaunch's tar-river-greenville-nc is this water" in n
               for n in rows["Tar River"]["notes"])
    assert rows["NEUSE RIVER"]["reach_slugs"] == {"03020201000171": "neuse-river-nc"}
    # EPA's spelling goes to the hand aliases; a whole path text does not
    assert aliases == {"neuse-river-nc": ["NEUSE RV"]}
    assert new["count"] == len(new["waters"])


def test_an_nhd_record_shadowed_by_another_water_of_its_slug_takes_a_town_slug(fixture_doc):
    doc, existing = fixture_doc
    new, actions, _ = N.resolve_existing_duplicates(json.loads(json.dumps(doc)), existing, ["NC"], when="2026-11-04")
    acts = {a["slug"]: a for a in actions}
    assert acts["little-river-nc"]["action"] == "renamed"
    assert acts["little-river-nc"]["to"] == "little-river-goldsboro-nc"
    assert "openboatlaunch's record of another Little River" in acts["little-river-nc"]["why"]
    rec = next(w for w in new["waters"] if w["name"] == "Little River")
    assert rec["slug"] == "little-river-goldsboro-nc" and rec["geometry"]          # the record stays, under its own slug
    row = next(t for t in new["targets"] if t["name"] == "Little River")
    assert row["slugs"] == ["little-river-goldsboro-nc"]
    assert row["reach_slugs"] == {"03020201000999": "little-river-goldsboro-nc"}
    # a second pass finds nothing more to do
    again, more, _ = N.resolve_existing_duplicates(new, existing, ["NC"], when="2026-11-04")
    assert more == [] and again["waters"] == new["waters"]


def test_the_bounding_box_test_is_sure_only_when_it_says_another_water():
    w = {"slug": "x-nc", "bbox": [-79.9, 35.2, -79.8, 35.3], "towns": ["Candor"]}
    far = LineString([(-78.1, 35.45), (-78.0, 35.4)])
    assert N.same_water_by_box(far, w)[0] is False
    inside = LineString([(-79.88, 35.22), (-79.82, 35.28)])
    assert N.same_water_by_box(inside, w)[0] is True
    # touching the box with a sliver, no town in common, the box mostly outside the feature's: undecided
    sliver = LineString([(-79.80, 35.25), (-79.0, 35.9)])
    assert N.same_water_by_box(sliver, w)[0] is None
    assert N.same_water_by_box(sliver, w, towns=["Candor"])[0] is True
    # no box: a town in common decides, a bay never by town alone
    assert N.same_water_by_box(inside, {"slug": "y-nc", "towns": ["Riceboro"]}, ["Riceboro"])[0] is True
    assert N.same_water_by_box(inside, {"slug": "y-nc", "towns": ["Riceboro"], "kind": "bay"}, ["Riceboro"])[0] is None


def test_the_builder_takes_the_openboatlaunch_record_when_its_outline_is_absent(fixture_doc, monkeypatch):
    _, existing = fixture_doc
    g = LineString([(-78.3, 35.3), (-77.9, 35.38)])
    rec = {"name": "Neuse River", "towns": ["Goldsboro"], "_geom": g, "length_km": 40.0, "note": "",
           "gnis_id": "1013910", "comids": [1]}
    monkeypatch.setattr(N, "build_feature", lambda nhd, st, c: dict(rec))
    run = N.Run.__new__(N.Run)
    run.existing, run.nhd = existing, None
    assert run.new_record(("line", "NC", "1013910"), {}, {"state": "NC", "name": "Neuse River", "points": Counter()},
                          {}) == {"_existing": "neuse-river-nc"}
    rec.update(name="Little River", _geom=LineString([(-78.1, 35.45), (-78.0, 35.4)]))
    out = run.new_record(("line", "NC", "2"), {}, {"state": "NC", "name": "Little River", "points": Counter()}, {})
    assert "_existing" not in out                    # another Little River: built, and assign_slugs gives it a town slug


def test_tidy_main_writes_the_file_and_the_hand_aliases(fixture_doc, monkeypatch, tmp_path):
    doc, existing = fixture_doc
    path, apath = tmp_path / "waters-nhd.json", tmp_path / "water-aliases.json"
    path.write_text(json.dumps(doc))
    apath.write_text(json.dumps({"neuse-river-nc": ["Neuse"], "charles-river-ma": ["Charles River Basin"]}))
    monkeypatch.setattr(N, "existing_waters", lambda: existing)
    assert N.tidy_main(["nc"], path=path, aliases_path=apath) == 0
    out = json.loads(path.read_text())
    assert out["stats"]["state_builds"]["NC"]["existing_duplicates"]["dropped"] == 2
    assert out["stats"]["state_builds"]["NC"]["existing_duplicates"]["renamed"] == 1
    assert json.loads(apath.read_text()) == {"charles-river-ma": ["Charles River Basin"], "neuse-river-nc": ["Neuse", "NEUSE RV"]}
    assert N.tidy_main(["NC"], path=path, aliases_path=apath) == 0             # a second pass: nothing new, nothing lost
    again = json.loads(path.read_text())["stats"]["state_builds"]["NC"]["existing_duplicates"]
    assert again["dropped"] == 2 and again["renamed"] == 1 and len(again["actions"]) == 3


# ---------------------------------------------------------------- outfall ties to a record with no outline here

def no_outline_matcher(tmp_path, monkeypatch, waters, outlines):
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path / "no-snapshot")
    mt = OW.Matcher.__new__(OW.Matcher)
    mt.waters = waters
    mt.dis_towns = {}
    mt._outlines = {}
    mt.towns = SimpleNamespace(outlines=lambda st, names: outlines)
    return mt


def test_a_record_without_an_outline_reaches_a_town_by_its_box_or_its_town_list(tmp_path, monkeypatch):
    raeford = box(-79.25, 34.95, -79.20, 35.00)
    waters = {"rockfish-creek-nc": obl_rec("rockfish-creek-nc", "Rockfish Creek", [-78.2, 34.6, -77.9, 34.8], ["Wallace"]),
              "little-river-nc": obl_rec("little-river-nc", "Little River", [-79.3, 34.9, -79.0, 35.1], ["Candor"])}
    mt = no_outline_matcher(tmp_path, monkeypatch, waters, [raeford])
    o = {"state": "NC", "city": "RAEFORD"}
    assert mt.no_outline("rockfish-creek-nc")
    assert mt.reaches_town("rockfish-creek-nc", o) is False         # its box lies 100 km from Raeford: sure
    assert mt.reaches_town("little-river-nc", o) is None             # its box holds Raeford: not known
    assert mt.reaches_town("rockfish-creek-nc", {"state": "NC", "city": "WALLACE"}) is True     # its town list


def test_several_records_named_and_one_unmeasured_do_not_crash_or_choose(tmp_path, monkeypatch):
    """2026-11-04: the rerun stopped with TypeError (None < float) on a text naming two waters, one an openboatlaunch
    record with no outline here; a record that cannot be measured must not be taken for the one at the point."""
    waters = {"black-creek-fl": {**obl_rec("black-creek-fl", "Black Creek", [-81.8, 30.0, -81.6, 30.2], []), "state": "FL"},
              "saint-johns-river-fl": {**obl_rec("saint-johns-river-fl", "St Johns River", [-81.9, 28.0, -81.3, 30.5], []),
                                       "state": "FL"}}
    mt = no_outline_matcher(tmp_path, monkeypatch, waters, [])
    mt.resolver = SimpleNamespace(by_name=lambda v, st, lat, lon, ev: (list(waters), None, None), canon=lambda s: s,
                                  guard_detail=lambda slugs, ev: (list(slugs), [], {}),
                                  name_limit_m=lambda s: (50_000.0, "test limit"))
    mt.fake = lambda o, t: {}
    mt.dist = lambda s, lat, lon: {"black-creek-fl": 100.0}.get(s)       # only Black Creek measured
    mt._aside = mt._several = None
    o = {"state": "FL", "lat": 30.1, "lon": -81.7}
    assert mt.by_name(o, "Black Creek and St Johns River") == (None, None)
    assert mt._several == ["black-creek-fl", "saint-johns-river-fl"]
    mt.dist = lambda s, lat, lon: {"black-creek-fl": 100.0, "saint-johns-river-fl": 5_000.0}.get(s)
    assert mt.by_name(o, "Black Creek and St Johns River")[0] == "black-creek-fl"     # both measured: the one at the point
    assert OW.far(None) > OW.far(1e9)


def test_the_guard_sets_aside_an_unmeasured_record_whose_box_is_too_far(tmp_path, monkeypatch):
    waters = {"lick-creek-nc": obl_rec("lick-creek-nc", "Lick Creek", [-79.3, 35.4, -79.2, 35.5], ["Sanford"], kind="stream")}
    mt = no_outline_matcher(tmp_path, monkeypatch, waters, [])
    mt.resolver = SimpleNamespace(guard_detail=lambda slugs, ev: (list(slugs), [], {}),
                                  name_limit_m=lambda s: (5_000.0, "test limit"))
    mt.fake = lambda o, t: {}
    ok, why = mt.guard_ok("lick-creek-nc", {"lat": 35.5, "lon": -80.2}, "Lick Creek")       # Denton, 88 km west
    assert not ok and "bounding box is" in why
    # inside its box (9 by 11 km): the water lies within 7.2 km of the point at most, which a 5 km limit does not cover:
    # held for want of the outline (a box holding the point is no measurement); an 8 km limit covers it
    mt._evidence = {}
    ok, why = mt.guard_ok("lick-creek-nc", {"lat": 35.45, "lon": -79.25}, "Lick Creek")
    assert not ok and OW.HELD in why
    mt.resolver.name_limit_m = lambda s: (8_000.0, "test limit")
    ok, _ = mt.guard_ok("lick-creek-nc", {"lat": 35.45, "lon": -79.25}, "Lick Creek")
    assert ok and "within 7.2 km of the point" in mt.evidence_of()["lick-creek-nc"]


def long_river_matcher(tmp_path, monkeypatch, towns_out):
    """A 190 km river record with no outline here whose box holds a town 64 km from the river (Valdosta's 'Suwannee
    River' plant, review 2026-11-04 water-followups P1-1)."""
    waters = {"suwannee-river-ga": {**obl_rec("suwannee-river-ga", "Suwannee River", [-83.4, 29.6, -82.0, 31.0], ["Fargo"]),
                                    "state": "GA"}}
    mt = no_outline_matcher(tmp_path, monkeypatch, waters, towns_out)
    mt.resolver = SimpleNamespace(guard_detail=lambda slugs, ev: (list(slugs), [], {}),
                                  name_limit_m=lambda s: (12_000.0, "the river record's extent counted to 10 km plus 2 km"),
                                  town_conflict=lambda ev, slug: None, canon=lambda s: s,
                                  distance_m=lambda s, lat, lon: None,
                                  by_name=lambda v, st, lat, lon, ev: (["suwannee-river-ga"], None, None))
    mt.fake = lambda o, t: {}
    mt._evidence, mt._held = {}, {}
    mt._aside = mt._several = None
    return mt


def test_a_long_rivers_box_holding_the_point_is_no_measurement(tmp_path, monkeypatch):
    mt = long_river_matcher(tmp_path, monkeypatch, [box(-83.35, 30.78, -83.2, 30.9)])
    valdosta = {"state": "GA", "npdes_permit": "GA0000001", "city": "VALDOSTA", "lat": 30.80, "lon": -83.23,
                "reach_gnis_name": "Mud Swamp"}
    ok, why = mt.guard_ok("suwannee-river-ga", valdosta, "Suwannee River")
    assert not ok and OW.HELD in why and "named 'Mud Swamp'" in why
    assert mt.by_name(valdosta, "Suwannee River") == (None, None)
    assert OW.HELD in mt._aside[0][1]
    # the same box with evidence: EPA's reach at the point carries the record's name, or its town list names the town
    ok, why = mt.guard_ok("suwannee-river-ga", {**valdosta, "reach_gnis_name": "Suwannee River"}, "Suwannee River")
    assert ok and "EPA's NHDPlus reach at the point is named 'Suwannee River'" in mt.evidence_of()["suwannee-river-ga"]
    ok, _ = mt.guard_ok("suwannee-river-ga", {**valdosta, "city": "FARGO"}, "Suwannee River")
    assert ok and "town list names the permittee's town (fargo)" in mt.evidence_of()["suwannee-river-ga"]


def test_an_unmeasured_record_beyond_the_guards_distance_keeps_its_town_check(tmp_path, monkeypatch):
    """The guard asks a named record beyond 2 km of the point to name the report's town; one with no outline here whose
    box alone is 3 km off is held to the same check (Mary Esther's 'East Bay River', Maury's 'Contentnea Creek')."""
    mt = long_river_matcher(tmp_path, monkeypatch, [])
    mt.waters["small-river-ga"] = {**obl_rec("small-river-ga", "Small River", [-83.0, 31.0, -82.99, 31.01], ["Fargo"]),
                                   "state": "GA"}
    mt.resolver.town_conflict = lambda ev, slug: "the report's town (maury) is not among the water's towns (Fargo)"
    o = {"state": "GA", "npdes_permit": "GA0000002", "city": "MAURY", "lat": 31.035, "lon": -82.995}
    ok, why = mt.unmeasured("small-river-ga", o, 12_000.0)
    assert not ok and "bounding box is 2.8 km from the point and the report's town (maury)" in why


def test_the_builders_record_with_no_outline_needs_evidence_at_a_known_point_and_town(tmp_path, monkeypatch):
    """'Neither a point nor a known town' let the builder's record stand; an unmeasured record has no distance although
    the row has a point, and was tied with neither check (Whittier's plant 163 km from the Tuckasegee record's box,
    Havelock's 42 km from the Neuse's)."""
    mt = long_river_matcher(tmp_path, monkeypatch, [box(-83.35, 30.78, -83.2, 30.9)])
    mt.targets = {("GA", N.compact("Suwannee River")): {"state": "GA", "name": "Suwannee River", "define_by": "reach",
                                                        "permits": ["GA0000001"], "slugs": ["suwannee-river-ga"], "how": []}}
    mt.dist = lambda s, lat, lon: None
    o = {"state": "GA", "npdes_permit": "GA0000001", "city": "VALDOSTA", "lat": 30.80, "lon": -83.23}
    assert mt.by_builder_permit(o, "Suwannee River") == (None, None)
    assert "suwannee-river-ga, is not measured here" in mt._builder_far and OW.HELD in mt._builder_far
    s, _ = mt.by_builder_permit({**o, "city": "FARGO"}, "Suwannee River")       # its town list: kept
    assert s == "suwannee-river-ga"
    mt.towns = None                                                          # no point and no town to check: as built
    assert mt.by_builder_permit({**o, "lat": None, "lon": None, "city": ""}, "Suwannee River")[0] == "suwannee-river-ga"


def test_water_match_says_what_an_unmeasured_tie_rests_on(tmp_path, monkeypatch):
    mt = long_river_matcher(tmp_path, monkeypatch, [])
    mt.dist = lambda s, lat, lon: None
    mt._evidence = {"suwannee-river-ga": "its town list names the permittee's town (fargo)"}
    o = {"state": "GA", "npdes_permit": "GA0000003", "city": "FARGO", "lat": 30.7, "lon": -82.56,
         "receiving_water_echo": "Suwannee River"}
    OW.apply(o, {"slug": "suwannee-river-ga", "step": "name", "how": "its receiving water 'Suwannee River' by name"}, mt)
    assert o["water_slug"] == "suwannee-river-ga" and o["match"] == "name_only"
    assert o["water_match"].endswith(OW.NO_OUTLINE_NOTE + "; kept as its town list names the permittee's town (fargo)")




def test_the_far_builder_record_reason_reads_without_a_point():
    mt = OW.Matcher.__new__(OW.Matcher)
    mt.waters = {"little-river-nc": {"state": "NC", "name": "Little River"}}
    mt.targets = {("NC", N.compact("Little River")): {"state": "NC", "name": "Little River", "define_by": "reach",
                                                       "permits": ["NC0000003"], "slugs": ["little-river-nc"], "how": []}}
    mt.resolver = SimpleNamespace(canon=lambda s: s)
    mt.dis_towns = {}
    mt.dist = lambda slug, lat, lon: None
    mt.reaches_town = lambda slug, o: False
    o = {"state": "NC", "npdes_permit": "NC0000003", "city": "KENLY", "lat": None, "lon": None}
    assert mt.by_builder_permit(o, "Little River") == (None, None)
    assert "little-river-nc, does not reach the permittee's town (kenly)" in mt._builder_far


def test_a_reservoir_by_its_hand_alias_and_a_row_without_a_record(monkeypatch, tmp_path):
    """Lake Sidney Lanier (review P2-4): NHDPlus names only an 18 km2 polygon near Buford 'Lake Sidney Lanier'; with the
    hand alias on openboatlaunch's Lake Lanier the fragment is dropped for it, and the 'Lake Lanier' row the build left
    without a record takes it (the operators' towns are on its town list)."""
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path / "no-snapshot")
    lanier = {"slug": "lake-lanier-ga", "name": "Lake Lanier", "kind": "reservoir", "state": "GA",
              "bbox": [-84.1211, 34.14627, -83.68924, 34.43986], "aliases": ["Lake Sidney Lanier"],
              "towns": ["Buford", "Cumming", "Flowery Branch", "Gainesville"]}
    frag = Polygon([(-84.07, 34.15), (-84.0, 34.15), (-84.0, 34.19), (-84.07, 34.19)])
    doc = {"targets": [
        {"state": "GA", "name": "Lake Sidney Lanier", "slugs": ["lake-sidney-lanier-ga"], "towns": ["Gainesville", "Cumming"]},
        {"state": "GA", "name": "Lake Lanier", "slugs": [], "towns": ["Buford", "Dahlonega"], "reason": "not found"},
        {"state": "GA", "name": "Mill Creek", "slugs": [], "towns": ["Dalton"], "reason": "not found"}],
        "waters": [{"slug": "lake-sidney-lanier-ga", "name": "Lake Sidney Lanier", "kind": "lake", "state": "GA",
                    "towns": ["Buford"], "bbox": list(frag.bounds), "geometry": mapping(frag)}]}
    existing = {"lake-lanier-ga": lanier,
                "mill-creek-ga": {"slug": "mill-creek-ga", "name": "Mill Creek", "state": "GA", "towns": ["Macon"]}}
    new, actions, _ = N.resolve_existing_duplicates(doc, existing, ["GA"], when="2026-11-04")
    assert new["waters"] == []
    rows = {t["name"]: t for t in new["targets"]}
    assert rows["Lake Sidney Lanier"]["slugs"] == ["lake-lanier-ga"]
    assert rows["Lake Lanier"]["slugs"] == ["lake-lanier-ga"] and rows["Lake Lanier"]["reason"] is None
    assert "reaches the operators' town (buford)" in rows["Lake Lanier"]["notes"][-1]
    assert rows["Mill Creek"]["slugs"] == []           # Macon's Mill Creek does not reach Dalton: left as it was
    assert sorted(a["action"] for a in actions) == ["dropped", "mapped"]


# ---------------------------------------------------------------- public reasons (review 2026-11-04 P3)

FL_REASON = ("no NHD flowline or waterbody of that name in the state; no NHD high-resolution flowline of that name within "
             "3 km of the points; OSM state query for FL failed twice (https://overpass-api.de/api/interpreter: "
             "ConnectionError): left for the next run")


def test_a_reason_names_no_tool_and_keeps_the_detail_aside():
    row = {"state": "FL", "name": "Bayou Chico", "slugs": [], "reason": FL_REASON,
           "places_failed": [{"lon": -87.2, "lat": 30.4, "reason": "not tried this run (--place-budget 120 s used)"},
                             {"lon": -87.3, "lat": 30.5, "reason": "no NHD flowline of that name within 2 km"}]}
    out = N.public_row(row, "2026-11-04")
    assert out["reason"].endswith("the map service (OpenStreetMap) could not be reached on 2026-11-04: left for the next run")
    assert "overpass" not in out["reason"].lower() and "Error" not in out["reason"]
    assert out["reason_detail"] == ["OSM state query for FL failed twice (https://overpass-api.de/api/interpreter: "
                                    "ConnectionError)"]
    assert out["places_failed"][0] == {"lon": -87.2, "lat": 30.4, "detail": "(--place-budget 120 s used)",
                                       "reason": "not tried this run (the run's time or request limit was reached on 2026-11-04)"}
    assert out["places_failed"][1] == row["places_failed"][1]
    assert N.public_row(out, "2026-11-05") == out                 # already public: unchanged, the date kept
    assert N.public_voice("build error (KeyError: 'geometry')", "2026-11-04")[0] == \
        "the record could not be built on 2026-11-04 (a fault in the build, logged)"


def test_a_row_not_reached_still_reads_as_not_reached_for_the_merge():
    row = {"state": "NC", "name": "Mill Creek", "slugs": [], "reason": f"{N.NOT_REACHED} (--budget-s used); the next run resumes"}
    out = N.finish_rows([{**row, "_recs": []}], date="2026-11-04")[0]
    assert out["reason"].startswith(N.NOT_REACHED) and "--budget" not in out["reason"]
    old = [{"state": "NC", "name": "Mill Creek", "slugs": ["mill-creek-nc"], "reason": None}]
    assert N.merge_targets(old, [out]) == old


def test_public_reasons_dates_each_state_by_its_build(monkeypatch):
    doc = {"built": "2026-11-05T00:00:00Z", "stats": {"state_builds": {"FL": {"built": "2026-11-04T02:45:19Z"}}},
           "targets": [{"state": "FL", "name": "A", "reason": FL_REASON},
                       {"state": "GA", "name": "B", "reason": FL_REASON.replace("FL", "GA")},
                       {"state": "VA", "name": "C", "reason": FL_REASON}]}
    assert N.public_reasons(doc, {"FL", "GA"}) == 2
    assert "reached on 2026-11-04" in doc["targets"][0]["reason"]
    assert "reached on 2026-11-05" in doc["targets"][1]["reason"]         # no build date: the file's
    assert doc["targets"][2]["reason"] == FL_REASON                        # another state: not touched


# ---------------------------------------------------------------- 'Unnamed stream' records (review 2026-11-04 P3)

def test_an_unnamed_stream_is_named_for_its_town_or_its_operators_and_listed_otherwise():
    line = mapping(LineString([(-82.60, 27.52), (-82.59, 27.53)]))
    doc = {"targets": [
        {"state": "FL", "name": None, "slugs": ["unnamed-stream-palmetto-fl"], "towns": ["Palmetto"],
         "reach_slugs": {"16919440": "unnamed-stream-palmetto-fl"}, "outfall_ref": ["FL0020401", "001"]},
        {"state": "FL", "name": None, "slugs": ["unnamed-stream-2178575-fl"], "towns": ["Southport"]}],
        "waters": [
            {"slug": "unnamed-stream-palmetto-fl", "name": "Unnamed stream", "state": "FL", "towns": ["Palmetto"],
             "comids": [16919440], "note": "NHDPlus V2.1: the unnamed network flowline COMID 16919440", "geometry": line},
            {"slug": "unnamed-stream-2178575-fl", "name": "Unnamed stream", "state": "FL", "towns": [],
             "comids": [2178575], "geometry": line},
            {"slug": "unnamed-stream-9-fl", "name": "Unnamed stream", "state": "FL", "towns": [], "comids": [9],
             "geometry": line},
            {"slug": "unnamed-tributary-to-neuse-river-nc", "name": "Unnamed tributary to Neuse River", "state": "NC",
             "towns": ["Kinston"], "geometry": line}]}
    actions, left = N.name_unnamed_streams(doc, ["FL", "NC"], when="2026-11-04")
    by = {w["slug"]: w for w in doc["waters"]}
    w = by["unnamed-stream-near-palmetto-fl"]
    assert w["name"] == "Unnamed stream near Palmetto" and w["slug_aliases"] == ["unnamed-stream-palmetto-fl"]
    assert "named for its town list (Palmetto)" in w["note"]
    assert by["unnamed-stream-near-southport-fl"]["name"] == "Unnamed stream near Southport"   # the operators' town
    assert left == ["unnamed-stream-9-fl"] and by["unnamed-stream-9-fl"]["name"] == "Unnamed stream"
    assert "unnamed-tributary-to-neuse-river-nc" in by                                          # already named: kept
    assert doc["targets"][0]["slugs"] == ["unnamed-stream-near-palmetto-fl"]
    assert doc["targets"][0]["reach_slugs"] == {"16919440": "unnamed-stream-near-palmetto-fl"}
    assert S.slug_aliases(by)["unnamed-stream-palmetto-fl"] == "unnamed-stream-near-palmetto-fl"     # status follows it
    assert N.name_unnamed_streams(doc, ["FL"], when="2026-11-04") == ([], ["unnamed-stream-9-fl"])  # idempotent


def test_the_build_names_a_new_unnamed_stream_for_its_town(monkeypatch, tmp_path):
    monkeypatch.setattr(S, "OBL_WATER_DIR", tmp_path / "no-snapshot")
    assert N.unnamed_name("Manatee River") == "Unnamed tributary to Manatee River"
    assert N.unnamed_name(None, "west palm beach") == "Unnamed stream near West Palm Beach"
    assert N.unnamed_name(None) == "Unnamed stream"
    rec = {"name": "Unnamed stream", "towns": [], "_geom": LineString([(-80.07, 26.68), (-80.071, 26.69)]),
           "length_km": 0.6, "note": "", "comids": [59942]}
    monkeypatch.setattr(N, "build_feature", lambda nhd, st, c: dict(rec))
    run = N.Run.__new__(N.Run)
    run.existing, run.nhd = {}, None
    t = {"state": "FL", "name": None, "points": Counter(), "towns": Counter({"West Palm Beach": 2})}
    assert run.new_record(("line", "FL", "comid59942"), {}, t, {})["name"] == "Unnamed stream near West Palm Beach"


def test_a_held_record_is_not_replaced_by_a_near_named_one_in_the_town(tmp_path, monkeypatch):
    """Wilmington's 'Northeast Cape Fear River' plant: its record held for want of the outline, the town step must not
    take the Cape Fear River (a near name on Wilmington's town list) in its place."""
    waters = {"cape-fear-river-nc": obl_rec("cape-fear-river-nc", "Cape Fear River", [-79.0, 33.8, -77.9, 35.6],
                                            ["Wilmington", "Fayetteville"]),
              "northeast-cape-fear-river-nc": obl_rec("northeast-cape-fear-river-nc", "Northeast Cape Fear River",
                                                      [-78.1, 34.2, -77.6, 35.2], ["Burgaw"])}
    mt = no_outline_matcher(tmp_path, monkeypatch, waters, [box(-77.95, 34.15, -77.85, 34.3)])
    mt.dis_waters = {}
    o = {"state": "NC", "npdes_permit": "NC0000004", "city": "WILMINGTON", "lat": None, "lon": None}
    mt._evidence, mt._held = {}, {}
    mt._aside = [("northeast-cape-fear-river-nc", f"no point, and its town list does not name the permittee's town "
                                                  f"(wilmington): {OW.HELD}")]
    assert mt.by_name_and_town(o, "Northeast Cape Fear River") == (None, None)
    mt._aside = None                    # the text's own record set aside for a sure reason: the town step as before
    s, _ = mt.by_name_and_town(o, "Cape Fear River")
    assert s == "cape-fear-river-nc" and "town list names" in mt.evidence_of()["cape-fear-river-nc"]


def test_a_box_beyond_the_limit_sets_the_name_aside_but_the_permits_town_still_decides(tmp_path, monkeypatch):
    """Whittier's plant: EPA's point 160 km from the Tuckasegee record's box. The name guard sets the record aside (the
    box is a sure lower bound), as it does a measured record; the builder's record for the permit is then taken by the
    town list, however far EPA's point (the rule of review 2026-11-04 P1-2)."""
    mt = long_river_matcher(tmp_path, monkeypatch, [])
    o = {"state": "GA", "npdes_permit": "GA0000001", "city": "FARGO", "lat": 33.0, "lon": -84.0}
    ok, why = mt.guard_ok("suwannee-river-ga", o, "Suwannee River")
    assert not ok and why.startswith("its bounding box is") and "km from the point" in why
    mt.targets = {("GA", N.compact("Suwannee River")): {"state": "GA", "name": "Suwannee River", "define_by": "reach",
                                                        "permits": ["GA0000001"], "slugs": ["suwannee-river-ga"], "how": []}}
    mt.dist = lambda s, lat, lon: None
    assert mt.by_builder_permit(o, "Suwannee River")[0] == "suwannee-river-ga"
    assert "town list names the permittee's town (fargo)" in mt.evidence_of()["suwannee-river-ga"]


def test_a_rebuild_of_the_state_keeps_the_tidys_log(tmp_path, monkeypatch):
    """The tidy's log is the only record of the NHD records it dropped or renamed: a later state build (NC's rebuild of
    2026-11-04 after its tidy) kept only its own statistics and the 41 drops and 9 renames left the file."""
    out = tmp_path / "waters-nhd.json"
    monkeypatch.setattr(N, "OUT", out)
    log = {"date": "2026-11-04", "dropped": 1, "renamed": 0, "rows_mapped": 0, "unnamed_named": 0, "unnamed_left": [],
           "actions": [{"slug": "neuse-river-nc", "action": "dropped", "to": "neuse-river-nc", "why": "same name"}]}
    out.write_text(json.dumps({"partial": False, "stats": {"state_builds": {"NC": {"records": 5, "existing_duplicates": log}}},
                               "targets": [], "waters": []}))
    N.write_output([], [], [], [], partial=True, stats={"NC": {"records": 4}}, final=True, scope_states={"NC"})
    nc = json.loads(out.read_text())["stats"]["state_builds"]["NC"]
    assert nc["records"] == 4 and nc["existing_duplicates"] == log


def test_a_tidy_that_repeats_an_action_does_not_count_it_twice(fixture_doc, monkeypatch, tmp_path):
    doc, existing = fixture_doc
    path, apath = tmp_path / "waters-nhd.json", tmp_path / "water-aliases.json"
    path.write_text(json.dumps(doc))
    apath.write_text("{}")
    monkeypatch.setattr(N, "existing_waters", lambda: existing)
    N.tidy_main(["NC"], path=path, aliases_path=apath)
    first = json.loads(path.read_text())["stats"]["state_builds"]["NC"]["existing_duplicates"]
    d = json.loads(path.read_text())
    d["waters"] = doc["waters"]                  # the same records back (a rebuild), the log kept: the same actions again
    d["targets"] = doc["targets"]
    path.write_text(json.dumps(d))
    N.tidy_main(["NC"], path=path, aliases_path=apath)
    again = json.loads(path.read_text())["stats"]["state_builds"]["NC"]["existing_duplicates"]
    assert again["actions"] == first["actions"] and again["dropped"] == first["dropped"]


# ---------------------------------------------------------------- the place pass at the end of the budget (IL review)

def test_the_place_pass_stops_quietly_when_the_budget_ends_while_a_record_is_built(monkeypatch):
    """resolve_point is inside the pass's BudgetExhausted guard; the geometry fetch of the record it chose
    (new_record -> build_feature) was not, so the run died with a traceback instead of leaving the place for the
    next run (Illinois build, 2026-11-04)."""
    run = N.Run.__new__(N.Run)
    run.args, run.net_end, run.feats, run.existing, run.nhd = SimpleNamespace(place_budget=None), None, {}, {}, None
    t = {"key": "il|mill creek", "state": "IL", "name": "Mill Creek", "points": Counter({(-88.0, 41.5): 3})}
    row = {"how": ["name at a point"], "slugs": [], "_recs": [], "reason": None}
    monkeypatch.setattr(run, "uncovered_places", lambda t_, r_: [(-88.0, 41.5, 2, 3)], raising=False)
    monkeypatch.setattr(run, "place_geoms", lambda r_: [], raising=False)
    monkeypatch.setattr(N, "resolve_point", lambda nhd, t_, lon, lat: ({"type": "line", "gnis_id": "1"}, "point"))

    def out_of_budget(*a, **k):
        raise N.BudgetExhausted("--max-requests 10 used")
    monkeypatch.setattr(N, "build_feature", out_of_budget)
    run.place_pass([(t, row)])                                   # before the fix: BudgetExhausted escaped
    assert row["places_failed"] == [{"lon": -88.0, "lat": 41.5, "reason": "not tried this run (--max-requests 10 used)"}]
    assert run.feats == {} and row["slugs"] == []


def test_a_canal_named_for_two_places_is_one_water():
    """Illinois review, 2026-11-04: 'Chicago Sanitary and Ship Canal' (109 Illinois outfall rows) was split at its
    'and' into targets 'Chicago Sanitary' and 'Ship Canal', so the state's chief CSO receiving water got no record."""
    for t, want in (("CHICAGO SANITARY AND SHIP CANAL", ["CHICAGO SANITARY and SHIP CANAL"]),
                    ("Chicago Sanitary & Ship Canal", ["Chicago Sanitary and Ship Canal"]),
                    ("Illinois and Michigan Canal", ["Illinois and Michigan Canal"]),
                    ("Delaware & Raritan Canal", ["Delaware and Raritan Canal"]),
                    ("IL & MICH CANAL CHICAGO SANITARY AND SHIP CANAL", ["IL and MICH CANAL", "CHICAGO SANITARY and SHIP CANAL"]),
                    # lists still split: a kind word before the 'and', or one after it
                    ("Mill Creek & Erie Canal", ["Mill Creek", "Erie Canal"]),
                    ("CEDAR CREEK & COURT CREEK", ["CEDAR CREEK", "COURT CREEK"]),
                    ("Fox River, Indian Creek and Blackberry Creek", ["Fox River", "Indian Creek", "Blackberry Creek"])):
        assert N.split_names(t, False) == want, t
        assert N.national_parts(t) == (want, None), t
