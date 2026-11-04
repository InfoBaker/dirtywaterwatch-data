"""VT DEC pending-report retention, Manchester all-clear bounds and NH per-permittee health
(review 2026-11-02 findings #3, #11, #14). No network: the merge/pairing/assembly functions are
called directly on synthetic records.

Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from common import event  # noqa: E402
from ingest import nh_permittees as NH  # noqa: E402
from ingest import vt_dec as VT  # noqa: E402

T0 = "2026-10-01T12:00:00Z"


def vt(kind: str, rid: str, facility="Hartford - WRJ", start="2026-09-20T07:00:00-04:00", sub=None, **raw):
    r = {"Submission Number": sub or (rid if kind == "pending" else "")}
    r.update(raw)
    return event(source_id="vt-dec", source_record_id=f"{kind}:{rid}", discharger_name=facility,
                 started_at=start, status="unknown", raw=r)


# --------------------------------------------------------------------------- VT #3

def test_pending_absent_without_replacement_is_kept_and_marked():
    p = vt("pending", "HQS-1")
    out = VT.merge([p], [], T0)
    assert [r["event_id"] for r in out] == ["vt-dec:pending:HQS-1"]
    assert out[0]["raw"]["_pending_missing_since"] == T0


def test_missing_since_is_not_reset_by_later_runs():
    p = vt("pending", "HQS-1")
    VT.merge([p], [], T0)
    out = VT.merge([p], [], "2026-10-20T12:00:00Z")
    assert out[0]["raw"]["_pending_missing_since"] == T0


def test_pending_dropped_after_90_days_missing():
    p = vt("pending", "HQS-1")
    VT.merge([p], [], T0)
    assert VT.merge([p], [], "2026-12-29T12:00:00Z") == [p]          # day 89
    assert VT.merge([p], [], "2026-12-31T12:00:00Z") == []           # day 91


def test_pending_replaced_by_reviewed_with_same_submission():
    p = vt("pending", "HQS-1")
    rev = vt("incident", "7200", sub="HQS-1", start="2026-09-21T08:00:00-04:00")
    out = VT.merge([p], [rev], T0)
    assert [r["event_id"] for r in out] == ["vt-dec:incident:7200"]


def test_pending_replaced_by_reviewed_with_same_facility_and_start_day():
    p = vt("pending", "HQS-1")
    rev = vt("incident", "7201", sub="HQS-OTHER", start="2026-09-20T09:30:00-04:00")
    out = VT.merge([p], [rev], T0)
    assert [r["event_id"] for r in out] == ["vt-dec:incident:7201"]


def test_reviewed_from_an_earlier_run_also_replaces():
    p = vt("pending", "HQS-1")
    rev = vt("incident", "7200", sub="HQS-1")
    out = VT.merge([p, rev], [], T0)
    assert [r["event_id"] for r in out] == ["vt-dec:incident:7200"]


def test_other_facility_same_day_does_not_replace():
    p = vt("pending", "HQS-1")
    rev = vt("incident", "7202", facility="Woodstock", sub="HQS-X")
    out = VT.merge([p], [rev], T0)
    assert {r["event_id"] for r in out} == {"vt-dec:pending:HQS-1", "vt-dec:incident:7202"}


def test_pending_back_on_the_page_clears_the_mark():
    p = vt("pending", "HQS-1")
    VT.merge([p], [], T0)
    again = vt("pending", "HQS-1")
    again["raw"]["_pending_missing_since"] = T0      # as if copied from an old record
    out = VT.merge([p], [again], "2026-10-02T12:00:00Z")
    assert len(out) == 1 and "_pending_missing_since" not in out[0]["raw"]


def test_pending_on_page_dropped_only_by_submission_number():
    p = vt("pending", "HQS-1")
    rev = vt("incident", "7201", sub="HQS-OTHER")    # same facility and day, other submission
    out = VT.merge([], [p, rev], T0)
    assert {r["event_id"] for r in out} == {"vt-dec:pending:HQS-1", "vt-dec:incident:7201"}


def test_missing_table_is_a_failed_fetch():
    tables = {t: [["h"]] for t in VT.TABLES}
    VT.check_tables(tables)
    del tables["body_GridViewSewageOverflowsUnOfficial"]
    with pytest.raises(RuntimeError, match="UnOfficial"):
        VT.check_tables(tables)


# --------------------------------------------------------------------------- NH #11

def mh(item: int, kind: str, published: str) -> dict:
    return NH._ev("manchester", f"Item{item}", event_type="cso", status="unknown",
                  reported_at=published, published_at=published, time_precision="minute",
                  raw={"item_id": f"Item{item}", "kind": kind, "published": published})


def test_all_clear_gives_a_bound_not_an_end():
    a1 = mh(1, "activation", "2026-10-12T15:04:00-04:00")
    a2 = mh(2, "activation", "2026-10-14T00:08:00-04:00")
    c = mh(3, "all_clear", "2026-10-18T08:23:00-04:00")
    late = mh(4, "activation", "2026-10-20T10:00:00-04:00")
    NH.pair_manchester([late, c, a2, a1])
    for a in (a1, a2):
        assert a["status"] == "ended" and a["ended_at"] is None and a["time_precision"] == "bound"
        assert a["raw"]["_ended_before"] == "2026-10-17T20:23:00-04:00"
        assert "Item3" in a["raw"]["_ended_before_basis"]
    assert c["status"] == "ended" and c["ended_at"] is None and c["time_precision"] == "bound"
    assert c["parent_event_id"] == a2["event_id"]
    assert c["raw"]["_ended_before"] == "2026-10-17T20:23:00-04:00"
    assert late["status"] == "ongoing" and late["ended_at"] is None and "_ended_before" not in late["raw"]


def test_same_minute_activation_and_all_clear():
    a = mh(14032, "activation", "2026-10-18T08:23:00-04:00")
    c = mh(14033, "all_clear", "2026-10-18T08:23:00-04:00")
    NH.pair_manchester([c, a])
    assert a["status"] == "ended" and a["ended_at"] is None
    assert c["parent_event_id"] == a["event_id"]


def test_pairing_is_idempotent_and_clears_old_exact_ends():
    a = mh(1, "activation", "2026-10-12T15:04:00-04:00")
    a["ended_at"], a["raw"]["ended_at_basis"] = "2026-10-12T03:00:00-04:00", "old"
    c = mh(2, "all_clear", "2026-10-13T08:00:00-04:00")
    NH.pair_manchester([a, c])
    NH.pair_manchester([a, c])
    assert a["ended_at"] is None and "ended_at_basis" not in a["raw"]
    assert a["raw"]["_ended_before"] == "2026-10-12T20:00:00-04:00"


# --------------------------------------------------------------------------- NH #14

def nashua_rec(day: str) -> dict:
    return NH._ev("nashua", f"{day}:006", event_type="cso", status="ended", started_at=f"{day}T00:00:00-04:00",
                  water_slugs=["nashua-river-nh"], water_match="outfall_registry", raw={})


def test_partial_failure_keeps_records_and_the_failed_clock():
    prev_file = {"ok": True, "last_ok_at": "2026-10-01T00:00:00Z",
                 "meta": {"permittees": {"nashua": {"ok": True, "last_ok_at": "2026-10-30T00:00:00Z"}}},
                 "records": [nashua_rec("2026-08-03")]}
    new = {"manchester": [mh(9, "activation", "2026-11-01T10:00:00-04:00")],
           "portsmouth": [], "exeter": []}
    records, health = NH.assemble(prev_file, new, {"nashua": "HTTPError: 503"}, "2026-11-02T12:00:00Z")
    assert "nh-permittees:nashua:2026-08-03:006" in {r["event_id"] for r in records}
    f = health["partial_failures"]
    assert set(f) == {"nashua"}
    assert f["nashua"]["last_ok_at"] == "2026-10-30T00:00:00Z"          # not refreshed by the others
    assert f["nashua"]["water_slugs"] == ["nashua-river-nh"]
    assert f["nashua"]["event_id_prefix"] == "nh-permittees:nashua:"
    assert f["nashua"]["error"] == "HTTPError: 503"
    p = health["permittees"]
    assert p["nashua"]["ok"] is False and p["nashua"]["last_ok_at"] == "2026-10-30T00:00:00Z"
    assert p["manchester"] == {"ok": True, "last_ok_at": "2026-11-02T12:00:00Z",
                               "last_attempt_at": "2026-11-02T12:00:00Z", "error": None, "records": 1}


def test_repeated_failures_keep_the_old_clock():
    prev_file = {"ok": True, "meta": {"permittees": {"exeter": {"ok": False, "last_ok_at": "2026-09-01T00:00:00Z"}}},
                 "records": []}
    _, h1 = NH.assemble(prev_file, {"nashua": []}, {"exeter": "x"}, "2026-11-02T12:00:00Z")
    _, h2 = NH.assemble({"ok": True, "meta": h1, "records": []}, {"nashua": []}, {"exeter": "x"},
                        "2026-11-03T12:00:00Z")
    assert h2["partial_failures"]["exeter"]["last_ok_at"] == "2026-09-01T00:00:00Z"


def test_all_ok_means_no_partial_failures():
    new = {k: [] for k in NH.PERMITTEES}
    _, health = NH.assemble({}, new, {}, "2026-11-02T12:00:00Z")
    assert health["partial_failures"] == {}
    assert all(v["ok"] for v in health["permittees"].values())


def test_empty_parse_counts_as_failure():
    with pytest.raises(RuntimeError):
        NH._require([], "manchester records")
