"""Round-3 fixes for Delaware and South Carolina (verify2 review), on invented data."""
import copy
import json
import os
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from build import status as S
from ingest import de_dnrec_recwater as W
from ingest import sc_des_advisories as A

ROOT = Path(__file__).resolve().parents[2]
J1, J6, N1 = "2026-07-01T14:00:00Z", "2026-07-06T14:00:00Z", "2026-11-01T14:00:00Z"
SEP1 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


# ------------------------------------------------- P1-1: a late poll-observed end never fills the gap with red

def _de_station(code):
    return [{"UnitID": 77, "UnitName": "Invented Beach", "CurrentAdvisory": code, "Latitude": 38.7, "Longitude": -75.08}]


def _de_feed():
    _, s1 = W.poll_records(_de_station(0), [], {}, J1, date(2026, 7, 1))
    before, s2 = W.poll_records(_de_station(0), [], s1, J6, date(2026, 7, 6))
    after, _ = W.poll_records(_de_station(1), [], s2, N1, date(2026, 11, 1))     # another status: the end seen
    return W.SOURCE_ID, before, after


def _beach(adv):
    return [{"attributes": {"OBJECTID": 1, "STAT": "INV-1", "HUC_12": "030601100305", "COUNTY": "Horry",
                            "ADVISORY": adv}, "geometry": {"x": -78.9, "y": 33.6}}]


def _sc_beach_feed():
    _, s1, _ = A.beach_records(_beach("Short Term Advisory"), {}, J1)
    before, s2, _ = A.beach_records(_beach("Short Term Advisory"), {"beach": s1}, J6)
    after, _, _ = A.beach_records(_beach("No Advisory"), {"beach": s2}, N1)
    return A.BEACH_ID, before, after


def _hab_layer():
    return [{"attributes": {"OBJECTID": 5, "NAME": "Invented Reservoir", "Algal_Bloom": "Microcystis",
                            "Date": int(datetime(2026, 7, 1, 4, tzinfo=timezone.utc).timestamp() * 1000),
                            "Advisory_Tier": "Advisory", "Recreational_Guidance": None, "GlobalID": "g-inv-1"},
             "centroid": {"x": -82.3, "y": 33.8}}]


def _sc_hab_feed():
    _, s1, _ = A.hab_records(_hab_layer(), [], {}, J1)
    before, s2, _ = A.hab_records(_hab_layer(), [], {"hab": s1}, J6)
    after, _, _ = A.hab_records([], [], {"hab": s2}, N1)        # both read, neither lists it: the end seen
    return A.HAB_ID, before, after


FEEDS = {"de-map": _de_feed, "sc-beach": _sc_beach_feed, "sc-hab": _sc_hab_feed}


def _build(sid, recs, now):
    from tests.test_status import TEST_RULES
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    d = Path(tempfile.mkdtemp())
    (d / f"{sid}.json").write_text(json.dumps({"source_id": sid, "ok": True, "last_ok_at": iso(now), "meta": {},
                                               "records": recs}))
    out, _ = S.build(now=now, write=False, events_dir=d, waters={}, outfalls=[], registry={}, reaches={},
                     flows=({}, {}), rules=TEST_RULES, placement_cache=None)
    return out


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def _point_colour(out, eid, at):
    for p in out["advisory_points"]:
        if p["event_id"] == eid:
            for s, e, c, _ in p["intervals"]:
                if s <= iso(at) and (e is None or e > iso(at)):
                    return c
    return "grey"


def _day_colours(rec, until):
    from tests.test_status import TEST_RULES
    ivs = S.event_intervals(rec, None, until, None, TEST_RULES)
    out, t = {}, datetime(2026, 7, 1, 18, tzinfo=timezone.utc)
    while t < until:
        on = [i["color"] for i in ivs if i["start"] <= t and (i["end"] is None or i["end"] > t)]
        out[t.date().isoformat()] = max(on, key=lambda c: S.RANK[c]) if on else "grey"
        t += timedelta(days=1)
    return out


@pytest.mark.parametrize("feed", sorted(FEEDS))
def test_an_end_seen_by_polling_months_later_never_turns_the_unconfirmed_days_red(feed, monkeypatch):
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    sid, before, after = FEEDS[feed]()
    b, a = before[0], after[0]
    assert b["status"] == "advisory_active" and not b.get("ended_at")
    assert a["status"] == "advisory_lifted" and a["ended_at"] == N1 and a["raw"]["ended_at_precision"] == "poll"
    # through the status build: September 1 is grey while the advisory is unread, and stays grey once its end is seen
    assert _point_colour(_build(sid, before, datetime(2026, 9, 2, tzinfo=timezone.utc)), b["event_id"], SEP1) == "grey"
    assert _point_colour(_build(sid, after, datetime(2026, 11, 2, tzinfo=timezone.utc)), a["event_id"], SEP1) == "grey"
    # every earlier day keeps its colour: red to 14 days after July 6, never red after it
    nov = datetime(2026, 11, 1, 13, tzinfo=timezone.utc)
    cb, ca = _day_colours(b, nov), _day_colours(a, nov)
    assert cb == ca
    assert ca["2026-07-03"] == "red" and ca["2026-07-19"] == "red" and ca["2026-07-21"] == "grey"
    assert "red" not in [c for d, c in ca.items() if d > "2026-07-20"]


def test_an_end_seen_soon_after_the_last_read_still_ends_the_red_there(monkeypatch):
    from tests.test_status import TEST_RULES
    sid, _, after = _sc_beach_feed()
    a = copy.deepcopy(after[0])
    a["ended_at"] = "2026-07-08T14:00:00Z"
    ca = _day_colours(a, datetime(2026, 8, 1, tzinfo=timezone.utc))
    assert ca["2026-07-07"] == "red" and ca["2026-07-09"] == "grey"


def test_another_states_poll_ended_advisory_keeps_its_colour(monkeypatch):
    # keyed on the three sources: the same record under another source is coloured as on 2b1184a
    from tests.test_status import TEST_RULES
    _, _, after = _sc_beach_feed()
    a = copy.deepcopy(after[0])
    a.update(source_id="xx-invented-beach", event_id="xx-invented-beach:1")
    a["raw"]["state"] = "XX"
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    ivs = S.event_intervals(a, None, now, None, TEST_RULES)
    monkeypatch.setattr(S, "POLL_END_HORIZON_SOURCES", set())
    assert ivs == S.event_intervals(a, None, now, None, TEST_RULES)
    assert _day_colours(a, now)["2026-09-01"] == "red"          # unchanged: other feeds keep their own reading


MAIN_EVENTS = Path(os.environ.get("DWW_OTHER_EVENTS", "/Users/infobaker/Documents/dirtywaterwatch/data/build/events"))


@pytest.mark.skipif(not MAIN_EVENTS.is_dir(), reason="no saved event files of the live states on this machine")
def test_every_other_states_intervals_are_identical(monkeypatch):
    # every saved record of the live states, coloured with and without the three sources' rule: identical
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    n = 0
    for f in sorted(MAIN_EVENTS.glob("*.json")):
        try:
            recs = json.loads(f.read_text()).get("records") or []
        except (ValueError, AttributeError):
            continue
        recs = [r for r in recs if r.get("source_id") not in S.POLL_END_HORIZON_SOURCES]
        new = [S.event_intervals(r, None, now, None, rules) for r in recs]
        with monkeypatch.context() as m:
            m.setattr(S, "POLL_END_HORIZON_SOURCES", set())
            old = [S.event_intervals(r, None, now, None, rules) for r in recs]
        assert new == old, f.name
        n += len(recs)
    assert n
