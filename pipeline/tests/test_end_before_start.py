"""Records whose end came out before their start (2026-11-03): the CT forms' "00:00 AM" end on the start's
own date is the midnight that closes that day; a MassDEP Verified Data Report's end is not copied into a
notice that started after it. Ends before starts that the sources themselves give stay as they are (the
status build ignores the end and notes it).
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import ma_massdep  # noqa: E402
from ingest.ct_deep import midnight_end  # noqa: E402


def test_a_midnight_end_on_the_start_date_is_the_end_of_that_day():
    end, note = midnight_end("2026-09-29T12:45:00-04:00", "2026-09-29T00:00:00-04:00")
    assert end == "2026-09-30T00:00:00-04:00" and "midnight that ends that day" in note
    # across the change back to standard time the next midnight carries its own offset
    assert midnight_end("2026-11-01T12:45:00-05:00", "2026-11-01T00:00:00-04:00")[0] == "2026-11-02T00:00:00-05:00"


def test_other_ends_before_the_start_are_left_as_the_source_gives_them():
    for st, en in [("2026-09-26T03:30:00-04:00", "2026-09-26T00:30:00-04:00"),     # overnight, date not advanced
                   ("2025-10-13T00:45:00-04:00", "2025-10-12T23:45:00-04:00"),     # end date before start date
                   ("2026-09-26T03:30:00-04:00", "2026-09-27T00:00:00-04:00")]:    # a valid next-day midnight
        assert midnight_end(st, en) == (en, None)
    assert midnight_end(None, "2026-09-26T00:00:00-04:00") == ("2026-09-26T00:00:00-04:00", None)


def rec(rid, cls, start, end=None, kind=None, number=None, parent=None, status="ongoing"):
    raw = {"_report_class": cls, "incidentNumber": number or rid}
    if kind:
        raw["reportingType"] = kind
    if parent:
        raw["parentIncidentId"] = parent
    return {"event_id": f"ma-massdep:{rid}", "source_record_id": rid, "started_at": start, "ended_at": end,
            "outfall_id": "001", "discharger_name": "Town", "status": status, "parent_event_id": None,
            "published_at": None, "raw": raw}


def test_a_verified_end_before_the_notices_start_is_not_copied():
    notice = rec("n1", "Public Notification Report", "2026-09-13T19:00:00-04:00", kind="Initial-Ongoing")
    vdr = rec("v1", "Verified Data Report", "2026-09-13T18:30:00-04:00", "2026-09-13T18:36:00-04:00",
              number="26017880", status="ended")
    ceased = rec("c1", "Public Notification Report", "2026-09-13T19:30:00-04:00", kind="Ceased", parent="n1")
    stats = ma_massdep.link([notice, vdr, ceased], {})
    assert notice["ended_at"] is None and notice["status"] == "ended"
    assert "18:36" in notice["raw"]["_verified_period"] and vdr["parent_event_id"] == "ma-massdep:n1"
    assert ceased["ended_at"] is None and stats["verified_end_before_notice_start"] == 1


def test_a_verified_end_after_the_notices_start_is_copied():
    notice = rec("n2", "Public Notification Report", "2026-09-13T18:40:00-04:00", kind="Initial-Ongoing")
    vdr = rec("v2", "Verified Data Report", "2026-09-13T18:30:00-04:00", "2026-09-13T21:00:00-04:00",
              number="26017881", status="ended")
    early = rec("c2", "Public Notification Report", "2026-09-13T20:00:00-04:00", kind="Ceased", parent="n2")
    late = rec("c3", "Public Notification Report", "2026-09-13T21:30:00-04:00", kind="Ceased", parent="n2")
    ma_massdep.link([notice, vdr, early, late], {})
    assert notice["ended_at"] == "2026-09-13T21:00:00-04:00" and "_verified_period" not in notice["raw"]
    assert early["ended_at"] == "2026-09-13T21:00:00-04:00"      # a Ceased update takes its parent's verified end
    assert late["ended_at"] is None                               # unless that end is before its own start
