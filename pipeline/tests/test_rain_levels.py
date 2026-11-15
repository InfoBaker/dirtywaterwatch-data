"""Rain levels from each operator's own overflow history in the status build (build/rain_likely.py with
data/rain-levels.json, build/rain_history.py): the precedence (history, operator rule, state, default), the safety
guarantee, the level and the label, the evidence record, and that nothing changes where no levels file is loaded.
Fixtures are plain dicts in the levels file's format, some made by rain_history.analyse on synthetic storms.
Run from pipeline/: python -m pytest tests/test_rain_levels.py -q
"""
from __future__ import annotations

import copy
import json
import random
import re
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import rain_history as RH  # noqa: E402
from build import rain_likely as RL  # noqa: E402
from build import status as S  # noqa: E402
from export import build as X  # noqa: E402
from export import outfalls as XO  # noqa: E402
from tests.test_rain_likely import (LIKELY, NOW, PERMIT, POSSIBLE, RAIN_RULES, STATE_RULES, rain_world,  # noqa: E402
                                    wet)
from tests.test_status import TEST_RULES  # noqa: E402


@pytest.fixture(autouse=True)
def _rules(monkeypatch):
    monkeypatch.setattr(S, "_RULES", TEST_RULES)


TODAY = "2026-11-14"


def entry(possible_in=0.25, likely_in=1.0, quiet_enough=False, usable=True, why_not=None, outfalls=None, notes=()):
    """One operator's entry in the levels file's format (spec section 1)."""
    if not usable:
        return {"permit": PERMIT, "name": "Test Water and Sewer", "state": "MA", "computed": TODAY, "method_version": RH.METHOD_VERSION,
                "usable": False, "why_not": why_not or "4 storms followed by a reported overflow (fewer than 10)",
                "storms": 30, "followed": 4, "period": ["2022-07-01", "2026-10-31"]}
    rng = lambda lo, hi, n, k: {"lo": lo, "hi": hi, "storms": n, "followed": k, "share": round(k / n, 3)}  # noqa: E731
    return {"permit": PERMIT, "name": "Test Water and Sewer", "state": "MA", "computed": TODAY, "method_version": RH.METHOD_VERSION,
            "usable": True, "why_not": None, "period": ["2019-01-01", "2026-10-31"], "record_from": "2015-01-01",
            "storms": 408, "followed": 67, "reports": 90, "reports_with_no_storm": 3, "day_precision_reports": 0,
            "bands": [rng(0.1, 0.25, 157, 0), rng(0.25, 1.0, 207, 29), rng(1.0, None, 44, 38)],
            "lowest_reported": {"size_in": 0.35, "day": "2019-02-23", "rounded_in": possible_in},
            "possible_in": possible_in, "likely_in": likely_in,
            "quiet": ({**rng(0.1, possible_in, 157 if quiet_enough else 12, 0), "enough": quiet_enough}
                      if possible_in > 0.1 else None),
            "possible": rng(possible_in, likely_in, 207, 29) if likely_in is None or likely_in > possible_in else None,
            "likely": rng(likely_in, None, 44, 38) if likely_in is not None else None,
            "left_out": [], "notes": list(notes),
            "not_used": {"copies": 0, "monthly_or_yearly": 0, "not_rain_driven": 0, "no_start": 0},
            "sources": [{"source_id": "ma-massdep", "reports": 90, "first": "2019-01-03", "last": "2026-10-20",
                         "coverage_end": "2026-10-31"}],
            "points": [[42.1, -72.6]], "outfalls": outfalls}


def levels_file(permits: dict) -> dict:
    return {"method_version": RH.METHOD_VERSION, "built": "2026-11-14T06:00:00Z", "today": TODAY, "method": "plain sentences",
            "rain_record": {"source_id": "iem-iemre-mrms-daily", "name": RL.RAIN_RECORD_NAME,
                            "url": "https://mesonet.agron.iastate.edu/iemre/", "first_day": "2015-01-01",
                            "day": "America/Chicago calendar days"},
            "settings": RH.settings(RAIN_RULES), "crosscheck": None,
            "counts": {"permits": len(permits), "usable": sum(1 for e in permits.values() if e.get("usable")),
                       "with_quiet_range": 0, "never_likely": 0},
            "permits": permits}


def build(levels=None, *, rules=None, key=True, **kw):
    w = rain_world(**kw)
    if rules is not None:
        w["rules"] = rules
    if key:
        w["rain"]["levels"] = levels
    return S.build(now=NOW, write=False, **w)


def caution_hours(st) -> set:
    """Every hour (as an ISO string) inside a piece of a rain episode."""
    out = set()
    for ep in st["rain_likely"]["episodes"].values():
        for a, b in ep["pieces"]:
            t = S.parse_time(a)
            end = S.parse_time(b) if b else NOW + timedelta(hours=1)
            while t < end:
                out.add(t.isoformat())
                t += timedelta(hours=1)
    return out


