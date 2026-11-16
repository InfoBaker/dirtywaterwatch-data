"""The rain caution for separate sewers (build/rain_sso.py; owner, 2026-11-16): the test and its pinned parameters, each
guard, the placement, the caution in time, the switch, and the combined sewer caution unchanged byte for byte."""
from __future__ import annotations

import copy
import json
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from build import rain_likely as RL  # noqa: E402
from build import rain_sso as SS  # noqa: E402
from build import status as S  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RULES = json.loads((ROOT / "data" / "rules.json").read_text())
TODAY = date(2026, 11, 16)
NOW = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
GRADES = {"AL": "Dated reports", "TX": "Dated reports, delayed"}


def rules_on(**over) -> dict:
    r = copy.deepcopy({"rain_likely": RULES["rain_likely"]})
    ss = r["rain_likely"]["separate_sewers"]
    ss.update(enabled=True, approved=["al-wet", "al-dry", "tx-wet", "al-gone", "al-stale"], **over)
    return r


# ---------------------------------------------------------------- a synthetic record

def rain_days() -> dict[date, float]:
    """A storm of 1.2 inches every 6th day, a 0.3-inch day every 9th, dry otherwise, 2023 to today."""
    out, d, i = {}, date(2023, 1, 1), 0
    while d <= TODAY:
        out[d] = 1.2 if i % 6 == 0 else 0.3 if i % 9 == 0 else 0.0
        d += timedelta(days=1)
        i += 1
    return out


DAILY = rain_days()
STORM_DAYS = sorted(d for d, v in DAILY.items() if v >= 1.0)
DRY_DAYS = sorted(d for d, v in DAILY.items() if v == 0.0 and DAILY.get(d - timedelta(days=1)) == 0.0
                  and DAILY.get(d - timedelta(days=2)) == 0.0)


def rec(eid, op, day, st="AL", water="town-creek-al", lat=33.84, lon=-87.28, et="sso", prec="day", **kw):
    return {"event_id": eid, "event_type": et, "started_at": day.isoformat(), "time_precision": prec,
            "discharger_id": op, "state": st, "lat": lat, "lon": lon, "source_id": "al-adem",
            "reported_at": (day + timedelta(days=1)).isoformat(), "water_slugs": [water] if water else [], **kw}


def records(until=TODAY - timedelta(days=20)) -> list[dict]:
    out = []
    for i, d in enumerate(d for d in STORM_DAYS[::2] if d <= until):              # rain-driven: after every other storm
        out.append(rec(f"w{i}", "al-wet", d, water="town-creek-al" if i % 3 else "mobile-bay-al",
                       lat=33.84 + (i % 4) * 0.001))
    for i, d in enumerate(d for d in DRY_DAYS[::3] if d <= until):                # blockages: on dry days
        out.append(rec(f"d{i}", "al-dry", d, water="dry-creek-al"))
    for i, d in enumerate(d for d in STORM_DAYS[::2] if d <= until):              # rain-driven, in a delayed state
        out.append(rec(f"t{i}", "tx-wet", d, st="TX", water="tx-creek"))
    for i, d in enumerate(d for d in STORM_DAYS[::2] if d <= date(2025, 6, 1)):   # rain-driven until mid-2025, then none
        out.append(rec(f"g{i}", "al-gone", d, water="gone-creek-al"))
    for i, d in enumerate(d for d in STORM_DAYS[::2] if d <= until):              # rain-driven, but none for 4 months
        if d > TODAY - timedelta(days=120):
            break
        out.append(rec(f"s{i}", "al-stale", d, water="stale-creek-al"))
    for i, d in enumerate(STORM_DAYS[::2][:40]):                                  # not in the approved set
        out.append(rec(f"x{i}", "al-other-person", d, water="x-creek-al"))
    out.append(rec("w-copy", "al-wet", STORM_DAYS[3], duplicate_of="w1"))
    out.append(rec("w-month", "al-wet", STORM_DAYS[5], prec="month"))
    out.append(rec("w-cso", "al-wet", DRY_DAYS[5], et="cso"))
    return out


def built(rules=None, grades=GRADES, recs=None):
    recs = records() if recs is None else recs
    reader = lambda lat, lon, years, offline, budget: dict(DAILY)          # noqa: E731
    return SS.build(offline=True, today=TODAY, now=NOW, sources=[("al-adem", recs)], rules=rules or rules_on(),
                    operator_of=lambda r: r.get("discharger_id"), placements={}, reader=reader,
                    have=lambda *a: True, grades=grades, write=False)


