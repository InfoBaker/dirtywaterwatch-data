"""California's go-live gates (2026-11-06): the Pacific Ocean under the open-ocean shoreline rule (data/rules.json
reach.shoreline.oceans, states ["CA"]) and San Francisco Bay under the lake model as a bay (reach.shoreline.lakes, kinds
["bay"], states ["CA"]), and the deep ocean outfalls tied to the ocean though they end beyond snap_km
(ocean_tie_offshore_km). The records are openboatlaunch's as its water pages publish them (pacific-ocean-ca: a bay with
no wikidata; san-francisco-bay-ca: a bay, 149,773 acres, Q232264). Geometry is synthetic; no network.
Run from pipeline/: python -m pytest tests/test_ca_shoreline.py -q
"""
from __future__ import annotations

import copy
import hashlib
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from shapely import segmentize  # noqa: E402
from shapely.geometry import box, mapping  # noqa: E402

from build import reaches as R  # noqa: E402
from build import shoreline as SH  # noqa: E402
from build import status as S  # noqa: E402
from common import event  # noqa: E402
from export import build as X  # noqa: E402
from ingest import outfall_waters as OW  # noqa: E402
from ingest import waters_from_nhd as N  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RULES = json.loads((ROOT / "data" / "rules.json").read_text())
SHORE = SH.rule(RULES)
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
H = timedelta(hours=1)

# a coast running north-south at lon -122.50 (land to the east); behind it a bay (-122.49 to -122.35, lat 37.60 to
# 37.95) that opens to the sea through a strait 1.6 km wide (lat 37.802 to 37.8164), like the Golden Gate; the state's
# waters (the TIGER polygon less the land) reach 5.3 km out, to lon -122.56
BAY = box(-122.49, 37.60, -122.35, 37.95)
STRAIT = box(-122.501, 37.802, -122.489, 37.8164)
CA_LAND = box(-123.5, 36.5, -121.0, 38.8).difference(box(-123.5, 36.5, -122.50, 38.8)).difference(BAY).difference(STRAIT)
CA_TIGER = box(-122.56, 36.5, -121.0, 38.8)
LAND = {"CA": CA_LAND}
BAY_OUTLINE = segmentize(BAY, 0.002)


def rec(slug, name, kind, state="CA", **extra):
    return slug, {"slug": slug, "name": name, "kind": kind, "state": state, "towns": [], "bbox": None, **extra}


WATERS = dict([
    rec("pacific-ocean-ca", "Pacific Ocean", "bay"),
    rec("san-francisco-bay-ca", "San Francisco Bay", "bay", wikidata="Q232264", area_km2=606.1,
        bbox=list(BAY.bounds), geometry=mapping(BAY_OUTLINE)),
    rec("san-francisco-bay-east-bay-ca", "San Francisco Bay-East Bay", "bay"),
    rec("monterey-bay-ca", "Monterey Bay", "bay", area_km2=936.0),
    rec("carquinez-strait-ca", "Carquinez Strait", "sound", wikidata="Q1044843", area_km2=24.9),
    rec("pacific-ocean-wa", "Pacific Ocean", "bay", state="WA"),
    rec("pacific-ocean-or", "Pacific Ocean", "sound", state="OR", area_km2=50000.0),
    rec("san-francisco-bay-fl", "San Francisco Bay", "bay", state="FL", area_km2=606.1),
])


@pytest.fixture(autouse=True)
def _census(monkeypatch):
    monkeypatch.setattr(R, "tiger_states", lambda: {"CA": CA_TIGER})
    R._OCEAN.clear()
    S._GEOM_CACHE.clear()
    yield
    R._OCEAN.clear()
    S._GEOM_CACHE.clear()


# ---------------------------------------------------------------- the rule

def test_the_pacific_ocean_is_an_ocean_entry_for_california_only():
    sh = RULES["reach"]["shoreline"]
    pac = [e for e in sh["oceans"] if e["name"] == "Pacific Ocean"]
    assert len(pac) == 1 and pac[0]["wikidata"] == "Q98" and pac[0]["states"] == ["CA"]
    assert {e["name"]: e["states"] for e in sh["oceans"] if e["name"] != "Pacific Ocean"} == {
        "Atlantic Ocean": ["FL"], "Gulf of America": ["FL"]}                 # Florida's entries are unchanged


