"""build/rain_history.py: synthetic histories with known answers (no network, no real data/build)."""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

import pytest

from build import rain_history as R
from build.rain_thresholds import BudgetSpent

CFG = R.settings({})
D0 = date(2019, 1, 1)


def series(sizes, start=D0, step=5):
    """A daily record with one wet day every `step` days (the rest dry, 0.0): [(storm day, size)]."""
    daily, days = {}, []
    d = start
    for s in sizes:
        for i in range(step):
            daily[d + timedelta(days=i)] = 0.0
        daily[d] = s
        days.append(d)
        d += timedelta(days=step)
    return daily, days


def span(d0, d1=None, outfall=None, precision="minute"):
    return {"first": d0, "last": d1 or d0, "outfall": outfall, "precision": precision, "source_id": "x"}


def an(h, **kw):
    daily, spans, end, today = h
    return R.analyse(daily, spans, end, CFG, today, **kw)


def history(sizes, followed, start=D0, step=5, outfall=None):
    """(daily, spans, coverage_end, today) for storms of the given sizes, a report on each storm marked followed."""
    daily, days = series(sizes, start, step)
    spans = [span(d, outfall=outfall) for d, f in zip(days, followed) if f]
    end = days[-1] + timedelta(days=step)
    return daily, spans, end, end + timedelta(days=CFG["lag_days"])


# ---------------------------------------------------------------- storms and followed

def test_storms_are_runs_sized_by_their_wettest_day_and_a_missing_day_ends_a_run():
    d = date(2024, 5, 1)
    daily = {d: 0.2, d + timedelta(1): 0.6, d + timedelta(2): 0.1, d + timedelta(3): 0.05,
             d + timedelta(4): 0.3, d + timedelta(6): 0.4, d + timedelta(7): 0.0}   # day 5 missing
    got = R.storms(daily, d, d + timedelta(7), 0.1)
    assert [(s["first"], s["last"], s["size"], s["peak_day"]) for s in got] == [
        (d, d + timedelta(2), 0.6, d + timedelta(1)),
        (d + timedelta(4), d + timedelta(4), 0.3, d + timedelta(4)),
        (d + timedelta(6), d + timedelta(6), 0.4, d + timedelta(6))]


def test_followed_takes_the_day_after_the_storm_and_no_later():
    d = date(2024, 5, 1)
    st = [{"first": d, "last": d + timedelta(1), "size": 0.5, "peak_day": d}]
    assert R.mark_followed(st, [span(d + timedelta(2))])[0]["followed"] is True      # the day after the last day
    assert R.mark_followed(st, [span(d + timedelta(3))])[0]["followed"] is False
    assert R.mark_followed(st, [span(d - timedelta(1))])[0]["followed"] is False
    # a report that spans days covers every one of them
    assert R.mark_followed(st, [span(d - timedelta(3), d)])[0]["followed"] is True


def test_report_spans_day_precision_keeps_the_day_and_a_long_report_is_capped_at_seven_days():
    recs = [{"event_type": "cso", "npdes_permit": "OH1", "time_precision": "day", "started_at": "2024-05-02",
             "ended_at": "2024-05-03"},
            {"event_type": "cso", "npdes_permit": "OH1", "started_at": "2024-06-01T10:00:00-05:00",
             "ended_at": "2024-07-01T10:00:00-05:00"}]
    got = R.report_spans(recs, lambda r: r["npdes_permit"])
    a, b = sorted(got["OH1"], key=lambda s: s["first"])
    assert (a["first"], a["last"], a["precision"]) == (date(2024, 5, 2), date(2024, 5, 3), "day")
    assert (b["first"], b["last"]) == (date(2024, 6, 1), date(2024, 6, 8))
    # the day-precision report matches a storm on the day before it (the one-day margin)
    st = [{"first": date(2024, 5, 1), "last": date(2024, 5, 1), "size": 0.4, "peak_day": date(2024, 5, 1)}]
    assert R.mark_followed(st, [a])[0]["followed"] is True


