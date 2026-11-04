"""NBC CSO Alarm Map: activations accumulated across polls (open, continue, close, reappear), the
Worker's 5-minute sightings folded in from D1 or /api/live (no network)."""
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