def test_openboatlaunchs_pacific_record_for_california_is_the_ocean_and_no_other_states_is():
    assert SH.is_ocean(WATERS["pacific-ocean-ca"], SHORE)                   # by name: the record has no wikidata
    assert SH.is_ocean({**WATERS["pacific-ocean-ca"], "name": "North Pacific Ocean"}, SHORE)
    assert SH.is_ocean({"name": "Ocean", "kind": "sea", "state": "CA", "wikidata": "Q98"}, SHORE)
    assert not SH.is_shoreline(WATERS["pacific-ocean-wa"], SHORE)           # the states guard: CA only
    assert not SH.is_shoreline(WATERS["pacific-ocean-or"], SHORE)
    assert not SH.is_shoreline({"name": "Pacific Ocean", "kind": "stream", "state": "CA"}, SHORE)   # not a sea kind
    assert not SH.is_shoreline(WATERS["monterey-bay-ca"], SHORE)            # a bay on the coast keeps its handling
    assert not SH.is_shoreline(WATERS["carquinez-strait-ca"], SHORE)


def test_san_francisco_bay_is_a_bay_under_the_lake_model_by_its_wikidata_and_only_in_california():
    sh = RULES["reach"]["shoreline"]
    e = [x for x in sh["lakes"] if x["name"] == "San Francisco Bay"]
    assert len(e) == 1 and e[0]["wikidata"] == "Q232264" and e[0]["kinds"] == ["bay"] and e[0]["states"] == ["CA"]
    for word in ("owner", "data/", "docs/", "safe."):
        assert word not in e[0]["rationale"]
    assert "not shown as clean" in e[0]["rationale"] and "20 kilometres each way" in e[0]["rationale"]
    hit = SH.shoreline_entry(WATERS["san-francisco-bay-ca"], SHORE)
    assert hit["name"] == "San Francisco Bay" and hit.get("bay") is True and not hit.get("ocean")
    nowd = {**WATERS["san-francisco-bay-ca"], "wikidata": None}
    assert SH.shoreline_entry(nowd, SHORE)["name"] == "San Francisco Bay"        # by name at its area
    assert not SH.is_shoreline({**nowd, "area_km2": 3.0}, SHORE)                 # a small namesake is not
    assert not SH.is_shoreline(WATERS["san-francisco-bay-east-bay-ca"], SHORE)   # a named piece keeps its handling
    assert not SH.is_shoreline(WATERS["san-francisco-bay-fl"], SHORE)            # the states guard
    assert SH.shoreline_slugs(WATERS, SHORE) == {"pacific-ocean-ca", "san-francisco-bay-ca"}


def test_the_lake_entries_still_match_lakes_only_unless_they_name_a_kind():
    erie = {"name": "Lake Erie", "kind": "lake", "wikidata": "Q5492", "area_km2": 26000, "state": "PA"}
    hit = SH.shoreline_entry(erie, SHORE)
    assert hit["name"] == "Lake Erie" and "bay" not in hit and "sound" not in hit
    assert not SH.is_shoreline({**erie, "kind": "bay"}, SHORE)       # a bay record carrying a Great Lake's id is not
    assert SH.shoreline_entry({"name": "Lake St. Clair", "kind": "lake", "wikidata": "Q736707"}, SHORE)["name"] == "Lake St. Clair"
    assert not SH.is_shoreline({**WATERS["san-francisco-bay-ca"], "kind": "lake", "state": "MI"}, SHORE)


def test_the_ocean_text_names_the_open_ocean_not_only_floridas_waters():
    sh = RULES["reach"]["shoreline"]
    assert "Pacific" in sh["ocean_rationale"] and "never as a colour over the ocean" in sh["ocean_rationale"]
    assert "lagoons and bays behind them" in sh["ocean_rationale"]
    assert sh["ocean_tie_offshore_km"] == pytest.approx(22.2)