# ---------------------------------------------------------------- nothing changes without a levels file

NEW_KEYS = {"level", "evidence", "history", "levels", "label_by_level", "rain_level"}


def _strip(o):
    if isinstance(o, dict):
        return {k: _strip(v) for k, v in o.items() if k not in NEW_KEYS}
    if isinstance(o, list):
        return [_strip(v) for v in o]
    return o


def _no_built(st):
    st = copy.deepcopy(st)
    st.pop("built", None)
    for s in (st.get("sources") or {}).values():
        if isinstance(s, dict):
            s.pop("checked_at", None)
    return st


def test_a_levels_file_without_the_operator_changes_only_the_new_fields():
    vals = wet(range(0, 6))
    a, _ = build(key=False, values=vals)
    b, _ = build(levels_file({"MA0100552": entry()}), values=vals)
    # the active water reads "likely" both ways (the 10th-percentile row is the operator's basis); the rest is the same
    assert json.dumps(_strip(_no_built(a)), sort_keys=True, default=str) == \
        json.dumps(_strip(_no_built(b)), sort_keys=True, default=str)
    p = b["rain_likely"]["permits"][PERMIT]
    assert p["threshold_in"] == 0.3 and p["threshold_kind"] == "operator_history"      # today's row, byte for byte
    assert p["evidence"]["why_no_history"] == RL.NO_ENTRY and p["history"] is None and p["level"] == "likely"


# ---------------------------------------------------------------- precedence

def test_a_usable_history_comes_first_even_before_the_operators_own_rule():
    rules = copy.deepcopy(RAIN_RULES)
    rules["rain_likely"]["fallback"]["by_permit"] = {PERMIT: {"inches": 0.5, "basis": "the operator's rule",
                                                              "source": "operator"}}
    st, _ = build(levels_file({PERMIT: entry(possible_in=0.25, quiet_enough=True)}), rules=rules,
                  values=wet(range(0, 6), v=0.6))
    p = st["rain_likely"]["permits"][PERMIT]
    assert p["evidence"]["basis"] == "operator_history" and p["threshold_in"] == 0.25 and p["trigger_basis"] == "operator"
    assert p["evidence"]["why_no_history"] is None and p["evidence"]["rule_text"] is None
    # an unusable history: the operator's own rule, with the reason
    st, _ = build(levels_file({PERMIT: entry(usable=False)}), rules=rules, values=wet(range(0, 6), v=0.6))
    p = st["rain_likely"]["permits"][PERMIT]
    assert p["evidence"]["basis"] == "operator_rule" and p["threshold_in"] == 0.5 and p["level"] == "likely"
    assert p["evidence"]["why_no_history"].startswith("4 storms") and p["evidence"]["rule_text"] == "the operator's rule"


@pytest.mark.parametrize("rules,basis,amount,level,label", [
    (STATE_RULES, "state_rule", 0.3, "likely", LIKELY), (RAIN_RULES, "site_default", 0.1, "possible", POSSIBLE)])
def test_an_unusable_history_goes_to_the_fallback_never_to_the_percentile_row(rules, basis, amount, level, label):
    st, _ = build(levels_file({PERMIT: entry(usable=False, why_not="12 storms in the record (fewer than 20)")}),
                  rules=rules, values=wet(range(0, 6)))
    p = st["rain_likely"]["permits"][PERMIT]
    assert p["threshold_in"] == amount and p["threshold_kind"] != "operator_history"   # the row says 0.3: not used
    assert p["threshold_rule"] != "rain_likely.percentile" and p["n_discharge_days"] is None
    ev = p["evidence"]
    assert ev["basis"] == basis and ev["level"] == level and ev["why_no_history"] == "12 storms in the record (fewer than 20)"
    assert ev["class"] is None and ev["likely_in"] is None and ev["caution_in"] == amount
    ep = next(iter(st["rain_likely"]["episodes"].values()))
    assert ep["level"] == level and ep["label"] == label and ep["rain"]["evidence"]["basis"] == basis
    assert st["waters"]["other-pond-ma"]["reasons"][0]["label"] == label


# ---------------------------------------------------------------- the safety guarantee

def _series(seed: int) -> dict:
    rnd = random.Random(seed)
    return {b: round(rnd.choice([0.0, 0.0, 0.05, 0.12, 0.2, 0.3, 0.45, 0.8, 1.3]), 2) for b in range(0, 200)}


@pytest.mark.parametrize("seed", range(6))
@pytest.mark.parametrize("p_in", [0.25, 0.5, 1.0])
@pytest.mark.parametrize("rules", [RAIN_RULES, STATE_RULES])
def test_a_thin_quiet_range_never_removes_a_caution_the_fallback_shows(seed, p_in, rules):
    vals = _series(seed)
    fallback, _ = build(levels_file({PERMIT: entry(usable=False)}), rules=rules, values=vals)
    hist, _ = build(levels_file({PERMIT: entry(possible_in=p_in, likely_in=None if p_in == 1.0 else 1.0)}),
                    rules=rules, values=vals)
    assert caution_hours(fallback) <= caution_hours(hist)
    assert hist["rain_likely"]["permits"][PERMIT]["evidence"]["caution_in"] == min(
        p_in, fallback["rain_likely"]["permits"][PERMIT]["threshold_in"])


