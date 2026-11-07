"""Provisional outfalls from the overflow reports (build/provisional_outfalls.py; docs/national-outfalls.md, "Locations
from the reports themselves" and "Provisional outfall pipeline"). No network: the NLDI / NHDPlus answers are a
pre-filled cache. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import os
import sys
from collections import Counter
from pathlib import Path

import pytest
from shapely.geometry import box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import provisional_outfalls as P  # noqa: E402
from common import event  # noqa: E402


def ev(i, lat, lon, op="ct-ansonia", permit=None, et="sso", raw=None, **kw):
    return {**event(source_id="ct-deep-archive", source_record_id=f"r{i}", event_type=et, discharger_id=op,
                    npdes_permit=permit, lat=lat, lon=lon, coord_source="source" if lat is not None else None,
                    started_at=f"2021-0{1 + i % 8}-01T10:00:00-05:00", raw=raw or {}, **kw)}


KEY = {"ct-ansonia": "ct-ansonia", "ct-derby": "ct-derby", "ct-shelton": "ct-shelton", "CT0100013": "ct-ansonia"}
BY_ID = {"ct-ansonia": {"id": "ct-ansonia", "name": "Ansonia WPCA", "state": "CT", "npdes_permit": "CT0100013"},
         "ct-derby": {"id": "ct-derby", "name": "Derby", "state": "CT"},
         "ct-shelton": {"id": "ct-shelton", "name": "Shelton", "state": "CT"}}
CT = {"CT": box(-73.8, 40.9, -71.7, 42.1)}


# ---------------------------------------------------------------- privacy

@pytest.mark.parametrize("raw,kw", [
    ({"BYPASS_PRIV_PUB": "Yes", "BYPASS_LOCATION": "Manhole"}, {}),
    ({"BYPASS_LOCATION": "Basement"}, {}),
    ({"Location of Bypass": "Lateral - Private"}, {}),
    ({"_responsibility": "Private"}, {}),
    ({"row": {"overflow_type": "Unauthorized Discharge"}}, {}),
    ({"sewage": [{"component": "House Lateral", "impacts": []}]}, {}),
    ({"sewage": [{"component": "Manhole", "impacts": ["Sewage Backup in Building"]}]}, {}),
    ({}, {"volume_text": "10 gallons into the basement of the house"}),
    ({"row": {"addressDescription": "backup into a home on Elm"}}, {}),
])
def test_private_property_and_building_backups_are_left_out(raw, kw):
    assert P.privacy_reason(ev(1, 41.3, -73.0, raw=raw, **kw))


@pytest.mark.parametrize("raw", [
    {"BYPASS_PRIV_PUB": "No", "BYPASS_LOCATION": "Manhole"},
    {"Location of Bypass": "Pump Station", "How was Incident Discovered": "Received a possible stoppage call from homeowner"},
    {"row": {"addressDescription": "Manhole is in the center of Melrose at Westgate, SSO #002"}},
    {"sewage": [{"component": "Manhole", "impacts": ["Discharge to State Waters"]}]},
])
def test_public_system_reports_are_kept(raw):
    assert P.privacy_reason(ev(1, 41.3, -73.0, raw=raw)) is None


@pytest.mark.parametrize("name,want", [
    ("3470 North Chatham Rd", None),
    ("Sewer Main, 284 West St, Bristol, CT", None),
    ("700 S. Caroline st", None),
    ("Main St 06401", None),
    ("Pump Station, Glen Drive", "Pump Station, Glen Drive"),
    ("SSO #005", "SSO #005"),
    ("CSO 006", "CSO 006"),
    ("cloth filter", "cloth filter"),
])
def test_place_names_never_carry_a_street_address(name, want):
    assert P.safe_place_name(name) == want


# ---------------------------------------------------------------- coordinates and places

@pytest.mark.parametrize("lat,lon,why", [
    (0, 0, "at (0, 0)"), (-73.0, 41.3, "latitude and longitude swapped"), (41.3, 73.0, "longitude without its minus sign"),
    (42.5, -71.0, "outside CT"), (41.3, -73.0, None), (None, -73.0, "no coordinates"),
])
def test_coordinate_quality(lat, lon, why):
    assert P.coord_problem(lat, lon, "CT", CT) == why


def test_reports_within_50_m_are_one_place_and_80_m_apart_are_two():
    lat, lon = 41.3, -73.0
    d = 30 / 111_320
    groups = P.cluster_points([(lat, lon, "a"), (lat, lon, "b"), (lat + d, lon, "c"), (lat + 2.7 * d, lon, "d")])
    assert sorted(len(g) for g in groups) == [1, 3]
    assert groups[0][0][:2] == (lat, lon)                 # the most reported point leads


def test_places_drop_duplicates_operatorless_private_and_centroids():
    evs = [ev(1, 41.30, -73.00), ev(2, 41.30, -73.00), ev(3, 41.31, -73.01, raw={"BYPASS_LOCATION": "Basement"}),
           ev(4, 41.32, -73.02, duplicate_of="x:1"), ev(5, 41.33, -73.03, op=None),
           ev(6, 41.40, -73.10, op="ct-ansonia"), ev(7, 41.40, -73.10, op="ct-derby"), ev(8, 41.40, -73.10, op="ct-shelton"),
           ev(9, None, None), ev(10, 42.6, -71.0)]
    places, drops, unlocated = P.build_places(evs, outlines=CT, key=KEY, by_id=BY_ID)
    assert [(p["discharger_id"], p["report_count"]) for p in places] == [("ct-ansonia", 2)]
    assert drops["private property or building backup"] == 1
    assert drops["a copy of another source's report (duplicate_of)"] == 1
    assert drops["no operator named"] == 1
    assert drops["point shared by 3 or more operators (a town or county centroid)"] == 3
    assert drops["point outside the report's state"] == 1
    assert {e["event_id"] for e in unlocated} == {"ct-deep-archive:r9", "ct-deep-archive:r10"}
    p = places[0]
    assert p["npdes_permit"] == "CT0100013" and p["state"] == "CT" and p["permittee"] == "Ansonia WPCA"
    assert p["event_ids"][0] == "ct-deep-archive:r2"       # the latest first
    assert p["overflow_count"] == 2 and p["coord_source"] == "source"
    assert p["first_report_at"] < p["last_report_at"]


def test_reached_water_yes_no_unknown():
    assert P.reached(ev(1, 41.3, -73.0, raw={"REACH_WATER_BODY": "No"})) == "no"
    assert P.reached(ev(1, 41.3, -73.0, raw={"REACH_WATER_BODY": "Yes"})) == "yes"
    assert P.reached(ev(1, 41.3, -73.0, raw={"row": {"surfaceWater": "Yes"}})) == "yes"
    assert P.reached(ev(1, 41.3, -73.0)) == "unknown"


# ---------------------------------------------------------------- supersede, confirm, kind, confidence

def place(**kw):
    base = {"id": "rep-x", "discharger_id": "ct-ansonia", "npdes_permits": ["CT0100013"], "lat": 41.3, "lon": -73.0,
            "outfall_ids": [], "event_types": {"sso": 2}, "overflow_count": 2, "report_count": 2,
            "coord_source": "source", "coord_sources": {"source": 2}}
    return {**base, **kw}


def test_an_official_outfall_of_the_same_operator_within_100_m_supersedes():
    near = 80 / 111_320
    reg = [{"npdes_permit": "CT0100013", "outfall": "002", "lat": 41.3 + near, "lon": -73.0, "outfall_kind": "plant",
            "_file": "data/outfalls-plants-us.json"},
           {"npdes_permit": "CT0999999", "outfall": "001", "lat": 41.3, "lon": -73.0, "_file": "data/outfalls-new-england.json"}]
    a, b = place(), place(id="rep-y", lat=41.31)
    P.classify([a, b], reg, [])
    assert a["record_status"] == "superseded" and a["superseded_by"]["outfall"] == "002"
    assert b["record_status"] == "provisional" and b["superseded_by"] is None


def test_a_state_layer_outfall_supersedes_with_a_pointer():
    lay = [{"npdes_permit": "CT0100013", "outfall": "007", "lat": 41.3, "lon": -73.0, "_file": "data/build/x.json"}]
    a = place(event_types={"cso": 3})
    P.classify([a], [], lay)
    assert a["record_status"] == "superseded" and a["superseded_by"]["file"] == "data/build/x.json"


def test_an_outfall_layer_point_is_a_cso_and_a_stand_in_never_is():
    a = place(coord_source="outfall_layer", event_types={"blended": 2})
    b = place(id="b", event_types={"cso": 3}, outfall_ids=["145"], cso_outfall_overflows={"145": 3}, stand_in=True)
    P.classify([a, b], [], [])
    assert a["outfall_kind"] == "cso" and b["outfall_kind"] == "reported"


def test_a_cso_outfall_the_registry_lacks_named_in_two_overflows_is_kind_cso():
    reg = [{"npdes_permit": "CT0100013", "outfall": "001", "lat": 41.5, "lon": -73.0, "_file": "data/outfalls-new-england.json"}]
    a = place(event_types={"cso": 2}, outfall_ids=["145"])
    b = place(id="rep-b", event_types={"cso": 2}, outfall_ids=["001"])
    c = place(id="rep-c", event_types={"cso": 1}, outfall_ids=["146"], overflow_count=1, report_count=1)
    d = place(id="rep-d", event_types={"sso": 2}, outfall_ids=["147"])
    P.classify([a, b, c, d], reg, [])
    assert [x["outfall_kind"] for x in (a, b, c, d)] == ["cso", "reported", "reported", "reported"]
    assert a["coords_from"] == "report" and a["outfall"] == a["id"]


def test_confidence():
    a, b, c = place(), place(id="b", overflow_count=1, report_count=1), place(id="c", coord_sources={"geocode": 2})
    d = place(id="d", stand_in=True)
    P.classify([a, b, c, d], [], [])
    assert [x["confidence"] for x in (a, b, c, d)] == ["high", "medium", "medium", "low"]


def test_registry_rows_never_include_this_builders_own_rows():
    rows = [{"npdes_permit": "CT1", "lat": 1, "lon": 2, "outfall_kind": "cso"},
            {"npdes_permit": "CT1", "lat": 1, "lon": 2, "outfall_kind": "reported", "source_id": P.SOURCE_ID},
            {"npdes_permit": "CT1", "lat": 1, "lon": 2, "outfall_kind": "cso", "coords_from": "report"},
            {"npdes_permit": "CT1", "lat": None, "lon": 2}]
    assert len(P.registry_rows(rows)) == 1


def test_first_seen_and_id_are_kept_across_runs():
    prev = {"ct-ansonia": [{"id": "rep-old", "lat": 41.3002, "lon": -73.0, "first_seen": "2026-11-01T00:00:00Z"}]}
    a, b = place(id="rep-new"), place(id="rep-far", lat=41.4)
    P.carry_over([a, b], prev, "2026-11-03T00:00:00Z")
    assert (a["id"], a["first_seen"]) == ("rep-old", "2026-11-01T00:00:00Z")
    assert (b["id"], b["first_seen"]) == ("rep-far", "2026-11-03T00:00:00Z")


# ---------------------------------------------------------------- the water (cached answers, no network)

class NoNet:
    budget = P.Budget(0, 0)
    counts = Counter()

    def get_json(self, *a, **k):
        return None, "budget"


def hydro_with(cache):
    c = {"hydro": {}, "flowline": {}, "waterbody": {}, "dm": {}, **cache}
    return P.Hydro(NoNet(), c)


def test_unnamed_flowline_walks_downstream_to_the_first_named_water():
    h = hydro_with({
        "hydro": {"41.30000,-73.00000": {"comid": 1, "via": "hydrolocation", "measure": 50.0, "snap": [-73.0, 41.3],
                                         "snap_m": 12, "fetched_at": "2026-11-03T00:00:00Z"}},
        "flowline": {"1": {"comid": 1, "gnis_name": None, "lengthkm": 2.0, "hydroseq": 30},
                     "2": {"comid": 2, "gnis_name": None, "lengthkm": 1.5, "hydroseq": 20},
                     "3": {"comid": 3, "gnis_name": "Naugatuck River", "gnis_id": "123", "lengthkm": 4, "hydroseq": 10}},
        "dm": {"1": [{"comid": 3, "start": [-73.1, 41.2]}, {"comid": 1, "start": [-73.0, 41.3]},
                     {"comid": 2, "start": [-73.05, 41.25]}]}})
    w = h.water_at(41.3, -73.0)
    assert w["status"] == "done" and w["relation"] == "unnamed tributary to" and w["name"] == "Naugatuck River"
    assert w["downstream_km"] == 2.5 and w["named_comid"] == 3 and w["at"] == [-73.1, 41.2]


def test_artificial_path_takes_the_waterbody_name_and_a_spent_budget_is_pending():
    h = hydro_with({
        "hydro": {"41.30000,-73.00000": {"comid": 1, "via": "position", "snap": [-73.0, 41.3], "snap_m": 5,
                                         "fetched_at": "2026-11-03T00:00:00Z"}},
        "flowline": {"1": {"comid": 1, "gnis_name": None, "wbareacomid": 9, "ftype": "ArtificialPath"}},
        "waterbody": {"9": {"comid": 9, "gnis_name": "Long Island Sound", "gnis_id": "77"}}})
    w = h.water_at(41.3, -73.0)
    assert (w["relation"], w["name"], w["named_what"]) == ("on", "Long Island Sound", "waterbody")
    assert h.water_at(41.5, -73.0)["status"] == "pending"


def test_names_compare_across_spellings():
    assert P.name_in_text("Twomile Creek", "2 Mile Creek")
    assert P.name_in_text("Connecticut River", "CONNECTICUT R.")
    assert not P.name_in_text("Mill Brook", "Mill River")


def test_the_reports_water_is_never_overwritten_by_the_traced_one():
    class M(P.WaterMatcher):
        def __init__(self):
            pass

        def match(self, *a):
            return "niagara-river-ny", "name"

        def report_slugs(self, p):
            return list(p.get("reports_water_slugs") or [])

    w = {"status": "done", "relation": "on", "name": "Niagara River", "comid": 5, "named_comid": 5, "snap_m": 40,
         "via": "position"}
    a = place(reports_water_slugs=["scajaquada-creek-ny"], reports_water_text=["Scajaquada Creek"])
    P.water_fields(a, w, M())
    assert a["water_slugs"] == ["scajaquada-creek-ny"] and a["water"]["check"] == "disagree"
    b = place(reports_water_slugs=[], reports_water_text=["2 Mile Creek"])
    P.water_fields(b, w, M())
    assert b["water_slugs"] == [] and b["water"]["check"] == "unclear"
    c = place(reports_water_slugs=[], reports_water_text=[])
    P.water_fields(c, w, M())
    assert c["water_slugs"] == ["niagara-river-ny"] and c["water_match"] == "hydrolocation"
    d = place(reports_water_slugs=[], reports_water_text=[])
    P.water_fields(d, {**w, "snap_m": 3000}, M())
    assert d["water_slugs"] == [] and "candidate" in d["water"]["candidate_only"]


def test_public_rows_carry_the_label_and_no_address(tmp_path):
    a = place(reports_water_slugs=[], reports_water_text=[], sources={"ct-deep": 2}, reached_water="yes",
              record_status="provisional", water={"status": "pending", "why": "budget"},
              place_names=["Pump Station, Glen Drive"])
    r = P.public_row(a)
    assert r["label"] == P.PUBLIC_LABEL and r["on_map"] is True and "pending" not in r["label"]
    assert "water not traced yet" in r["method"]
    no = P.public_row({**a, "reached_water": "no"})
    assert no["on_map"] is False


def test_a_stale_lock_is_ignored(tmp_path, monkeypatch):
    lock = tmp_path / "x.lock"
    monkeypatch.setattr(P, "LOCK_PATH", lock)
    lock.write_text("999999")
    assert P.lock_holder() is None


# ---------------------------------------------------------------- reports without a point (build/report_geolocate.py)

from build import report_geolocate as RG  # noqa: E402


def loc_ev(name=None, et="sso", **raw):
    return {"outfall_name": name, "raw": raw, "event_type": et, "waterbody_text": None}


@pytest.mark.parametrize("text,kind,want", [
    ("Iranistan Ave, Bridgeport, CT", "street", {"street": "Iranistan Ave", "town": "Bridgeport"}),
    ("North Hilton and Edmonson Ave", "intersection", {"a": "North Hilton", "b": "Edmonson Ave"}),
    ("Manhole, SANFORD ST @ BELLEVUE ST", "intersection", {"a": "SANFORD ST", "b": "BELLEVUE ST"}),
    ("Manhole, intersection of Newfield st and Rose circle.", "intersection", {"a": "Newfield st", "b": "Rose circle"}),
    ("Pump Station, Glen Drive", "pump_station", {"street": "Glen Drive"}),
    ("Pump Station, 534 Thresher Ave, Groton, CT", "address", {"query": "534 Thresher Ave, Groton, CT"}),
    ("CSO 009 - 152 Main St.", "address", {"street_address": "152 Main St."}),
    ("Main Plant", "plant", {}),
    ("Manhole 20 on Darrows Lane", "street", {"street": "Darrows Lane"}),
    ("Manhole is in the center of Melrose at Westgate, SSO #002", "unknown", {}),
    ("Address", "none", {}),
])
def test_location_rules(text, kind, want):
    p = RG.parse_location(loc_ev(text), "CT")
    assert p["kind"] == kind
    for k, v in want.items():
        assert p[k] == v


def test_address_fields_come_first_and_placeholders_are_not_addresses():
    assert RG.parse_location(loc_ev("Sewer Main", Address="60 Eastridge Dr, Waterbury, CT"), "CT") == \
        {"kind": "address", "query": "60 Eastridge Dr, Waterbury, CT"}
    ny = loc_ev(None, row={"geoaddress": "Please see DEP's website below", "streetNumber": "x"})
    assert RG.parse_location(ny, "NY")["kind"] == "none"
    assert RG.oneline_parts("1014 Canterbury Lane, MD 20646", "MD") == ("1014 Canterbury Lane", "", "MD", "20646")


class FakeGeo:
    def __init__(self, census=None, box=(41.0, -73.5, 41.5, -73.0), elements=(), facility=None):
        self._census, self._box, self._els, self._fac = census, box, list(elements), facility

    def census(self, q):
        return self._census

    def town_box(self, town, state):
        return list(self._box) if self._box else False

    def overpass(self, box, names, facilities):
        return {"elements": self._els}

    def echo_facility(self, permit):
        return self._fac


def way(i, name, pts, nodes=None):
    return {"type": "way", "id": i, "tags": {"highway": "residential", "name": name},
            "geometry": [{"lat": a, "lon": b} for a, b in pts], "nodes": nodes or list(range(i * 100, i * 100 + len(pts)))}


def test_census_address_match_is_medium_and_another_state_is_rejected():
    m = [{"coordinates": {"x": -73.06, "y": 41.54}, "addressComponents": {"city": "WATERBURY", "state": "CT"}}]
    r = RG.resolve({"kind": "address", "query": "60 Eastridge Dr, Waterbury, CT"}, "Waterbury", "CT", FakeGeo(m), None)
    assert (r["status"], r["step"], r["confidence"], r["precision_m"]) == ("placed", "a", "medium", 50)
    m2 = [{"coordinates": {"x": -72.0, "y": 42.0}, "addressComponents": {"city": "X", "state": "MA"}}]
    assert RG.resolve({"kind": "address", "query": "1 A St, Y, CT"}, "Y", "CT", FakeGeo(m2), None)["status"] == "not_placed"
    assert RG.resolve({"kind": "address", "query": "1 A St, Y, CT"}, "Y", "CT", FakeGeo([]), None)["status"] == "not_placed"


def test_junction_of_two_named_streets_and_never_a_town_centroid():
    a = way(1, "Capitol Avenue", [(41.1, -73.2), (41.1, -73.1)], nodes=[1, 2])
    b = way(2, "Park Terrace", [(41.0, -73.1), (41.1, -73.1)], nodes=[3, 2])
    r = RG.resolve({"kind": "intersection", "a": "Capitol Ave", "b": "Park Ter"}, "Hartford", "CT",
                   FakeGeo(elements=[a, b]), None)
    assert r["status"] == "placed" and (round(r["lat"], 3), round(r["lon"], 3)) == (41.1, -73.1) and r["step"] == "b"
    r = RG.resolve({"kind": "intersection", "a": "Capitol Ave", "b": "Elm St"}, "Hartford", "CT", FakeGeo(elements=[a]), None)
    assert r["status"] == "not_placed"
    assert RG.resolve({"kind": "street", "street": "Main St"}, None, "CT", FakeGeo(), None)["status"] == "not_placed"
    assert RG.resolve({"kind": "street", "street": "Main St"}, "Nowhere", "CT", FakeGeo(box=None), None)["status"] == \
        "not_placed"


def test_street_only_is_low_with_a_radius_and_a_long_street_is_not_placed():
    short = way(1, "River Road", [(41.10, -73.20), (41.10, -73.19)])
    r = RG.resolve({"kind": "street", "street": "River Rd"}, "Shelton", "CT", FakeGeo(elements=[short]), None)
    assert r["status"] == "placed" and r["confidence"] == "low" and 300 < r["precision_m"] < 500 and r["step"] == "d"
    long_ = way(2, "Post Road", [(41.10, -73.30), (41.10, -73.20)])
    assert RG.resolve({"kind": "street", "street": "Post Rd"}, "Darien", "CT", FakeGeo(elements=[long_]),
                      None)["status"] == "not_placed"


def test_pump_station_on_the_named_street_then_the_plant_from_epa():
    st = way(1, "Glen Drive", [(41.10, -73.20), (41.10, -73.19)])
    ps = {"type": "node", "id": 5, "lat": 41.1005, "lon": -73.195, "tags": {"man_made": "pumping_station"}}
    far = {"type": "node", "id": 6, "lat": 41.2, "lon": -73.0, "tags": {"man_made": "pumping_station"}}
    r = RG.resolve({"kind": "pump_station", "street": "Glen Drive", "name": "Glen Drive"}, "Ansonia", "CT",
                   FakeGeo(elements=[st, ps, far]), None)
    assert r["status"] == "placed" and r["step"] == "c" and r["lat"] == 41.1005
    r = RG.resolve({"kind": "plant"}, "Ansonia", "CT", FakeGeo(elements=[], facility={"lat": 41.3, "lon": -73.0}),
                   "CT0100013")
    assert r["status"] == "placed" and "EPA FRS" in r["detail"] and r["confidence"] == "medium"


class FakeJudge:
    stopped = None
    jev = "typesafe/jev-test"

    def __init__(self, kind=None, conf=0.9, query=None, noul=0.1):
        self.kind, self.conf, self.query, self.noul = kind, conf, query, noul

    def decide(self, version, state, questions):
        if "private" in questions:
            return {"answers": {"private": {"type": "noul", "noul": self.noul}}}
        return {"answers": {"kind": {"type": "choice", "choice": self.kind, "confidence": self.conf}}}

    def write(self, *a, **k):
        return self.query


def test_model_reads_only_what_rules_left_and_never_gives_coordinates():
    q = {"kind": "intersection", "street1": "Melrose", "street2": "Westgate", "facility": None, "address": None,
         "town": "Buffalo"}
    p, note = RG.model_parse(FakeJudge("intersection", 0.9, q), "Manhole is in the center of Melrose at Westgate",
                             "Buffalo", "NY")
    assert p == {"kind": "intersection", "a": "Melrose", "b": "Westgate", "town": "Buffalo"} and "luna" in note
    p, note = RG.model_parse(FakeJudge("intersection", 0.5, q), "x", "Buffalo", "NY")
    assert p is None and "unsure" in note
    p, _ = RG.model_parse(FakeJudge("none", 0.95), "Fairfield, CT", "Fairfield", "CT")
    assert p == {"kind": "none"}


def test_model_privacy_opinion_only_excludes():
    events = {"e1": {"event_id": "e1", "outfall_name": "Manhole on the front lawn of the house at Elm", "raw": {}}}
    places = [{"id": "a", "_all_event_ids": ["e1"]}, {"id": "b", "_all_event_ids": []}]
    kept, why = RG.privacy_second_opinion(places, events, FakeJudge(noul=0.9))
    assert [p["id"] for p in kept] == ["b"] and why["excluded by the model's privacy opinion"] == 1
    kept, _ = RG.privacy_second_opinion(places, events, FakeJudge(noul=0.2))
    assert len(kept) == 2


def test_judge_caches_answers_and_stops_at_the_cap(tmp_path):
    from build import llm_judge as LJ
    j = LJ.Judge(cap_usd=0.00002, cache_path=tmp_path / "c.json", log_path=tmp_path / "l.jsonl")
    calls = []

    def post(url, body, timeout=60):
        calls.append(body)
        return {"answers": {"x": {"type": "noul", "noul": 0.3}}, "usage": {"input_tokens": 10, "cost": 0.000015}}

    j._post = post
    a = j.decide("v1", {"t": "a"}, {"x": {"type": "noul", "instructions": "?"}})
    b = j.decide("v1", {"t": "a"}, {"x": {"type": "noul", "instructions": "?"}})
    assert a == b and len(calls) == 1 and j.calls["cached"] == 1
    j.decide("v1", {"t": "b"}, {"x": {"type": "noul", "instructions": "?"}})
    with pytest.raises(LJ.SpendCap):
        j.decide("v1", {"t": "c"}, {"x": {"type": "noul", "instructions": "?"}})
    j.save()
    assert len(LJ.Judge(cache_path=tmp_path / "c.json", log_path=tmp_path / "l.jsonl").cache) == 2


class FakeResp:
    def __init__(self, code, headers=None, body=None):
        self.status_code, self.headers, self._body = code, headers or {}, body

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, responses):
        self.responses, self.calls = list(responses), 0

    def get(self, url, params=None, timeout=None):
        self.calls += 1
        return self.responses.pop(0)


def test_a_spent_hourly_allowance_stops_asking_and_is_never_cached():
    net = P.Net(P.Budget(60, 100), pause=0)
    s = FakeSession([FakeResp(429, {"Retry-After": "335"})])
    net.session = lambda: s
    assert net.get_json("nldi-position", "https://api.water.usgs.gov/x", {}) == (None, "rate limited")
    assert net.get_json("nldi-position", "https://api.water.usgs.gov/y", {}) == (None, "rate limited")
    assert s.calls == 1 and net.rate_limited
    h = P.Hydro(net, {"hydro": {}, "flowline": {}, "waterbody": {}, "dm": {}})
    assert h.locate(41.3, -73.0) is None and h.cache["hydro"] == {}
    assert P.transient("HTTP 502") and P.transient("ReadTimeout") and not P.transient("no flowline")


def test_an_offline_run_never_writes_the_cache(tmp_path):
    net = P.Net(P.Budget(60, 100), offline=True)
    h = P.Hydro(net, {"hydro": {}, "flowline": {}, "waterbody": {}, "dm": {}})
    assert h.locate(41.3, -73.0) is None and h.cache["hydro"] == {}
    h.save(tmp_path / "c.json")
    assert not (tmp_path / "c.json").exists()


# ---------------------------------------------------------------- review 2026-11-03 (SOL, interim findings)

@pytest.mark.parametrize("name", ["Manhole at 399 Tremont, SSO #004", "John Doe", "Sewer Main, bottom of Damien Road at house #25",
                                  "Manhole, Private lands West of Hillcrest Ave"])
def test_no_house_number_person_or_private_place_in_a_name(name):
    assert P.safe_place_name(name) is None


def test_two_places_never_take_the_same_previous_id():
    ps = [place(id="a", lat=41.3), place(id="b", lat=41.3006)]
    P.carry_over(ps, {"ct-ansonia": [{"id": "old", "lat": 41.3003, "lon": -73.0, "first_seen": "2025-01-01"}]},
                 "2026-11-03T00:00:00Z")
    assert len({p["id"] for p in ps}) == 2 and sorted(p["first_seen"] for p in ps)[0] == "2025-01-01"


def test_one_cso_report_and_one_sso_report_do_not_make_a_cso_outfall():
    p = place(event_types={"cso": 1, "sso": 1}, outfall_ids=["007"], cso_outfall_overflows={"007": 1})
    P.classify([p], [], [])
    assert p["outfall_kind"] == "reported"


def test_an_error_body_or_broken_json_from_a_model_is_never_cached(tmp_path):
    from build import llm_judge as LJ
    j = LJ.Judge(cache_path=tmp_path / "c.json", log_path=tmp_path / "l.jsonl")
    j._post = lambda *a, **k: {"error": {"message": "temporary service error"}}
    assert j.decide("v", {}, {}) is None and j.cache == {}
    j._post = lambda *a, **k: {"choices": [{"message": {"content": "broken JSON"}}], "usage": {"cost": 0.01}}
    assert j.write("v", "s", "u", {}) is None and j.cache == {}


def test_a_failed_name_lookup_is_pending_never_an_unnamed_stream():
    class FailNet(NoNet):
        budget = P.Budget(60, 100)

        def get_json(self, *a, **k):
            return None, "HTTP 503"

    h = P.Hydro(FailNet(), {"hydro": {"41.30000,-73.00000": {"comid": 1, "via": "position", "snap": [-73.0, 41.3],
                                                              "snap_m": 5, "fetched_at": "2026-11-03T00:00:00Z"}},
                            "flowline": {}, "waterbody": {}, "dm": {}})
    w = h.water_at(41.3, -73.0)
    assert w["status"] == "pending" and h.cache["flowline"] == {}


def test_caches_are_merged_with_what_another_run_wrote(tmp_path):
    path = tmp_path / "c.json"
    path.write_text('{"hydro": {"a": {"comid": 1}}, "dm": {}}')
    P.save_merged(path, {"hydro": {"b": {"comid": 2}}, "dm": {"9": []}})
    import json as _j
    d = _j.loads(path.read_text())
    assert set(d["hydro"]) == {"a", "b"} and d["dm"] == {"9": []}


def test_model_extractions_must_be_in_the_text():
    q = {"kind": "intersection", "street1": "Main Street", "street2": "Elm Street", "facility": None, "address": None,
         "town": "Springfield"}
    p, note = RG.model_parse(FakeJudge("intersection", 0.9, q), "Manhole at Melrose and Westgate", "Buffalo", "NY")
    assert p is None and "not in the text" in note
    assert RG.grounded("Main St", "manhole on MAIN STREET near the bridge")


def test_a_census_match_in_another_zip_or_town_is_not_placed_far_from_the_operator():
    m = [{"coordinates": {"x": -73.06, "y": 41.54}, "addressComponents": {"city": "OTHERTOWN", "state": "CT",
                                                                          "zip": "06999"}, "match_type": "Exact"}]
    r = RG.resolve({"kind": "address", "query": "60 Eastridge Dr, Waterbury, CT 06708"}, "Waterbury", "CT",
                   FakeGeo(m), None)
    assert r["status"] == "not_placed" and "ZIP" in r["why"]
    r = RG.resolve({"kind": "address", "query": "60 Eastridge Dr, Waterbury, CT"}, "Waterbury", "CT", FakeGeo(m), None)
    assert r["status"] == "placed" and r["town_mismatch"]


def test_the_lock_is_taken_once(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "LOCK_PATH", tmp_path / "x.lock")
    assert P.acquire_lock() is True
    (tmp_path / "x.lock").write_text(str(os.getppid()))   # a live process holds it
    assert P.acquire_lock() is False
    (tmp_path / "x.lock").write_text("999999")       # a dead run's lock is taken over
    assert P.acquire_lock() is True


def test_the_shared_hourly_allowance_keeps_a_reserve():
    net = P.Net(P.Budget(60, 100), pause=0)
    s = FakeSession([FakeResp(200, {"x-ratelimit-remaining": "120"}, {"features": []})])
    net.session = lambda: s
    assert net.get_json("nldi-position", "https://api.water.usgs.gov/x", {}) == ({"features": []}, None)
    assert net.get_json("nldi-position", "https://api.water.usgs.gov/y", {}) == (None, "rate limited")


def test_a_geolocated_place_beside_a_reported_point_joins_it():
    a = place(event_types={"sso": 2}, sources={"ct-deep-archive": 2}, coord_sources={"source": 2},
              reached_counts={"yes": 2}, outfall_ids=[], place_names=[], reports_water_text=[], reports_water_slugs=[],
              first_report_at="2021-01-01T00:00:00Z", last_report_at="2021-02-01T00:00:00Z", _all_event_ids=["a1"])
    g = {**a, "id": "g", "lat": 41.3002, "geolocation": {"step": "a"}, "report_count": 1, "overflow_count": 1,
         "sources": {"ct-deep": 1}, "coord_sources": {"geocode": 1}, "reached_counts": {"unknown": 1},
         "first_report_at": "2026-01-01T00:00:00Z", "last_report_at": "2026-01-01T00:00:00Z", "_all_event_ids": ["g1"]}
    far = {**g, "id": "far", "lat": 41.4}
    places = [a]
    assert P.join_places(places, [g, far]) == 1
    assert [p["id"] for p in places] == ["rep-x", "far"] and places[0]["report_count"] == 3
    assert places[0]["sources"] == {"ct-deep-archive": 2, "ct-deep": 1} and places[0]["last_report_at"].startswith("2026")


def test_geolocate_runs_offline_with_and_without_towns(tmp_path, monkeypatch):
    import types
    monkeypatch.setattr(RG, "GEO_CACHE", tmp_path / "geo.json")
    monkeypatch.setattr(P, "registry_rows", lambda rows=None: [])
    evs = [{**ev(i, None, None, op=op, raw=raw), "_op": op, "_state": "CT", "outfall_name": name}
           for i, (op, raw, name) in enumerate([
               ("ct-ansonia", {"Address": "60 Eastridge Dr, Waterbury, CT"}, None),
               ("ct-derby", {}, "Manhole, Elm St and Main St"),             # no town anywhere
               ("ct-derby", {}, "Gazo CSO"),
               ("ct-shelton", {"Municipality": "Shelton"}, "River Road")])]
    args = types.SimpleNamespace(offline=True, geo_budget_s=5, judge=None)
    places, stats = RG.geolocate(evs, args, key=KEY, by_id=BY_ID, anchors={})
    assert places == [] and stats["reports_in"] == 4
    assert stats["by_outcome"]["pending (request budget)"] >= 1
    assert not (tmp_path / "geo.json").exists()            # an offline run writes no cache
