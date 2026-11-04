"""out/coverage.json (docs/plan.md §2.y, export/coverage.py): what is reported, state by state and water by water,
and the grade a quiet map must carry. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from common import event  # noqa: E402
from export import coverage as C  # noqa: E402

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=UTC)
D = timedelta(days=1)


@pytest.fixture(autouse=True)
def covered(monkeypatch):
    monkeypatch.setattr(S, "_STATES", {"MA", "NJ", "ME", "PA", "VA", "CT"})


def iso(t):
    return t.isoformat().replace("+00:00", "Z")


def rec(sid, rid, state, start, prec=None, **kw):
    extra = {k: kw.pop(k) for k in ("superseded", "state_") if k in kw}
    e = event(source_id=sid, source_record_id=rid, event_type=kw.pop("event_type", "cso"), status="ended",
              started_at=iso(start) if isinstance(start, datetime) else start, time_precision=prec,
              water_slugs=kw.pop("water_slugs", []), **kw)
    e["state"] = state
    if "superseded" in extra:
        e["superseded"] = extra["superseded"]
    return e


FEEDS = [{"source_id": "ma-massdep", "registry_ids": ["r-ma"], "expected_cadence_hours": 6},
         {"source_id": "nj-echo-monthly", "registry_ids": ["r-nj"], "expected_cadence_hours": 720},
         {"source_id": "me-dep-cso-annual", "registry_ids": ["r-me"], "expected_cadence_hours": 8760},
         {"source_id": "pa-phila-csocast", "registry_ids": ["r-pa"], "expected_cadence_hours": 1},
         {"source_id": "va-deq-prep", "registry_ids": ["r-va"], "expected_cadence_hours": 24},
         {"source_id": "ct-quiet", "registry_ids": ["r-ct"], "expected_cadence_hours": 24}]
REGISTRY = [{"id": "r-ma", "name": "MassDEP sewage notifications", "states": ["MA"], "event_types": ["cso", "sso"]},
            {"id": "r-nj", "name": "EPA monthly reports", "states": ["NJ"], "event_types": ["cso"]},
            {"id": "r-me", "name": "Maine DEP annual totals", "states": ["ME"], "event_types": ["annual_total"]},
            {"id": "r-pa", "name": "Philadelphia CSOcast", "states": ["PA"], "event_types": ["cso"]},
            {"id": "r-va", "name": "Virginia DEQ", "states": ["VA"], "event_types": ["sso"]},
            {"id": "r-ct", "name": "Connecticut dashboard", "states": ["CT"], "event_types": ["cso", "sso"]}]
RULES = {"red": {"by_state": {
    "VA": {"basis": "Virginia law places no public notice duty on the discharger (Va. Code § 62.1-44.5 B). "
                    "Reports go to DEQ within 24 hours."},
    "MA": {"basis": "Massachusetts requires notices to tell people to avoid contact for 48 hours. This site counts them."}}}}
WATERS = [{"slug": "test-river-ma", "state": "MA", "events": ["ma-massdep:1", "ma-massdep:2"]},
          {"slug": "hudson-river-nj", "state": "NJ", "events": ["nj-echo-monthly:1"]},
          {"slug": "quiet-brook-ct", "state": "CT", "events": []}]


def build(events):
    return C.coverage(events, WATERS, FEEDS, REGISTRY, [], RULES, iso(NOW), rain_states={"MA": {"covered": True}})


def test_grades_follow_the_plans_thresholds_and_poll_precision_counts_as_dated():
    evs = [rec("ma-massdep", "1", "MA", NOW - 2 * D, "minute", reported_at=iso(NOW - 2 * D + timedelta(hours=6)),
               water_slugs=["test-river-ma"]),
           rec("ma-massdep", "2", "MA", NOW - 5 * D, "minute", reported_at=iso(NOW - 5 * D + timedelta(hours=2))),
           rec("ma-massdep", "3", "MA", NOW - 9 * D, "minute", reported_at=iso(NOW - 9 * D + timedelta(hours=4))),
           rec("ma-massdep", "old", "MA", NOW - 400 * D, "minute"),                       # outside the 12 months
           rec("ma-massdep", "rev", "MA", NOW - 3 * D, "minute", superseded="revised by ma-massdep:1"),
           rec("ma-massdep", "dup", "MA", NOW - 3 * D, "minute", duplicate_of="ma-massdep:1"),
           rec("nj-echo-monthly", "1", "NJ", "2026-09-01", "month", water_slugs=["hudson-river-nj"]),
           rec("nj-echo-monthly", "2", "NJ", "2026-08-01", "month"),
           rec("me-dep-cso-annual", "1", "ME", "2025-01-01", "year", event_type="annual_total",
               published_at="2026-04-01"),
           rec("pa-phila-csocast", "1", "PA", NOW - 1 * D, "poll"), rec("pa-phila-csocast", "2", "PA", NOW - 2 * D, "poll"),
           rec("va-deq-prep", "1", "VA", NOW - 40 * D, "minute", event_type="sso",
               reported_at=iso(NOW - 40 * D + 9 * D)),
           rec("va-deq-prep", "2", "VA", NOW - 41 * D, "minute", event_type="sso", reported_at=iso(NOW - 41 * D + 10 * D)),
           rec("va-deq-prep", "3", "VA", NOW - 42 * D, "minute", event_type="sso", reported_at=iso(NOW - 42 * D + 8 * D))]
    cov = build(evs)
    st = cov["states"]
    ma = st["MA"]
    assert (ma["grade"], ma["records_12m"], ma["dated_share"]) == ("Dated reports", 3, 1.0)
    assert ma["latest_dated"] == iso(NOW - 2 * D) and ma["lag_days"] == 0.17           # median of 6, 2 and 4 hours
    assert ma["sentence"] == "Massachusetts publishes dated overflow reports; the newest is from Nov 1, 2026."
    assert ma["duty"] == "Massachusetts requires notices to tell people to avoid contact for 48 hours."
    assert ma["feeds"][0]["name"] == "MassDEP sewage notifications" and ma["feeds"][0]["precision_text"] == "to the minute"
    assert ma["rain_caution"] == {"covered": True} and cov["rain_caution_states"] == {"MA": {"covered": True}}
    pa = st["PA"]
    assert pa["grade"] == "Dated reports" and pa["dated_share"] == 1.0
    assert pa["feeds"][0]["precision"] == "poll" and pa["feeds"][0]["precision_text"] == "to the poll (checked through the day)"
    nj = st["NJ"]
    assert nj["grade"] == "Monthly totals only" and nj["dated_share"] == 0.0 and nj["latest_dated"] is None
    assert "monthly totals, not dated reports" in nj["sentence"]
    assert st["ME"]["grade"] == "Annual totals only" and st["ME"]["records_12m"] == 1    # counted by its publication
    va = st["VA"]
    assert va["grade"] == "Dated reports, delayed" and va["lag_days"] == 9.0
    assert "the newest is from Sep 24, 2026 and reports typically appear 9 days after a discharge" in va["sentence"]
    assert va["duty"] == "Virginia law places no public notice duty on the discharger (Va. Code § 62.1-44.5 B)."
    ct = st["CT"]
    assert ct["grade"] == "No public reports" and ct["records_12m"] == 0 and ct["duty"] is None
    assert ct["sentence"].startswith("Connecticut publishes no sewage overflow reports we can read")
    assert ct["feeds"] == [{"source_id": "ct-quiet", "name": "Connecticut dashboard", "precision": None,
                            "precision_text": None, "precisions": {}, "cadence_hours": 24, "records_12m": 0,
                            "latest": None, "lag_days": None}]
    w = cov["waters"]
    assert w["hudson-river-nj"]["grade"] == "Monthly totals only"
    assert w["hudson-river-nj"]["sentence"].startswith("Only monthly totals are reported for this water")
    assert w["test-river-ma"]["grade"] == "Dated reports" and w["test-river-ma"]["records_12m"] == 2
    assert w["quiet-brook-ct"]["records_12m"] == 0 and w["quiet-brook-ct"]["state_grade"] == "No public reports"
    assert w["quiet-brook-ct"]["sentence"].startswith("No report we read names this water in the last 12 months")


def test_a_mostly_dated_state_whose_newest_report_is_old_is_delayed_and_no_state_code_is_invented():
    evs = [rec("ma-massdep", str(i), "MA", NOW - (20 + i) * D, "day") for i in range(5)]
    evs.append(rec("ma-massdep", "us", "US", NOW - 3 * D, "minute"))
    cov = build(evs)
    assert cov["states"]["MA"]["grade"] == "Dated reports, delayed" and "US" not in cov["states"]
    assert cov["states"]["MA"]["sentence"] == ("Massachusetts publishes dated reports, but the newest is from Oct 14, "
                                               "2026; a quiet map in Massachusetts can mean a report has not appeared yet.")
    assert C.is_dated({"time_precision": "poll"}) and C.is_dated({"time_precision": "hour"})
    assert not C.is_dated({"time_precision": "month"}) and not C.is_dated({"event_type": "annual_total"})


def test_barriers_and_how_each_states_operators_tell_the_public():
    def ch(i, st, op=None, **kw):
        base = {"id": f"{st.lower()}-{i}", "state": st, "operator_id": op, "agency": None if op else "Agency",
                "channel_kind": "operator_page", "publishes": "unknown", "monitored": False,
                "unmonitored_reason": "other", "barrier": None, "note": ""}
        base.update(kw)
        return base
    reg = {"channels": [
        # state A: a state table covering every operator posts each overflow (read through a feed)
        ch("table", "MA", channel_kind="feed", publishes="notices", unmonitored_reason="feed_ingested",
           feed_source_id="ma-massdep", note="Covers every operator in the state"),
        ch("a1", "MA", "ma-a", barrier="not_verified"), ch("a2", "MA", "ma-b", barrier="login_required"),
        # state B: the operators' own channels only
        ch("site", "NJ", "nj-a", channel_kind="shared_site", publishes="likelihood", monitored=True,
           unmonitored_reason=None),
        ch("pdf", "NJ", "nj-b", publishes="notices", monitored=True, unmonitored_reason=None),
        ch("mail", "NJ", "nj-c", channel_kind="news_page", barrier="print_only"),
        ch("x", "NJ", "nj-d", channel_kind="social", publishes="notices", unmonitored_reason="login",
           barrier="login_required"),
        ch("signs", "NJ", None, channel_kind="lights_signs_page", barrier="signs_only", note="Covers: nj-e, nj-d"),
        ch("e", "NJ", "nj-e", barrier="not_verified"), ch("f", "NJ", "nj-f", barrier="no_web_page"),
        ch("echo", "NJ", None, channel_kind="feed", publishes="notices", unmonitored_reason="feed_ingested",
           feed_source_id="echo-sewer-overflow", note="Covers every operator in the state"),
        ch("wall", "NJ", "nj-f", publishes="notices", barrier="bot_wall", unmonitored_reason="bot_wall")]}
    out = C.notice_reach(reg, frozenset({"ma-massdep", "echo-sewer-overflow"}))
    ma, nj = out["MA"], out["NJ"]
    assert ma["told_online"]["operators"] == 2 and ma["told_online"]["share"] == 1.0
    assert ma["barriers"] == {"login_required": {"count": 1, "ids": ["ma-b"]}, "not_verified": {"count": 1, "ids": ["ma-a"]}}
    t = nj["told_online"]
    assert t["classes"] == {"online": ["nj-b", "nj-f"], "likelihood": ["nj-a"], "print_only": ["nj-c"],
                            "login_only": ["nj-d"], "signs_only": ["nj-e"], "none": []}
    assert (t["operators"], t["online"], t["share"]) == (6, 2, 0.3333)
    assert t["labels"]["online"] == "posted online for each overflow"
    assert nj["barriers"]["signs_only"] == {"count": 1, "ids": ["nj-signs"]}            # an agency row: its own id
    # the export carries them per state
    evs = [rec("ma-massdep", "1", "MA", NOW - 2 * D, "minute")]
    cov = C.coverage(evs, WATERS, FEEDS, REGISTRY, [], RULES, iso(NOW), register=reg)
    assert cov["states"]["MA"]["told_online"]["online"] == 2 and "barriers" in cov["states"]["MA"]