@pytest.fixture(scope="module")
def levels():
    return built()


# ---------------------------------------------------------------- the switch and the pinned test

def test_rules_pin_the_assessments_test_with_the_switch_off_and_the_owners_words():
    ss = RULES["rain_likely"]["separate_sewers"]
    assert ss["enabled"] is False and "live_states" not in ss
    assert "Yes, build the rain caution for those 28 operators" in ss["_enabled_rationale"] and "28" in ss["_approved_note"]
    assert "2026-11-16" in ss["_enabled_rationale"] and "2026-11-16" in ss["_approved_note"]
    cfg = SS.settings(RULES)
    assert cfg["min_lift"] == 1.5 and cfg["first_day"] == "2023-01-01" and cfg["event_types"] == ["sso"]
    assert cfg["recent_days"] == 365 and cfg["recent_min_followed"] == 1 and cfg["max_report_age_days"] == 90
    assert cfg["history_points"] == 1
    st = [op[:2] for op in ss["approved"]]
    assert len(ss["approved"]) == 28 and st.count("al") == 23 and st.count("ct") == 4 and st.count("fl") == 1
    for k in SS.DEFAULTS:
        if k not in ("enabled", "approved"):
            assert ss[k] == SS.DEFAULTS[k], k       # the code's defaults are the pinned values
    assert not SS.enabled(RULES)
    assert "no risk" not in json.dumps(ss).lower() and "safe" not in json.dumps(ss).lower()


def test_the_seed_file_reproduces_the_assessments_28_from_the_records():
    """data/rain-levels-sso.json, built by scripts/rain_sso_seed.py from the site's yearly exports of 2026-11-16 and
    the assessment's rain record: every approved operator passes the test itself (a usable history and a lift of 1.5
    or more); the guards decide the rest, each with its reason."""
    d = SS.load_levels(build_path=Path("/nonexistent"))
    assert d is not None and d["method_version"] == SS.METHOD_VERSION
    ops = d["operators"]
    assert set(ops) == set(RULES["rain_likely"]["separate_sewers"]["approved"])
    for op, e in ops.items():
        assert e["read"] and e["usable"] and e["lift"] >= 1.5, op
        assert e["qualifies"] == (not e["why_not"]), op
    assert all(set(e["why_not"]) <= {f"newest dated report ({e['newest_report']}) older than 90 days"}
               for e in ops.values())
    assert d["counts"]["qualify"] == sum(1 for e in ops.values() if e["qualifies"])
    assert "outside_the_set" in d["counts"] and len(ops) == 28       # no operator outside the set is named


# ---------------------------------------------------------------- the reports

def test_only_dated_sanitary_overflow_reports_from_the_first_day_count():
    cfg = SS.settings(rules_on())
    recs = [rec("a", "op", date(2024, 5, 1)), rec("b", "op", date(2022, 5, 1)), rec("c", "op", date(2024, 5, 2), prec="month"),
            rec("d", "op", date(2024, 5, 3), duplicate_of="a"), rec("e", "op", date(2024, 5, 4), et="cso"),
            rec("f", "op", date(2024, 5, 5), prec="bound"), rec("g", "op", date(2024, 5, 6))]
    spans, left = SS.sso_spans(recs, lambda r: r["discharger_id"], cfg, {"g": {"superseded": "a", "water_slugs": []}})
    assert [s["event_id"] for s in spans["op"]] == ["a"]
    assert left["op"] == {"before_first_day": 1, "not_dated_to_the_day": 2, "copies": 2}


def test_a_rain_driven_operator_qualifies_with_its_counts(levels):
    e = levels["operators"]["al-wet"]
    assert e["qualifies"] is True and e["why_not"] == [] and e["usable"] is True
    assert e["lift"] >= 1.5 and e["followed"] >= 10 and e["storms"] >= 20
    assert e["possible_in"] == 1.0 and e["recent"]["followed"] >= 1
    assert e["places"]["reports"] == e["reports"]        # every report followed rain
    assert {w["water_slug"] for w in e["places"]["waters"]} == {"town-creek-al", "mobile-bay-al"}
    assert e["not_used"] == {"copies": 1, "not_dated_to_the_day": 1}
    assert levels["counts"]["qualify"] == 1 and levels["counts"]["qualify_by_state"] == {"AL": 1}


def test_an_operator_whose_overflows_are_dry_weather_gets_nothing(levels):
    e = levels["operators"]["al-dry"]
    assert e["qualifies"] is False and e["lift"] < 1.0
    assert any(w.startswith("no strong rain signal") for w in e["why_not"])