def test_report_spans_leaves_out_and_counts_what_is_not_a_dated_wet_report():
    base = {"npdes_permit": "MA1", "started_at": "2024-05-02T10:00:00-04:00"}
    recs = [{**base, "event_type": "sso"},                                        # not counted at all
            {**base, "event_type": "cso", "duplicate_of": "y"},
            {**base, "event_type": "cso", "time_precision": "month"},
            {**base, "event_type": "cso", "time_precision": "year"},
            {**base, "event_type": "cso", "outfall_id": "gate 1"},
            {"npdes_permit": "MA1", "event_type": "cso"},
            {**base, "event_type": "blended", "outfall_id": "SPR010"},
            # 11:30 p.m. Eastern on July 1 is 10:30 p.m. in Chicago: July 1, not the UTC date (July 2)
            {"npdes_permit": "MA1", "event_type": "cso", "started_at": "2024-07-02T03:30:00Z"}]
    got = R.report_spans(recs, lambda r: r["npdes_permit"], skip={("MA1", "GATE 1")})
    assert got[None]["MA1"] == {"copies": 1, "monthly_or_yearly": 2, "not_rain_driven": 1, "no_start": 1}
    assert sorted(s["first"] for s in got["MA1"]) == [date(2024, 5, 2), date(2024, 7, 1)]
    assert {s["outfall"] for s in got["MA1"]} == {"SPR010", None}


# ---------------------------------------------------------------- levels

def test_lowest_reported_is_the_smallest_followed_storm_rounded_down_to_a_rung():
    sts = [{"size": 0.9, "followed": True, "first": D0, "peak_day": D0},
           {"size": 0.35, "followed": True, "first": D0 + timedelta(9), "peak_day": D0 + timedelta(10)},
           {"size": 0.2, "followed": False, "first": D0, "peak_day": D0}]
    assert R.lowest_reported(sts, CFG["rungs_in"]) == {"size_in": 0.35, "day": "2019-01-11", "rounded_in": 0.25}
    assert R.lowest_reported([{**s, "followed": False} for s in sts], CFG["rungs_in"]) is None
    assert R.lowest_reported([{"size": 2.7, "followed": True, "first": D0, "peak_day": D0}],
                             CFG["rungs_in"])["rounded_in"] == 2.0


def band(lo, hi, n, k):
    return {"lo": lo, "hi": hi, "storms": n, "followed": k}


def test_likely_needs_the_band_share_and_the_share_of_all_larger_storms():
    # 0.25 band reaches half (6 of 10) but with everything larger only 23 of 50: not likely there
    bands = [band(0.1, 0.25, 20, 2), band(0.25, 0.5, 10, 6), band(0.5, 1.0, 30, 8), band(1.0, None, 10, 9)]
    assert R.likely_from(bands, 0.1, CFG) == 1.0
    # with the larger storms over half too, the 0.25 band sets it
    bands[2] = band(0.5, 1.0, 30, 20)
    assert R.likely_from(bands, 0.1, CFG) == 0.25
    # never below the possible amount
    assert R.likely_from(bands, 0.5, CFG) == 0.5


def test_thin_bands_are_pooled_downward_and_none_reaching_half_gives_none():
    bands = [band(0.1, 0.25, 20, 2), band(0.25, 0.5, 15, 3), band(0.5, 0.75, 4, 4), band(0.75, 1.0, 3, 3),
             band(1.0, None, 5, 5)]
    pooled = R.pool_thin(bands, 10)
    assert [(b["lo"], b["hi"], b["storms"], b["followed"]) for b in pooled] == [
        (0.1, 0.25, 20, 2), (0.25, 0.5, 15, 3), (0.5, None, 12, 12)]
    assert R.likely_from(bands, 0.1, CFG) == 0.5
    assert R.likely_from([band(0.1, 0.25, 20, 2), band(0.25, None, 40, 19)], 0.1, CFG) is None


def test_a_thin_bottom_remainder_joins_the_band_above():
    pooled = R.pool_thin([band(0.1, 0.25, 3, 0), band(0.25, None, 12, 6)], 10)
    assert [(b["lo"], b["storms"]) for b in pooled] == [(0.1, 15)]


# ---------------------------------------------------------------- the quiet range