# ---------------------------------------------------------------- the walks

def _ocean(lat=37.76, lon=-122.515, open_m=None):
    shore = SHORE if open_m is None else {**SHORE, "ocean_open_m": open_m}
    c = {"key": "pt-1", "permit": None, "outfall": None, "water_slug": "pacific-ocean-ca", "lat": lat, "lon": lon,
         "sources": ["event-point"], "state": "CA", "model": "shoreline"}
    return R.shoreline_record(c, WATERS, shore, LAND)


def test_a_pacific_report_walks_the_open_coast_across_the_strait_and_not_into_the_bay():
    r = _ocean()
    assert r["error"] is None and r["ocean"] is True and r["outline"] == "census_ocean" and not r.get("bay")
    assert [s["km_end"] for s in r["segments"]] == [pytest.approx(20, abs=0.05)] * 2
    assert r["waters"][0] == "pacific-ocean-ca" and r["states"] == ["CA"]
    lons = [x for s in r["segments"] for x, _ in s["coords"]]
    assert min(lons) > -122.51 and max(lons) < -122.495                    # the open coast, never the bay
    assert "san-francisco-bay-ca" not in r["waters"]
    lats = sorted(s["coords"][-1][1] for s in r["segments"])
    assert lats[0] < 37.802 and lats[1] > 37.8164                           # across the strait's mouth


def test_without_the_opening_the_ocean_walk_would_turn_into_the_bay():
    lons = [x for s in _ocean(open_m=0)["segments"] for x, _ in s["coords"]]
    assert max(lons) >= -122.4901                                           # through the strait to the bay's shore


def _bay(lat=37.75, lon=-122.36, key="pt-b"):
    c = {"key": key, "permit": None, "outfall": None, "water_slug": "san-francisco-bay-ca", "lat": lat, "lon": lon,
         "sources": ["event-point"], "state": "CA", "model": "shoreline"}
    return R.shoreline_record(c, WATERS, SHORE, LAND)


def test_a_bay_report_walks_the_bays_own_shore_each_way_and_is_worded_as_a_bay():
    r = _bay()
    assert r["error"] is None and r["bay"] is True and r["ocean"] is False and r["outline"] == "record"
    assert r["waters"][0] == "san-francisco-bay-ca" and r["river"] == "San Francisco Bay"
    assert [s["km_end"] for s in r["segments"]] == [pytest.approx(20, abs=0.05)] * 2
    a = {"event_id": "e1", "reach": "pt-b", "status": "red", "rule": "ongoing", "short": "s", "hours_since_start": 2}
    feats = X.shore_event_features(a, {**r, "outfall": None}, {}, {})
    seg = [f for f in feats if f["properties"]["feature"] == "segment"]
    label = seg[0]["properties"]["label"]
    assert "San Francisco Bay shore at the reported location" in label and "rest of the bay" in label
    assert "Great Lakes" not in label and "rest of the lake" not in label and "Tides" in label
    props = X.shore_path_props(r)
    assert props["bay"] is True and "ocean" not in props
    assert all("Great Lakes" not in s["label"] and "this lake" not in s["label"] for s in props["stops"])
    lake = X.shore_path_props({**r, "bay": False})
    assert "Great Lakes" in lake["stops"][0]["label"] and "bay" not in lake


# ---------------------------------------------------------------- the status

def _build(records, reaches):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "ca-test.json").write_text(json.dumps({"source_id": "ca-test", "ok": True, "last_ok_at": NOW.isoformat(),
                                                  "meta": {}, "records": records}))
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    saved = S._STATES
    S._STATES = {"CA"}
    try:
        return S.build(now=NOW, write=False, events_dir=tmp, waters=copy.deepcopy(WATERS), outfalls=[], registry={},
                       reaches=copy.deepcopy(reaches), flows=({}, {}), discharger_towns={}, discharger_waters={},
                       rules={**RULES, "live_states": ["CA"]})
    finally:
        S._STATES = saved
        S._SHORE_REACHES.clear()


