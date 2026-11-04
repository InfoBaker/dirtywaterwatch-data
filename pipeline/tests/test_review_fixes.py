"""One test per fix from docs/reviews/2026-11-02-codex-review.md (findings 1, 4-10, 12, 13, 15-17) and
the NH follow-ups (partial permittee failures, bounded ends). Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import common  # noqa: E402
from build import reaches as R  # noqa: E402
from build import status as S  # noqa: E402
from export import build as X  # noqa: E402
from tests.test_status import TEST_RULES, _reach, ev, iso, tmp_events, world  # noqa: E402

H = timedelta(hours=1)
NOW = datetime(2026, 11, 2, 12, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _rules(monkeypatch):
    monkeypatch.setattr(S, "_RULES", TEST_RULES)


def colour(e, t, state="MA", now=None, water=None):
    c, ivs = S.status_at(S.event_intervals(e, state, now or t, water=water), t)
    return c, [iv["rule"] for iv in ivs]


# 1 ---------------------------------------------------------------- failed fetch keeps meta

def test_failed_fetch_keeps_the_previous_meta_and_restriction(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    rec = ev("b", source_id="nh-des-swimming", event_type="beach_advisory", status="advisory_active",
             started_at=iso(NOW - H))
    common.write_events("nh-des-swimming", [rec], meta={"distribution_discouraged": True, "covers_waters": ["x"]})
    common.write_events("nh-des-swimming", [], ok=False, error="HTTP 500")
    d = json.loads((tmp_path / "nh-des-swimming.json").read_text())
    assert d["ok"] is False and d["count"] == 1
    assert d["meta"] == {"distribution_discouraged": True, "covers_waters": ["x"]}
    common.write_events("nh-des-swimming", [], ok=False, error="HTTP 500", meta={"distribution_discouraged": False})
    d = json.loads((tmp_path / "nh-des-swimming.json").read_text())
    assert d["meta"]["distribution_discouraged"] is True          # a failure never lifts the restriction
    _, events, _ = S.load_events(tmp_path, include_restricted=False)
    assert events == []


# 4 ---------------------------------------------------------------- a known future end is an end

def test_ongoing_with_a_future_end_is_in_progress_now_and_in_replay():
    e = ev(status="ongoing", started_at="2026-10-01T12:00:00-04:00", ended_at="2026-11-04T12:00:00-05:00")
    assert colour(e, NOW, now=NOW) == ("red", ["discharge"])
    assert colour(e, datetime(2026, 10, 20, tzinfo=UTC), now=NOW) == ("red", ["discharge"])
    assert colour(e, datetime(2026, 11, 5, 12, tzinfo=UTC), now=NOW) == ("red", ["authority_window"])


# 5 ---------------------------------------------------------------- DST: windows in UTC

def test_naive_and_offset_ends_give_the_same_window_across_dst():
    naive = ev("n", status="ended", started_at="2026-03-06T10:00:00", ended_at="2026-03-06T12:00:00")
    offset = ev("o", status="ended", started_at="2026-03-06T10:00:00-05:00", ended_at="2026-03-06T12:00:00-05:00")
    for e in (naive, offset):          # 48 h after 17:00Z on Mar 6 is 17:00Z on Mar 8, DST or not
        assert colour(e, datetime(2026, 3, 8, 16, 30, tzinfo=UTC))[0] == "red"
        assert colour(e, datetime(2026, 3, 8, 17, 30, tzinfo=UTC))[0] == "yellow"
        assert colour(e, datetime(2026, 3, 9, 16, 30, tzinfo=UTC))[0] == "yellow"   # 72 h: 17:00Z Mar 9
        assert colour(e, datetime(2026, 3, 9, 17, 30, tzinfo=UTC))[0] == "grey"
    assert S.parse_time("2026-03-06T12:00:00") == datetime(2026, 3, 6, 17, 0, tzinfo=UTC)


def test_day_precision_end_counts_from_the_end_of_that_local_day():
    e = ev(status="ended", started_at="2026-11-01T00:00:00-04:00", ended_at="2026-11-01T00:00:00-04:00",
           time_precision="day")
    ivs = S.event_intervals(e, "MA", NOW)
    assert ivs[0]["end"] == datetime(2026, 11, 2, 5, 0, tzinfo=UTC)      # midnight EST after the DST change
    assert S.end_of_local_day(datetime(2026, 3, 8, 12, tzinfo=UTC)) == datetime(2026, 3, 9, 4, 0, tzinfo=UTC)


# 6 ---------------------------------------------------------------- unusable gauge flow

def test_zero_negative_or_odd_gauge_flow_never_raises():
    assert R.jobson(25000, 18000, 0, 2.6e-4) == (None, None)
    assert R.jobson(25000, 18000, -10, 2.6e-4) == (None, None)
    assert R.jobson(25000, 18000, float("nan"), 2.6e-4) == (None, None)
    t = R.travel([{"km_start": 0, "km_end": 5, "totdasqkm": 25000, "qe_ma": 18000, "slope": 2.6e-4}], 0)
    assert t[0]["hours_typical"] is None
    reach = _reach()
    gauges = {"rivers": {"Test River": [{"id": "USGS-1", "site": "1", "name": "g", "lat": 42.0, "lon": -72.0,
                                         "qe_ma_cfs": 18000}]}}
    for v in (0.0, -5.0, float("inf")):
        f = R.flow_for(reach, gauges, {"sites": {"USGS-1": {"value": v, "unit": "ft^3/s", "time": iso(NOW - H)}}}, NOW)
        assert f["gauge"] is None and f["q_ratio"] == 1.0 and "not usable" in f["flow_basis"]
    f = R.flow_for(reach, gauges, {"sites": {"USGS-1": {"value": 900.0, "unit": "m^3/s", "time": iso(NOW - H)}}}, NOW)
    assert f["gauge"] is None
    e = ev("r", status="ongoing", started_at=iso(NOW - 2 * H), npdes_permit="MA0101613", outfall_id="013")
    w = world(tmp_events([e]))
    w["reaches"] = {reach["key"]: reach}
    w["flows"] = (gauges, {"sites": {"USGS-1": {"value": 0.0, "unit": "ft^3/s", "time": iso(NOW - H)}}})
    st, _ = S.build(now=NOW, write=False, **w)
    assert st["reach_events_active"][0]["gauge"] is None


# 7 ---------------------------------------------------------------- missing NHD attributes

def test_missing_attributes_stop_the_trace_and_give_no_travel_time():
    lines = [{"comid": 1, "coords": [[-72.0, 42.0], [-71.9, 42.0]]}, {"comid": 2, "coords": [[-71.9, 42.0], [-71.8, 42.0]]}]
    a1 = {"comid": 1, "hydroseq": 2, "tidal": 0, "wbareacomid": 0, "totdasqkm": 100, "qe_ma": 50, "slope": 1e-3}
    segs, why = R.build_segments(lines, {1: a1}, 40)
    assert why == "attributes unavailable" and [s["comid"] for s in segs] == [1]
    segs, why = R.build_segments(lines, {}, 40)
    assert why == "attributes unavailable" and segs == []
    t = R.travel([{"km_start": 0, "km_end": 10}], 1)
    assert t[0]["hours_typical"] is None and t[0]["hours_fast"] is None        # never zero
    t = R.travel([{"km_start": 0, "km_end": 5, "totdasqkm": 100, "qe_ma": 50, "slope": 1e-3},
                  {"km_start": 5, "km_end": 9}], 1)
    assert t[0]["hours_typical"] > 0 and t[1]["hours_typical"] is None and t[1]["hours_typical_start"] == t[0]["hours_typical"]


# 8 ---------------------------------------------------------------- fixtures are opt-in

def test_fixtures_are_off_by_default_and_the_export_refuses_them(monkeypatch):
    fx = ev("fx", source_id="fixture-ma", status="ongoing", started_at=iso(NOW - H))
    d = tmp_events([], [fx])
    w = world(d)
    st, _ = S.build(now=NOW, write=False, **w)
    assert st["fixtures_included"] is False and "test-river-ma" not in st["waters"]
    monkeypatch.delenv("DWW_ALLOW_FIXTURES", raising=False)
    with pytest.raises(SystemExit):
        X.export(include_fixtures=True)


# 9 / 10 ---------------------------------------------------------- point advisories

def test_point_advisories_reach_active_and_effects_with_their_own_intervals():
    bay = ev("bay", event_type="beach_advisory", status="advisory_active", started_at=iso(NOW - 5 * H),
             water_slugs=["test-bay-ma"], lat=42.05, lon=-70.95)
    old = ev("old", event_type="beach_closure", status="advisory_active", started_at=iso(NOW - timedelta(days=20)),
             water_slugs=["test-bay-ma"], lat=42.05, lon=-70.95)
    st, hist = S.build(now=NOW, write=False, **world(tmp_events([bay, old])))
    pts = {p["event_id"]: p for p in st["advisory_points"]}
    assert pts["ma-test:bay"]["status"] == "red" and pts["ma-test:bay"]["intervals"][0][2] == "red"
    # the aged-out closure: grey now, but its red interval is there for replay, and `until` is the
    # end of the colouring (14 days after confirmation), not of the grey note after it
    o = pts["ma-test:old"]
    assert o["status"] == "grey" and o["intervals"][0][2] == "red"
    assert o["until"] == S.iso(S.parse_time(old["started_at"]) + timedelta(days=14))
    assert "R" in hist["points"]["ma-test:old"]                  # a beach hour: its own letter (docs/plan.md §2.z)
    effects, active = defaultdict(list), defaultdict(list)
    X.point_effects(st, effects, active)
    assert active["ma-test:bay"][0]["placement"] == "point" and "ma-test:old" not in active
    assert effects["ma-test:old"][0]["status"] == "red"


# 12 ---------------------------------------------------------------- unknown status from the report

def test_unknown_status_intervals_start_at_the_report_time():
    start, report = datetime(2026, 8, 1, 12, tzinfo=UTC), datetime(2026, 8, 10, 12, tzinfo=UTC)
    e = ev(status="unknown", started_at=iso(start), reported_at=iso(report))
    assert colour(e, datetime(2026, 8, 5, tzinfo=UTC), now=NOW)[0] == "grey"
    assert colour(e, report + H, now=NOW) == ("yellow", ["no_end"])
    assert colour(e, report + timedelta(days=14) - H, now=NOW)[0] == "yellow"
    assert colour(e, report + timedelta(days=14) + H, now=NOW) == ("unresolved", ["unresolved"])
    assert colour(e, report + timedelta(days=30) + H, now=NOW) == ("grey", ["end_never_reported"])


# 13 ---------------------------------------------------------------- end before start

def test_end_before_start_is_a_recorded_validation_error():
    e = ev("bad", status="ended", started_at=iso(NOW - 5 * H), ended_at=iso(NOW - 50 * H))
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([e])))
    assert "before started_at" in st["placements"]["ma-test:bad"]["validation_error"]
    assert any("ended_at before started_at" in p for p in st["problems"])
    assert st["waters"]["test-river-ma"]["status"] == "yellow"       # treated as no end: 14 days from the report


# 15 ---------------------------------------------------------------- export freshness

def test_export_rebuilds_when_any_input_is_newer(tmp_path):
    rules = tmp_path / "rules.json"
    rules.write_text("{}")
    built = datetime.now(UTC) - timedelta(minutes=5)
    st = {"built": iso(built), "fixtures_included": False, "restricted_included": False}
    hist = {"built": iso(built)}
    assert "rules.json" in X.stale_reason(st, hist, False, False, [rules])
    old = time.time() - 3600
    os.utime(rules, (old, old))
    assert X.stale_reason(st, hist, False, False, [rules]) is None
    assert "different builds" in X.stale_reason(st, {"built": "x"}, False, False, [rules])
    assert "fixture" in X.stale_reason(st, hist, True, False, [rules])


# 16 ---------------------------------------------------------------- privacy scrub

def test_strip_personal_recurses_and_scrubs_text():
    out = common.strip_personal({
        "details": {"contactEmail": "x@example.invalid", "FirstName": "Ann", "last_name": "Lee",
                    "steps": [{"note": "Call 555-555-1212 or (413) 555-1212; mail ann.lee@town.gov"}]},
        "comments": "Call 555-555-1212", "reporterClass": "Permittee", "permit": "MA0101613",
        "volume": "1,200,000", "id": "2031521141906769", "date": "2026-10-01"})
    assert "contactEmail" not in out["details"] and "FirstName" not in out["details"] and "last_name" not in out["details"]
    assert out["details"]["steps"][0]["note"] == "Call [phone removed] or [phone removed]; mail [email removed]"
    assert out["comments"] == "Call [phone removed]" and out["reporterClass"] == "Permittee"
    assert out["permit"] == "MA0101613" and out["volume"] == "1,200,000" and out["id"] == "2031521141906769"
    assert out["date"] == "2026-10-01"


# 17 ---------------------------------------------------------------- volumes

@pytest.mark.parametrize("text,expected", [
    ("35.5 MG", (35_500_000, "estimated")), ("1,200,000 gallons", (1_200_000, "unknown")), ("75236", (75236, "unknown")),
    ("10,000-50,000", (None, "estimated")), ("10 to 50 million gallons", (None, "estimated")),
    ("<100", (None, "estimated")), ("approximately 1-2 MG", (None, "estimated")), ("over 300,000 gallons", (None, "estimated")),
    ("-200 gallons", (None, "unknown")), ("1e6 gallons", (1_000_000, "unknown")), ("2.5e-1 MG", (250_000, "estimated")),
    ("80 mgd", (None, "unknown")), ("approx. 5000 gal", (5000, "estimated")), (-5, (None, "unknown")),
])
def test_parse_volume_gal(text, expected):
    assert common.parse_volume_gal(text) == expected


# NH follow-ups -------------------------------------------------------------------------------

def test_a_failed_permittee_makes_its_waters_stale():
    e = ev("m", source_id="nh-permittees", status="ended", started_at=iso(NOW - 300 * H), ended_at=iso(NOW - 299 * H))
    d = tmp_events([])
    (d / "nh-permittees.json").write_text(json.dumps({
        "source_id": "nh-permittees", "ok": True, "last_ok_at": iso(NOW),
        "meta": {"partial_failures": {"Manchester": {"discharger_id": "nh-manchester", "npdes_permit": "NH0100447",
                                                     "event_id_prefix": "nh-permittees:m", "water_slugs": ["test-bay-ma"],
                                                     "error": "HTTP 503", "failed_at": iso(NOW),
                                                     "last_ok_at": iso(NOW - 30 * H)}}},
        "records": [e]}))
    st, _ = S.build(now=NOW, write=False, **world(d))
    for slug in ("test-river-ma", "test-bay-ma"):
        w = st["waters"][slug]
        assert w["stale"] and "Manchester: HTTP 503" in w["stale_sources"][0]["reason"]


def test_a_bounded_end_counts_windows_from_the_bound():
    bound = NOW - 10 * H
    e = ev("ac", status="ended", reported_at=iso(NOW - 2 * H), time_precision="bound",
           raw={"_ended_before": iso(bound)})
    assert colour(e, NOW) == ("red", ["authority_window"])                 # 48 h from the bound
    assert colour(e, bound + 49 * H)[0] == "yellow"
    st, _ = S.build(now=NOW, write=False, **world(tmp_events([e])))
    assert "ended by" in st["waters"]["test-river-ma"]["reason_short"]


def test_a_dischargers_red_window_beats_the_states():
    rules = json.loads(json.dumps(TEST_RULES))
    rules["red"]["by_state"]["PA"] = {"hours": None, "basis": "no stated period", "source": "pa"}
    rules["red"]["by_discharger"] = {"pa-alcosan": {"hours": 48, "clock": "end_of_discharge", "basis": "ALCOSAN log",
                                                    "source": "ALCOSAN"}, "_example": {"hours": 1}}
    e = ev("a", status="ended", started_at=iso(NOW - 12 * H), ended_at=iso(NOW - 10 * H), discharger_id="pa-alcosan")
    r = S.red_rule_for(e, "PA", rules)
    assert r["rule"] == "red.by_discharger.pa-alcosan" and r["hours"] == 48
    c, ivs = S.status_at(S.event_intervals(e, "PA", NOW, rules=rules), NOW)
    assert c == "red" and ivs[0]["rule_applied"]["rule"] == "red.by_discharger.pa-alcosan"
    other = ev("b", status="ended", started_at=iso(NOW - 12 * H), ended_at=iso(NOW - 10 * H), discharger_id="pa-other")
    assert S.red_rule_for(other, "PA", rules)["rule"] == "red.by_state.PA"
    assert S.status_at(S.event_intervals(other, "PA", NOW, rules=rules), NOW)[0] == "yellow"   # PA: no window
    stated = ev("c", status="ended", started_at=iso(NOW - 12 * H), ended_at=iso(NOW - 10 * H),
                discharger_id="pa-alcosan", advice_window_hours=24)
    assert S.red_rule_for(stated, "PA", rules)["rule"] == "red.event"
    pub = X.public_rules(rules)
    assert pub["red"]["by_discharger"] == {"pa-alcosan": rules["red"]["by_discharger"]["pa-alcosan"]}
    assert X.publicize({"red_rule": {**r}})["red_rule"]["rules_ref"] == "red.by_discharger.pa-alcosan"


def test_new_jersey_works_without_code_changes():
    rules = json.loads(json.dumps(TEST_RULES))
    rules["red"]["by_state"]["NJ"] = {"hours": None, "basis": "no stated period", "source": "nj"}
    w = world(tmp_events([]))
    w["waters"]["passaic-river-nj"] = {"slug": "passaic-river-nj", "name": "Passaic River", "kind": "river",
                                       "state": "NJ", "towns": ["Newark"], "bbox": [-74.2, 40.7, -74.1, 40.8]}
    e = ev("nj1", source_id="nj-dep", status="ended", npdes_permit="NJ0021016", water_slugs=[],
           waterbody_text="PASSAIC RIVER", started_at=iso(NOW - 6 * H), ended_at=iso(NOW - 4 * H))
    w["events_dir"] = tmp_events([e])
    st, _ = S.build(now=NOW, write=False, rules=rules, **{k: v for k, v in w.items() if k != "rules"})
    assert "NJ" in S.states() and S.event_state(e) == "NJ"
    assert st["placements"]["nj-dep:nj1"]["water_slugs"] == ["passaic-river-nj"]
    river = st["waters"]["passaic-river-nj"]
    assert river["state"] == "NJ" and river["reasons"][0]["red_rule"]["rule"] == "red.by_state.NJ"
    assert river["status"] == "yellow"                 # NJ: no authority window, so caution after the end
    assert st["counts"]["waters"]["NJ"] == {"yellow": 1}