def test_a_state_not_graded_dated_reports_gets_nothing(levels):
    e = levels["operators"]["tx-wet"]
    assert e["lift"] >= 1.5 and e["qualifies"] is False
    assert e["why_not"] == ['its state\'s reports grade "Dated reports, delayed", not "Dated reports"']


def test_with_no_grades_on_file_nothing_qualifies():
    d = built(grades={})
    assert d["counts"]["qualify"] == 0
    assert "the state's reporting grade is not on file yet" in d["operators"]["al-wet"]["why_not"]


def test_recency_a_repaired_system_drops_out(levels):
    e = levels["operators"]["al-gone"]
    assert e["lift"] >= 1.5 and e["recent"]["followed"] == 0 and e["qualifies"] is False
    assert any("last 365 days" in w for w in e["why_not"])


def test_freshness_an_operator_with_no_report_for_90_days_drops_out(levels):
    e = levels["operators"]["al-stale"]
    assert e["qualifies"] is False and e["recent"]["followed"] >= 1
    assert e["why_not"] == [f"newest dated report ({e['newest_report']}) older than 90 days"]


def test_an_operator_outside_the_approved_set_is_never_named(levels):
    assert "al-other-person" not in levels["operators"] and levels["counts"]["outside_the_set"] == 1
    assert "al-other-person" not in json.dumps(levels)


def test_a_source_published_in_batches_never_enters_a_history():
    assert SS.source_ok({"records": 5}, SS.settings(rules_on()), batches=True)
    recs = records()
    d = SS.build(offline=True, today=TODAY, now=NOW, sources=[("tx-batches", recs)], rules=rules_on(),
                 operator_of=lambda r: r.get("discharger_id"), placements={}, batches={"tx-batches": True},
                 reader=lambda *a: dict(DAILY), have=lambda *a: True, grades=GRADES, write=False)
    assert d["counts"]["qualify"] == 0 and d["operators"]["al-wet"]["reports"] == 0


# ---------------------------------------------------------------- where it goes

WATERS = {"town-creek-al": {"kind": "stream", "name": "Town Creek", "state": "AL"},
          "black-warrior-al": {"kind": "river", "name": "Black Warrior River", "state": "AL"},
          "mobile-bay-al": {"kind": "bay", "name": "Mobile Bay", "state": "AL"},
          "lake-x-al": {"kind": "reservoir", "name": "Lake X", "state": "AL"},
          "elsewhere-al": {"kind": "river", "name": "Elsewhere River", "state": "AL"}}


def entry_with(events):
    from collections import Counter
    c = Counter(w for ev in events for w in ev["water_slugs"])
    return {"places": {"events": events, "waters": [{"water_slug": w, "reports": n} for w, n in c.most_common()]}}


def test_placement_only_on_stretches_below_the_reported_points_and_tidal_waters_they_reached():
    evs = [{"event_id": "e1", "point": [33.84, -87.28], "water_slugs": ["town-creek-al"], "reaches": []},
           {"event_id": "e2", "point": [33.85, -87.28], "water_slugs": ["town-creek-al"], "reaches": []},
           {"event_id": "e3", "point": [30.6, -88.0], "water_slugs": ["mobile-bay-al"], "reaches": []},
           {"event_id": "e4", "point": [30.6, -88.0], "water_slugs": ["mobile-bay-al"], "reaches": []},
           {"event_id": "e5", "point": [33.0, -87.0], "water_slugs": ["lake-x-al"], "reaches": []},
           {"event_id": "e6", "point": [33.1, -87.0], "water_slugs": ["black-warrior-al"], "reaches": []}]
    reaches = {"pt-aaa": {"key": "pt-aaa", "segments": [{"x": 1}], "water_slug": "town-creek-al", "event_ids": ["e1", "e2"]},
               "pt-bbb": {"key": "pt-bbb", "segments": [], "cut_reason": "no_trace", "event_ids": ["e6"]},
               "other": {"key": "other", "segments": [{"x": 1}], "water_slug": "elsewhere-al", "event_ids": ["zz"]}}
    keys, tags, reach_of, named = SS.placement(entry_with(evs), WATERS, reaches,
                                               lambda r, w: ["town-creek-al", "black-warrior-al"] if r["key"] == "pt-aaa" else [])
    assert keys == ["pt-aaa"]
    assert tags == {"black-warrior-al": "reach", "mobile-bay-al": "tidal", "town-creek-al": "reach"}
    assert "elsewhere-al" not in tags and "lake-x-al" not in tags         # no report reached it / a whole lake
    why = {w["water_slug"]: w["why"] for w in named}
    assert why["lake-x-al"].startswith("a whole lake") and why["mobile-bay-al"].startswith("tidal")
    # with no stretch traced yet, a river reached is named and gets no mark (never the whole river)
    _, tags2, _, named2 = SS.placement(entry_with(evs[:2]), WATERS, {}, lambda r, w: [])
    assert tags2 == {} and named2[0]["why"] == "no downstream stretch traced yet from the reported points"
    # one report on a bay is not enough to mark it
    _, tags3, _, _ = SS.placement(entry_with(evs[2:3]), WATERS, {}, lambda r, w: [])
    assert tags3 == {}


