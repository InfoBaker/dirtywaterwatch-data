"""NHD records that duplicate an openboatlaunch record now on file (ingest.waters_from_nhd.resolve_existing_duplicates,
--dedupe-existing), and the outfall steps on a record whose outline is not on this machine (ingest.outfall_waters,
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


def test_dedupe_main_writes_the_file_and_the_hand_aliases(fixture_doc, monkeypatch, tmp_path):
    doc, existing = fixture_doc
    path, apath = tmp_path / "waters-nhd.json", tmp_path / "water-aliases.json"
    path.write_text(json.dumps(doc))
    apath.write_text(json.dumps({"neuse-river-nc": ["Neuse"], "charles-river-ma": ["Charles River Basin"]}))
    monkeypatch.setattr(N, "existing_waters", lambda: existing)
    assert N.dedupe_main(["nc"], path=path, aliases_path=apath) == 0
    out = json.loads(path.read_text())
    assert out["stats"]["state_builds"]["NC"]["existing_duplicates"]["dropped"] == 2
    assert out["stats"]["state_builds"]["NC"]["existing_duplicates"]["renamed"] == 1
    assert json.loads(apath.read_text()) == {"charles-river-ma": ["Charles River Basin"], "neuse-river-nc": ["Neuse", "NEUSE RV"]}


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
    ok, _ = mt.guard_ok("lick-creek-nc", {"lat": 35.45, "lon": -79.25}, "Lick Creek")        # inside its box: kept
    assert ok




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