def _storm_days(sizes_followed, start=date(2020, 1, 1)):
    """Synthetic daily rain: one-day storms sixteen days apart (70 of them span three years, which a quiet range
    needs), the followed ones first; spans for the followed ones."""
    yes = [x for x in sizes_followed if x[1]]
    no = [x for x in sizes_followed if not x[1]]
    # spread evenly, a followed storm first: no long stretch without a report (that would read as a reporting gap)
    placed = [(i / len(yes), 0, x) for i, x in enumerate(yes)] + [((j + 0.5) / len(no), 1, x) for j, x in enumerate(no)]
    sizes_followed = [x for _, _, x in sorted(placed, key=lambda t: t[:2])]
    daily, spans, d = {}, [], start
    for size, followed in sizes_followed:
        daily[d] = size
        if followed:
            spans.append({"first": d, "last": d, "outfall": None, "precision": "minute", "source_id": "ma-massdep"})
        d += timedelta(days=16)
    day = start                                     # every other day observed and dry (the minimums count them)
    while day < d:
        daily.setdefault(day, 0.0)
        day += timedelta(days=1)
    return daily, spans, d


def _analysed(sizes_followed):
    daily, spans, end = _storm_days(sizes_followed)
    cfg = RH.settings(RAIN_RULES)
    e = RH.analyse(daily, spans, end, cfg, end + timedelta(days=30))
    e.pop("_storms", None)
    e.pop("_every", None)
    return {**e, "permit": PERMIT, "name": "Test", "state": "MA", "computed": TODAY, "method_version": RH.METHOD_VERSION, "sources": []}


def test_caution_from_the_rung_of_one_followed_small_storm_and_from_possible_in_when_quiet_enough():
    quiet = [(0.15, False)] * 40 + [(0.7, True)] * 30
    e = _analysed(quiet)
    assert e["usable"] and e["possible_in"] == 0.5 and e["quiet"]["enough"] is True
    assert RL.caution_amount(e, 0.1, RAIN_RULES) == 0.5                 # quiet enough: no caution below 0.5 inch
    one = [(0.15, False)] * 39 + [(0.15, True)] + [(0.7, True)] * 30
    e1 = _analysed(one)
    assert e1["possible_in"] == 0.1 and RL.caution_amount(e1, 1.0, RAIN_RULES) == 0.1   # back down to that rung
    thin = [(0.15, False)] * 12 + [(0.7, True)] * 60
    e2 = _analysed(thin)
    assert e2["possible_in"] == 0.5 and e2["quiet"]["enough"] is False
    assert RL.caution_amount(e2, 0.1, RAIN_RULES) == 0.1 and RL.caution_amount(e2, 1.0, RAIN_RULES) == 0.5


def test_quiet_enough_starts_the_caution_at_possible_in_in_the_build():
    st, _ = build(levels_file({PERMIT: entry(possible_in=0.25, quiet_enough=True)}), values=wet(range(0, 6), v=0.2))
    p = st["rain_likely"]["permits"][PERMIT]
    assert p["threshold_in"] == 0.25 and p["status"] == "below" and st["rain_likely"]["episodes"] == {}
    assert p["evidence"]["quiet"]["enough"] is True and p["evidence"]["class"] is None and p["level"] == "possible"


def test_below_lowest_class_where_the_quiet_range_is_too_thin():
    st, _ = build(levels_file({PERMIT: entry(possible_in=0.25)}), values=wet(range(0, 6), v=0.2))
    p = st["rain_likely"]["permits"][PERMIT]
    assert p["threshold_in"] == 0.1 and p["status"] == "likely"
    c = p["evidence"]["class"]
    assert c == {"kind": "below_lowest", "lo": 0.1, "hi": 0.25, "storms": 12, "followed": 0}
    assert p["level"] == "possible" and p["label"] == POSSIBLE
    r = st["waters"]["other-pond-ma"]["reasons"][0]
    assert "none of 12 storms of 0.1 to 0.25 inch followed by a reported overflow" in r["short"]


# ---------------------------------------------------------------- level and label

@pytest.mark.parametrize("peak,kind,level,label", [(0.5, "possible", "possible", POSSIBLE),
                                                   (1.0, "likely", "likely", LIKELY), (1.4, "likely", "likely", LIKELY)])
