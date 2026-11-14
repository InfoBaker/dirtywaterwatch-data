"""Review 2026-11-14 (Astra data P2-5): the compact exports carry the precision of a record's start and end, so a
poll-bounded Nebraska observation is never read from the index, active.json, a water summary or an advisory point as
an agency's issue or lift time. Records with no end precision of their own are written as before."""
from export import build as B

POLL = {"event_id": "ne-dwee-beachwatch:X-2026-w23", "source_id": "ne-dwee-beachwatch", "event_type": "hab_advisory",
        "status": "advisory_lifted", "state": "NE", "started_at": "2026-06-12T16:00:00Z",
        "ended_at": "2026-06-19T16:00:00Z", "sampled_at": "2026-06-08", "time_precision": "poll", "water_slugs": [],
        "file": "events/x.json", "raw": {"ended_at_precision": "poll", "_station": "X"}}
MIXED = {**POLL, "event_id": "x:mixed", "time_precision": "minute"}
PLAIN = {"event_id": "ma-massdep:1", "source_id": "ma-massdep", "event_type": "cso", "status": "ended", "state": "MA",
         "started_at": "2026-06-12T10:00:00-04:00", "ended_at": "2026-06-12T12:00:00-04:00", "time_precision": "minute",
         "water_slugs": [], "file": "events/y.json", "raw": {}}


def test_astra_p2_5_compact_forms_keep_start_and_end_precision():
    assert B.INDEX_FIELDS[-2:] == ["time_precision", "ended_at_precision"]
    for full, start, end in ((POLL, "poll", "poll"), (MIXED, "minute", "poll"), (PLAIN, "minute", "minute")):
        slim = B.slim_event(full)
        assert "raw" not in slim and slim["time_precision"] == start
        ix = B.index_obj(slim)
        assert (ix["time_precision"], ix["ended_at_precision"]) == (start, end)
        active = B.active_entries({full["event_id"]: [{"status": "red", "water": "w"}]}, {full["event_id"]: slim})
        assert (active[0]["time_precision"], active[0]["ended_at_precision"]) == (start, end)
        assert B.bounds_precision(slim) == {"time_precision": start, "ended_at_precision": end}
    # the end's own precision is written only where it differs from the start's: other records' slim rows unchanged
    assert "ended_at_precision" not in B.slim_event(PLAIN) and B.slim_event(MIXED)["ended_at_precision"] == "poll"
    assert B.index_obj(B.slim_event({**PLAIN, "ended_at": None}))["ended_at_precision"] is None