def test_trace_points_ask_for_a_stretch_from_each_river_report_point():
    lv = {"method_version": 1, "operators": {"al-wet": {"qualifies": True, "possible_in": 0.1, "state": "AL", "places": {
        "events": [{"event_id": "e1", "point": [33.8401, -87.28], "water_slugs": ["town-creek-al"]},
                   {"event_id": "e2", "point": [33.8402, -87.28], "water_slugs": ["town-creek-al"]},
                   {"event_id": "e3", "point": [30.6, -88.0], "water_slugs": ["mobile-bay-al"]},
                   {"event_id": "e4", "point": None, "water_slugs": ["town-creek-al"]}]}}}}
    assert SS.trace_points(WATERS, {"rain_likely": RULES["rain_likely"]}, lv) == []          # switch off
    pts = SS.trace_points(WATERS, rules_on(), lv)
    assert len(pts) == 1 and pts[0]["key"] == SS.trace_key("e1") and pts[0]["event_ids"] == ["e1", "e2"]
    assert pts[0]["water_slug"] == "town-creek-al"
    from build import reaches as R
    import hashlib
    assert SS.trace_key("e1") == "pt-" + hashlib.sha1(b"e1").hexdigest()[:12]      # the key event_points gives
    assert "event_ids" in R.META_FIELDS


def test_live_points_only_with_the_switch_on(levels):
    assert SS.live_points({"rain_likely": RULES["rain_likely"]}, levels) == []
    pts = SS.live_points(rules_on(), levels)
    assert pts and {p["permit"] for p in pts} == {"sso:al-wet"} and all(p["source"] == SS.POINT_SOURCE for p in pts)


# ---------------------------------------------------------------- the caution in time

H = timedelta(hours=1)
N = 90 * 24


def rain_for(values: dict[int, float], key="sso:al-wet", now=NOW):
    start = now - (N - 1) * H
    arr = [None] * N
    for back, v in values.items():
        arr[N - 1 - back] = v
    return {"rainfall": {"fetched_at": S.iso(now), "ok": True, "mrms": {"valid_time": S.iso(now), "points": 1},
                         "permits": {key: {"name": "Wet Utilities", "state": "AL", "valid_time": S.iso(now), "h24": arr[-1],
                                           "h24_point": "33.84,-87.28", "read": "grid"}}},
            "history": {"start": S.iso(start), "permits": {key: arr}}, "thresholds": {"permits": {}}}


def storm(hours: range, v: float):
    vals = {b: 0.0 for b in range(0, 200)}
    for b in hours:
        vals[b] = v
    return vals


def run(levels, values, events=(), rules=None, grades=GRADES, placements=None):
    reaches = {"pt-1": {"key": "pt-1", "segments": [{"x": 1}], "water_slug": "town-creek-al",
                        "event_ids": [ev["event_id"] for ev in levels["operators"]["al-wet"]["places"]["events"]][:3]}}
    return SS.compute(rain_for(values), rules or rules_on(), list(events), NOW, NOW - timedelta(days=30),
                      {**WATERS, "dry-creek-al": {"kind": "stream", "name": "Dry Creek"}}, reaches,
                      lambda r, w: ["town-creek-al"], placements or {}, levels, grades)


