"""NBC CSO Alarm Map: activations accumulated across polls (open, continue, close, reappear), the
Worker's 5-minute sightings folded in from its file in the bucket or /api/live (no network)."""
import json

from ingest import ri_nbc as N

REFS = ({}, {}, {})


def pin(act=None, deact=None, site="OF 035_Moshassuck_Charles", sid=35):
    return {"SITE_ID": sid, "SITE_DESCRIPTION": site, "OUTFALL_LAT": "41.8301", "OUTFALL_LONG": "-71.4102",
            "ACTIVATION_DATE": act, "DEACTIVATION_DATE": deact, "ALARM_DESCRIPTION": "", "CSO_ALARM_HISTORYID": 7 if act else 0,
            "SITE_NOTES": "", "Duration": 0, "HoursSinceLast": 0}


def recs(st):
    return {k: N.to_record(k, ev) for k, ev in st["events"].items()}


def test_open_continue_close_by_poll_and_reappear():
    st = {}
    N.poll(st, [pin()], [], "2026-11-03T17:00:00Z", REFS)
    assert st["events"] == {}
    # open: the first poll that shows the activation; the start is NBC's ACTIVATION_DATE
    N.poll(st, [pin("Nov  3 2026  1:05PM")], [], "2026-11-03T18:00:00Z", REFS)
    (key, ev), = st["events"].items()
    assert key == "OF035-20261103T1305" and ev["state"] == "ongoing"
    r = recs(st)[key]
    assert r["status"] == "ongoing" and r["started_at"] == "2026-11-03T13:05:00-05:00" and r["ended_at"] is None
    assert r["time_precision"] == "minute" and r["raw"]["first_seen_active_at"] == "2026-11-03T18:00:00Z"
    # continue
    N.poll(st, [pin("Nov  3 2026  1:05PM")], [], "2026-11-03T19:00:00Z", REFS)
    assert ev["state"] == "ongoing" and ev["last_seen_active_at"] == "2026-11-03T19:00:00Z"
    # close: gone from /pins with no deactivation -> ended at the first poll that no longer showed it
    N.poll(st, [pin()], [], "2026-11-03T20:00:00Z", REFS)
    r = recs(st)[key]
    assert r["status"] == "ended" and r["ended_at"] == "2026-11-03T15:00:00-05:00" and r["time_precision"] == "poll"
    assert r["raw"]["last_seen_active_at"] == "2026-11-03T19:00:00Z"
    assert r["raw"]["first_seen_clear_at"] == "2026-11-03T20:00:00Z"
    assert "at or before" in r["raw"]["time_basis"]["ended_at"]
    assert [o["state"] for o in r["raw"]["observations"]] == ["active", "active", "absent"]
    # stays closed while it is gone (the absent run grows, no new sightings kept in between)
    N.poll(st, [pin()], [], "2026-11-03T21:00:00Z", REFS)
    assert len(ev["obs"]) == 3 and ev["state"] == "ended"
    # reappear: the same activation back on /pins with no deactivation is ongoing again
    N.poll(st, [pin("Nov  3 2026  1:05PM")], [], "2026-11-03T22:00:00Z", REFS)
    r = recs(st)[key]
    assert r["status"] == "ongoing" and r["ended_at"] is None and r["raw"]["spells_seen_active"] == 2
    # a new activation at the same outfall is a new event; NBC's deactivation ends it to the minute
    N.poll(st, [pin("Nov  4 2026  2:00AM", "Nov  4 2026  3:10AM")], [], "2026-11-04T09:00:00Z", REFS)
    new = recs(st)["OF035-20261104T0200"]
    assert new["status"] == "ended" and new["ended_at"] == "2026-11-04T03:10:00-05:00" and new["time_precision"] == "minute"
    assert recs(st)[key]["status"] == "ended"            # the older one left /pins at that poll