def quiet_case(n_small, small_followed=0, step=16):      # step 16: 69 storms or more span three years
    sizes, followed = [], []
    for i in range(max(n_small, 40)):
        if i < 40:
            sizes.append(0.6)
            followed.append(True)
        if i < n_small:
            sizes.append(0.15)
            followed.append(i < small_followed)
    return history(sizes, followed, step=step)


def test_thirty_small_storms_in_under_three_years_are_not_enough():
    a = an(quiet_case(30, step=7))          # 70 storms a week apart: 490 days of record
    assert a["usable"] and a["possible_in"] == 0.5
    assert a["quiet"]["storms"] == 30 and a["quiet"]["followed"] == 0 and a["quiet"]["enough"] is False


def test_thirty_small_storms_none_followed_is_enough_to_show_no_caution_below():
    a = an(quiet_case(30))
    assert a["usable"] and a["possible_in"] == 0.5 and a["lowest_reported"]["size_in"] == 0.6
    assert a["quiet"] == {"lo": 0.1, "hi": 0.5, "storms": 30, "followed": 0, "share": 0.0, "enough": True}
    assert a["likely_in"] == 0.5 and a["possible"] is None and a["likely"]["storms"] == 40


def test_twenty_nine_small_storms_are_not_enough():
    a = an(quiet_case(29))
    assert a["usable"] and a["quiet"]["storms"] == 29 and a["quiet"]["enough"] is False


def test_one_followed_storm_in_the_quiet_range_moves_possible_down_to_it():
    a = an(quiet_case(40, small_followed=1))
    assert a["possible_in"] == 0.1 and a["quiet"] is None
    assert a["possible"] == {"lo": 0.1, "hi": 0.5, "storms": 40, "followed": 1, "share": 0.025}


# ---------------------------------------------------------------- usable minimums

def test_each_minimum_fails_with_its_reason():
    a = an(history([0.5] * 30, [True] * 9 + [False] * 21))
    assert not a["usable"] and a["why_not"] == "9 storms followed by a report; 10 are needed"
    assert "possible_in" not in a
    a = an(history([0.5] * 15, [True] * 15))
    assert a["why_not"] == "15 storms on record; 20 are needed"
    a = an(history([0.5] * 25, [True] * 25, step=4))
    assert a["why_not"] == "101 days of record; 365 are needed"
    a = an(history([0.5] * 80, [True] * 80))
    assert a["usable"] and a["why_not"] is None


def test_no_report_in_the_period_says_why():
    daily, _ = series([0.5] * 10)
    a = R.analyse(daily, [span(date(2012, 3, 1))], date(2020, 1, 1), CFG, date(2020, 2, 1))
    assert not a["usable"] and "before 2015" in a["why_not"]


# ---------------------------------------------------------------- the period of record

def test_a_reporting_gap_is_left_out_not_counted_as_quiet():
    # 60 storms reported, then 90 storms (450 days) with no report at all, then 60 reported again
    sizes = [0.5] * 210
    followed = [True] * 60 + [False] * 90 + [True] * 60
    daily, spans, end, today = history(sizes, followed)
    a = R.analyse(daily, spans, end, CFG, today)
    gap = [x for x in a["left_out"] if x["why"] == "reporting_gap"]
    assert len(gap) == 1 and gap[0]["storms"] >= 85
    assert a["storms"] < 130 and a["followed"] == 120


def year_storms(y0, y1, share, per_year=40, size=0.5):
    sizes, followed, days = [], [], []
    for y in range(y0, y1 + 1):
        for i in range(per_year):
            days.append(date(y, 1, 3) + timedelta(days=i * 8))
            sizes.append(size)
            followed.append((i % 10) < share * 10)
    return days, sizes, followed


def build_daily(days, sizes, extra=()):
    daily = {}
    d = min(days)
    while d <= max(days) + timedelta(days=10):
        daily[d] = 0.0
        d += timedelta(days=1)
    for d, s in list(zip(days, sizes)) + list(extra):
        daily[d] = s
    return daily