def _ev(rid, **kw):
    kw.setdefault("event_type", "sso")
    kw.setdefault("status", "ongoing")
    kw.setdefault("started_at", (NOW - 2 * H).isoformat())
    return event(source_id="ca-test", source_record_id=rid, **kw)


def test_a_bay_report_colours_its_stretch_and_the_bay_is_never_filled_whole():
    key = "pt-" + hashlib.sha1(b"ca-test:1").hexdigest()[:12]
    r = {**_bay(key=key), "event_ids": ["ca-test:1"]}
    st, _ = _build([_ev("1", waterbody_text="San Francisco Bay", lat=37.75, lon=-122.36)], {key: r})
    w = st["waters"]["san-francisco-bay-ca"]
    assert w["events"] == ["ca-test:1"] and w["status"] in ("red", "yellow") and w["reaches"] == [key]
    assert w["fill"] is False and w["stretch_model"] == "shoreline" and w["status_basis"] == S.BAY_STATUS_BASIS


def test_a_pacific_and_a_bay_report_with_no_stretch_yet_are_listed_and_never_fill():
    st, _ = _build([_ev("2", waterbody_text="Pacific Ocean", lat=37.76, lon=-122.515),
                    _ev("3", waterbody_text="San Francisco Bay", lat=37.75, lon=-122.36)], {})
    ocean, bay = st["waters"]["pacific-ocean-ca"], st["waters"]["san-francisco-bay-ca"]
    assert ocean["events"] == ["ca-test:2"] and ocean["fill"] is False and ocean["status_basis"] == S.OCEAN_STATUS_BASIS
    assert bay["events"] == ["ca-test:3"] and bay["fill"] is False and bay["status_basis"] == S.BAY_STATUS_BASIS
    monterey = st["waters"].get("monterey-bay-ca") or {}
    assert monterey.get("fill") in (None, False)                         # a bay is never filled in any case


def test_the_names_pass_reads_the_pacific_with_a_record_as_that_water_in_california_only():
    waters = copy.deepcopy(WATERS)
    r = S.Resolver(waters, [], placement_rules={})
    assert N.ocean_record_named(r, "Pacific Ocean", "CA")
    assert not N.ocean_record_named(r, "Pacific Ocean", "WA")


# ---------------------------------------------------------------- the registry's ties

def _matcher():
    return SimpleNamespace(waters=WATERS, states=SimpleNamespace(shapes={"CA": CA_LAND}))


@pytest.mark.parametrize("lat,lon,kept,word", [
    (37.76, -122.53, True, "offshore"),       # 2.6 km out: a stretch can start here
    (37.76, -122.58, True, "no shoreline stretch"),   # 7 km out, like Point Loma's or the Southwest Ocean Outfall's end
    (37.76, -122.80, False, "more than 22.2 km"),      # 26 km out: not taken as this coast's outfall
    (38.2, -122.42, False, "inland"),         # 7 km inland: held as before
])
def test_a_deep_ocean_outfall_is_tied_to_the_ocean_and_an_inland_point_is_still_held(lat, lon, kept, word):
    ok, why = OW.Matcher.ocean_evidence(_matcher(), "pacific-ocean-ca", {"lat": lat, "lon": lon, "state": "CA"})
    assert ok is kept and word in why and "reach.shoreline.oceans" in why
    assert ("held until" in why) is (not kept)
    assert OW.Matcher.ocean_evidence(_matcher(), "san-francisco-bay-ca", {"lat": lat, "lon": lon}) is None


def test_without_the_offshore_limit_a_deep_outfall_is_held_as_before(monkeypatch):
    monkeypatch.setattr(OW.S, "load_rules", lambda *a, **k: {**RULES, "reach": {**RULES["reach"], "shoreline": {
        **RULES["reach"]["shoreline"], "ocean_tie_offshore_km": None}}})
    ok, why = OW.Matcher.ocean_evidence(_matcher(), "pacific-ocean-ca", {"lat": 37.76, "lon": -122.58, "state": "CA"})
    assert ok is False and "more than 5 km" in why