def test_deactivation_on_pins_and_aged_off_map():
    st = {}
    N.poll(st, [pin("Nov  3 2026  1:05PM")], [], "2026-11-03T18:00:00Z", REFS)
    N.poll(st, [pin("Nov  3 2026  1:05PM", "Nov  3 2026  2:40PM")], [], "2026-11-03T20:00:00Z", REFS)
    N.poll(st, [pin()], [], "2026-11-05T20:00:00Z", REFS)        # off the map later: the source end stands
    r, = recs(st).values()
    assert r["status"] == "ended" and r["ended_at"] == "2026-11-03T14:40:00-05:00" and r["time_precision"] == "minute"
    # still active when it left /pins more than ~48 h after its start: it may have aged off the map
    st2 = {}
    N.poll(st2, [pin("Nov  1 2026  1:05PM")], [], "2026-11-03T16:00:00Z", REFS)
    N.poll(st2, [pin()], [], "2026-11-03T17:00:00Z", REFS)
    r2, = recs(st2).values()
    assert r2["status"] == "unknown" and r2["ended_at"] is None
    assert r2["raw"]["vanished_without_deactivation"] == {"last_seen_at": "2026-11-03T16:00:00Z",
                                                           "missing_at": "2026-11-03T17:00:00Z"}


def test_worker_sightings_from_d1():
    st = {}
    N.poll(st, [pin("Nov  3 2026  1:05PM")], [], "2026-11-03T18:00:00Z", REFS)
    N.poll(st, [pin()], [], "2026-11-03T19:00:00Z", REFS)
    worker_rec = lambda status, **raw: json.dumps({
        "event_id": "ri-nbc:OF035-20261103T1305", "status": status, "started_at": "2026-11-03T13:05:00-05:00",
        "ended_at": None, "outfall_name": "OF 035_Moshassuck_Charles", "lat": 41.83, "lon": -71.41, "raw": raw})
    other = lambda status, **raw: json.dumps({
        "event_id": "ri-nbc:OF220-20261103T1530", "status": status, "started_at": "2026-11-03T15:30:00-05:00",
        "ended_at": None, "outfall_name": "OF 220_Moshassuck_Esten", "lat": 41.86, "lon": -71.4,
        "raw": {**raw, "pins": {"SITE_ID": 220, "SITE_DESCRIPTION": "OF 220_Moshassuck_Esten", "OUTFALL_LAT": "41.86",
                               "OUTFALL_LONG": "-71.40", "ACTIVATION_DATE": "Nov  3 2026  3:30PM"}}})
    events = [{"event_id": "ri-nbc:OF035-20261103T1305", "first_seen_at": "2026-11-03T18:10:58Z", "last_changed_at": "2026-11-03T18:40:58Z"},
              {"event_id": "ri-nbc:OF220-20261103T1530", "first_seen_at": "2026-11-03T20:35:58Z", "last_changed_at": "2026-11-03T21:00:58Z"}]
    revisions = [
        {"event_id": "ri-nbc:OF035-20261103T1305", "fetched_at": "2026-11-03T18:10:58Z", "record": worker_rec("ongoing")},
        {"event_id": "ri-nbc:OF035-20261103T1305", "fetched_at": "2026-11-03T18:40:58Z", "record": worker_rec(
            "unknown", vanished_without_deactivation={"last_seen_at": "2026-11-03T18:10:58Z", "missing_at": "2026-11-03T18:40:58Z"})},
        # an activation that came and went between two hourly runs: only the Worker saw it
        {"event_id": "ri-nbc:OF220-20261103T1530", "fetched_at": "2026-11-03T20:35:58Z", "record": other("ongoing")},
        {"event_id": "ri-nbc:OF220-20261103T1530", "fetched_at": "2026-11-03T21:00:58Z", "record": other(
            "unknown", vanished_without_deactivation={"last_seen_at": "2026-11-03T20:35:58Z", "missing_at": "2026-11-03T21:00:58Z"})},
    ]
    wk = N.worker_from_d1(events, revisions)
    assert set(wk) == {"OF035-20261103T1305", "OF220-20261103T1530"}
    stats = N.merge_worker(st, wk, REFS, "d1")
    for ev in st["events"].values():
        N.derive(ev)
    assert stats["worker_new"] == 1
    r = recs(st)
    # the Worker missed it at 18:40:58, before the hourly poll at 19:00: the earlier sighting closes it
    a = r["OF035-20261103T1305"]
    assert a["status"] == "ended" and a["ended_at"] == "2026-11-03T13:40:58-05:00" and a["time_precision"] == "poll"
    assert a["raw"]["last_seen_active_at"] == "2026-11-03T18:10:58Z"
    assert {o["by"] for o in a["raw"]["observations"]} == {"pipeline", "worker"}
    b = r["OF220-20261103T1530"]
    assert b["status"] == "ended" and b["started_at"] == "2026-11-03T15:30:00-05:00"
    assert b["ended_at"] == "2026-11-03T16:00:58-05:00" and b["outfall_id"] == "OF 220"
    assert b["npdes_permit"] == "RI0100072" and b["raw"]["worker"]["channel"] == "d1"
    assert b["raw"]["first_seen_at"] == "2026-11-03T20:35:58Z"
    # merging the same rows again changes nothing
    before = json.dumps(st, sort_keys=True)
    N.merge_worker(st, N.worker_from_d1(events, revisions), REFS, "d1")
    for ev in st["events"].values():
        N.derive(ev)
    assert json.dumps(st, sort_keys=True) == before