def test_reports_more_frequent_later_leave_the_earlier_years_out_of_the_shares_only():
    d1, s1, f1 = year_storms(2016, 2018, 0.1)
    d2, s2, f2 = year_storms(2019, 2022, 0.9)
    days, sizes, followed = d1 + d2, s1 + s2, f1 + f2
    small = date(2016, 6, 1)                     # a small storm in the early years, followed by a report
    daily = build_daily(days, sizes, [(small, 0.12)])
    spans = [span(d) for d, f in zip(days, followed) if f] + [span(small)]
    a = R.analyse(daily, spans, date(2022, 12, 31), CFG, date(2023, 2, 1))
    cut = [x for x in a["left_out"] if x["why"] == "reported_less_before"]
    assert cut and cut[0]["to"] == "2018-12-31" and a["period"][0] == "2019-01-01"
    assert a["storms"] == 160 and a["notes"] == []
    assert a["lowest_reported"]["size_in"] == 0.12 and a["possible_in"] == 0.1


def test_reports_less_frequent_later_are_a_note_and_nothing_is_cut():
    d1, s1, f1 = year_storms(2016, 2019, 0.9)
    d2, s2, f2 = year_storms(2020, 2022, 0.1)
    days, sizes, followed = d1 + d2, s1 + s2, f1 + f2
    daily = build_daily(days, sizes)
    spans = [span(d) for d, f in zip(days, followed) if f]
    a = R.analyse(daily, spans, date(2022, 12, 31), CFG, date(2023, 2, 1))
    assert [x for x in a["left_out"] if x["why"] != "reporting_gap"] == []
    assert a["notes"] and a["notes"][0]["what"] == "reported_less_since" and a["notes"][0]["year"] == 2020
    assert a["notes"][0]["z"] < 0 and a["storms"] == 280


def test_a_cited_change_starts_the_record_at_the_change():
    daily, spans, end, today = history([0.5] * 300, [True] * 300)
    cut = date(2020, 1, 1)
    a = R.analyse(daily, spans, end, CFG, today, cuts=[{"from": cut, "what": "tunnel", "source": "https://x"}])
    assert a["record_from"] == "2020-01-01" and a["period"][0] == "2020-01-01"
    assert a["left_out"][0] == {"from": "2019-01-01", "to": "2019-12-31", "why": "system_change_cited",
                                "what": "tunnel", "source": "https://x"}
    late = R.analyse(daily, spans, end, CFG, today, cuts=[{"from": today, "what": "x", "source": "y"}])
    assert not late["usable"] and "too recent" in late["why_not"]


# ---------------------------------------------------------------- rain points, outfalls

def test_rain_points_start_at_the_median_and_add_far_outfalls_only():
    pts = [(42.10, -72.60), (42.11, -72.60), (42.12, -72.61), (42.50, -72.60), (42.10, -73.20), (42.13, -72.62),
           (42.12, -72.61)]
    got = R.rain_points(pts)
    assert got[0] == (42.12, -72.61)        # the median over every outfall point, repeats included
    assert set(got[1:]) == {(42.5, -72.6), (42.1, -73.2)} and len(got) == 3
    assert R.rain_points([(42.1, -72.6), (42.12, -72.61)]) == [(42.11, -72.6)]
    many = [(40 + i, -80.0) for i in range(8)]
    assert len(R.rain_points(many)) == 4 and len(R.rain_points(many, max_points=2)) == 2
    assert R.rain_points([]) == []


def test_outfall_counts_use_only_the_reports_that_name_the_outfall():
    sizes = [0.6, 0.15] * 40
    daily, days = series(sizes)
    big = days[0::2]
    spans = [span(d, outfall="SPR010") for d in big] + [span(d, outfall="SPR012") for d in big[20:30]]
    end = days[-1] + timedelta(days=5)
    a = R.analyse(daily, spans, end, CFG, end + timedelta(days=14))
    sts = a.pop("_storms")
    out = R.outfall_evidence(spans, sts, a, CFG)
    assert set(out) == {"010", "012"}
    assert out["010"]["reports"] == 40 and out["010"]["followed"] == 40 and out["010"]["storms"] == 80
    assert out["012"]["followed"] == 10 and out["012"]["likely"] == {"lo": 0.5, "hi": None, "storms": 40, "followed": 10}
    assert out["012"]["lowest_reported"]["rounded_in"] == 0.5
    # reports that seldom name an outfall: no per-outfall record
    unnamed = [{**s, "outfall": None} for s in spans[:30]] + spans[30:]
    assert R.outfall_evidence(unnamed, sts, a, CFG) is None