def test_the_level_follows_the_peak_and_the_label_the_level(peak, kind, level, label):
    st, _ = build(levels_file({PERMIT: entry(possible_in=0.25, likely_in=1.0)}), values=wet(range(0, 6), v=peak))
    blk = st["rain_likely"]
    ep = next(iter(blk["episodes"].values()))
    assert ep["level"] == level and ep["label"] == label and ep["trigger_basis"] == "operator"
    ev = ep["rain"]["evidence"]
    assert ev["class"]["kind"] == kind and ev["level"] == level and ev["caution_in"] == 0.1 and ev["likely_in"] == 1.0
    assert ev["period"] == ["2019-01-01", "2026-10-31"] and ev["report_sources"] == ["ma-massdep"]
    assert ev["rain_record"] == "iem-iemre-mrms-daily" and ev["method_version"] == RH.METHOD_VERSION and ev["computed"] == TODAY
    assert set(ev) == {"basis", "level", "caution_in", "likely_in", "class", "period", "lowest_reported", "quiet", "notes",
                       "why_no_history", "rule_text", "report_sources", "rain_record", "method_version", "computed"}
    p = blk["permits"][PERMIT]
    assert p["level"] == level and p["label"] == label and p["evidence"]["class"] == ev["class"]
    assert set(p["history"]) == set(RL.HISTORY_FIELDS) and p["history"]["storms"] == 408
    pond = st["waters"]["other-pond-ma"]
    r = pond["reasons"][0]
    assert r["level"] == level and r["label"] == label and r["short"].startswith(label)
    assert pond["rain"]["level"] == level and pond["rain"]["label"] == label
    assert blk["waters"]["other-pond-ma"]["level"] == level
    assert st["reaches"]["MA0101613-13"]["rain_level"] == level
    assert st["rules"]["rain_likely"]["label_by_level"] == {"likely": LIKELY, "possible": POSSIBLE}
    assert "inch" in r["short"] and not re.search(r"\d in\b", r["short"])


def test_the_short_reason_states_the_counts():
    st, _ = build(levels_file({PERMIT: entry(possible_in=0.25, likely_in=1.0)}), values=wet(range(0, 6), v=1.2))
    r = st["waters"]["other-pond-ma"]["reasons"][0]
    assert r["short"] == (f"{LIKELY} · Test Water and Sewer · 1.20 inches in 24 hours (radar) · its own reports, "
                          "January 2019 to October 2026: an overflow after 38 of 44 storms of 1 inch or more")
    st, _ = build(levels_file({PERMIT: entry(possible_in=0.25, likely_in=1.0)}), values=wet(range(0, 6), v=0.4))
    assert st["waters"]["other-pond-ma"]["reasons"][0]["short"].endswith(
        "an overflow after 29 of 207 storms of 0.25 to 1 inch; smallest storm followed 0.35 inch, rounded down to 0.25 inch")


def test_a_water_is_likely_when_any_operators_episode_is_likely():
    w = rain_world(values=wet(range(0, 6), v=0.6))
    rain = w["rain"]
    other = "MA0100552"
    rain["rainfall"]["permits"][other] = {**rain["rainfall"]["permits"][PERMIT], "name": "Other Sewer"}
    rain["history"]["permits"][other] = list(rain["history"]["permits"][PERMIT])
    rain["levels"] = levels_file({PERMIT: entry(possible_in=0.1, likely_in=0.5),
                                  other: {**entry(possible_in=0.1, likely_in=1.0), "permit": other}})
    st, _ = S.build(now=NOW, write=False, **w)
    blk = st["rain_likely"]
    assert {blk["permits"][p]["level"] for p in (PERMIT, other)} == {"likely", "possible"}
    assert blk["waters"]["other-pond-ma"]["level"] == "likely"
    pond = st["waters"]["other-pond-ma"]
    assert pond["rain"]["level"] == "likely" and pond["rain"]["label"] == LIKELY
    assert [r["level"] for r in pond["reasons"]] == ["likely", "possible"] and pond["reason_short"].startswith(LIKELY)
    rain["levels"]["permits"][PERMIT]["likely_in"] = 1.0
    st, _ = S.build(now=NOW, write=False, **w)
    assert st["rain_likely"]["waters"]["other-pond-ma"]["level"] == "possible"
    assert st["waters"]["other-pond-ma"]["rain"]["label"] == POSSIBLE


def test_an_operator_rules_season_and_tail_with_and_without_a_history():
    rules = copy.deepcopy(RAIN_RULES)
    rules["rain_likely"]["fallback"]["by_permit"] = {PERMIT: {"inches": 0.25, "tail_hours": 72, "months": [5, 6, 7, 8, 9, 10],
                                                              "time_zone": "America/New_York", "basis": "rule", "source": "s"}}
    vals = wet(range(20, 30), v=0.6)          # August (in season): above until 20 hours ago
    st, _ = build(levels_file({PERMIT: entry(usable=False)}), rules=rules, values=vals)
    ep = next(iter(st["rain_likely"]["episodes"].values()))
    assert ep["rain"]["threshold_kind"] == "operator_rule" and ep["rain"]["until_rule"].startswith("72 hours")
    st, _ = build(levels_file({PERMIT: entry(possible_in=0.25, quiet_enough=True)}), rules=rules, values=vals)
    ep = next(iter(st["rain_likely"]["episodes"].values()))
    assert ep["rain"]["threshold_kind"] == "operator_history" and ep["rain"]["until_rule"].startswith("72 hours")