def test_worker_from_live_and_legacy_state():
    js = {"events": [
        {"event_id": "ri-nbc:OF035-20261103T1305", "source_id": "ri-nbc", "status": "ongoing",
         "started_at": "2026-11-03T13:05:00-05:00", "ended_at": None, "outfall_id": "OF 035",
         "outfall_name": "OF 035_Moshassuck_Charles", "lat": 41.83, "lon": -71.41,
         "first_seen_at": "2026-11-03T18:05:58Z", "last_changed_at": "2026-11-03T18:05:58Z"},
        {"event_id": "ma-massdep:x", "source_id": "ma-massdep", "status": "ongoing"}]}
    wk = N.worker_from_live(js)
    assert list(wk) == ["OF035-20261103T1305"] and wk["OF035-20261103T1305"]["obs"][0] == ("2026-11-03T18:05:58Z", "active")
    st = {}
    N.merge_worker(st, wk, REFS, "api_live")
    ev = st["events"]["OF035-20261103T1305"]
    N.derive(ev)
    assert ev["state"] == "ongoing" and ev["first_seen_at"] == "2026-11-03T18:05:58Z"
    # a state file written before the sightings: its stored end is the source's
    legacy = {"events": {"OF220-20261005T2050": {"state": "ended", "started_at": "2026-10-05T20:50:00-04:00",
                                                 "ended_at": "2026-10-05T23:11:00-04:00", "first_seen_at": "2026-11-02T10:54:00Z"}}}
    N.migrate(legacy)
    e = legacy["events"]["OF220-20261005T2050"]
    N.derive(e)
    assert e["state"] == "ended" and e["ended_at"] == "2026-10-05T23:11:00-04:00" and e["end_basis"] == "source"


def test_a_missing_row_or_a_short_answer_is_not_an_end():
    other = pin(site="OF 220_Moshassuck_Esten", sid=220)
    st = {}
    N.poll(st, [pin("Nov  3 2026  1:05PM"), other], [], "2026-11-03T18:00:00Z", REFS)
    # the outfall's own row is missing: nothing is said about it
    N.poll(st, [other, pin(site="OF 221_Moshassuck_X", sid=221)], [], "2026-11-03T19:00:00Z", REFS)
    (key, ev), = st["events"].items()
    assert ev["state"] == "ongoing" and [o[1] for o in ev["obs"]] == ["active"]
    # an answer with far fewer sites than usual is partial: no judgement either
    st2 = {"max_sites": 60}
    N.poll(st2, [pin("Nov  3 2026  1:05PM")], [], "2026-11-03T18:00:00Z", REFS)
    stats = N.poll(st2, [pin()], [], "2026-11-03T19:00:00Z", REFS)
    (k2, e2), = st2["events"].items()
    assert e2["state"] == "ongoing" and stats["pins_complete"] is False and stats["not_judged"] == 1


# ---------------------------------------------------------------- the Worker's file (inbox/nbc-worker.json, 2026-11-18)

def worker_file(written="2026-11-03T21:05:00Z", poller_ok="2026-11-03T21:05:00Z", **over):
    rec = json.dumps({"event_id": "ri-nbc:OF220-20261103T1530", "status": "ongoing",
                      "started_at": "2026-11-03T15:30:00-05:00", "ended_at": None, "outfall_name": "OF 220_Moshassuck_Esten",
                      "lat": 41.86, "lon": -71.4, "raw": {}})
    return {"schema": 1, "source_id": "ri-nbc", "written_at": written, "window_days": 7,
            "since": "2026-10-27T21:05:00Z", "poller": {"last_ok_at": poller_ok, "last_error": None},
            "events": [{"event_id": "ri-nbc:OF220-20261103T1530", "first_seen_at": "2026-11-03T20:35:58Z",
                        "last_changed_at": "2026-11-03T21:00:58Z", "status": "ongoing"}],
            "revisions": [{"event_id": "ri-nbc:OF220-20261103T1530", "fetched_at": "2026-11-01T20:35:58Z", "record": rec},
                          {"event_id": "ri-nbc:OF220-20261103T1530", "fetched_at": "2026-11-03T20:35:58Z", "record": rec}],
            **over}