def test_heavy_rain_sets_the_caution_on_the_stretch_with_its_evidence(levels):
    levels = copy.deepcopy(levels)
    levels["operators"]["al-wet"]["likely_in"] = None      # "possible" only, unless the record meets "likely"
    by_water, by_reach, blk = run(levels, storm(range(0, 6), 1.2))
    row = blk["operators"]["al-wet"]
    assert row["status"] == "likely" and row["level"] == "possible"         # no "likely" amount in this record
    assert row["label"] == "Discharge possible: heavy rain, no report received" == RULES["rain_likely"]["history"]["label_by_level"]["possible"]
    iv = by_reach["pt-1"][0]
    assert iv["rule"] == "rain_likely" and iv["color"] == "yellow" and iv["placement"] == "reach"
    assert set(by_water) == {"town-creek-al", "mobile-bay-al"}               # the stretch's water and the bay reached
    assert by_water["mobile-bay-al"][0]["placement"] == "tidal"
    assert "dry-creek-al" not in by_water                                   # another operator's water: nothing
    ev = iv["rain"]["evidence"]
    assert ev["basis"] == "separate_sewer_history" and ev["no_outfall"] is True
    assert ev["storms"] == levels["operators"]["al-wet"]["storms"] and ev["followed"] == levels["operators"]["al-wet"]["followed"]
    assert ev["period"] == levels["operators"]["al-wet"]["period"]
    r = iv["rain"]
    assert r["peak_24h_in"] == 1.2 and r["peak_at"] and r["valid_time"] and r["until"] is None
    assert r["until_rule"].startswith("48 hours after the 24-hour total falls below")
    assert set(blk["_episodes"]) == {iv["event_id"]} and iv["event_id"].startswith("rain_likely:sso:al-wet:")
    assert RL.short(iv).startswith("Discharge possible") and "separate sewer" in RL.short(iv)
    assert "radar peak 1.20 inches in the 24 hours to " + r["peak_at"][:16].replace("T", " ") + " UTC" in RL.short(iv)


def test_rain_below_the_operators_amount_sets_nothing(levels):
    by_water, by_reach, blk = run(levels, storm(range(0, 6), 0.5))
    assert by_water == {} and by_reach == {} and blk["operators"]["al-wet"]["status"] == "below"


def test_the_likely_level_only_where_the_record_meets_it(levels):
    lv = copy.deepcopy(levels)
    lv["operators"]["al-wet"]["likely_in"] = 1.0
    _, by_reach, blk = run(lv, storm(range(0, 6), 1.2))
    assert by_reach["pt-1"][0]["level"] == "likely" and blk["operators"]["al-wet"]["label"].startswith("Discharge likely")
    lv["operators"]["al-wet"]["likely_in"] = 1.5
    _, by_reach, blk = run(lv, storm(range(0, 6), 1.2))       # above the possible amount, below the likely one
    assert by_reach["pt-1"][0]["level"] == "possible"


def test_a_report_from_the_operator_holds_the_caution_back(levels):
    rep = {"event_id": "new-report", "event_type": "sso", "discharger_id": "al-wet", "started_at": S.iso(NOW - 2 * H),
           "time_precision": "minute"}
    _, _, blk = run(levels, storm(range(0, 6), 1.2), events=[rep])
    row = blk["operators"]["al-wet"]
    assert row["status"] == "suppressed" and row["suppressed_by"] == ["new-report"]
    other = {**rep, "event_id": "other", "discharger_id": "al-dry"}
    _, _, blk2 = run(levels, storm(range(0, 6), 1.2), events=[other])
    assert blk2["operators"]["al-wet"]["status"] == "likely"


def test_operators_that_fail_a_guard_get_nothing_and_say_why(levels):
    by_water, _, blk = run(levels, storm(range(0, 6), 1.2))
    assert set(blk["operators"]) == {"al-wet"}
    assert set(blk["not_covered"]) == {"al-dry", "tx-wet", "al-gone", "al-stale"}
    assert all(blk["not_covered"][op]["why_not"] for op in blk["not_covered"])
    # a grade that has dropped since the daily pass: the hourly check leaves it out too
    by_water2, _, blk2 = run(levels, storm(range(0, 6), 1.2), grades={"AL": "Dated reports, delayed"})
    assert by_water2 == {} and blk2["operators"] == {} and "al-wet" in blk2["not_covered"]
    by_water3, _, _ = run(levels, storm(range(0, 6), 1.2), grades=None if False else {})
    assert by_water3 == {}


def test_with_the_switch_off_nothing_is_computed(levels):
    rules = rules_on()
    rules["rain_likely"]["separate_sewers"]["enabled"] = False
    assert SS.qualifying(levels, rules) == {}
    by_water, by_reach, blk = run(levels, storm(range(0, 6), 1.2), rules=rules)
    assert by_water == {} and by_reach == {} and blk["operators"] == {}


def test_coverage_names_the_separate_sewer_operators_per_state(levels):
    _, _, blk = run(levels, storm(range(0, 6), 1.2))
    cov = RL.caution_coverage({"enabled": True, "permits": {}, "separate_sewers": blk})
    assert cov["AL"]["separate_sewers"]["operators"] == 1
    assert cov["AL"]["sentence"].startswith("Our rain caution here covers only one separate sewer operator")
    assert "no risk" not in cov["AL"]["sentence"] and "safe" not in cov["AL"]["sentence"]
    assert RL.caution_coverage({"enabled": True, "permits": {}}) == {}       # off: nothing added


