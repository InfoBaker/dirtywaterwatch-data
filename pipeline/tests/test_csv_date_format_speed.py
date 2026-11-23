"""Calendar-day formatting keeps the site's New York date without locale formatting per row."""
from datetime import UTC, datetime

import pytest

from export import csv as C


@pytest.mark.parametrize('stamp', [
    '2026-01-01T04:59:00+00:00', '2026-01-01T05:00:00+00:00',
    '2026-03-08T06:59:00+00:00', '2026-03-08T07:00:00+00:00',
    '2026-11-01T05:59:00+00:00', '2026-11-01T06:00:00+00:00',
    '2024-02-29T05:00:00+00:00', '1969-12-31T23:59:00+00:00',
    '0999-12-31T12:00:00+00:00', '1000-01-01T12:00:00+00:00',
    '9999-12-31T12:00:00+00:00',
])
def test_ny_day_matches_existing_calendar_format(stamp):
    minutes = int(datetime.fromisoformat(stamp).timestamp() // 60)
    expected = datetime.fromtimestamp(minutes * 60, UTC).astimezone(C.NY).strftime('%Y-%m-%d')
    assert C._ny_day(minutes) == expected


def test_modern_day_does_not_call_locale_formatter(monkeypatch):
    class Instant:
        year = 2026

        def astimezone(self, zone):
            assert zone == C.NY
            return self

        def date(self):
            return datetime(2026, 6, 1).date()

        def strftime(self, fmt):
            raise AssertionError('locale formatting repeated for a CSV date')

    class Clock:
        @staticmethod
        def fromtimestamp(value, zone):
            return Instant()

    monkeypatch.setattr(C, 'datetime', Clock)
    assert C._ny_day(0) == '2026-06-01'