def test_the_workers_file_is_read_in_place_of_d1():
    now = "2026-11-03T22:00:00Z"
    wk, why = N.read_worker_inbox(None, now, reader=lambda key: (worker_file(), None))
    assert why is None and set(wk) == {"OF220-20261103T1530"} and len(wk["OF220-20261103T1530"]["obs"]) == 2
    # after a good read, only the revisions since two days before it
    wk, _ = N.read_worker_inbox("2026-11-02T00:00:00Z", now, reader=lambda key: (worker_file(), None))
    assert [o[0] for o in wk["OF220-20261103T1530"]["obs"]] == ["2026-11-03T20:35:58Z"]
    assert wk["OF220-20261103T1530"]["first_seen_at"] == "2026-11-03T20:35:58Z"


def test_a_stale_absent_or_odd_workers_file_is_not_used():
    now = "2026-11-03T23:30:00Z"
    cases = {
        "written at 2026-11-03T21:05:00Z, more than 2 hours ago": (worker_file(), None),
        "the Worker's NBC poller last succeeded at 2026-11-03T20:00:00Z": (
            worker_file(written="2026-11-03T23:25:00Z", poller_ok="2026-11-03T20:00:00Z"), None),
        "does not say when the Worker's NBC poller": (worker_file(written="2026-11-03T23:25:00Z", poller=None), None),
        "no file": (None, "absent"),
        "not read (exit 1": (None, "not read (exit 1: refused)"),
        "not in the Worker's form": (worker_file(written="2026-11-03T23:25:00Z", schema=2), None),
    }
    for want, answer in cases.items():
        wk, why = N.read_worker_inbox(None, now, reader=lambda key, a=answer: a)
        assert wk is None and want in why, (want, why)


def test_ri_nbc_reads_the_inbox_through_the_filtered_wrangler(tmp_path, monkeypatch):
    (tmp_path / "inbox").mkdir()
    (tmp_path / "inbox" / "nbc-worker.json").write_text(json.dumps(worker_file()))
    monkeypatch.setenv("DWW_INBOX_DIR", str(tmp_path))
    wk, why = N.read_worker_inbox(None, "2026-11-03T22:00:00Z")
    assert why is None and "OF220-20261103T1530" in wk


def test_p2_4_a_malformed_workers_file_falls_back(tmp_path):
    now = "2026-11-03T22:00:00Z"
    for bad in ({"revisions": [None]}, {"events": [None]}, {"revisions": [{"event_id": 5, "fetched_at": "x"}]},
                {"open_records": [None]}, {"open_records": {"x": 1}}, {"revisions": [{"event_id": "ri-nbc:A",
                                                                                         "fetched_at": None}]}):
        wk, why = N.read_worker_inbox(None, now, reader=lambda key, b=bad: (worker_file(**b), None))
        assert wk is None and "not in the Worker's form" in why, bad


def test_p2_5_an_open_record_older_than_the_window_is_folded_in():
    old = json.dumps({"event_id": "ri-nbc:OF101-20261020T0100", "status": "ongoing",
                      "started_at": "2026-10-20T01:00:00-04:00", "ended_at": None, "outfall_name": "OF 101_x",
                      "lat": 41.9, "lon": -71.4, "raw": {}})
    doc = worker_file(open_records=[{"event_id": "ri-nbc:OF101-20261020T0100", "fetched_at": "2026-10-20T05:10:00Z",
                                     "record": old}])
    # a later read (since after the open record's last change) still gets it: it is never filtered by `since`
    wk, why = N.read_worker_inbox("2026-11-02T00:00:00Z", "2026-11-03T22:00:00Z", reader=lambda key: (doc, None))
    assert why is None and "OF101-20261020T0100" in wk and wk["OF101-20261020T0100"]["record"]["status"] == "ongoing"
    st = {}
    assert N.merge_worker(st, wk, REFS, "inbox")["worker_new"] == 2


def test_p1_3_the_live_fallbacks_error_is_a_category():
    class Boom:
        def get(self, *a, **k):
            raise ConnectionError(f"HTTPSConnectionPool: {'0123456789abcdef' * 2}.r2.cloudflarestorage.com refused")
    wk, why = N.read_worker_live(Boom())
    assert wk is None and why == f"{N.LIVE_URL}: unreachable"
