"""Shoreline stretches on the Great Lakes (decision of 2026-11-04: modelled like rivers, never filled whole):
data/rules.json reach.shoreline, build/shoreline.py (the geometry), build/reaches.py (the candidates and the cached
stretch records), build/status.py (the lake counts the report and is drawn as an outline; the stretch carries the
colour), build/rain_likely.py (a plant's stretch takes no CSO rain caution) and export/build.py (the stretch in
reaches.geojson with its states). Fixtures: a box-shaped "Lake Erie" whose south shore is Pennsylvania's land and,
east of -79.76, New York's; its north and side edges lie away from land (a Canadian shore, a state cut).
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import copy
import json
import math
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from shapely.geometry import Point, box, shape  # noqa: E402

from build import rain_likely as RL  # noqa: E402
from build import reaches as R  # noqa: E402
from build import shoreline as SH  # noqa: E402
from build import status as S  # noqa: E402
from common import event  # noqa: E402
from export import build as X  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
H = timedelta(hours=1)
PERMIT = "PA0026301"


def _lake_polygon():
    """A box lake: the south shore (lat 42.0) in 1 km steps from -80.5 to -79.5, then the east side, the north
    edge and the west side as single long edges (away from land)."""
    n = 82
    south = [[round(-80.5 + i / n, 6), 42.0] for i in range(n + 1)]
    return {"type": "Polygon", "coordinates": [south + [[-79.5, 42.5], [-80.5, 42.5], [-80.5, 42.0]]]}


LAKE = _lake_polygon()
PA_LAND = box(-81.0, 41.5, -79.76, 42.0)
NY_LAND = box(-79.76, 41.5, -79.0, 42.0)
LAND = {"PA": PA_LAND, "NY": NY_LAND}
RULES_FILE = json.loads((ROOT / "data" / "rules.json").read_text())
SHORE = SH.rule(RULES_FILE)


def w(slug, name, kind, geom, state="PA", **extra):
    b = shape(geom).bounds
    return slug, {"slug": slug, "name": name, "kind": kind, "state": state, "towns": ["Erie"],
                  "bbox": list(b), "geometry": geom, **extra}


WATERS = dict([
    w("lake-erie-pa", "Lake Erie", "lake", LAKE, area_km2=26067.843, wikidata="Q5492"),
    w("lake-erie-ny", "Lake Erie", "lake", LAKE, state="NY", area_km2=26067.843, wikidata="Q5492"),
    w("mill-creek-pa", "Mill Creek", "stream", {"type": "LineString", "coordinates": [[-80.3, 41.9], [-80.3, 41.99]]}),
    w("lake-pleasant-pa", "Lake Pleasant", "lake",
      {"type": "Polygon", "coordinates": [[[-79.9, 41.9], [-79.89, 41.9], [-79.89, 41.91], [-79.9, 41.9]]]},
      area_km2=0.5),
])


def km_between(a, b):
    return R.seg_km([a, b])


# ---------------------------------------------------------------- which lakes

def test_the_great_lakes_are_shoreline_lakes_by_their_identifiers_and_small_namesakes_are_not():
    assert SH.is_shoreline(WATERS["lake-erie-pa"], SHORE)
    assert SH.is_shoreline({"kind": "lake", "name": "Lake Michigan", "gnis_id": 1623080, "area_km2": 33583.8}, SHORE)
    assert SH.is_shoreline({"kind": "lake", "name": "Lake Ontario", "area_km2": 19811.9}, SHORE)       # by name
    # New York's 0.7 km2 "Lake Superior" (Q35734889) is a pond, not the lake
    assert not SH.is_shoreline({"kind": "lake", "name": "Lake Superior", "wikidata": "Q35734889",
                                "area_km2": 0.728}, SHORE)
    # Lake Champlain stays a whole-water lake until min_area_km2 is set; a river named for a lake never is one
    champlain = {"kind": "lake", "name": "Lake Champlain", "wikidata": "Q68467", "area_km2": 1180.974}
    assert not SH.is_shoreline(champlain, SHORE)
    assert SH.is_shoreline(champlain, {**SHORE, "min_area_km2": 1000})
    assert not SH.is_shoreline({"kind": "river", "name": "Lake Erie", "wikidata": "Q5492"}, SHORE)


def test_the_rule_in_rules_json_has_its_numbers_rationale_and_source():
    r = RULES_FILE["reach"]["shoreline"]
    assert r["each_way_km"] == RULES_FILE["reach"]["cap_km"] == 40
    assert r["min_area_km2"] is None
    assert [e["name"] for e in r["lakes"]] == ["Lake Superior", "Lake Michigan", "Lake Huron", "Lake Erie",
                                               "Lake Ontario"]
    assert "not a measured value" in r["rationale"] and "40 kilometres each way" in r["rationale"]
    # the duration it states is the lake caution the stretch takes (a stretch's windows are its lake's)
    hours = RULES_FILE["yellow"]["by_water_kind"]["lake"]["hours"]
    assert f"{hours}-hour lake caution" in r["rationale"] and f"{hours}-hour lake caution" in r["source"]
    assert "cb_2023_us_state_500k" in r["source"] and "40-kilometre" in r["source"]
    public = X.public_rules(RULES_FILE)["reach"]["shoreline"]
    assert "_internal_doc" not in public and not X.internal_wording(public)


# ---------------------------------------------------------------- the geometry

def test_a_stretch_runs_along_the_shore_each_way_to_the_limit_and_names_the_states_it_touches():
    land = PA_LAND.union(NY_LAND)
    r = SH.stretch(-80.0, 41.999, shape(LAKE), land, 40, 500, 3, 5, land_states=LAND)
    east, west = r["sides"]
    assert east["km"] == pytest.approx(40, abs=0.01) and west["km"] == pytest.approx(40, abs=0.01)
    assert east["stop"] == west["stop"] == SH.STOP_LIMIT
    assert r["states"] == ["NY", "PA"] and r["snap_m"] < 200
    for side in r["sides"]:
        assert all(c[1] == pytest.approx(42.0, abs=1e-6) for c in side["coords"])       # on the shore, never offshore
        assert km_between(side["coords"][0], side["coords"][-1]) == pytest.approx(40, abs=0.05)
    assert r["length_km"] == pytest.approx(80, abs=0.02)


def test_a_stretch_stops_where_the_shore_ends_and_never_follows_a_line_through_the_lake():
    land = PA_LAND.union(NY_LAND)
    r = SH.stretch(-80.45, 41.999, shape(LAKE), land, 40, 500, 3, 5, land_states=LAND)
    east, west = r["sides"]
    assert west["stop"] == SH.STOP_END and west["coords"][-1] == [-80.5, 42.0]
    assert west["km"] == pytest.approx(km_between([-80.45, 42.0], [-80.5, 42.0]), abs=0.05)
    assert east["stop"] == SH.STOP_LIMIT and r["states"] == ["PA"]
    assert max(c[1] for s in r["sides"] for c in s["coords"]) == pytest.approx(42.0)


def test_a_short_gap_in_the_land_is_crossed_and_a_long_one_ends_the_stretch():
    river_mouth = PA_LAND.difference(box(-80.215, 41.98, -80.205, 42.01))       # under a kilometre
    r = SH.stretch(-80.0, 41.999, shape(LAKE), river_mouth, 40, 500, 3, 5)
    assert r["sides"][1]["km"] == pytest.approx(40, abs=0.01)
    wide = PA_LAND.difference(box(-80.3, 41.98, -80.2, 42.01))                  # about 8 km
    r = SH.stretch(-80.0, 41.999, shape(LAKE), wide, 40, 500, 3, 5)
    west = r["sides"][1]
    assert west["stop"] == SH.STOP_END and west["coords"][-1][0] >= -80.2 - 0.013
    assert west["km"] < 20


def test_a_point_far_from_any_shore_gets_no_stretch():
    with pytest.raises(SH.NoShore):
        SH.stretch(-80.0, 42.25, shape(LAKE), PA_LAND, 40, 500, 3, 5)


# ---------------------------------------------------------------- the reach records (build/reaches.py)

def _row(outfall, slug, lat=41.999, lon=-80.0, kind=None):
    return {"npdes_permit": PERMIT, "outfall": outfall, "state": "PA", "water_slug": slug, "lat": lat, "lon": lon,
            "outfall_kind": kind, "_file": "data/outfalls-mid-atlantic.json"}


def test_lake_outfalls_are_shoreline_candidates_plants_included_and_ponds_are_still_not_traced():
    rows = [_row("001", "lake-erie-pa"), _row("002", "lake-erie-pa", lat=None, lon=None),
            _row("003", "lake-pleasant-pa", 41.905, -79.895), _row("101", "lake-erie-pa", kind="plant"),
            _row("004", "mill-creek-pa", 41.95, -80.3)]
    skipped = {}
    c = {x["key"]: x for x in R.candidate_outfalls(WATERS, rows, {"PA"}, skipped, set(), plants=False, shore=SHORE)}
    assert c[f"{PERMIT}-001"]["model"] == "shoreline" and c[f"{PERMIT}-101"]["model"] == "shoreline"
    assert "model" not in c[f"{PERMIT}-004"]
    assert skipped[f"{PERMIT}-002"]["why"] == "no_location"
    assert skipped[f"{PERMIT}-003"]["why"] == "not_river"
    # with the rule's lake list empty, the Great Lake outfall is skipped as before
    skipped = {}
    c = R.candidate_outfalls(WATERS, rows, {"PA"}, skipped, set(), plants=False, shore={**SHORE, "lakes": []})
    assert [x["key"] for x in c] == [f"{PERMIT}-004"] and skipped[f"{PERMIT}-001"]["why"] == "not_river"


def shore_rec(outfall="001", lon=-80.0, kind="cso", **kw):
    c = {"key": f"{PERMIT}-{outfall}", "permit": PERMIT, "outfall": outfall, "water_slug": "lake-erie-pa",
         "lat": 41.999, "lon": lon, "name": None, "sources": ["echo"], "state": "PA", "outfall_kind": kind,
         "model": "shoreline", **kw}
    S._GEOM_CACHE.clear()
    return R.shoreline_record(c, WATERS, SHORE, LAND)


def test_a_shoreline_record_has_a_segment_each_way_the_lakes_records_and_states():
    rec = shore_rec()
    assert rec["model"] == "shoreline" and rec["cut_reason"] == "shoreline" and rec["error"] is None
    assert [s["km_start"] for s in rec["segments"]] == [0.0, 0.0]
    assert [s["km_end"] for s in rec["segments"]] == [pytest.approx(40, abs=0.01)] * 2
    assert rec["states"] == ["NY", "PA"] and rec["waters"] == ["lake-erie-pa", "lake-erie-ny"]
    assert [s["cut_reason"] for s in rec["stops"]] == ["shoreline_limit", "shoreline_limit"]
    assert rec["river"] == rec["lake"] == "Lake Erie" and rec["rule_sig"] == R.shore_sig(SHORE)
    assert R.outcome(rec) == "shoreline"
    far = R.shoreline_record({"key": "k", "permit": PERMIT, "outfall": "9", "water_slug": "lake-erie-pa",
                              "lat": 42.25, "lon": -80.0}, WATERS, SHORE, LAND)
    assert far["cut_reason"] == "no_trace" and "no shore" in far["error"] and far["segments"] == []


def test_run_shorelines_builds_without_a_request_and_rebuilds_when_the_rule_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "REACH_DIR", tmp_path)
    monkeypatch.setattr(R, "nldi_get", lambda *a, **k: pytest.fail("a shoreline stretch asked NLDI"))
    cands = [{"key": f"{PERMIT}-001", "permit": PERMIT, "outfall": "001", "water_slug": "lake-erie-pa",
              "lat": 41.999, "lon": -80.0, "sources": ["echo"], "state": "PA", "model": "shoreline"}]
    S._GEOM_CACHE.clear()
    out = R.run_shorelines(cands, WATERS, SHORE, log=lambda m: None, land=LAND)
    assert out["built"] == 1 and (tmp_path / f"{PERMIT}-001.json").exists()
    assert R.run_shorelines(cands, WATERS, SHORE, log=lambda m: None, land=LAND)["due"] == 0
    shorter = {**SHORE, "each_way_km": 10}
    assert R.run_shorelines(cands, WATERS, shorter, log=lambda m: None, land=LAND)["built"] == 1
    assert json.loads((tmp_path / f"{PERMIT}-001.json").read_text())["length_km"] == pytest.approx(20, abs=0.02)
    # no Census outlines: nothing built, nothing cached as a failure
    monkeypatch.setattr(R, "land_outlines", lambda: (_ for _ in ()).throw(OSError("offline")))
    cands[0]["lat"] = 41.9985
    cands[0]["lat"] += 0.001
    out = R.run_shorelines(cands, WATERS, SHORE, log=lambda m: None)
    assert out.get("stopped") and json.loads((tmp_path / f"{PERMIT}-001.json").read_text())["each_way_km"] == 10


# ---------------------------------------------------------------- the status build

@pytest.fixture(autouse=True)
def _status_state():
    saved = dict(S.PLACE_STEPS)
    S.PLACE_STEPS.update(registry=True, relaxed_guard=True, no_receiving_water=True, outfall_ids=True,
                         multi_outfall=True)
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    S._STATES = {"PA", "NY"}
    yield
    S.PLACE_STEPS.update(saved)
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    S._SHORE_REACHES.clear()
    S._STATES = None


def ev(rid, **kw):
    kw.setdefault("event_type", "cso")
    kw.setdefault("status", "ongoing")
    kw.setdefault("npdes_permit", PERMIT)
    kw.setdefault("started_at", (NOW - 2 * H).isoformat())
    return event(source_id="pa-test", source_record_id=rid, **kw)


REGISTRY_ROWS = [_row("001", "lake-erie-pa"), _row("004", "mill-creek-pa", 41.95, -80.3)]


def river_reach():
    return {"key": f"{PERMIT}-004", "permit": PERMIT, "outfall": "004", "water_slug": "mill-creek-pa", "lat": 41.95,
            "lon": -80.3, "river": "Mill Creek", "cut_reason": "lake_or_reservoir", "length_km": 4.0, "state": "PA",
            "segments": [{"comid": 1, "km_start": 0.0, "km_end": 4.0, "totdasqkm": 50, "qe_ma": 30, "slope": 1e-3,
                          "gnis_name": "Mill Creek", "coords": [[-80.3, 41.95], [-80.3, 41.99]]}]}


def _build(records, reaches, rules=None, waters=None):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "pa-test.json").write_text(json.dumps({"source_id": "pa-test", "ok": True, "last_ok_at": NOW.isoformat(),
                                                  "meta": {}, "records": records}))
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    st, hist = S.build(now=NOW, write=False, events_dir=tmp, waters=copy.deepcopy(waters or WATERS),
                       outfalls=list(REGISTRY_ROWS), registry={}, reaches=copy.deepcopy(reaches), flows=({}, {}),
                       discharger_towns={}, discharger_waters={}, rules=rules or RULES_FILE)
    return st, hist


RECORDS = [ev("1", outfall_id="001", waterbody_text="Lake Erie"),
           ev("2", outfall_id="004", waterbody_text="Mill Creek"),
           ev("3", event_type="sso", waterbody_text="Lake Pleasant", npdes_permit=None, lat=41.905, lon=-79.895)]


def test_a_great_lake_report_colours_its_stretch_and_not_the_outline_and_still_counts_on_the_lake():
    lake_reach = shore_rec()
    st, _ = _build(RECORDS, {lake_reach["key"]: lake_reach, f"{PERMIT}-004": river_reach()})
    lake = st["waters"]["lake-erie-pa"]
    assert lake["status"] == "red" and lake["fill"] is False and lake["stretch_model"] == "shoreline"
    assert lake["status_basis"] == S.SHORE_STATUS_BASIS and lake["summary"] == S.SHORE_SUMMARY
    assert lake["events"] == ["pa-test:1"] and lake["reaches"] == [f"{PERMIT}-001"]
    assert [r["placement"] for r in lake["reasons"]] == ["reach"]
    assert "on a modeled shoreline stretch" in lake["reasons"][0]["short"]
    # the stretch reaches New York's shore: New York's Lake Erie record lists the report, outline only
    ny = st["waters"]["lake-erie-ny"]
    assert ny["events"] == ["pa-test:1"] and ny["status"] == "red" and ny["fill"] is False
    r = st["reaches"][f"{PERMIT}-001"]
    assert r["status"] == "red" and r["model"] == "shoreline" and r["states"] == ["NY", "PA"]
    active = [a for a in st["reach_events_active"] if a["reach"] == f"{PERMIT}-001"]
    assert len(active) == 1 and all(sg["hours_typical"] is None for sg in active[0]["segments"])
    assert active[0]["flow_basis"] is None
    assert not [p for p in st["problems"] if "travel time" in p]
    assert st["counts"]["placed"] == 3


def test_a_great_lake_report_with_no_stretch_is_listed_and_counted_but_colours_no_shore():
    st, _ = _build([ev("1", outfall_id="001", waterbody_text="Lake Erie", lat=41.999, lon=-80.0)], {})
    lake = st["waters"]["lake-erie-pa"]
    assert lake["events"] == ["pa-test:1"] and lake["status"] == "red" and lake["fill"] is False
    assert [r["placement"] for r in lake["reasons"]] == ["shoreline_unmodeled"]
    assert "lake shore: stretch not modeled" in lake["reasons"][0]["short"]
    need = [n for n in st["needs_reach"] if n["event_id"] == "pa-test:1"]
    assert need and need[0]["model"] == "shoreline" and need[0]["water_slug"] == "lake-erie-pa"


def _without_lake(st, hist, slugs=("mill-creek-pa", "lake-pleasant-pa")):
    """The parts of a build that belong to the other waters and their reaches."""
    keep_r = {k for k, v in st["reaches"].items() if v.get("water_slug") in slugs}
    return json.dumps({"waters": {s: st["waters"].get(s) for s in slugs},
                       "reaches": {k: st["reaches"][k] for k in sorted(keep_r)},
                       "active": [a for a in st["reach_events_active"] if a["reach"] in keep_r],
                       "placements": {k: v for k, v in st["placements"].items() if k != "pa-test:1"},
                       "hist": {s: hist["waters"].get(s) for s in slugs},
                       "hist_reaches": {k: hist["reaches"].get(k) for k in sorted(keep_r)}}, sort_keys=True, default=str)


def test_every_other_water_is_byte_identical_with_the_rule_on_or_off():
    off = copy.deepcopy(RULES_FILE)
    off["reach"].pop("shoreline")
    lake_reach = shore_rec()
    on_st, on_h = _build(RECORDS, {lake_reach["key"]: lake_reach, f"{PERMIT}-004": river_reach()})
    off_st, off_h = _build(RECORDS, {f"{PERMIT}-004": river_reach()}, rules=off)
    assert _without_lake(on_st, on_h) == _without_lake(off_st, off_h)
    assert on_st["waters"]["mill-creek-pa"]["status"] == "red" and on_st["waters"]["mill-creek-pa"]["fill"] is False
    assert "stretch_model" not in on_st["waters"]["mill-creek-pa"]
    pond = on_st["waters"]["lake-pleasant-pa"]
    assert pond["fill"] is True and pond["status_basis"] == "whole water" and "stretch_model" not in pond
    # with the rule off, the Great Lake is the whole-water lake it was
    lake = off_st["waters"]["lake-erie-pa"]
    assert lake["fill"] is True and lake["status_basis"] == "whole water" and "stretch_model" not in lake
    assert [r["placement"] for r in lake["reasons"]] == [None]


# ---------------------------------------------------------------- the export

def test_the_export_carries_the_stretch_with_its_states_and_the_river_reach_unchanged(monkeypatch):
    monkeypatch.setattr(R, "cap_km", lambda rules=None: 40.0)
    lake_reach = shore_rec()
    cached = {lake_reach["key"]: lake_reach, f"{PERMIT}-004": river_reach()}
    st, _ = _build(RECORDS, cached)
    by_event = {f"pa-test:{i}": {"started_at": (NOW - 2 * H).isoformat()} for i in (1, 2, 3)}
    feats, paths = X.reach_features(st, by_event, cached)
    lake_f = [f for f in feats if f["properties"]["reach"] == f"{PERMIT}-001"]
    assert [f["properties"]["feature"] for f in lake_f] == ["segment", "segment", "stop", "stop"]
    for f in lake_f:
        p = f["properties"]
        assert p["model"] == "shoreline" and p["states"] == ["NY", "PA"] and p["status"] == "red"
        assert p["waters"] == ["lake-erie-pa", "lake-erie-ny"]
    seg = lake_f[0]["properties"]
    assert seg["arrival_hours_typical"] is None and seg["gauge"] is None and "Lake Erie shore" in seg["label"]
    assert "downstream" not in seg["label"] and seg["line_text"] == X.SHORE_LINE_TEXT
    assert lake_f[2]["properties"]["cut_reason"] == "shoreline_limit" and "40 km" in lake_f[2]["properties"]["label"]
    path = [f for f in paths if f["id"] == f"{PERMIT}-001"][0]["properties"]
    assert path["model"] == "shoreline" and path["states"] == ["NY", "PA"] and len(path["stops"]) == 2
    # the river reach's features are exactly what they are without the shoreline record
    river_alone, river_paths = X.reach_features(
        {**st, "reach_events_active": [a for a in st["reach_events_active"] if a["reach"] == f"{PERMIT}-004"]},
        by_event, {f"{PERMIT}-004": river_reach()})
    assert [f for f in feats if f["properties"]["reach"] == f"{PERMIT}-004"] == river_alone
    assert [f for f in paths if f["id"] == f"{PERMIT}-004"] == river_paths
    assert all("model" not in f["properties"] and "states" not in f["properties"] for f in river_alone + river_paths)
    # the state files: the stretch in Pennsylvania's and New York's, properties.states the outfall's state first
    by_state, homeless = X.reaches_by_state(feats, paths, st, cached, {"PA", "NY"})
    assert homeless == []
    ny = [f for f in by_state["NY"] if f["properties"]["reach"] == f"{PERMIT}-001"]
    assert len(ny) == 5 and all(f["properties"]["states"] == ["PA", "NY"] for f in ny)
    assert all(f["properties"]["reach"] != f"{PERMIT}-004" for f in by_state["NY"])


def test_rain_caution_never_reads_a_plants_shoreline_stretch():
    plant = shore_rec("101", kind="plant")
    cso = shore_rec("001")
    keys, tags, _, _ = RL.targets(PERMIT, WATERS, [], [], {plant["key"]: plant, cso["key"]: cso}, S.reach_waters)
    assert keys == [cso["key"]] and tags == {"lake-erie-pa": "reach", "lake-erie-ny": "reach"}


def test_the_stretch_keeps_the_lake_caution_after_the_reported_end():
    lake_reach = shore_rec()
    ended = ev("1", outfall_id="001", waterbody_text="Lake Erie", status="ended",
               started_at=(NOW - 82 * H).isoformat(), ended_at=(NOW - 80 * H).isoformat())
    st, _ = _build([ended], {lake_reach["key"]: lake_reach})
    hours = RULES_FILE["yellow"]["by_water_kind"]["lake"]["hours"]
    assert hours > 80 and st["reaches"][lake_reach["key"]]["status"] == "yellow"
    assert st["waters"]["lake-erie-pa"]["status"] == "yellow" and st["waters"]["lake-erie-pa"]["fill"] is False


def test_a_report_on_a_river_and_a_great_lake_is_traced_from_its_point_down_the_river():
    both = ev("1", event_type="sso", npdes_permit=None, waterbody_text="Lake Erie; Mill Creek", lat=41.99, lon=-80.3,
              water_slugs=["lake-erie-pa", "mill-creek-pa"])
    st, _ = _build([both], {})
    assert st["placements"]["pa-test:1"]["water_slugs"] == ["lake-erie-pa", "mill-creek-pa"]
    assert [(n["water_slug"], n.get("model")) for n in st["needs_reach"]] == [("mill-creek-pa", None)]
    lake_only = ev("2", event_type="sso", npdes_permit=None, waterbody_text="Lake Erie", lat=41.999, lon=-80.0,
                   water_slugs=["lake-erie-pa"])
    st, _ = _build([lake_only], {})
    assert [(n["water_slug"], n.get("model")) for n in st["needs_reach"]] == [("lake-erie-pa", "shoreline")]