# ---------------------------------------------------------------- the daily pass

TODAY = date(2026, 11, 14)
NOW = datetime(2026, 11, 14, 12, 0, tzinfo=UTC)


def records_for(permit, days, outfall="CSO1"):
    return [{"event_type": "cso", "npdes_permit": permit, "outfall_id": outfall,
             "started_at": f"{d.isoformat()}T12:00:00-05:00"} for d in days]


def pass_inputs(n_permits=3):
    """Permits P0..P{n-1}, each with 80 storms all reported; P9 with none."""
    sizes = [0.6] * 80
    daily, days = series(sizes, start=date(2024, 1, 1), step=7)
    recs = []
    outfalls = [{"permit": "P9", "lat": 40.0, "lon": -80.0, "name": "No Reports", "state": "OH"}]
    for i in range(n_permits):
        recs += records_for(f"P{i}", days)
        outfalls.append({"permit": f"P{i}", "lat": 41.0 + i, "lon": -80.0, "name": f"Op {i}", "state": "OH"})
    return daily, recs, outfalls


def run_pass(tmp_path, reader, have=lambda *a: True, prev=None, budget=100, **kw):
    daily, recs, outfalls = pass_inputs()
    kw.setdefault("rules", {})
    return R.build(budget=budget, today=TODAY, now=NOW, sources=[("oh-src", recs)], outfalls=outfalls, skip=set(),
                   prev=prev or {}, by_discharger={}, reader=reader, have=have, live_history={},
                   out_path=tmp_path / "rain-levels.json", **kw)


def test_the_pass_gives_every_permit_an_entry_and_writes_sorted_keys(tmp_path):
    daily, _, _ = pass_inputs()
    d = run_pass(tmp_path, lambda lat, lon, years, offline, budget: daily)
    assert sorted(d["permits"]) == ["P0", "P1", "P2", "P9"]
    p0 = d["permits"]["P0"]
    assert p0["usable"] and p0["sources"] == [{"source_id": "oh-src", "reports": 80, "first": "2024-01-01",
                                               "last": p0["sources"][0]["last"], "coverage_end": p0["sources"][0]["last"]}]
    assert p0["points"] == [[41.0, -80.0]] and "_storms" not in p0 and p0["outfalls"] is not None
    assert d["permits"]["P9"]["why_not"] == R.NO_REPORT and not d["permits"]["P9"]["usable"]
    assert d["counts"] == {"permits": 4, "usable": 3, "with_quiet_range": 0, "never_likely": 0}
    text = (tmp_path / "rain-levels.json").read_text()
    assert json.loads(text) == d and list(json.loads(text)) == sorted(json.loads(text))
    assert not (tmp_path / "rain-levels.json.tmp").exists()
    assert d["crosscheck"]["comparisons"] == 0 and d["crosscheck"]["note"]


def test_a_spent_budget_keeps_the_previous_entries_and_marks_the_rest_not_read(tmp_path):
    daily, _, _ = pass_inputs()
    calls = []

    def reader(lat, lon, years, offline, budget):
        if not offline:
            calls.append(lat)
            if len(calls) > 1:
                raise BudgetSpent("spent")
        return daily
    old = {"permit": "P1", "usable": True, "computed": "2026-11-01", "marker": "kept"}
    prev = {"method_version": R.METHOD_VERSION, "permits": {"P1": old}}
    d = run_pass(tmp_path, reader, have=lambda lat, lon, years: lat == 41.0, prev=prev)
    assert d["permits"]["P0"]["usable"] and d["permits"]["P0"]["computed"] == "2026-11-14"
    assert d["permits"]["P1"] == old
    assert d["permits"]["P2"]["why_not"] == R.NOT_READ and not d["permits"]["P2"]["usable"]
    assert d["run"]["stopped"].startswith("BudgetSpent") and d["run"]["not_read"] == 2
    # a previous file of another method version gives nothing to keep
    d = run_pass(tmp_path, reader, have=lambda *a: False, prev={**prev, "method_version": 0})
    assert d["permits"]["P1"]["why_not"] == R.NOT_READ


