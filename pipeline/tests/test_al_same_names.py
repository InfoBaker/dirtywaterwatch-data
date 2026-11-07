"""Alabama's county-aware name placement (final audit 2026-11-07 P2-2): a name several Alabama waters share goes only to
a record reaching the county of the report's own point, or within the name-match distance of it; the second Black Creek
(GNIS 114418, west Birmingham) and Eslava Creek (GNIS 118029, Mobile) have hand records, so the nearest same-named
record takes their reports. Records are the batch's (simplified outlines, tests/fixtures/al_same_named_waters.json);
the points are ADEM's. Every other state's name placement is unchanged."""
import copy
import json
from pathlib import Path

import pytest

from build import status as S

WATERS = json.loads((Path(__file__).parent / "fixtures" / "al_same_named_waters.json").read_text())


@pytest.fixture(autouse=True)
def alabama_live(monkeypatch):
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"AL"})


def resolver(*slugs):
    return S.Resolver({s: copy.deepcopy(WATERS[s]) for s in slugs}, [], placement_rules={})


def report(rid, text, lat, lon, permit, state="AL"):
    return {"event_id": f"al-adem-sso-history:{rid}", "source_id": "al-adem-sso-history", "source_record_id": rid,
            "event_type": "sso", "status": "ended", "waterbody_text": text, "water_slugs": [], "water_match": "none",
            "lat": lat, "lon": lon, "npdes_permit": permit, "raw": {"state": state}}


def test_the_county_of_a_point_is_read_from_the_census_outlines():
    assert S.point_county("AL", 30.501409, -87.913858) == ("01003", "Baldwin County")       # Fairhope
    assert S.point_county("AL", 33.549718, -86.865845) == ("01073", "Jefferson County")     # west Birmingham
    assert S.point_county("AL", 40.0, -80.0) is None


def test_fairhopes_cowan_creek_is_not_fergusons():
    # SSO-00013224 (City of Fairhope, 2020): cowan-creek-al lies near Ferguson, about 400 km north, with no outline
    r = resolver("cowan-creek-al").resolve(report("SSO-00013224", "Cowan Creek", 30.501409, -87.913858, "AL0020842"))
    assert r["water_slugs"] == []
    slugs, note, _ = resolver("cowan-creek-al").by_name("Cowan Creek", "AL", 30.501409, -87.913858,
                                                         report("x", "Cowan Creek", 30.501409, -87.913858, None))
    assert slugs == [] and "Baldwin County" in note


def test_school_house_creek_is_not_lowndes_countys_house_creek():
    # SSO-00209177 (Baldwin County Sewer Service, 2022): the name reads as House Creek, whose record lies in Lowndes County
    r = resolver("house-creek-al").resolve(report("SSO-00209177", "School House Creek", 30.318025, -87.728398,
                                                  "ALSI9902013"))
    assert r["water_slugs"] == []


@pytest.mark.parametrize("rid,lat,lon", [("SSO-00210917", 33.549718, -86.865845), ("SSO-00210520", 33.557003, -86.834229),
                                         ("SSO-00208172", 33.554708, -86.837401)])
def test_west_birminghams_black_creek_takes_its_reports(rid, lat, lon):
    r = resolver("black-creek-fultondale-al", "black-creek-birmingham-al").resolve(
        report(rid, "Black Creek", lat, lon, "AL0023647"))
    assert r["water_slugs"] == ["black-creek-birmingham-al"]


def test_fultondales_black_creek_keeps_reports_at_fultondale():
    r = resolver("black-creek-fultondale-al", "black-creek-birmingham-al").resolve(
        report("x", "Black Creek", 33.6135, -86.8100, "AL0026913"))
    assert r["water_slugs"] == ["black-creek-fultondale-al"]


@pytest.mark.parametrize("rid,lat,lon", [("SSO-00213268", 30.68395, -88.120938), ("SSO-00212383", 30.68585, -88.124),
                                         ("SSO-00010827", 30.664669, -88.16266)])
def test_the_second_eslava_creek_takes_its_reports(rid, lat, lon):
    r = resolver("eslava-creek-al", "eslava-creek-mobile-al").resolve(report(rid, "Eslava Creek", lat, lon, "AL0023094"))
    assert r["water_slugs"] == ["eslava-creek-mobile-al"]


def test_a_record_with_no_box_is_kept():
    nobox = {**WATERS["cowan-creek-al"], "slug": "cowan-creek-nobox-al", "bbox": None}
    res = S.Resolver({"cowan-creek-nobox-al": nobox}, [], placement_rules={})
    slugs, _, _ = res.by_name("Cowan Creek", "AL", 30.501409, -87.913858,
                              report("x", "Cowan Creek", 30.501409, -87.913858, None))
    assert slugs == ["cowan-creek-nobox-al"]


def test_other_states_are_unchanged():
    # the same records and point under another state's code take the old path, rule or no rule
    def as_state(st):
        ws = {s: {**copy.deepcopy(WATERS[s]), "state": st} for s in ("cowan-creek-al", "house-creek-al")}
        res = S.Resolver(ws, [], placement_rules={})
        return [res.by_name(n, st, 30.501409, -87.913858, report("x", n, 30.501409, -87.913858, None, st))[0]
                for n in ("Cowan Creek", "House Creek")]
    with_rule = as_state("MS")
    saved = dict(S.COUNTY_STATES)
    try:
        S.COUNTY_STATES.clear()
        without = as_state("MS")
    finally:
        S.COUNTY_STATES.update(saved)
    assert with_rule == without == [["cowan-creek-al"], ["house-creek-al"]]


def test_the_names_pass_sees_fairhopes_cowan_creek_as_unbuilt():
    from ingest import waters_from_nhd as N
    res = resolver("cowan-creek-al", "black-creek-fultondale-al", "black-creek-birmingham-al")
    slugs, at = N.has_record_at(res, "Cowan Creek", "AL", [(-87.913858, 30.501409)], [], per_place=True)
    assert slugs == [] and at == [[]]
    slugs, at = N.has_record_at(res, "Black Creek", "AL", [(-86.865845, 33.549718)], [], per_place=True)
    assert at == [["black-creek-birmingham-al"]]
