"""NH beach reason and bloom regression tests, using synthetic source attributes."""
from datetime import UTC, datetime

import pytest

from build import beach_reason as BR, status as S
from ingest import nh_des_swimming as NH

AT = "2026-11-25T01:34:00Z"
NOW = datetime(2026, 11, 25, tzinfo=UTC)


def record(monkeypatch, label, **extra):
    monkeypatch.setattr(NH, "match_waters", lambda *args: ([], []))
    attrs = {"EPA_ID": "TEST", "Beach_Name": "Example Beach", "Status": label,
             "SampleDate": 1795478400000, "DateIssued": 1795478400000, **extra}
    return NH.beach_records([{"attributes": attrs}], AT, AT)


@pytest.mark.parametrize("label", ["Closed", "Monitoring Season Completed", "Unrecognized status"])
def test_reasonless_status_is_listed_without_colour(monkeypatch, label):
    r, = record(monkeypatch, label)
    rules = S.load_rules()
    assert r["raw"]["Status"] == label
    assert BR.judge(r, rules)["stated"] is False
    assert S.event_intervals(r, "NH", NOW, rules=rules) == []
    assert r["status"] != "advisory_active"
    assert BR.label(r, BR.config(rules)) == "Beach status listed; the source gives no water-quality reason"


def test_program_advisory_and_dated_history_keep_their_reason(monkeypatch):
    current, = record(monkeypatch, "Advisory")
    seasonal, history = record(monkeypatch, "Monitoring Season Completed", Advisory_history="7/3-7/5")
    rules = S.load_rules()
    assert BR.judge(current, rules)["stated"] is True
    assert BR.judge(history, rules)["stated"] is True
    assert history["status"] == "advisory_lifted"
    assert S.event_intervals(current, "NH", NOW, rules=rules)
    assert S.event_intervals(history, "NH", NOW, rules=rules)
    assert not S.event_intervals(seasonal, "NH", NOW, rules=rules)


def test_blooms_stay_in_the_bloom_category(monkeypatch):
    monkeypatch.setattr(NH, "match_waters", lambda *args: ([], []))
    r, = NH.hab_records([{"attributes": {"WB_ID": "TEST", "WB_NAME": "Example Lake",
        "Bloom_status": "Warning", "LatestAdvisory": "Warning", "StatusDate": 1795478400000}}], AT, AT)
    assert r["event_type"] == "hab_advisory" and S.category_of(r["event_type"]) == "bloom"
    assert BR.judge(r, S.load_rules()) is None