# ---------------------------------------------------------------- the export

def test_the_export_carries_level_evidence_and_the_outfalls_own_counts():
    oh = {"013": {"reports": 40, "storms": 251, "followed": 30, "lowest_reported": None,
                  "possible": {"lo": 0.25, "hi": 1.0, "storms": 207, "followed": 20},
                  "likely": {"lo": 1.0, "hi": None, "storms": 44, "followed": 10}}}
    lv = levels_file({PERMIT: entry(outfalls=oh)})
    st, _ = build(lv, values=wet(range(0, 6), v=1.2))
    pub = X.publicize(X.public_rain(st["rain_likely"]))
    assert pub["label_by_level"]["possible"] == POSSIBLE and pub["levels"]["method_version"] == RH.METHOD_VERSION
    p = pub["permits"][PERMIT]
    assert p["level"] == "likely" and p["evidence"]["basis"] == "operator_history" and p["history"]["storms"] == 408
    assert all(e["rain"]["evidence"]["class"]["kind"] == "likely" for e in pub["episodes"].values())
    assert X.internal_wording(pub) == []
    rows = XO.outfall_rows([{"npdes_permit": PERMIT, "outfall": "013", "state": "MA", "lat": 42.0, "lon": -72.0,
                             "outfall_status": "CSO"},
                            {"npdes_permit": PERMIT, "outfall": "014", "state": "MA", "lat": 42.0, "lon": -72.0,
                             "outfall_status": "CSO"}], {"MA"}, rain_permits=pub["permits"], levels=lv)
    r13, r14 = rows[0]["rain"], rows[1]["rain"]
    assert r13["level"] == "likely" and r13["caution_in"] == 0.1 and r13["likely_in"] == 1.0
    assert r13["outfall_history"] == oh["013"] and r14["outfall_history"] is None
    # no levels: the row is what it was
    st0, _ = build(key=False, values=wet(range(0, 6), v=1.2))
    row0 = XO.rain_of(X.public_rain(st0["rain_likely"])["permits"][PERMIT], lv, PERMIT, "013")
    assert set(row0) == set(XO.RAIN_FIELDS)
    assert "rain-levels.json" in X.PUBLIC_PAYLOADS
    assert "levels" not in X.public_rain(st0["rain_likely"])


def test_coverage_names_the_operators_own_reports_where_they_are_used():
    st, _ = build(levels_file({PERMIT: entry()}), values=wet(range(0, 6)))
    cov = RL.caution_coverage(st["rain_likely"], {"MA": {PERMIT}})
    s = cov["MA"]["sentence"]
    assert "from each operator's own overflow reports where it has enough of them" in s
    assert s.startswith('The "discharge likely" or "discharge possible" caution covers 1')
    st0, _ = build(key=False, values=wet(range(0, 6)))
    assert "own overflow reports" not in RL.caution_coverage(st0["rain_likely"], {"MA": {PERMIT}})["MA"]["sentence"]


def test_rules_json_history_block_matches_the_defaults_and_reads_plainly():
    rl = json.loads((Path(__file__).resolve().parents[2] / "data" / "rules.json").read_text())["rain_likely"]
    h = rl["history"]
    keys = list(rl)
    assert keys.index("history") == keys.index("label_by_basis_rationale") + 1
    for k in ("rungs_in", "likely_share", "quiet_min_storms", "min_storms", "min_report_storms", "min_total_storms",
              "min_period_days", "quiet_min_period_days"):
        assert h[k] == RH.DEFAULTS[k] and h[f"{k}_rationale"], k
    assert h["system_changes"] == {} and h["_system_changes_doc"]
    assert RL.labels_by_level(json.loads((Path(__file__).resolve().parents[2] / "data" / "rules.json").read_text())) \
        == {"likely": LIKELY, "possible": POSSIBLE}
    for text in (h["doc"], h["source"], h["label_by_level_rationale"], rl["doc"], rl["label_by_basis_rationale"],
                 rl["threshold_rationale"], *(h[k] for k in h if k.endswith("_rationale"))):
        assert not X.INTERNAL_WORDING.search(text) and "safe" not in text.lower()
        assert "—" not in text and " - " not in text and "–" not in text
    assert "NOAA MRMS" in h["source"] and "Iowa Environmental Mesonet" in h["source"]


# ---------------------------------------------------------------- the review's findings (2026-11-14 evening)

def _rules_with(by_permit=None, by_state=None):
    rules = copy.deepcopy(RAIN_RULES)
    if by_permit:
        rules["rain_likely"]["fallback"]["by_permit"] = by_permit
    if by_state:
        rules["rain_likely"]["fallback"]["by_state"] = {**rules["rain_likely"]["fallback"]["by_state"], **by_state}
    return rules