# ---------------------------------------------------------------- the combined sewer caution, byte for byte

def test_combined_sewer_compute_is_unchanged_with_the_switch_on_and_sso_readings_present():
    """The fixture of test_rain_levels (the combined sewer caution's output before the levels, pinned rules): HEAD's
    compute gives it with the separate sewer switch on and an "sso:" operator's readings in the rainfall files."""
    from tests.test_rain_levels import BASELINE, baseline_cases
    fx = json.loads(BASELINE.read_text())
    rules = copy.deepcopy(fx["rules"])
    rules["rain_likely"]["separate_sewers"] = {**RULES["rain_likely"]["separate_sewers"], "enabled": True}
    for (now, rain, r, waters), want in zip(baseline_cases(rules), fx["cases"]):
        extra = rain_for(storm(range(0, 30), 2.0), now=now)
        rain["rainfall"]["permits"].update(extra["rainfall"]["permits"])
        rain["history"]["permits"]["sso:al-wet"] = extra["history"]["permits"]["sso:al-wet"][-len(
            next(iter(rain["history"]["permits"].values()))):]
        by_water, by_reach, block = RL.compute(copy.deepcopy(rain), r, [], now, now - timedelta(days=30), waters, [],
                                               {}, lambda a, b: [])
        got = json.loads(json.dumps({"by_water": by_water, "by_reach": by_reach, "block": block}, sort_keys=True,
                                    default=str))
        assert got == want


def _status(rules, levels=None, grades=None, sso=False):
    from tests.test_rain_likely import rain_input, rain_world, wet
    from tests.test_status import _reach
    w = rain_world(values=wet(range(0, 6)))
    w["rules"] = rules
    if sso:     # an active separate sewer caution beside the combined sewer one, on a stretch from its report point
        r = rain_input(wet(range(0, 4), v=0.9), permit="sso:al-wet")
        w["rain"]["rainfall"]["permits"]["sso:al-wet"] = r["rainfall"]["permits"]["sso:al-wet"]
        w["rain"]["history"]["permits"]["sso:al-wet"] = r["history"]["permits"]["sso:al-wet"]
        w["reaches"] = {**w["reaches"], "pt-sso1": {**_reach(key="pt-sso1"), "permit": None, "outfall": None,
                                                    "event_ids": ["sso-e1"]}}
    if levels is not None:
        w["rain"] = {**w["rain"], "levels_sso": levels, "grades_sso": grades}
    st, hist = S.build(now=datetime(2026, 8, 10, 12, 0, tzinfo=UTC), write=False, **w)
    return json.loads(json.dumps(st, sort_keys=True, default=str)), json.loads(json.dumps(hist, sort_keys=True, default=str))


def test_status_build_is_byte_identical_with_the_switch_off(monkeypatch, levels):
    from tests.test_rain_likely import RAIN_RULES
    monkeypatch.setattr(S, "_RULES", RAIN_RULES)
    before = _status(RAIN_RULES)
    off = copy.deepcopy(RAIN_RULES)
    off["rain_likely"]["separate_sewers"] = {**RULES["rain_likely"]["separate_sewers"], "enabled": False}
    after = _status(off, levels, GRADES)
    for x in (*before, *after):
        x.pop("built", None)
    assert before == after


SSO_LEVELS = {"method_version": 1, "today": "2026-08-10", "operators": {"al-wet": {
    "op": "al-wet", "name": "Wet Utilities", "state": "MA", "qualifies": True, "why_not": [], "possible_in": 0.3,
    "likely_in": None, "newest_report": "2026-08-01", "period": ["2023-01-05", "2026-07-20"], "storms": 190,
    "followed": 40, "reports": 60, "lift": 2.0, "sources": ["x"], "permits": [], "live_points": [[42.0, -72.0]],
    "places": {"reports": 1, "waters": [{"water_slug": "test-river-ma", "reports": 1}],
               "events": [{"event_id": "sso-e1", "day": "2026-07-01", "point": [42.0, -72.0],
                           "water_slugs": ["test-river-ma"], "reaches": []}]}}}}