def test_operators_already_in_the_cache_are_still_read_after_the_budget_is_spent(tmp_path):
    daily, _, _ = pass_inputs()

    def reader(lat, lon, years, offline, budget):
        if not offline:
            raise BudgetSpent("spent")
        return daily
    d = run_pass(tmp_path, reader, have=lambda *a: True)
    assert all(d["permits"][p]["usable"] for p in ("P0", "P1", "P2")) and d["run"]["not_read"] == 0


def test_cited_changes_come_from_the_rules(tmp_path):
    daily, _, _ = pass_inputs()
    rules = {"rain_likely": {"history": {"system_changes": {
        "P0": [{"from": "2024-06-01", "what": "storage tunnel in service", "source": "https://example.org"}]}}}}
    d = run_pass(tmp_path, lambda *a: daily, rules=rules)
    assert d["permits"]["P0"]["record_from"] == "2024-06-01"
    assert d["permits"]["P0"]["left_out"][0]["why"] == "system_change_cited"
    assert d["permits"]["P1"]["record_from"] == "2024-01-01"


def test_the_crosscheck_compares_each_chicago_midnight_with_the_day_that_ends_then():
    start = datetime(2026, 11, 3, 0, tzinfo=UTC)
    values = [None] * 72
    values[6] = 0.6       # 06:00Z Nov 3 = midnight in Chicago (CST): the 24 hours of Nov 2
    values[30] = 0.0      # midnight Nov 4: Nov 3 (record 0.02): neither reaches 0.05, not compared
    values[54] = 0.1      # midnight Nov 5: Nov 4 (record 0.2): live lower
    hist = {"start": "2026-11-03T00:00:00Z", "step_hours": 1, "permits": {"P0": values, "P1": [0.3] * 72}}
    daily = {"P0": {date(2026, 11, 2): 0.3, date(2026, 11, 3): 0.02, date(2026, 11, 4): 0.2}}
    x = R.crosscheck(hist, daily)
    assert (x["comparisons"], x["live_higher"], x["operators"]) == (2, 1, 1)
    assert x["median_live_over_record"] == 1.25 and x["from"] == "2026-11-03T06:00:00Z"
    assert R.crosscheck(hist, daily, since=start + timedelta(hours=12))["comparisons"] == 1
    assert R.crosscheck(None, daily)["comparisons"] == 0
    assert "no day" in R.crosscheck(hist, {})["note"]


def test_if_older_h_does_nothing_while_the_build_copy_is_young(tmp_path, monkeypatch):
    p = tmp_path / "rain-levels.json"
    monkeypatch.setattr(R, "LEVELS_BUILD", p)
    monkeypatch.setattr(R, "build", lambda **kw: (_ for _ in ()).throw(AssertionError("build ran")))
    p.write_text(json.dumps({"method_version": R.METHOD_VERSION, "built": (datetime.now(UTC) - timedelta(hours=3))
                             .strftime("%Y-%m-%dT%H:%M:%SZ"), "permits": {}}))
    assert R.main(["--if-older-h", "20"]) == 0
    assert R.fresh_enough(20, p) and not R.fresh_enough(2, p)
    p.write_text(json.dumps({"method_version": 0, "built": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")}))
    assert not R.fresh_enough(20, p)
    with pytest.raises(AssertionError, match="build ran"):
        R.main(["--if-older-h", "20"])


def test_load_levels_prefers_the_build_copy_of_this_method_version(tmp_path):
    b, s = tmp_path / "build.json", tmp_path / "seed.json"
    s.write_text(json.dumps({"method_version": R.METHOD_VERSION, "permits": {"S": {}}}))
    assert R.load_levels(b, s)["permits"] == {"S": {}}
    b.write_text(json.dumps({"method_version": R.METHOD_VERSION, "permits": {"B": {}}}))
    assert R.load_levels(b, s)["permits"] == {"B": {}}
    b.write_text(json.dumps({"method_version": R.METHOD_VERSION + 1, "permits": {"B": {}}}))
    assert R.load_levels(b, s)["permits"] == {"S": {}}
    b.write_text("{not json")
    assert R.load_levels(b, s)["permits"] == {"S": {}}
    s.unlink()
    assert R.load_levels(b, s) is None
