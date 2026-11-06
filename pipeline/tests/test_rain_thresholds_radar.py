"""Operator rain triggers from the radar on reported discharge days (Georgia, Michigan): build/rain_thresholds.py
radar_* and merge_radar, on fixtures. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import rain_likely as RL  # noqa: E402
from build import rain_thresholds as RT  # noqa: E402
from common import DATA_DIR  # noqa: E402

TODAY = date(2026, 11, 6)
RULES = {"rain_likely": {"fallback": {"default": {"inches": 0.1, "basis": "default", "source": "methods",
                                                  "trigger_basis": "default"}, "by_state": {}}}}


def rec(permit, day, etype="cso", outfall="001", dup=None, discharger=None):
    return {"event_id": f"x:{permit}:{day}:{outfall}", "npdes_permit": permit, "discharger_id": discharger,
            "event_type": etype, "started_at": f"{day}T03:15:00-05:00", "outfall_id": outfall, "duplicate_of": dup}


def test_discharge_days_are_start_days_of_the_states_cso_reports_without_copies():
    recs = [rec("MI0000001", "2020-06-01"), rec("MI0000001", "2020-06-01", outfall="002"),
            rec("MI0000001", "2020-06-02", dup="x:other"),                 # a copy is not a second discharge
            rec("MI0000001", "2020-06-03", etype="sso"),                   # not the type asked for
            rec(None, "2020-06-04", discharger="mi-glwa"),                 # filed by name: its operator's only permit
            rec(None, "2020-06-05", discharger="mi-two"),                  # two permits: never a guess
            rec("GA0000001", "2020-06-06"),                                # another state
            rec("MI0000001", "2014-12-31"),                                # before the first day read
            rec("MI0000001", TODAY.isoformat())]                           # today is not a whole day yet
    days = RT.radar_discharge_days(recs, "MI", ("cso",), {"mi-glwa": ["MI0000001"], "mi-two": ["MI1", "MI2"]}, TODAY,
                                   RT.RADAR_FIRST_DAY)
    assert set(days) == {"MI0000001"}
    assert days["MI0000001"] == {date(2020, 6, 1): {"001", "002"}, date(2020, 6, 4): {"001"}}
    assert RT.RADAR_FIRST_DAY == date(2015, 1, 1)


def test_a_discharge_day_reads_the_larger_of_its_own_and_the_day_befores_radar_total():
    s = {date(2020, 6, 1): 0.8, date(2020, 6, 2): 0.02, date(2020, 6, 4): 0.3}
    assert RT.day_radar(s, date(2020, 6, 2)) == 0.8            # the storm the evening before
    assert RT.day_radar(s, date(2020, 6, 4)) == 0.3            # the day before has no value: the day itself
    assert RT.day_radar(s, date(2020, 6, 3)) is None           # the day itself has none: missing, not zero


def test_permits_by_discharger_lists_every_permit_of_a_row():
    rows = [{"id": "a", "npdes_permit": "MI1", "npdes_permits": ["MI1", "MI2"]}, {"id": "b", "npdes_permit": "GA1"}]
    by = RT.permits_by_discharger(rows)
    assert by == {"a": ["MI1", "MI2"], "b": ["GA1"]}
    assert RT.record_permit({"discharger_id": "a"}, by) is None and RT.record_permit({"discharger_id": "b"}, by) == "GA1"


def _days(n, start=date(2016, 5, 1)):
    return {start + timedelta(days=7 * i): {"001"} for i in range(n)}


def test_radar_row_takes_the_10th_percentile_of_days_with_radar_rain_and_counts_the_rest():
    days = _days(14)
    ds = sorted(days)
    vals = [0.05, 0.12, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.2]
    series = {d: v for d, v in zip(ds, vals)}
    series[ds[12]] = 0.0                       # no radar rain that day or the day before: counted, not a sample
    # ds[13]: no value at all
    r = RT.radar_row("MI0000001", "Test City", "MI", days, series, 10, (42.3, -83.1), 3)
    assert r["n_start_days"] == 14 and r["n_discharge_days"] == 12
    assert r["n_no_radar_rain_days"] == 1 and r["n_no_radar_value_days"] == 1
    assert r["threshold_in"] == r["p10"] == RT.percentile(vals, 0.10) == 0.13
    assert r["p5"] == RT.percentile(vals, 0.05) and r["under_0_1_in"] == 1 and r["share_under_0_1_in"] == round(1 / 12, 3)
    assert r["since"] == ds[0].isoformat() and r["until"] == ds[11].isoformat()
    assert r["basis"] == "history" and r["rule"] == "rain_likely.percentile" and r["threshold_kind"] == "operator_history"
    assert r["source"] == ("NOAA MRMS radar at the operator's outlets on its reported discharge days, "
                           "EGLE MiEnviro list 2016 to 2016")
    assert "12 days" in r["basis_text"] and "nine discharge days in ten" in r["basis_text"]


def test_under_ten_days_with_radar_rain_keeps_the_published_rule():
    days = _days(12)
    series = {d: (0.0 if i < 3 else 0.5) for i, d in enumerate(sorted(days))}     # 9 samples
    r = RT.radar_row("GA0000001", "Test", "GA", days, series, 10, (33.7, -84.4), 1)
    assert r["threshold_in"] is None and r["basis"] is None and "9 discharge days" in r["why_fallback"]
    assert "source" not in r


class FakeResp:
    def __init__(self, code=200, text=None):
        self.status_code, self.text = code, text or json.dumps(
            {"data": [{"date": "2016-01-01", "mrms_precip_in": 0.25, "prism_precip_in": 0.2, "daily_high_f": 30}]})

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeSession:
    def __init__(self, codes):
        self.codes, self.urls = list(codes), []

    def get(self, url, **kw):
        self.urls.append(url)
        return FakeResp(self.codes.pop(0))


@pytest.fixture
def iem_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(RT, "IEM_DIR", tmp_path)
    monkeypatch.setattr(RT, "IEM_PAUSE_S", 0)
    return tmp_path


def test_iem_daily_keeps_a_compact_cache_and_counts_requests(iem_dir):
    b = RT.RequestBudget(5)
    s = FakeSession([200])
    out = RT.iem_daily(42.0, -83.0, [2016], session=s, budget=b)
    assert out == {date(2016, 1, 1): 0.25} and b.used == 1
    saved = json.loads((iem_dir / "42.00_-83.00_2016.json").read_text())
    assert saved["data"] == [{"date": "2016-01-01", "mrms_precip_in": 0.25, "prism_precip_in": 0.2}]
    assert RT.iem_daily(42.0, -83.0, [2016], session=FakeSession([]), budget=b) == out and b.used == 1   # cached


def test_iem_daily_stops_at_the_budget_and_on_a_refusal(iem_dir):
    with pytest.raises(RT.BudgetSpent):
        RT.iem_daily(42.0, -83.0, [2016, 2017], session=FakeSession([200, 200]), budget=RT.RequestBudget(1))
    with pytest.raises(RT.ServiceRefused):
        RT.iem_daily(43.0, -83.0, [2016], session=FakeSession([429]), budget=RT.RequestBudget(5))
    assert not (iem_dir / "43.00_-83.00_2016.json").exists()
    with pytest.raises(RT.ServiceRefused):
        RT.iem_daily(44.0, -83.0, [2016, 2017, 2018], session=FakeSession([404, 404, 404]), budget=RT.RequestBudget(5))
    # without a budget (the hourly Massachusetts build) a failure is printed and passed over, as before
    assert RT.iem_daily(45.0, -83.0, [2016], session=FakeSession([429])) == {}


def _world(tmp_path, monkeypatch, series_value=lambda d: 0.3):
    reg = {"MI0000001": {"state": "MI", "name": "TEST CSO", "points": [(42.31, -83.12), (42.33, -83.14)], "outfalls": {}},
           "MI0000002": {"state": "MI", "name": "SMALL CSO", "points": [(43.0, -84.0)], "outfalls": {}}}
    monkeypatch.setattr(RT, "cso_permittees", lambda: reg)
    monkeypatch.setattr(RT, "permits_by_discharger", lambda rows=None: {})
    monkeypatch.setattr(RT, "_discharger_names", lambda: {"MI0000001": {"id": "mi-test", "name": "City of Test"}})
    asked = []

    def fake_iem(lat, lon, years, offline=False, session=None, budget=None):
        asked.append((lat, lon, tuple(years)))
        budget.take()
        return {date(2016, 1, 1) + timedelta(days=i): series_value(i) for i in range(400)}
    monkeypatch.setattr(RT, "iem_daily", fake_iem)
    recs = [rec("MI0000001", (date(2016, 1, 1) + timedelta(days=i)).isoformat()) for i in range(0, 120, 6)]
    recs += [rec("MI0000002", "2016-02-01"), rec("MI0000009", "2016-02-02")]        # few days; no registered outfall
    p = tmp_path / "mi.json"
    p.write_text(json.dumps({"fetched_at": "2026-11-04T14:15:07Z", "records": recs}))
    monkeypatch.setattr(RT, "RADAR_FILE", tmp_path / "rain-thresholds-radar.json")
    return p, asked


def test_radar_build_reads_registered_operators_at_their_median_point_and_writes_the_file(tmp_path, monkeypatch):
    p, asked = _world(tmp_path, monkeypatch)
    d = RT.radar_build(["MI"], budget=10, events={"MI": p}, today=TODAY)
    assert asked == [(42.32, -83.13, (2015, 2016))]   # one operator with 10+ days (and the day before its first)
    r = d["permits"]["MI0000001"]
    assert r["threshold_in"] == 0.3 and r["n_discharge_days"] == 20 and r["name"] == "City of Test"
    assert d["permits"]["MI0000002"]["threshold_in"] is None
    assert d["permits"]["MI0000002"]["why_fallback"] == "1 discharge days (fewer than 10): the radar was not read"
    assert d["not_registered"] == {"MI0000009": {"state": "MI", "name": None, "n_start_days": 1}}
    assert d["requests"] == 1 and d["with_threshold"] == 1 and d["states"]["MI"]["records"] == 22
    assert json.loads(RT.RADAR_FILE.read_text())["permits"]["MI0000001"]["threshold_in"] == 0.3


def test_only_combined_sewer_reports_name_an_unregistered_operator(tmp_path, monkeypatch):
    p, _ = _world(tmp_path, monkeypatch)
    recs = json.loads(p.read_text())["records"] + [rec("GA0000009", "2026-01-05", etype="sso"),
                                                     rec("GA0000008", "2026-01-06", etype="cso")]
    p.write_text(json.dumps({"records": recs}))
    d = RT.radar_build(["MI", "GA"], budget=10, events={"MI": p, "GA": p}, today=TODAY)
    assert set(d["not_registered"]) == {"MI0000009", "GA0000008"}       # a sanitary spill names no CSO operator


def test_radar_build_writes_nothing_when_the_budget_runs_out(tmp_path, monkeypatch):
    p, _ = _world(tmp_path, monkeypatch)
    with pytest.raises(RT.BudgetSpent):
        RT.radar_build(["MI"], budget=0, events={"MI": p}, today=TODAY)
    assert not RT.RADAR_FILE.exists()


def test_merge_lays_the_radar_figure_over_the_fallback_but_never_over_reported_rainfall():
    permits = {"MA0101613": {"basis": "history", "threshold_in": 0.1},
               "MI0000001": {"basis": "published", "threshold_in": 0.1, "rule": "rain_likely.fallback.default"}}
    radar = {"permits": {
        "MA0101613": {"state": "MA", "threshold_in": 0.5, "basis": "history"},
        "MI0000001": {"permit": "MI0000001", "state": "MI", "threshold_in": 0.33, "basis": "history",
                      "rule": "rain_likely.percentile", "basis_text": "p10", "source": "NOAA MRMS radar ...",
                      "n_discharge_days": 120, "since": "2001-01-03", "until": "2026-10-30"},
        "MI0000002": {"state": "MI", "threshold_in": None, "basis": None}}}
    assert RT.merge_radar(permits, radar, {"MI0000001": {}}, RULES) == 1
    assert permits["MA0101613"]["threshold_in"] == 0.1
    assert permits["MI0000001"]["threshold_in"] == 0.33 and permits["MI0000001"]["fallback_in"] == 0.1
    assert "MI0000002" not in permits
    t = RL.threshold_for("MI0000001", "MI", {"permits": permits}, RULES)
    assert t["kind"] == "operator_history" and t["trigger_basis"] == "operator" and t["threshold_in"] == 0.33
    assert RL.LABELS[t["trigger_basis"]] == "Discharge likely: heavy rain, no report received"
    assert t["source"] == "NOAA MRMS radar ..." and t["n_discharge_days"] == 120


def test_the_hourly_build_merges_the_tracked_radar_file(tmp_path, monkeypatch):
    from build import status as S
    monkeypatch.setattr(RT, "EVENTS_DIR", tmp_path)            # no Massachusetts records
    monkeypatch.setattr(RT, "cso_permittees", lambda: {"GA0000001": {"state": "GA", "name": "T", "points": [(33.7, -84.4)],
                                                                     "outfalls": {}}})
    monkeypatch.setattr(S, "load_rules", lambda: RULES)
    f = tmp_path / "radar.json"
    f.write_text(json.dumps({"permits": {"GA0000001": {"permit": "GA0000001", "state": "GA", "threshold_in": 0.42,
                                                       "basis": "history", "rule": "rain_likely.percentile"}}}))
    monkeypatch.setattr(RT, "RADAR_FILE", f)
    d = RT.build(offline=True, today=TODAY, write=False)
    assert d["permits"]["GA0000001"]["threshold_in"] == 0.42 and d["with_radar_history"] == 1
    assert d["with_history"] == 1


def test_the_tracked_radar_file_is_sound():
    """data/rain-thresholds-radar.json, as committed: every operator figure rests on 10 or more days, is their 10th
    percentile, names the radar and the list, and carries no field beyond the safe ones."""
    d = json.loads((DATA_DIR / "rain-thresholds-radar.json").read_text())
    safe = {"permit", "name", "state", "has_cso_outfalls", "per_24h", "compare_to", "n_start_days", "n_discharge_days",
            "n_no_radar_rain_days", "n_no_radar_value_days", "since", "until", "p5", "p10", "p25", "p50", "p90",
            "under_0_1_in", "share_under_0_1_in", "point", "n_outfall_points", "point_basis", "threshold_method",
            "threshold_in", "basis", "rule", "threshold_kind", "basis_text", "source", "why_fallback"}
    assert d["permits"]
    for p, r in d["permits"].items():
        assert set(r) <= safe, set(r) - safe
        assert r["state"] in RT.RADAR_STATES and p.startswith(r["state"])
        if r["threshold_in"] is not None:
            assert r["n_discharge_days"] >= d["min_days"] and r["threshold_in"] == r["p10"] >= RT.TRACE_IN
            assert r["source"].startswith("NOAA MRMS radar at the operator's outlets on its reported discharge days, ")
            assert RT.RADAR_STATES[r["state"]]["list"] in r["source"]
        else:
            assert r["n_discharge_days"] < d["min_days"]


def test_rules_json_says_how_the_radar_amounts_are_made_and_cites_the_list():
    rl = json.loads((DATA_DIR / "rules.json").read_text())["rain_likely"]
    assert "Michigan" in rl["threshold_rationale"] and "radar" in rl["threshold_rationale"]
    assert "Massachusetts" in rl["threshold_rationale"] and "10th percentile" in rl["threshold_rationale"]
    assert "MiEnviro" in rl["threshold_source"] and "MRMS" in rl["threshold_source"]
    assert "MiEnviro" in rl["source"]
