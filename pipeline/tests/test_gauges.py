"""Conditions beside the status (ingest/gauges.py): which gauge a water gets, the readings cache, the
flags, and the export into out/conditions.json and waters/<slug>.json. Run from pipeline/:
python -m pytest tests -q
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import gauges as G  # noqa: E402

NOW = datetime(2026, 11, 2, 16, 0, tzinfo=UTC)


def t(hours_ago: float) -> str:
    return (NOW - timedelta(hours=hours_ago)).isoformat()


@pytest.fixture
def tmp_build(tmp_path, monkeypatch):
    for name in ("READINGS", "FLOW_STATS", "FLOOD", "CONDITIONS"):
        monkeypatch.setattr(G, name, tmp_path / f"{name.lower()}.json")
    monkeypatch.setattr(G.time, "sleep", lambda s: None)
    return tmp_path


def test_pretty_name_spells_out_usgs_abbreviations():
    assert G.pretty_name("CONNECTICUT R BELOW INDIAN STREAM NR PITTSBURG, NH") == \
        "Connecticut River below Indian Stream near Pittsburg, NH"
    assert G.pretty_name("BLACKSTONE RIVER, W. MAIN ST., AT MILLBURY, MA") == "Blackstone River, W. Main St., at Millbury, MA"
    assert G.pretty_name("Androscoggin River at Errol, NH") == "Androscoggin River at Errol, NH"
    assert G.pretty_name("W BR WESTFIELD R AT HUNTINGTON, MA") == "W Branch Westfield River at Huntington, MA"


def test_name_rule_keeps_branches_and_qualified_rivers_apart():
    assert G.on_water("Woonasquatucket River", "WOONASQUATUCKET RIVER AT CENTERDALE, RI")
    assert not G.on_water("Nashua River", "MERRIMACK RIVER AT NASHUA, NH")
    # openboatlaunch's word rule alone matches these; the qualifier check does not
    assert G.on_water("South Branch Park River", "NORTH BRANCH PARK RIVER AT HARTFORD, CT")
    assert not G.same_river("South Branch Park River", "NORTH BRANCH PARK RIVER AT HARTFORD, CT")
    assert not G.same_river("Nashua River", "NORTH NASHUA RIVER AT FITCHBURG, MA")
    assert not G.same_river("Androscoggin River", "Little Androscoggin River near South Paris, Maine")
    assert not G.same_river("Westfield River", "W BR WESTFIELD R AT HUNTINGTON, MA")
    assert G.same_river("Little Androscoggin River", "Little Androscoggin River near South Paris, Maine")
    assert G.same_river("Housatonic River", "HOUSATONIC RIVER NEAR GREAT BARRINGTON, MA")


def gauge(site, lon, lat, name="X RIVER AT Y, MA", **kw):
    return {"site": site, "name": name, "lon": lon, "lat": lat, "from": "hydrography", **kw}


def test_pick_takes_the_gauge_nearest_most_outlets_not_the_one_beside_a_single_outlet():
    # one outlet 0.1 km from gauge A, three outlets about 1-2 km from gauge B (the Springfield case)
    a, b = gauge("A", -72.55, 42.60), gauge("B", -72.60, 42.20)
    pts = [(-72.551, 42.6005), (-72.61, 42.20), (-72.60, 42.21), (-72.59, 42.19)]
    d, c = G.pick([a, b], pts, None, 50)
    assert c["site"] == "B" and 0.5 < d < 1.0


def test_choose_prefers_a_live_flow_gauge_and_merges_the_hydrography_table(monkeypatch):
    monkeypatch.setattr(G, "obl_launch", lambda s: None)
    w = {"slug": "x-river-ct", "name": "X River", "kind": "river", "launches": [], "extra": False}
    table = {"X River": [{"site": "STAGE", "name": "X RIVER AT HARTFORD, CT", "lon": -72.66, "lat": 41.76},
                         {"site": "FLOW", "name": "X RIVER AT THOMPSONVILLE, CT", "lon": -72.60, "lat": 41.99},
                         {"site": "FAR", "name": "X RIVER AT FAR AWAY, NH", "lon": -72.0, "lat": 44.0}]}
    outfalls = [(-72.665, 41.765)]
    c = G.choose(w, outfalls, {}, table, None, live={"FLOW", "FAR"})
    assert c["site"] == "FLOW" and c["distance_from"] == "outfall" and 20 < c["distance_km"] < 30
    c = G.choose(w, outfalls, {}, table, None, live=set())       # nothing live: the nearest gauge
    assert c["site"] == "STAGE"
    assert G.choose({**w, "name": "Other River"}, outfalls, {}, table, None, live=None) is None


def test_choose_uses_openboatlaunch_launch_gauges_and_skips_the_name_rule_when_the_join_ran(monkeypatch):
    launches = {"l1": {"lon": -72.0, "lat": 42.0, "gauge": {"id": "011", "name": "YANTIC RIVER AT Z, MA", "km": 3.0}},
                "l2": {"lon": -72.1, "lat": 42.0, "gauge": None}}
    monkeypatch.setattr(G, "obl_launch", lambda s: launches.get(s))
    gauges = {"011": {"id": "011", "name": "YANTIC RIVER AT Z, MA", "lon": -72.0, "lat": 42.02, "type": "ST", "nwps": "ZZZM3",
                      "state": "MA", "params": ["00060"]},
              "022": {"id": "022", "name": "YANTIC RIVER AT QUINN, MA", "lon": -72.1, "lat": 42.0, "type": "ST", "state": "MA",
                      "params": ["00060"]}}
    w = {"slug": "yantic-river-ma", "name": "Yantic River", "kind": "river", "launches": ["l1", "l2"], "extra": False}
    c = G.choose(w, [], gauges, {}, None, live=None)
    assert c["site"] == "011" and c["from"] == "openboatlaunch" and c["distance_from"] == "launch" and c["nwps"] == "ZZZM3"
    # a launch with no gauge in openboatlaunch (tidal, or none on the river): the name rule does not overrule it
    launches["l1"]["gauge"] = None
    assert G.choose(w, [], gauges, {}, None, live=None) is None
    # a water no launch placed (waters-extra): the name rule applies, within 25 km
    from shapely.geometry import LineString
    geom = LineString([(-72.2, 42.0), (-72.05, 42.0)])
    c = G.choose({**w, "extra": True, "launches": []}, [], gauges, {}, geom, live=None)
    assert c["site"] == "022" and c["from"] == "name" and c["distance_from"] == "water"


def test_parse_latest_keeps_the_newest_reading_per_parameter_and_strips_the_unit_underscore():
    feats = [{"properties": {"monitoring_location_id": "USGS-1", "parameter_code": "63680", "value": "3.5",
                             "unit_of_measure": "_FNU", "time": t(1)}},
             {"properties": {"monitoring_location_id": "USGS-1", "parameter_code": "00010", "value": "9.0",
                             "unit_of_measure": "degC", "time": t(5)}},
             {"properties": {"monitoring_location_id": "USGS-1", "parameter_code": "00010", "value": "8.0",
                             "unit_of_measure": "degC", "time": t(1)}},
             {"properties": {"monitoring_location_id": "USGS-1", "parameter_code": "99999", "value": "1", "time": t(1)}},
             {"properties": {"monitoring_location_id": "USGS-1", "parameter_code": "00060", "value": "-999999", "time": t(1)}}]
    s = G.parse_latest(feats)["USGS-1"]
    assert s["63680"]["unit"] == "FNU" and s["00010"]["value"] == 8.0 and set(s) == {"63680", "00010"}


def test_readings_are_refetched_only_when_older_than_15_minutes_and_survive_a_failure(tmp_build):
    calls = []

    def fetch(st):
        calls.append(st)
        return {"USGS-1": {"00060": {"value": 100.0, "unit": "ft^3/s", "time": t(0.2)}}}

    G.refresh_readings(["MA", "CT"], now=NOW, fetch=fetch)
    G.refresh_readings(["MA", "CT"], now=NOW + timedelta(minutes=10), fetch=fetch)
    assert calls == ["MA", "CT"]
    G.refresh_readings(["MA"], now=NOW + timedelta(minutes=16), fetch=fetch)
    assert calls == ["MA", "CT", "MA"]

    def down(st):
        raise RuntimeError("503")

    out = G.refresh_readings(["MA"], now=NOW + timedelta(minutes=40), fetch=down)
    assert out["states"]["MA"]["ok"] is False and out["sites"]["USGS-1"]["00060"]["value"] == 100.0
    G.refresh_readings(["MA"], now=NOW + timedelta(minutes=41), fetch=fetch)    # a failed state is retried at once
    assert calls[-1] == "MA" and len(calls) == 4


def test_percentile_and_flow_stats_are_cached_and_a_rate_limit_waits_for_the_next_run(tmp_build):
    assert G.percentile([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 0.9) == pytest.approx(9.1)
    calls = []

    def fetch(site, y0, y1):
        calls.append(site)
        return [float(i) for i in range(1, 1201)]

    out = G.flow_stats({"A"}, now=NOW, fetch=fetch)
    assert out["sites"]["A"]["p90_cfs"] == pytest.approx(1080.1) and out["sites"]["A"]["years"] == "2016-2025"
    G.flow_stats({"A"}, now=NOW + timedelta(days=30), fetch=fetch)
    assert calls == ["A"]
    short = G.flow_stats({"B"}, now=NOW, fetch=lambda *a: [1.0] * 20)
    assert short["sites"]["B"]["p90_cfs"] is None

    import requests

    def limited(site, y0, y1):
        r = requests.Response()
        r.status_code = 429
        raise requests.HTTPError("429", response=r)

    out = G.flow_stats({"C", "D"}, now=NOW, fetch=limited)
    assert "failed_at" not in out["sites"]["C"] and "D" not in out["sites"]       # stopped; both tried next run
    out = G.flow_stats({"C"}, now=NOW + timedelta(minutes=15), fetch=fetch)
    assert out["sites"]["C"]["p90_cfs"] is not None


def test_flood_stages_need_the_same_usgs_gauge(tmp_build):
    body = {"usgsId": "01184000", "flood": {"categories": {"action": {"stage": 14}, "minor": {"stage": 15},
                                                          "moderate": {"stage": 17}, "major": {"stage": -9999}}}}
    assert G.parse_flood(body, "01184000") == {"action": 14.0, "minor": 15.0, "moderate": 17.0}
    assert G.parse_flood(body, "01170500") is None
    out = G.flood_stages({"TMVC3": "01184000"}, now=NOW, fetch=lambda lid: body)
    assert out["gauges"]["TMVC3"]["match"] is True


def test_record_flags_follow_rules_conditions_and_ignore_old_readings():
    th = {"cold_water_c": 15, "turbid_ntu": 200}
    readings = {"states": {"CT": {"fetched_at": t(0.1)}}, "sites": {"USGS-9": {
        "_state": "CT",
        "00060": {"value": 40000.0, "unit": "ft^3/s", "time": t(0.5)},
        "00010": {"value": 11.6, "unit": "degC", "time": t(0.5)},
        "63680": {"value": 250.0, "unit": "FNU", "time": t(0.5)},
        "00095": {"value": 194.0, "unit": "uS/cm", "time": t(30)}}}}
    stats = {"sites": {"9": {"p90_cfs": 38500.0, "years": "2016-2025"}}}
    flood = {"gauges": {"TMVC3": {"site": "9", "match": True, "stages": {"minor": 15.0}}}}
    c = {"site": "9", "name": "CONNECTICUT RIVER AT THOMPSONVILLE, CT", "from": "openboatlaunch", "distance_km": 2.0,
         "distance_from": "outfall", "nwps": "TMVC3"}
    r = G.record(c, readings, stats, flood, th, NOW)
    assert r["flags"] == {"cold": True, "turbid": True, "high_flow": True}
    assert r["conductance"] is None and r["turbidity_unit"] == "FNU" and r["time"] == t(0.5)
    assert r["nwps"]["lid"] == "TMVC3" and r["nwps"]["minor"] == 15.0
    assert r["gauge_name"] == "Connecticut River at Thompsonville, CT"
    assert r["source_url"].startswith("https://waterdata.usgs.gov/monitoring-location/")
    readings["sites"]["USGS-9"]["00010"]["value"] = 16.0
    readings["sites"]["USGS-9"]["00060"]["time"] = t(13)                      # too old to show
    r = G.record(c, readings, stats, flood, th, NOW)
    assert r["flags"]["cold"] is False and r["flow_cfs"] is None and r["flags"]["high_flow"] is False


def test_export_attaches_conditions_to_tracked_waters_only():
    from export import build as X
    cond = {"built": "2026-11-02T16:00:00+00:00", "thresholds": {"cold_water_c": 15, "turbid_ntu": 200},
            "waters": {"a-river-ma": {"gauge_id": "1", "gauge_name": "A", "gauge_name_usgs": "A", "gauge_lat": 1,
                                      "gauge_lon": 2, "nwps_lid": "X", "flags": {"cold": True}},
                       "untracked-ma": {"gauge_id": "2"}}}
    out = X.public_conditions(cond, {"a-river-ma"})
    assert set(out["waters"]) == {"a-river-ma"} and out["count"] == 1
    rec = out["waters"]["a-river-ma"]
    assert "nwps_lid" not in rec and rec["gauge_name_usgs"] == "A" and rec["flags"] == {"cold": True}
    assert not X.internal_wording(out)
