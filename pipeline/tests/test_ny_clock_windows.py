"""NY stored-date windows; delivered with the shared status patch."""
from datetime import UTC, datetime, timedelta

import pytest

from build import status as S
from common import event

RULES = {"red": {"by_state": {"NY": {"hours": None}}}, "yellow": {"default_hours": 72},
         "unresolved": {"ongoing_red_days": 7, "unresolved_yellow_days": 30, "unknown_status_yellow_days": 14}}
NOW = datetime(2026, 11, 22, tzinfo=UTC)


@pytest.mark.parametrize("start, bound", [
    ("2021-03-02T00:00:00-05:00", "2021-03-04T05:00:00+00:00"),
    ("2021-03-13T00:00:00-05:00", "2021-03-15T04:00:00+00:00"),
    ("2021-11-06T00:00:00-04:00", "2021-11-08T05:00:00+00:00"),
])
@pytest.mark.parametrize("status, days", [("ongoing", 7), ("unknown", 14)])
def test_stored_date_windows_keep_start_and_count_from_latest_bound(start, bound, status, days):
    e = event(source_id="ny-dec-sprtk", source_record_id="clock", event_type="sso", status=status,
              started_at=start, time_precision="day")
    latest = datetime.fromisoformat(bound)
    ivs = S.event_intervals(e, "NY", NOW, rules=RULES)
    assert ivs[0]["start"] == datetime.fromisoformat(start)
    assert ivs[0]["end"] == latest + timedelta(days=days)
    assert ivs[1]["end"] == latest + timedelta(days=30)
    assert ivs[-1]["end"] == latest + timedelta(days=S.NOTE_DAYS)
    assert S.end_assumed(e, NOW, RULES) == latest + timedelta(days=30)
    assert e["started_at"] == start and e["ended_at"] is None


def test_a_later_report_keeps_its_clock_but_uses_the_later_start_cap():
    e = event(source_id="ny-dec-sprtk", source_record_id="clock", event_type="sso", status="unknown",
              started_at="2021-03-02T00:00:00-05:00", published_at="2021-03-22T12:00:00-04:00",
              time_precision="day")
    ivs = S.event_intervals(e, "NY", NOW, rules=RULES)
    assert ivs[0]["start"] == datetime.fromisoformat(e["published_at"])
    assert ivs[0]["end"] == datetime(2021, 4, 3, 5, tzinfo=UTC)


@pytest.mark.parametrize("source, precision", [("ny-dec-sprtk-history", "day"), ("ny-dec-sprtk-web", "day"),
                                                ("ny-dec-sprtk", "minute"), ("another-feed", "day")])
def test_other_clocks_keep_their_existing_windows(source, precision):
    e = event(source_id=source, source_record_id="clock", event_type="sso", status="ongoing",
              started_at="2021-03-02T00:00:00-05:00", time_precision=precision)
    start = datetime.fromisoformat(e["started_at"])
    ivs = S.event_intervals(e, "NY", NOW, rules=RULES)
    assert ivs[0]["end"] == start + timedelta(days=7)
    assert S.end_assumed(e, NOW, RULES) == start + timedelta(days=30)