def test_status_build_keeps_every_combined_sewer_field_with_an_active_separate_sewer_caution(monkeypatch):
    """Review 2026-11-16 P2-10: with a separate sewer caution in effect on the same river, every combined sewer row,
    interval, status and word is what it was without the switch."""
    from tests.test_rain_likely import PERMIT, RAIN_RULES
    monkeypatch.setattr(S, "_RULES", RAIN_RULES)
    before, hb = _status(RAIN_RULES)
    on = copy.deepcopy(RAIN_RULES)
    on["rain_likely"]["separate_sewers"] = {**rules_on()["rain_likely"]["separate_sewers"]}
    after, ha = _status(on, SSO_LEVELS, {"MA": "Dated reports"}, sso=True)
    blk_b, blk_a = before["rain_likely"], after["rain_likely"]
    ss = blk_a["separate_sewers"]
    assert ss["operators"]["al-wet"]["status"] == "likely" and ss["operators"]["al-wet"]["reaches"] == ["pt-sso1"]
    assert "separate_sewers" not in blk_b
    assert blk_a["permits"] == blk_b["permits"] and blk_a["counts"] == blk_b["counts"]
    assert {k: v for k, v in blk_a["episodes"].items() if PERMIT in k} == blk_b["episodes"]
    assert any(k.startswith("rain_likely:sso:al-wet:") for k in blk_a["episodes"])
    river_a = after["waters"]["test-river-ma"]["reasons"]
    sso_reasons = [x for x in river_a if (x.get("rain") or {}).get("permit") == "sso:al-wet"]
    assert sso_reasons and all(x["rule"] == "rain_likely" for x in sso_reasons)
    assert [x for x in river_a if x not in sso_reasons] == before["waters"]["test-river-ma"]["reasons"]
    assert after["waters"]["other-pond-ma"] == before["waters"]["other-pond-ma"]
    assert after["waters"]["test-river-ma"]["status"] == before["waters"]["test-river-ma"]["status"]
    assert after["reaches"]["MA0101613-13"] == before["reaches"]["MA0101613-13"]
    assert after["reaches"]["pt-sso1"]["status"] == "yellow"


def test_active_json_never_gives_the_operator_key_as_a_permit():
    from export import build as X
    ep = {"permit": "sso:al-wet", "discharger_id": "al-wet", "discharger_name": "Wet Utilities", "state": "AL",
          "label": "Discharge possible: heavy rain, no report received", "start": "2026-11-16T10:00:00Z", "end": None,
          "reaches": [], "rain": {"point": [33.84, -87.28]}}
    cso = {**ep, "permit": "MA0101613", "discharger_id": "ma-x"}
    rows = X.active_entries({"rain_likely:sso:al-wet:20261116T10Z": [{"status": "yellow", "water": "town-creek-al"}],
                             "rain_likely:MA0101613:20261116T10Z": [{"status": "yellow", "water": "w"}]}, {},
                            {"episodes": {"rain_likely:sso:al-wet:20261116T10Z": ep, "rain_likely:MA0101613:20261116T10Z": cso}})
    by = {r["event_id"]: r for r in rows}
    assert by["rain_likely:sso:al-wet:20261116T10Z"]["npdes_permit"] is None
    assert by["rain_likely:sso:al-wet:20261116T10Z"]["discharger_id"] == "al-wet"
    assert by["rain_likely:MA0101613:20261116T10Z"]["npdes_permit"] == "MA0101613"


# ---------------------------------------------------------------- review 2026-11-16 (Astra), data side

def test_review_p1_1_the_lift_leaves_reporting_gaps_out_of_both_sides():
    """Reports on every fourth day whatever the weather, in 2023 and in 2026 only: a two-year reporting gap must not
    inflate the ratio (it read 2.09 when the gap's days stayed in the denominator)."""
    cfg = SS.settings(rules_on())
    days = [d for d in DAILY if (d.year == 2023 or d >= date(2026, 1, 1)) and d.toordinal() % 4 == 0 and d <= TODAY - timedelta(days=20)]
    recs = [rec(f"r{i}", "al-wet", d) for i, d in enumerate(days)]
    spans, _ = SS.sso_spans(recs, lambda r: r["discharger_id"], cfg)
    from build import rain_history as RH
    a = RH.analyse(DAILY, spans["al-wet"], TODAY - timedelta(days=20), RH.settings(rules_on()), TODAY)
    assert any(x["why"] == "reporting_gap" for x in a["left_out"])
    sig = SS.signal(DAILY, spans["al-wet"], a)
    assert 0.7 <= sig["lift"] <= 1.3, sig


