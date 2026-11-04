"""Items D1 and D2 of docs/reviews/2026-11-03-wording-scan.md: the Kennebec record's name, and source dates the
ingesters keep as written but flag. Synthetic records only. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import ct_deep_archive, ny_sprtk  # noqa: E402

DATA = Path(__file__).resolve().parent.parent.parent / "data"
FETCHED = "2026-11-03T17:37:51Z"
NOTE = "start is in the future as published"


def test_the_bath_record_of_the_kennebec_is_not_named_like_the_other_in_capitals():
    # D1: lists read "Kennebec River, ME, KENNEBEC RIVER, ME" (the record's name lives in waters-nhd.json, not waters-extra.json)
    waters = {}
    for f in ("waters-ne.json", "waters-extra.json", "waters-nhd.json"):
        for w in json.loads((DATA / f).read_text())["waters"]:
            waters[w["slug"]] = w
    bath, main = waters["kennebec-river-bath-me"], waters["kennebec-river-me"]
    assert bath["name"] == "Kennebec River (Bath)" and main["name"] == "Kennebec River"
    assert bath["name"].casefold() != main["name"].casefold() and bath["slug"] == "kennebec-river-bath-me"
    assert "Kennebec River" in bath["aliases"]          # texts that say "Kennebec River" still find the record


def _notice(nid, air, start, end=None):
    n = {"id": nid, "synthetic_id": False, "tab": "t", "tab_index": 0, "row": 2, "row_raw": {}, "website": False,
         "f": {"notificationId": nid, "notificationStatus": "New", "airDateTime": air, "startDateTime": start,
               "endDateTime": end, "duration": "5 Minutes - Ended", "facilityId": "NYS900001",
               "facilityName": "Testville (T) Sanitary Sewers", "streetNumber": "1", "streetName": "Main", "city": "Testville",
               "quantity": "9,921 Gallons Actual"}}
    ny_sprtk.parse_notice(n)
    return n


def _ny_record(air, start, end=None):
    n = _notice("2310900174603285", air, start, end)
    ctx = {"echo": {}, "dischargers": {}, "cso_permits": set(), "place_cache": {}, "fetched_at": FETCHED}
    return ny_sprtk.to_record(n, "key:x", [n], 0, None, ctx)


def test_a_ny_start_more_than_24_hours_ahead_is_flagged_and_the_date_kept():
    # D2: ny-dec-sprtk:2310900174603285 aired 2026-01-02 and starts 2026-12-30 (UTC clock in the workbook: 06:00 = 01:00 EST)
    r = _ny_record("01/02/2026 15:25:52", "12/30/2026 06:00:00", "12/30/2026 06:05:00")
    assert r["started_at"] == "2026-12-30T01:00:00-05:00" and r["ended_at"] == "2026-12-30T01:05:00-05:00"
    assert len(r["raw"]["_dww_note"]) == 1 and r["raw"]["_dww_note"][0].startswith(NOTE)
    assert "2026-12-30T01:00:00-05:00" in r["raw"]["_dww_note"][0] and r["parse_error"] is None
    # 22 hours after the fetch time is not ahead enough; 26 hours is
    assert "_dww_note" not in _ny_record("11/03/2026 17:00:00", "11/04/2026 16:00:00")["raw"]
    assert _ny_record("11/03/2026 17:00:00", "11/04/2026 20:00:00")["raw"]["_dww_note"][0].startswith(NOTE)
    # a start in the past, or a start that only a day tells (the day's local midnight), carries no note
    assert "_dww_note" not in _ny_record("11/02/2026 17:00:00", "11/02/2026 16:00:00")["raw"]
    assert ny_sprtk.future_start_note(None, FETCHED) is None and ny_sprtk.future_start_note(datetime(2026, 1, 1, tzinfo=UTC), "") is None


def _ct_feature(start, stop):
    ms = lambda d: int(d.timestamp() * 1000)  # noqa: E731
    return {"attributes": {"OBJECTID": 1, "UTILITY_NAME": "Testville WPCF", "REPORTING_TOWN": "Testville",
                           "INCIDENT_TYPE1": "Sewage Bypass", "START_DATETIME": ms(start), "STOP_DATETIME": ms(stop),
                           "BYPASS_LOCATION": "Manhole", "STREET_ADDRESS": "1 Main Street", "FINAL_VOLUME": "0"},
            "geometry": {"x": -73.0, "y": 41.5}}


def test_ct_archive_flags_a_future_start_and_a_stop_a_century_late_and_keeps_the_dates():
    fetched = "2026-11-03T21:34:15Z"
    # bypass-35964743: started 2017-05-15, stopped 2107-05-15
    r = ct_deep_archive.normalise("bypass", _ct_feature(datetime(2017, 5, 15, 11, 35, tzinfo=UTC),
                                                       datetime(2107, 5, 15, 12, 30, tzinfo=UTC)), fetched)
    notes = r["raw"]["_dww_note"]
    assert r["started_at"] == "2017-05-15T07:35:00-04:00" and r["ended_at"] == "2107-05-15T08:30:00-04:00"
    assert not any(n.startswith(NOTE) for n in notes)
    assert [n for n in notes if n.startswith("stop is more than a year after the start as published")]
    # a start 2026-12-30: flagged, as written
    r = ct_deep_archive.normalise("bypass", _ct_feature(datetime(2026, 12, 30, 6, 0, tzinfo=UTC),
                                                       datetime(2026, 12, 30, 7, 0, tzinfo=UTC)), fetched)
    assert r["started_at"] == "2026-12-30T01:00:00-05:00" and r["ended_at"] == "2026-12-30T02:00:00-05:00"
    assert [n for n in r["raw"]["_dww_note"] if n.startswith(NOTE)] and r["parse_error"] is None
    # an ordinary record: no date note
    r = ct_deep_archive.normalise("bypass", _ct_feature(datetime(2019, 6, 1, 12, 0, tzinfo=UTC),
                                                       datetime(2019, 6, 1, 14, 0, tzinfo=UTC)), fetched)
    assert not [n for n in r["raw"].get("_dww_note", []) if n.startswith(NOTE) or "a year after" in n]
    assert ct_deep_archive.date_notes("2026-11-04T12:00:00-05:00", None, fetched) == []     # under 24 hours ahead