SD1_STYLE = {PERMIT: {"inches": 0.25, "tail_hours": 72, "months": [5, 6, 7, 8, 9, 10], "time_zone": "America/New_York",
                      "basis": "the operator's own published rule", "source": "the operator"}}


def build_at(now, levels, rules, values):
    from tests.test_rain_likely import rain_input
    w = rain_world(values={})
    w["rain"] = rain_input(values, now=now)
    w["rain"]["levels"] = levels
    w["rules"] = rules
    return S.build(now=now, write=False, **w)


def _hours(st, now) -> set:
    out = set()
    for ep in st["rain_likely"]["episodes"].values():
        a = S.parse_time(ep["start"])
        b = S.parse_time(ep["end"]) if ep["end"] else now + timedelta(days=30)    # open: still above, no end yet
        while a < b:
            out.add(a)
            a += timedelta(hours=1)
    return out


def test_a_thin_history_keeps_the_fallbacks_72_hours_across_the_start_of_the_season():
    """The reviewer's case (P1-3): 0.12 inch just before May 1 (New York time), 0.3 inch after midnight, an operator
    rule of 0.25 inch and 72 hours from May to October, a thin history keeping the 0.1 inch fallback."""
    from datetime import UTC, datetime
    now = datetime(2026, 5, 2, 12, 0, tzinfo=UTC)          # May 1 00:00 in New York is 04:00 UTC, 32 hours back
    vals = {b: 0.0 for b in range(0, 200)}
    for b in range(33, 41):
        vals[b] = 0.12
    for b in range(26, 33):
        vals[b] = 0.3
    rules = _rules_with(by_permit=SD1_STYLE)
    fb, _ = build_at(now, levels_file({PERMIT: entry(usable=False)}), rules, vals)
    hist, _ = build_at(now, levels_file({PERMIT: entry(possible_in=0.25)}), rules, vals)
    fb_end = max(S.parse_time(e["end"]) for e in fb["rain_likely"]["episodes"].values())
    assert fb_end == now - timedelta(hours=25) + timedelta(hours=72)       # below from 25 hours back, then 72 hours
    (ep,) = hist["rain_likely"]["episodes"].values()
    assert S.parse_time(ep["end"]) == fb_end and ep["rain"]["until_rule"] == \
        "72 hours after the 24-hour total falls below 0.25 inch, the operator's own rule"
    # second pass P2-13: the end is cited by the rule that set it; start, amount and times stay the history's
    r = ep["rain"]
    er = r["end_rule"]
    assert er == {"basis": "operator_rule", "threshold_in": 0.25, "tail_hours": 72, "rule": f"rain_likely.fallback.by_permit.{PERMIT}",
                  "text": "the operator's own published rule", "source": "the operator",
                  "last_above_at": S.iso(now - timedelta(hours=26)), "dropped_below_at": S.iso(now - timedelta(hours=25))}
    assert r["threshold_in"] == 0.1 and r["threshold_kind"] == "operator_history"
    assert r["above_from"] == S.iso(now - timedelta(hours=40))
    assert r["last_above_at"] == S.iso(now - timedelta(hours=26)) and r["dropped_below_at"] == S.iso(now - timedelta(hours=25))
    got = {(x["basis"], x["threshold_in"], x["tail_hours"], x["from"], x["until"]) for x in r["pieces_from"]}
    assert ("operator_history", 0.1, 48, S.iso(now - timedelta(hours=40)), S.iso(now + timedelta(hours=23))) in got
    assert ("operator_rule", 0.25, 72, S.iso(now - timedelta(hours=32)), S.iso(fb_end)) in got
    ra = hist["waters"]["other-pond-ma"]["reasons"][0]["rule_applied"]
    assert ra["threshold_in"] == 0.1 and ra["tail_hours"] == 72
    assert ra["end_rule"] == {"basis": "operator_rule", "threshold_in": 0.25, "tail_hours": 72,
                              "rule": f"rain_likely.fallback.by_permit.{PERMIT}"}
    assert _hours(fb, now) <= _hours(hist, now)
    assert ep["rain"]["evidence"]["basis"] == "operator_history" and ep["level"] == "possible"
    assert hist["rain_likely"]["permits"][PERMIT]["status"] == "likely"


@pytest.mark.parametrize("seed", range(5))
@pytest.mark.parametrize("now_s", ["2026-05-01T20:00:00+00:00", "2026-11-01T20:00:00+00:00",
                                   "2026-05-03T04:00:00+00:00"])
@pytest.mark.parametrize("p_in", [0.25, 0.5])
def test_the_safety_property_holds_across_a_season_boundary(seed, now_s, p_in):
    from datetime import datetime
    now = datetime.fromisoformat(now_s)
    vals = _series(seed)
    rules = _rules_with(by_permit=SD1_STYLE)
    fb, _ = build_at(now, levels_file({PERMIT: entry(usable=False)}), rules, vals)
    hist, _ = build_at(now, levels_file({PERMIT: entry(possible_in=p_in)}), rules, vals)
    assert _hours(fb, now) <= _hours(hist, now)


