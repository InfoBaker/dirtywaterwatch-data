"""Every live state has a coverage row (live site 2026-11-16: https://dirtywaterwatch.org/state/ok/ had no "Data and
its limits" section). Oklahoma's one feed, the National Park Service's bacteria table for Chickasaw, is a beach feed
(event type beach_advisory, not sewage) and read no result at the threshold, so it made no record: with no sewage
report and no sewage feed, export/coverage.coverage gave Oklahoma no row, and the site's own fallback none either.
A live state with no report gets the grade "No public reports" with no invented date or share; a state that is not
live still gets no row; every other row is what it was."""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from export import coverage as C  # noqa: E402
from tests.test_coverage import D, FEEDS, NOW, REGISTRY, RULES, WATERS, iso, rec  # noqa: E402

LIVE = {"MA", "NJ", "ME", "PA", "VA", "CT", "OK"}
# Oklahoma's real shape: a registered feed that is a beach feed (not sewage) and no record at all
OK_FEED = {"source_id": "ok-nps-chickasaw-bacteria", "registry_ids": ["ok-nps-chickasaw-bacteria"],
           "expected_cadence_hours": 168, "ok": True, "last_ok_at": "2026-11-16T03:00:00Z"}
OK_ROW = {"id": "ok-nps-chickasaw-bacteria", "level": "federal", "states": ["OK"], "event_types": ["beach_advisory"],
          "name": "National Park Service, Chickasaw National Recreation Area: bathing beach monitoring (E. coli table)"}


def events():
    return [rec("ma-massdep", "1", "MA", NOW - 2 * D, "minute", water_slugs=["test-river-ma"]),
            rec("ma-massdep", "2", "MA", NOW - 40 * D, "hour", water_slugs=["test-river-ma"]),
            rec("nj-echo-monthly", "1", "NJ", NOW - 60 * D, "month", water_slugs=["hudson-river-nj"]),
            rec("me-dep-cso-annual", "1", "ME", NOW - 90 * D, "year", event_type="annual_total"),
            rec("pa-phila-csocast", "1", "PA", NOW - 1 * D, "poll"),
            rec("va-deq-prep", "1", "VA", NOW - 20 * D, "day"),
            # a report in a state that is not live (Kansas here, not in LIVE): never a row
            rec("ks-somewhere", "1", "KS", NOW - 3 * D, "day")]


def build(live, feeds=FEEDS + [OK_FEED], registry=REGISTRY + [OK_ROW]):
    return C.coverage(events(), WATERS, feeds, registry, [], RULES, iso(NOW), live=live)


def test_a_live_state_with_a_feed_and_no_record_gets_a_no_public_reports_row(monkeypatch):
    monkeypatch.setattr(S, "_STATES", LIVE)
    ok = build(LIVE)["states"].get("OK")
    assert ok is not None, "a live state with no report must still have a coverage row"
    assert ok["code"] == "OK" and ok["name"] == "Oklahoma"
    assert ok["grade"] == "No public reports"
    assert ok["sentence"] == ("Oklahoma has published no sewage overflow reports we can read in the last 12 months; the "
                              "map shows no recent discharges there because none are reported, not because none happen.")
    assert ok["records_12m"] == 0 and ok["dated"] == 0
    # none, not zero percent of zero, and no made-up date
    assert ok["dated_share"] is None and ok["latest_dated"] is None and ok["lag_days"] is None
    assert ok["feeds"] == []      # the beach feed is not a sewage feed: not listed as one
    assert "published_in_batches" not in ok
    blob = json.dumps(ok)
    assert not re.search(r"\b(NaN|undefined|Infinity)\b", blob)


def test_a_live_state_with_nothing_at_all_gets_a_row_and_a_state_not_live_gets_none(monkeypatch):
    monkeypatch.setattr(S, "_STATES", LIVE)
    cov = build(LIVE, feeds=FEEDS, registry=REGISTRY)       # Oklahoma with no feed registered at all
    assert cov["states"]["OK"]["grade"] == "No public reports"
    assert "KS" not in cov["states"]                       # a report there, but not live
    assert set(cov["states"]) == LIVE


def test_every_other_states_row_is_unchanged(monkeypatch):
    """Compared on the test fixtures (the export's inputs are not in the repository): the row of every state that had
    one before the change is identical, byte for byte as JSON, with or without the live list."""
    monkeypatch.setattr(S, "_STATES", LIVE)
    before = C.coverage(events(), WATERS, FEEDS + [OK_FEED], REGISTRY + [OK_ROW], [], RULES, iso(NOW))
    after = build(LIVE)
    assert "OK" not in before["states"]                    # the defect: no row without the live list
    for st, row in before["states"].items():
        if st in LIVE:
            assert json.dumps(after["states"][st], sort_keys=True) == json.dumps(row, sort_keys=True), st
    assert json.dumps(after["waters"], sort_keys=True) == json.dumps(before["waters"], sort_keys=True)


def test_the_export_passes_the_live_states():
    src = (Path(__file__).resolve().parent.parent / "export" / "build.py").read_text()
    call = src[src.index("cov = coverage_mod.coverage("):]
    call = call[:call.index("write_compact(OUT_DIR / \"coverage.json\"")]
    assert "live=status_mod.states()" in call