def test_review_p1_2_the_hourly_check_reads_the_report_age_against_today(levels):
    assert "al-wet" in SS.qualifying(levels, rules_on(), GRADES, TODAY)
    later = TODAY + timedelta(days=100)
    assert SS.qualifying(levels, rules_on(), GRADES, later) == {}
    lv = copy.deepcopy(levels)
    reaches = {}
    by_water, _, blk = SS.compute(rain_for(storm(range(0, 6), 1.2), now=NOW + timedelta(days=100)), rules_on(), [],
                                  NOW + timedelta(days=100), NOW, WATERS, reaches, lambda r, w: [], {}, lv, GRADES)
    assert by_water == {} and "al-wet" in blk["not_covered"]
    assert any("older than 90 days" in w for w in blk["not_covered"]["al-wet"]["why_not"])


def test_review_p1_3_never_a_registry_outfalls_reach_or_a_report_with_no_point():
    evs = [{"event_id": "e1", "point": [33.84, -87.28], "water_slugs": ["town-creek-al"], "reaches": ["AL0001-1"]},
           {"event_id": "e2", "point": None, "water_slugs": ["town-creek-al"], "reaches": []}]
    reaches = {"AL0001-1": {"key": "AL0001-1", "permit": "AL0001", "outfall": "001", "segments": [{"x": 1}],
                            "water_slug": "town-creek-al"},
               "pt-e2": {"key": "pt-e2", "segments": [{"x": 1}], "water_slug": "town-creek-al", "event_ids": ["e2"]},
               "pt-other": {"key": "pt-other", "segments": [{"x": 1}], "water_slug": "town-creek-al", "event_ids": ["zz"]}}
    keys, tags, _, _ = SS.placement(entry_with(evs), WATERS, reaches, lambda r, w: ["town-creek-al"],
                                    {"e1": {"reach": "pt-other", "reaches": ["AL0001-1"]}})
    assert keys == [] and tags == {}


def test_review_p1_4_separate_sewer_points_never_change_the_combined_sewer_fallback():
    from ingest import rainfall as RF
    pts = {"a": {"permits": ["MA1"], "mrms": {"h24": 0.2}}, "b": {"permits": ["MA1"], "mrms": {"h24": 0.5}},
           "c": {"permits": ["MA2"], "mrms": {"h24": 0.1}}}
    base = RF.fallback_order(pts, ["a", "b", "c"], 2)
    more = {**pts, "s": {"permits": ["sso:al-wet"], "mrms": {"h24": 3.0}},
            "b": {"permits": ["MA1", "sso:al-x"], "mrms": {"h24": 0.5}}}
    assert RF.fallback_order(more, ["a", "b", "c", "s"], 2) == base
    assert RF.fallback_order(more, ["a", "b", "c", "s"], 4) == base + [x for x in RF.fallback_order(pts, ["a", "b", "c"], 4) if x not in base] + ["s"]


def test_review_p2_5_live_points_are_report_points(levels):
    e = levels["operators"]["al-wet"]
    given = {tuple(ev["point"]) for ev in e["places"]["events"] if ev["point"]}
    assert e["live_points"] and all(tuple(p) in given for p in e["live_points"])
    assert SS.report_points([(1.0, 1.0), (1.0, 2.0), (3.0, 1.0)], 1)[0] in {(1.0, 1.0), (1.0, 2.0), (3.0, 1.0)}


def test_review_p2_6_the_batch_rule_reads_the_events_files(tmp_path, monkeypatch):
    import common
    (tmp_path / "tx-batches.json").write_text(json.dumps({"meta": {"published_in_batches": True}, "records": records()}))
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    srcs, batches = SS.events_sources()
    assert batches == {"tx-batches": True} and srcs[0][0] == "tx-batches"
    d = SS.build(offline=True, today=TODAY, now=NOW, rules=rules_on(), operator_of=lambda r: r.get("discharger_id"),
                 placements={}, reader=lambda *a: dict(DAILY), have=lambda *a: True, grades=GRADES, write=False)
    assert d["counts"]["qualify"] == 0 and d["sources"]["tx-batches"]["excluded"]


def test_review_p2_8_the_rules_export_carries_the_block_only_when_on():
    from export import build as X
    off = X.live_rules(X.public_rules(RULES), {"AL"})
    assert "separate_sewers" not in off["rain_likely"]
    base = copy.deepcopy(RULES)
    del base["rain_likely"]["separate_sewers"]
    assert off == X.live_rules(X.public_rules(base), {"AL"})
    on = X.live_rules(X.public_rules(rules_on()), {"AL"})
    assert on["rain_likely"]["separate_sewers"]["enabled"] is True
    assert not any(k.startswith("_") for k in on["rain_likely"]["separate_sewers"])