def test_an_october_episode_running_into_november_keeps_its_own_rule_on_the_permit_row():
    """P2-7: the episode began in the operator rule's season; the permit row's evidence, level and label follow the
    rule that episode's start took, never the November build hour's site default."""
    from datetime import UTC, datetime
    now = datetime(2026, 11, 1, 14, 0, tzinfo=UTC)         # 10:00 on November 1 in New York
    vals = {b: 0.0 for b in range(0, 200)}
    for b in range(20, 26):                                # October 31 in New York, 0.3 inch
        vals[b] = 0.3
    rules = _rules_with(by_permit=SD1_STYLE, by_state={"MA": {"inches": 0.1, "basis": "the site default here",
                                                              "source": "s", "trigger_basis": "default"}})
    st, _ = build_at(now, levels_file({PERMIT: entry(usable=False)}), rules, vals)
    p = st["rain_likely"]["permits"][PERMIT]
    (ep,) = st["rain_likely"]["episodes"].values()
    assert ep["rain"]["threshold_kind"] == "operator_rule" and p["episode"] == next(iter(st["rain_likely"]["episodes"]))
    assert p["evidence"]["basis"] == "operator_rule" and p["evidence"]["caution_in"] == 0.25
    assert p["level"] == "likely" and p["label"] == LIKELY and p["evidence"] == ep["rain"]["evidence"]
    # second pass P2-7: every caution field of the row is the episode's, and so is the exported outfall's
    for k in ("threshold_in", "threshold_basis", "threshold_rule", "threshold_text", "threshold_source", "threshold_kind",
              "trigger_basis", "label"):
        assert p[k] == ep["rain"][k], k
    assert p["threshold_in"] == 0.25 and p["trigger_basis"] == "operator" and p["threshold_kind"] == "operator_rule"
    pub = X.publicize(X.public_rain(st["rain_likely"]))
    (row,) = XO.outfall_rows([{"npdes_permit": PERMIT, "outfall": "013", "state": "MA", "lat": 42.0, "lon": -72.0,
                               "outfall_status": "CSO"}], {"MA"}, rain_permits=pub["permits"],
                             levels=levels_file({PERMIT: entry(usable=False)}))
    rr = row["rain"]
    assert (rr["threshold_in"], rr["threshold_kind"], rr["trigger_basis"], rr["level"], rr["caution_in"]) == \
        (0.25, "operator_rule", "operator", "likely", 0.25)


def test_a_state_entry_applying_the_site_default_reads_as_the_site_default():
    rules = _rules_with(by_state={"MA": {"inches": 0.1, "basis": "the state's advice, with this site's default",
                                         "source": "s", "trigger_basis": "default"}})
    st, _ = build(levels_file({PERMIT: entry(usable=False)}), rules=rules, values=wet(range(0, 6)))
    ev = st["rain_likely"]["permits"][PERMIT]["evidence"]
    assert ev["basis"] == "site_default" and ev["level"] == "possible"
    assert ev["rule_text"] == "the state's advice, with this site's default"


def test_the_rationale_is_the_methods_own_only_with_a_levels_file():
    rules = json.loads((Path(__file__).resolve().parents[2] / "data" / "rules.json").read_text())
    st0, _ = build(key=False, rules=rules, values=wet(range(0, 6)))
    st1, _ = build(levels_file({PERMIT: entry()}), rules=rules, values=wet(range(0, 6)))
    r0, r1 = st0["waters"]["other-pond-ma"]["reasons"][0], st1["waters"]["other-pond-ma"]["reasons"][0]
    assert r0["rule_applied"]["rationale"] == rules["rain_likely"]["doc"] == r0["yellow_rule"]["rationale"]
    assert r1["rule_applied"]["rationale"] == rules["rain_likely"]["history"]["doc"]


PUBLIC_WORDS = re.compile(r"\.py\b|\.json\b|data/|build/|\bdef\b|_[a-z]+\(|rain_history|rain_likely\.py")


def test_no_public_text_of_the_levels_names_a_file_module_or_function():
    st, _ = build(levels_file({PERMIT: entry(possible_in=0.25)}), values=wet(range(0, 6), v=0.2))
    p = st["rain_likely"]["permits"][PERMIT]
    texts = [st["waters"]["other-pond-ma"]["reasons"][0]["short"], p["threshold_text"], p["threshold_source"],
             p["label"], *RL.caution_coverage(st["rain_likely"], {"MA": {PERMIT}})["MA"]["sentence"].split(";"),
             RL.NO_ENTRY]
    for t in texts:
        assert not PUBLIC_WORDS.search(t), t
        assert "rule one out" not in t and "safe" not in t.lower()


