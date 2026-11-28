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


# --------------------------------------------------------------------------- NH: an all-clear is not an event

MAN_PAGE = """<div class="DnnModule"><div>
<div id="Item14081" class="Announcement"><h4>City of Manchester CSO Notification</h4>
<div class="Header">Published: 11/13/2026 9:55 AM</div>
<p>Please be advised that the City of Manchester has experienced no CSO activations during the past 12 hours.</p></div>
<div id="Item14080" class="Announcement"><h4>City Of Manchester CSO Notification - No Activations for 12 Hours</h4>
<div class="Header">Published: 11/13/2026 4:09 AM</div>
<p>Please be advised that the City of Manchester has experienced no CSO activations during the past 12 hours.</p></div>
<div id="Item14079" class="Announcement"><h4>City of Manchester CSO Notification</h4>
<div class="Header">Published: 11/12/2026 4:58 PM</div>
<p>Please be advised that the City of Manchester has experienced CSO activations due to heavy rain and/or snow melt
and corresponding high flows.</p></div>
<div id="Item14078" class="Announcement"><h4>City Of Manchester CSO Notification - Activation</h4>
<div class="Header">Published: 11/12/2026 4:04 PM</div>
<p>Please be advised that the City of Manchester has experienced CSO activations due to heavy rain and corresponding
high flows.</p></div>
<div id="Item14001" class="Announcement"><h4>Office closed Friday</h4>
<div class="Header">Published: 11/01/2026 9:00 AM</div><p>The office is closed.</p></div>
</div></div>"""


def test_manchester_posts_are_read_from_their_own_sentence():
    recs = {r["raw"]["item_id"]: r for r in NH.manchester(MAN_PAGE, "2026-11-13T15:00:00Z")}
    assert {k: r["raw"]["kind"] for k, r in recs.items()} == {
        "Item14081": "all_clear", "Item14080": "all_clear", "Item14079": "activation", "Item14078": "activation",
        "Item14001": "other"}
    assert recs["Item14079"]["event_type"] == "cso" and recs["Item14001"]["event_type"] == "unknown"
    # the sentence wins over a title that says otherwise; the title decides only when the body has neither
    assert NH.manchester_kind("CSO Notification - Activation",
                              "the City of Manchester has experienced no CSO activations during the past 12 hours") \
        == "all_clear"
    assert NH.manchester_kind("CSO Notification - No Activations for 12 Hours", "") == "all_clear"
    assert NH.manchester_kind("CSO Notification - Activation", None) == "activation"


def test_a_stored_post_read_by_title_only_is_read_again_from_its_sentence():
    old = mh(14079, "other", "2026-11-12T16:58:00-05:00")
    old.update(event_type="unknown", material=None)
    old["raw"].update(title="City of Manchester CSO Notification",
                      body="Please be advised that the City of Manchester has experienced CSO activations due to rain")
    clear = mh(14081, "other", "2026-11-13T09:55:00-05:00")
    clear["raw"].update(title="City of Manchester CSO Notification",
                        body="the City of Manchester has experienced no CSO activations during the past 12 hours.")
    other = mh(14001, "other", "2026-11-01T09:00:00-04:00")
    other.update(event_type="unknown")
    other["raw"].update(title="Office closed Friday", body="The office is closed.")
    NH.pair_manchester([old, clear, other])
    assert old["raw"]["kind"] == "activation" and old["event_type"] == "cso" and old["material"] == NH.CSO_MATERIAL
    assert old["status"] == "ended" and old["raw"]["_ended_before"] == "2026-11-12T21:55:00-05:00"
    assert clear["raw"]["kind"] == "all_clear"
    assert other["raw"]["kind"] == "other" and other["event_type"] == "unknown"


def _status():
    from build import status as S
    return S


def test_an_all_clear_is_kept_in_the_file_and_is_never_an_event(tmp_path):
    """Manchester's Nov. 13, 2026 notice (Item14080) said no overflow in the 12 hours before it and was published as
    "CSO reported" with a 72-hour window of its own."""
    import json
    from common import no_discharge_notice
    S = _status()
    a = mh(14078, "activation", "2026-11-12T16:04:00-05:00")
    c = mh(14080, "all_clear", "2026-11-13T04:09:00-05:00")
    lone = mh(14200, "all_clear", "2026-11-20T04:00:00-05:00")        # nothing open before it
    mail = event(source_id="nh-manchester-cso-email", source_record_id="m1", event_type="cso", status="ended",
                 reported_at="2026-11-13T09:10:00Z", published_at="2026-11-13T09:10:00Z", time_precision="minute",
                 raw={"_channel": "email", "kind": "all_clear", "_all_clear_hours": 12})
    recs = [a, c, lone]
    NH.pair_manchester(recs)
    assert [no_discharge_notice(r) for r in recs] == [False, True, True] and no_discharge_notice(mail)
    assert c in recs and lone in recs                                   # still in the source's file
    assert a["status"] == "ended" and "Item14080" in a["raw"]["_ended_before_basis"]
    d = tmp_path / "events"
    d.mkdir()
    for sid, rs in (("nh-permittees", recs), ("nh-manchester-cso-email", [mail])):
        (d / f"{sid}.json").write_text(json.dumps({"source_id": sid, "fetched_at": "2026-11-20T10:00:00Z", "ok": True,
                                                    "count": len(rs), "records": rs}))
    files, events, problems = S.load_events(d)
    assert not problems and [e["event_id"] for e in events] == [a["event_id"]]
    assert files["nh-permittees"]["no_discharge_notices"] == 2 and files["nh-permittees"]["records"] == 3
    assert files["nh-manchester-cso-email"]["no_discharge_notices"] == 1


def test_an_all_clear_starts_no_window_even_if_it_reaches_the_status_rules():
    from datetime import UTC, datetime
    S = _status()
    rules = S.read_json(S.DATA_DIR / "rules.json")
    now = datetime(2026, 11, 13, 12, 0, tzinfo=UTC)
    a = mh(14078, "activation", "2026-11-12T16:04:00-05:00")
    c = mh(14080, "all_clear", "2026-11-13T04:09:00-05:00")
    NH.pair_manchester([a, c])
    assert S._event_intervals(c, "NH", now, None, rules) == []
    assert S._event_intervals(a, "NH", now, None, rules)                # the activation keeps its windows


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
