"""MassDEP portal: a notice reported ceased with no cessation time ends at the latest when the ceased report was
published (ingest.ma_massdep.bound_ceased). Before 2026-11-27 such a notice stayed 'end not confirmed' for 30 days:
Springfield's four Initial-Ongoing notices of 2026-11-06, ceased on the portal 2026-11-09, still showed on
2026-11-27. Invented records in the portal's shapes."""
from __future__ import annotations

from datetime import datetime

from build import status as S
from ingest import ma_massdep as M


def rec(num, rtype, start, published, outfall="SPR010", cls="Public Notification Report", status=None, ended=None):
    sid = f"id-{num}"
    st = status or {"Initial-Ongoing": "ongoing", "Ongoing": "ongoing"}.get(rtype, "ended")
    return {"event_id": f"ma-massdep:{sid}", "source_record_id": sid, "source_id": "ma-massdep",
            "event_type": "cso", "status": st, "discharger_name": "SPRINGFIELD WATER & SEWER COMMISSION",
            "outfall_id": outfall, "started_at": start, "ended_at": ended, "time_precision": "minute",
            "published_at": published, "parent_event_id": None,
            "raw": {"_report_class": cls, "reportingType": rtype, "incidentNumber": num,
                    "_parent_number": num.split("-")[0] if rtype == "Ceased" else None}}


def springfield_nov6():
    parent = rec("26017944", "Initial-Ongoing", "2026-11-06T11:10:00-05:00", "2026-11-06T13:23:00-05:00")
    child = rec("26017944-1", "Ceased", "2026-11-06T11:10:00-05:00", "2026-11-09T08:40:00-05:00")
    hol = rec("26018000", "Initial-Ceased", "2026-11-06T10:50:00-05:00", "2026-11-09T11:00:00-05:00",
              outfall="HOL018")
    still = rec("26019999", "Initial-Ongoing", "2026-11-26T17:50:00-05:00", "2026-11-26T19:00:00-05:00",
                outfall="SPR012")
    return parent, child, hol, still


def test_ceased_reports_bound_the_end_at_their_publication():
    parent, child, hol, still = recs = springfield_nov6()
    stats = M.link(list(recs), {})
    assert stats["ceased_linked"] == 1 and stats["ended_by_bound"] == 3
    assert parent["status"] == "ended" and parent["ended_at"] is None and parent["time_precision"] == "bound"
    assert parent["raw"]["_ended_before"] == "2026-11-09T08:40:00-05:00"          # the Ceased child's publication
    assert "26017944-1" in parent["raw"]["_ended_before_basis"]
    assert child["raw"]["_ended_before"] == "2026-11-09T08:40:00-05:00"
    assert hol["raw"]["_ended_before"] == "2026-11-09T11:00:00-05:00"             # Initial-Ceased: its own
    assert still["status"] == "ongoing" and "_ended_before" not in still["raw"]   # an open notice stays open
    assert still["time_precision"] == "minute"


def test_a_verified_end_wins_over_the_bound():
    parent, child, _, _ = springfield_nov6()
    vdr = rec("26018100", "", "2026-11-06T11:10:00-05:00", "2026-12-05T09:00:00-05:00",
              cls="Verified Data Report", status="ended", ended="2026-11-06T13:40:00-05:00")
    M.link([parent, child, vdr], {})
    assert parent["ended_at"] == "2026-11-06T13:40:00-05:00"                  # the verified duration's end
    for r in (parent, child):
        assert r["ended_at"] and "_ended_before" not in r["raw"] and r["time_precision"] == "minute"


def test_the_site_clears_a_ceased_notice_after_the_authority_window_and_the_caution():
    parent, child, hol, still = recs = springfield_nov6()
    M.link(list(recs), {})
    rules = S.load_rules()
    now = datetime.fromisoformat("2026-11-27T03:00:00+00:00")
    for r in (parent, child, hol):
        ivs = S._event_intervals(r, "MA", now, None, rules)
        assert ivs, r["event_id"]
        assert max(iv["end"] for iv in ivs) < now                 # nothing current on Nov 27
        assert not any(iv["color"] == "unresolved" for iv in ivs)
    # while the authority's window runs the notice is red
    soon = datetime.fromisoformat("2026-11-10T12:00:00+00:00")
    ivs = S._event_intervals(parent, "MA", soon, None, rules)
    assert any(iv["color"] == "red" and iv["start"] <= soon < iv["end"] for iv in ivs)
    # the open notice of Nov 26 is red now
    ivs = S._event_intervals(still, "MA", now, None, rules)
    assert any(iv["color"] == "red" and iv["start"] <= now < iv["end"] for iv in ivs)


def test_a_rerun_recomputes_the_bound():
    parent, child, hol, still = recs = springfield_nov6()
    M.link(list(recs), {})
    still["status"] = "ended"                                     # say a later read finds it ceased with a VDR end
    still["ended_at"] = "2026-11-26T20:00:00-05:00"
    M.bound_ceased(list(recs))
    assert "_ended_before" not in still["raw"]