# ---------------------------------------------------------------- byte for byte against origin/main's code

BASELINE = Path(__file__).resolve().parent / "fixtures" / "rain_likely_baseline_no_levels.json"
BASELINE_COMMIT = "76c4655"      # origin/main when the levels work began (the merge base); its rain_likely.py and rules


def baseline_cases(rules: dict):
    """Synthetic inputs (deterministic) for compute() with no levels file: an operator with a 10th-percentile row, one
    on the site default, a state entry applying the default, and an operator rule with a season, at three hours."""
    from datetime import UTC, datetime
    from tests.test_rain_likely import rain_input
    rules = {"rain_likely": rules["rain_likely"]}
    waters = {"p-ma": {"slug": "p-ma", "kind": "pond", "state": "MA"}, "p-md": {"slug": "p-md", "kind": "pond", "state": "MD"},
              "p-ky": {"slug": "p-ky", "kind": "pond", "state": "KY"}}
    cases = []
    for now in (datetime(2026, 8, 10, 12, 0, tzinfo=UTC), datetime(2026, 11, 1, 14, 0, tzinfo=UTC),
                datetime(2026, 5, 1, 20, 0, tzinfo=UTC)):
        rain = {"rainfall": {"permits": {}}, "history": None, "thresholds": {"permits": {}}}
        for i, (permit, slug, v) in enumerate((("MA0101613", "p-ma", 0.35), ("MA0100552", "p-ma", 0.15),
                                               ("MD0021598", "p-md", 0.6), ("KY0021466", "p-ky", 0.3))):
            vals = {b: 0.0 for b in range(0, 200)}
            for b in range(4 + 7 * i, 12 + 7 * i):
                vals[b] = v
            r = rain_input(vals, threshold=0.3, permit=permit, now=now)
            info = r["rainfall"]["permits"][permit]
            info.update(state=permit[:2], outfalls=[{"outfall": "001", "water_slug": slug, "water_match": "name"}])
            rain["rainfall"].update({k: v for k, v in r["rainfall"].items() if k != "permits"})
            rain["rainfall"]["permits"][permit] = info
            rain["history"] = rain["history"] or {"start": r["history"]["start"], "permits": {}}
            rain["history"]["permits"][permit] = r["history"]["permits"][permit]
        rain["thresholds"]["permits"]["MA0101613"] = r["thresholds"]["permits"]["KY0021466"]
        cases.append((now, rain, rules, waters))
    return cases


def run_baseline(mod, rules: dict) -> list:
    out = []
    for now, rain, rules, waters in baseline_cases(rules):
        by_water, by_reach, block = mod.compute(copy.deepcopy(rain), rules, [], now, now - timedelta(days=30), waters, [],
                                                {}, lambda r, w: [])
        out.append(json.loads(json.dumps({"by_water": by_water, "by_reach": by_reach, "block": block}, sort_keys=True,
                                          default=str)))
    return out


def test_no_levels_output_equals_origin_mains():
    """The fixture was made once from BASELINE_COMMIT's build/rain_likely.py and data/rules.json (before the levels) by
    running this module from pipeline/: python -m tests.test_rain_levels (the command is in the fixture's _how). HEAD's
    code runs on the same pinned rules: with no levels file it must give the same output."""
    fx = json.loads(BASELINE.read_text())
    assert fx["commit"] == BASELINE_COMMIT and "history" not in fx["rules"]["rain_likely"]
    want = fx["cases"]
    got = run_baseline(RL, fx["rules"])
    assert len(got) == len(want) == 3
    for g, w in zip(got, want):
        assert g == w
    assert any(iv["rule_applied"]["rationale"] for c in got for ivs in c["by_water"].values() for iv in ivs)


if __name__ == "__main__":       # regenerate the baseline from BASELINE_COMMIT's code and rules (git show)
    import importlib.util
    import subprocess
    import tempfile

    def show(path):
        return subprocess.run(["git", "show", f"{BASELINE_COMMIT}:{path}"], check=True, capture_output=True,
                              text=True).stdout
    with tempfile.TemporaryDirectory() as d:
        src = Path(d) / "rain_likely_baseline.py"
        src.write_text(show("pipeline/build/rain_likely.py"))
        spec = importlib.util.spec_from_file_location("build.rain_likely_baseline", src)
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
    pinned = {"rain_likely": json.loads(show("data/rules.json"))["rain_likely"]}
    BASELINE.write_text(json.dumps({
        "_how": (f"made by `python -m tests.test_rain_levels` from pipeline/: the compute() output of "
                 f"`git show {BASELINE_COMMIT}:pipeline/build/rain_likely.py` on baseline_cases(), with the "
                 f"rain_likely block of `git show {BASELINE_COMMIT}:data/rules.json` (kept here as rules)"),
        "commit": BASELINE_COMMIT, "rules": pinned, "cases": run_baseline(old, pinned)}, indent=1, sort_keys=True) + "\n")
