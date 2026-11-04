"""The "discharge likely; no report received" caution (docs/rain-likely.md): thresholds from the
permittees' own reports (build/rain_thresholds.py), the radar and forecast readings
(ingest/rainfall.py) and the rule in build/status.py via build/rain_likely.py, with synthetic
rainfall. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import re
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import rain_likely as RL  # noqa: E402
from build import rain_thresholds as RT  # noqa: E402
from build import status as S  # noqa: E402
from common import DATA_DIR, event  # noqa: E402
from export import build as X  # noqa: E402
from ingest import rainfall as RF  # noqa: E402
from tests.test_status import TEST_RULES, _reach, ev, iso, tmp_events, world  # noqa: E402

H = timedelta(hours=1)
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
PERMIT = "MA0101613"
N = 90 * 24
RAIN_RULES = {**TEST_RULES, "rain_likely": {
    "enabled": True, "label": "Discharge likely: heavy rain, no report received", "tail_hours": 48,
    "notice_suppress_hours": 24, "rainfall_stale_hours": 3, "doc": "public explanation", "source": "sources",
    "fallback": {"default": {"inches": 0.1, "basis": "dry day", "source": "permit"},
                 "by_state": {"RI": {"inches": 0.5, "basis": "RIDEM", "source": "ridem"},
                              "ME": {"inches": 1.0, "basis": "MHB", "source": "mhb"}}}}}


@pytest.fixture(autouse=True)
def _rules(monkeypatch):
    monkeypatch.setattr(S, "_RULES", TEST_RULES)


def rain_input(values: dict[int, float], threshold=0.3, permit=PERMIT, now=NOW, h24=None, qpf=0.5, fetched=None):
    """values: {hours before now (0 = this hour): 24-hour total}; the series starts 90 days back."""
    start = now - (N - 1) * H
    arr = [None] * N
    for back, v in values.items():
        arr[N - 1 - back] = v
    cur = arr[-1] if h24 is None else h24
    fetched = fetched or now
    return {"rainfall": {"fetched_at": iso(fetched), "ok": True, "last_ok_at": iso(fetched),
                         "mrms": {"valid_time": iso(fetched), "points": 2},
                         "permits": {permit: {"name": "Test Water and Sewer", "state": permit[:2], "valid_time": iso(now),
                                              "h24": cur, "h6": cur, "h24_point": "42.00,-72.00", "qpf_24h_in": qpf,
                                              "outfalls": [{"outfall": "020", "water_slug": "other-pond-ma",
                                                            "water_match": "geometry+name", "point": "42.10,-72.00"}]}}},
            "history": {"start": iso(start), "permits": {permit: arr}},
            "thresholds": {"permits": {permit: {"threshold_in": threshold, "basis": "history",
                                                "rule": "rain_likely.percentile", "basis_text": "p10 of 50 days",
                                                "n_discharge_days": 50, "since": "2022-07-02", "until": "2026-07-31"}}}}


def rain_world(events=(), **kw):
    w = world(tmp_events(list(events)))
    w["reaches"] = {"MA0101613-13": _reach()}
    w["outfalls"] = [{"npdes_permit": PERMIT, "outfall": "013", "state": "MA", "water_slug": "test-river-ma",
                      "outfall_status": "CSO"}]
    w["rain"] = rain_input(**kw)
    w["rules"] = RAIN_RULES
    return w


def wet(hours_above: range, v=1.2, dry_after=True, dry=0.0):
    """A storm: the 24-hour total at v for the given hours back, dry before and after."""
    vals = {b: dry for b in range(0, 200)}
    for b in hours_above:
        vals[b] = v
    return vals


# ---------------------------------------------------------------- thresholds from the reports

def test_parse_rain_keeps_only_plain_plausible_numbers():
    assert RT.parse_rain("0.43") == 0.43 and RT.parse_rain(".5") == 0.5 and RT.parse_rain("1 in") == 1.0
    assert RT.parse_rain("0.00") == 0.0 and RT.parse_rain(2) == 2.0
    for bad in ("", None, "-1.00", "trace", "0.5-0.7", "35.52", "n/a"):
        assert RT.parse_rain(bad) is None, bad
    assert RT.percentile([0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1], 0.10) == 0.2
    assert RT.percentile([], 0.1) is None
    assert RT.outfall_key("SPR010") == "010" and RT.outfall_key("HOL08") == "008" and RT.outfall_key("SPR015A") == "015A"


def _vdr(i, day, rain, et="cso", oid="SPR010", cls="Verified Data Report"):
    return event(source_id="ma-massdep", source_record_id=f"r{i}", event_type=et, status="ended",
                 npdes_permit="MA0000001", discharger_name="TEST CITY", outfall_id=oid,
                 started_at=f"{day}T10:00:00-04:00", ended_at=f"{day}T12:00:00-04:00",
                 raw={"_report_class": cls, "rainfallData": rain})


def test_history_threshold_dry_days_and_attestations():
    recs = [_vdr(i, f"2025-06-{i + 1:02d}", f"{0.1 * (i + 1):.2f}") for i in range(12)]   # 0.10 .. 1.20 in
    recs += [_vdr(20, "2025-06-20", "-1.00"),                     # kept as text, not a sample
             _vdr(21, "2025-06-21", "0.00"),                      # a dry-weather discharge
             _vdr(22, "2025-06-22", "0.05", et="sso"),            # marks the day, gives no sample
             _vdr(23, "2025-07-04", "", cls="Public Notification Report")]   # July is not closed
    no_events = [{"npdes_permit": "MA0000001", "month": "Aug", "year": "2025"}]
    h = RT.history(recs, no_events, date(2026, 1, 1))["MA0000001"]
    values = sorted(h["rain_by_day"].values())
    assert len(values) == 12 and RT.threshold_from(values, 10) == RT.percentile(values, 0.1) == 0.21
    assert RT.threshold_from(values[:9], 10) is None              # too few days: the published fallback
    assert h["unparsed"] == [{"event_id": "ma-massdep:r20", "text": "-1.00"}]
    assert h["zero_days"] == {date(2025, 6, 21)}
    # June: 30 days less 15 notice days; July is not closed (no verified report, no attestation); August attested
    assert len(h["dry_days"]) == (30 - 15) + 31
    assert date(2025, 7, 10) not in h["dry_days"] and date(2025, 8, 10) in h["dry_days"]
    assert h["last_closed"] == date(2025, 8, 31) and h["first"] == date(2025, 6, 1)
    per = h["outfalls"]["010"]
    assert len(per) == 12 and h["outfall_first"]["010"] == date(2025, 6, 1)


def test_fallback_thresholds_follow_the_published_rules():
    assert RL.threshold_for("RI0100315", "RI", {}, RAIN_RULES)["threshold_in"] == 0.5
    assert RL.threshold_for("ME0100145", "ME", {}, RAIN_RULES)["threshold_in"] == 1.0
    t = RL.threshold_for("CT0100056", "CT", {}, RAIN_RULES)
    assert t["threshold_in"] == 0.1 and t["rule"] == "rain_likely.fallback.default" and t["basis"] == "published"
    own = RL.threshold_for(PERMIT, "MA", rain_input({})["thresholds"], RAIN_RULES)
    assert own["threshold_in"] == 0.3 and own["basis"] == "history"
    assert RT.fallback_for("RI", RAIN_RULES)["threshold_in"] == 0.5


# ---------------------------------------------------------------- the rule in time

def test_runs_open_drop_tail_stale_and_merge():
    start = NOW - 9 * H
    vals = [0.0, 0.4, 0.5, 0.2, None, None, 0.0, 0.0, 0.0, 0.0]    # above at -8 and -7, below from -6
    r = RL.runs(vals, start, 0.3, NOW)
    assert len(r) == 1 and r[0]["start"] == NOW - 8 * H and r[0]["dropped_at"] == NOW - 6 * H
    assert r[0]["end"] == NOW - 6 * H + 48 * H and r[0]["peak"] == 0.5
    open_ = RL.runs([0.0, 0.4, 0.6], NOW - 2 * H, 0.3, NOW)
    assert open_[0]["end"] is None                                    # still above at the latest reading
    stale = RL.runs([0.0, 0.4, 0.6, None, None, None, None, None], NOW - 7 * H, 0.3, NOW)
    assert stale[0]["end"] == NOW - 5 * H + 48 * H and stale[0]["rainfall_stale"]
    two = RL.runs([0.5, 0.0, 0.0, 0.5, 0.0], NOW - 4 * H, 0.3, NOW)  # a second storm inside the tail
    assert len(two) == 1 and two[0]["start"] == NOW - 4 * H and two[0]["end"] == NOW + 48 * H


def test_subtract_cuts_notice_windows_out():
    a, b = NOW - 10 * H, NOW + 10 * H
    assert RL.subtract(a, b, [(NOW - 2 * H, NOW + 22 * H)]) == [(a, NOW - 2 * H)]
    assert RL.subtract(a, None, [(NOW - 2 * H, NOW + 22 * H)]) == [(a, NOW - 2 * H), (NOW + 22 * H, None)]
    assert RL.subtract(a, b, []) == [(a, b)]


# ---------------------------------------------------------------- the rule on the map

def test_heavy_rain_colours_the_permittees_reach_river_and_pond_yellow():
    st, hist = S.build(now=NOW, write=False, **rain_world(values=wet(range(0, 6))))
    river, pond = st["waters"]["test-river-ma"], st["waters"]["other-pond-ma"]
    assert river["status"] == "yellow" and river["fill"] is False
    r = river["reasons"][0]
    assert r["rule"] == "rain_likely" and r["placement"] == "reach" and r["reach"] == "MA0101613-13"
    assert r["rule_applied"]["rule"] == "rain_likely" and r["until"] is None          # open while above
    assert r["rain"]["threshold_in"] == 0.3 and r["rain"]["peak_24h_in"] == 1.2 and r["rain"]["permit"] == PERMIT
    assert r["short"].startswith("Discharge likely: heavy rain, no report received")
    assert pond["status"] == "yellow" and pond["fill"] is True and pond["reasons"][0]["placement"] is None
    assert st["reaches"]["MA0101613-13"]["status"] == "yellow"
    assert st["reaches"]["MA0101613-13"]["active"] == [] and st["reaches"]["MA0101613-13"]["rain_likely"]
    assert st["reach_events_active"] == []                         # no discharge, no travel band
    blk = st["rain_likely"]
    assert blk["permits"][PERMIT]["status"] == "likely" and blk["counts"]["likely_now"] == 1
    assert hist["waters"]["other-pond-ma"][-6:] == "y" * 6 and hist["waters"]["other-pond-ma"][-8] == "g"
    assert pond["rain"]["rain_24h_in"] == 1.2 and pond["rain"]["rain_expected"] is True
    assert st["sources"][RL.SOURCE_ID]["stale"] is False and RL.SOURCE_ID in pond["covered_by"]


def test_valid_until_48_hours_after_the_total_drops_below_the_threshold():
    vals = wet(range(20, 30))                                      # above 29 to 20 hours ago, below from 19 h ago
    st, _ = S.build(now=NOW, write=False, **rain_world(values=vals))
    r = st["waters"]["other-pond-ma"]["reasons"][0]
    assert r["rule"] == "rain_likely" and r["until"] == iso(NOW - 19 * H + 48 * H).replace("+00:00", "Z")
    assert r["rain"]["dropped_below_at"] == S.iso(NOW - 19 * H)
    vals = wet(range(50, 60))                                      # dropped below 49 hours ago: over
    st, _ = S.build(now=NOW, write=False, **rain_world(values=vals))
    assert st["waters"]["other-pond-ma"]["status"] == "grey"
    assert st["rain_likely"]["permits"][PERMIT]["status"] == "below"


def test_rain_below_the_threshold_sets_nothing():
    st, _ = S.build(now=NOW, write=False, **rain_world(values=wet(range(0, 6), v=0.29)))
    assert "other-pond-ma" in st["waters"] and st["waters"]["other-pond-ma"]["status"] == "grey"
    assert st["waters"]["other-pond-ma"]["rain"]["rain_24h_in"] == 0.29


def test_a_notice_started_in_the_last_24_hours_suppresses_it():
    notice = ev("n", status="ongoing", started_at=iso(NOW - 3 * H), npdes_permit=PERMIT, outfall_id="SPR099",
                water_slugs=["test-bay-ma"])
    st, _ = S.build(now=NOW, write=False, **rain_world([notice], values=wet(range(0, 10))))
    assert st["waters"]["other-pond-ma"]["status"] == "grey"
    assert not any(r["rule"] == "rain_likely" for r in st["waters"]["test-river-ma"]["reasons"])
    p = st["rain_likely"]["permits"][PERMIT]
    assert p["status"] == "suppressed" and p["suppressed_by"] == ["ma-test:n"]
    assert st["waters"]["test-bay-ma"]["status"] == "red"               # the notice itself
    # 25 hours after the notice began, with the rain total still high, the caution is back
    old = ev("n", status="ended", started_at=iso(NOW - 25 * H), ended_at=iso(NOW - 24 * H), npdes_permit=PERMIT,
             water_slugs=["test-bay-ma"])
    st, _ = S.build(now=NOW, write=False, **rain_world([old], values=wet(range(0, 30))))
    assert st["waters"]["other-pond-ma"]["reasons"][0]["rule"] == "rain_likely"
    assert st["waters"]["other-pond-ma"]["reasons"][0]["from"] == S.iso(NOW - H)


def test_a_notice_from_another_permittee_does_not_suppress_it():
    other = ev("o", status="ongoing", started_at=iso(NOW - 3 * H), npdes_permit="MA0101630", water_slugs=["test-bay-ma"])
    st, _ = S.build(now=NOW, write=False, **rain_world([other], values=wet(range(0, 10))))
    assert st["waters"]["other-pond-ma"]["status"] == "yellow"


def test_a_lake_matched_by_distance_alone_is_not_filled():
    w = rain_world(values=wet(range(0, 6)))
    w["rain"]["rainfall"]["permits"][PERMIT]["outfalls"][0]["water_match"] = "geometry"
    w["outfalls"].append({"npdes_permit": PERMIT, "outfall": "021", "water_slug": "big-lake-ma", "match": "geometry",
                          "distance_m": 132, "outfall_status": "CSO"})
    st, _ = S.build(now=NOW, write=False, **w)
    assert "other-pond-ma" not in st["waters"] and "big-lake-ma" not in st["waters"]
    assert st["waters"]["test-river-ma"]["status"] == "yellow"              # the reach still carries it
    aside = st["rain_likely"]["permits"][PERMIT]["set_aside"]
    assert {a["water_slug"] for a in aside} == {"other-pond-ma", "big-lake-ma"}
    w["outfalls"][-1]["distance_m"] = 0                                 # an outfall in the lake: filled
    st, _ = S.build(now=NOW, write=False, **w)
    assert st["waters"]["big-lake-ma"]["status"] == "yellow" and st["waters"]["big-lake-ma"]["fill"] is True


def test_it_never_overrides_red():
    red = ev("p", status="ongoing", started_at=iso(NOW - 2 * H), npdes_permit="MA0101630", water_slugs=["other-pond-ma"])
    st, hist = S.build(now=NOW, write=False, **rain_world([red], values=wet(range(0, 10))))
    pond = st["waters"]["other-pond-ma"]
    assert pond["status"] == "red" and pond["reasons"][0]["rule"] == "ongoing"
    assert [r["rule"] for r in pond["reasons"]] == ["ongoing", "rain_likely"]
    assert hist["waters"]["other-pond-ma"][-2:] == "rr" and hist["waters"]["other-pond-ma"][-5] == "y"


def test_disabled_rule_changes_nothing():
    w = rain_world(values=wet(range(0, 10)))
    w["rules"] = TEST_RULES
    st, _ = S.build(now=NOW, write=False, **w)
    assert st["rain_likely"]["enabled"] is False
    assert st["waters"] == {} and st["reaches"] == {}


def test_stale_rainfall_closes_an_open_episode_and_flags_the_source():
    vals = {b: 1.2 for b in range(6, 12)}                          # last reading 6 hours ago, above
    w = rain_world(values=vals, fetched=NOW - 6 * H)
    st, _ = S.build(now=NOW, write=False, **w)
    r = st["waters"]["other-pond-ma"]["reasons"][0]
    assert r["rule"] == "rain_likely" and r["until"] == S.iso(NOW - 6 * H + 48 * H) and r["rain"]["rainfall_stale"]
    assert st["sources"][RL.SOURCE_ID]["stale"] is True


# ---------------------------------------------------------------- the export

def test_active_json_lists_the_episode_with_its_own_kind_and_rules_ref():
    st, _ = S.build(now=NOW, write=False, **rain_world(values=wet(range(0, 6))))
    active_now = {}
    for slug, w in st["waters"].items():
        for r in w["reasons"]:
            active_now.setdefault(r["event_id"], []).append({"water": slug, "status": r["status"], "rule": r["rule"],
                                                             "from": r["from"], "until": r["until"],
                                                             "rule_applied": r["rule_applied"], "rain": r.get("rain")})
    rows = X.publicize(X.active_entries(active_now, {}, st["rain_likely"]))
    assert len(rows) == 1 and rows[0]["kind"] == "rain_likely" and rows[0]["npdes_permit"] == PERMIT
    assert rows[0]["event_id"].startswith("rain_likely:MA0101613:") and rows[0]["file"] is None
    assert set(rows[0]["water_slugs"]) == {"test-river-ma", "other-pond-ma"}
    ra = rows[0]["reasons"][0]["rule_applied"]
    assert ra["rules_ref"] == "rain_likely" and "rationale" not in ra and "source" not in ra
    pub = X.public_rain(st["rain_likely"])
    assert pub["permits"][PERMIT]["threshold_in"] == 0.3 and "problems" not in pub
    assert X.internal_wording(X.publicize(pub)) == []


def test_rules_json_enables_it_in_public_words_with_the_configured_numbers():
    rules = json.loads((DATA_DIR / "rules.json").read_text())
    rl = rules["rain_likely"]
    assert rl["enabled"] is True and rl["label"] == "Discharge likely: heavy rain, no report received"
    assert {int(n) for n in re.findall(r"(\d+) hours", rl["tail_rationale"])} == {rl["tail_hours"]}
    assert {int(n) for n in re.findall(r"(\d+) hours", rl["notice_suppress_rationale"])} == {rl["notice_suppress_hours"]}
    assert f"{rl['percentile']}th percentile" in rl["threshold_rationale"]
    assert str(rl["min_discharge_days"]) in rl["threshold_rationale"]
    fb = rl["fallback"]
    assert fb["default"]["inches"] == 0.1 and fb["by_state"]["RI"]["inches"] == 0.5 and fb["by_state"]["ME"]["inches"] == 1.0
    for f in [fb["default"], *fb["by_state"].values()]:
        assert f["basis"] and f["source"]


# ---------------------------------------------------------------- the readings

def test_identify_answer_pairs_values_with_their_windows():
    names = ["conus_QPE_01H", "conus_QPE_03H", "conus_QPE_06H", "conus_QPE_12H", "conus_QPE_24H", "conus_QPE_48H",
             "conus_QPE_72H"]
    d = {"properties": {"Values": ["0.1", "0.3", "0.5", "0.9", "1.25", "1.6", "-3"]},
         "catalogItems": {"features": [{"attributes": {"name": n, "idp_validendtime": 1786377600000}} for n in names]}}
    m = RF.parse_identify(d)
    assert (m["h1"], m["h6"], m["h24"], m["h48"], m["h72"]) == (0.1, 0.5, 1.25, 1.6, None)
    assert m["valid_time"] == "2026-08-10T16:00:00Z" and m["problems"] == []
    d["properties"]["Values"] = ["2.0", "0.3", "0.5", "0.9", "1.25", "1.6", "1.7"]
    assert "mispaired" in RF.parse_identify(d)["problems"][0]
    sample_path = DATA_DIR.parent / "research/hydrography/raw/mrms-qpe-identify-springfield.json"
    if sample_path.exists():   # research/*/raw/ is git-ignored: the saved MRMS answer is only on the machine that fetched it
        sample = json.loads(sample_path.read_text())
        assert RF.parse_identify(sample)["h24"] == 0.0


def test_one_identify_call_per_point_per_hour():
    t = datetime(2026, 8, 10, 12, 30, tzinfo=UTC)
    assert not RF.needs_mrms({"fetched_at": "2026-08-10T12:06:00Z"}, t, False)
    assert RF.needs_mrms({"fetched_at": "2026-08-10T11:58:00Z"}, t, False)
    assert not RF.needs_mrms({"fetched_at": "2026-08-10T12:01:00Z"}, datetime(2026, 8, 10, 12, 3, tzinfo=UTC), False)
    assert RF.needs_mrms(None, t, False) and RF.needs_mrms({"fetched_at": "2026-08-10T12:06:00Z"}, t, True)
    pts = RF.group_points([{"permit": "A", "outfall": "1", "state": "MA", "lat": 42.1012, "lon": -72.5904, "source": "x"},
                           {"permit": "B", "outfall": "2", "state": "MA", "lat": 42.1049, "lon": -72.5851, "source": "x"}])
    assert list(pts) == ["42.10,-72.59"] and pts["42.10,-72.59"]["permits"] == ["A", "B"]


def test_forecast_sums_the_next_24_hours_in_proportion():
    now = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
    vals = [["2026-08-10T06:00:00+00:00", "PT12H", 25.4],             # half of it after now: 0.5 in
            ["2026-08-10T18:00:00+00:00", "PT6H", 12.7],              # all of it: 0.5 in
            ["2026-08-11T06:00:00+00:00", "P1D", 25.4],               # 6 of 24 h inside: 0.25 in
            ["2026-08-12T00:00:00+00:00", "PT6H", 99.0]]              # outside
    q = RF.qpf_next(vals, now)
    assert q["in_24h"] == 1.25 and q["covered_hours"] == 18.0           # 00:00-06:00 on the 11th has no period
    assert RF.parse_duration("P1DT6H") == timedelta(hours=30) and RF.parse_duration("bad") is None


def test_history_aligns_hours_and_fills_the_implied_earlier_windows():
    now = datetime(2026, 8, 10, 12, 10, tzinfo=UTC)
    h = RF.update_history(None, {PERMIT: {"valid_time": "2026-08-10T12:00:00Z", "h24": 0.4, "h48": 1.0, "h72": 1.1}}, now)
    arr = h["permits"][PERMIT]
    assert len(arr) == 90 * 24 and arr[-1] == 0.4 and arr[-25] == 0.6 and arr[-49] == 0.1
    later = now + 2 * H
    h2 = RF.update_history(h, {PERMIT: {"valid_time": "2026-08-10T14:00:00Z", "h24": 0.5, "h48": 0.9, "h72": 1.2}}, later)
    arr2 = h2["permits"][PERMIT]
    assert arr2[-1] == 0.5 and arr2[-3] == 0.4 and arr2[-2] is None and arr2[-27] == 0.6   # shifted by 2 hours
    assert arr2[-25] == 0.4                                     # an empty implied window is filled
