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


# ------------------------------------------------- P1-3: titles and beach names scrubbed before any save

SENT = ("Robin Sample", "843-555-0142", "302-555-0142", "1234 W", "pat@example.org")


def _assert_clean(blob):
    for x in SENT:
        assert x not in blob, x


def test_a_florence_title_with_a_telephone_and_house_number_never_reaches_a_save(monkeypatch, tmp_path):
    from ingest import sc_florence_sso as F
    fix = Path(__file__).resolve().parent / "fixtures" / "sc"
    bad = "Notification of Sanitary Sewer Overflow at 1234 W Sample Street on Jeffries Creek, call 843-555-0142"
    page = (fix / "florence_notice.html").read_text().replace(
        "Notification of Sanitary Sewer Overflow on Jeffries Creek</span></h1>", bad + "</span></h1>")
    assert bad in page
    listing = (fix / "florence_list.html").read_text()
    # carried state: an earlier run saved a title before this scrub, under another notice
    nid, title, paras = F.article((fix / "florence_notice.html").read_text())
    old = F.parse_notice(title, paras)
    old["title"] = "Sewage Spill at 1234 W Sample Street, call Robin Sample at 843-555-0142"
    carried = {"notices": {"/news/older": {"slug": "/news/older", "nid": "900", "last_read_at": "2026-11-14T00:00:00Z",
                                           "versions": [{"parsed": old, "hash": "x", "first_seen_at": "2026-11-01T00:00:00Z",
                                                         "last_seen_at": "2026-11-01T00:00:00Z"}]}},
               "backfilled_at": "2026-11-01T00:00:00Z"}
    (tmp_path / "state.json").write_text(json.dumps(carried))
    saves = []
    monkeypatch.setattr(F, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(F, "PAUSE_S", 0)
    monkeypatch.setattr(F, "save_raw", lambda *a, **k: saves.append(json.dumps(a, default=str)))
    monkeypatch.setattr(F, "write_json", lambda path, obj, *a, **k: saves.append(json.dumps(obj, default=str)))
    monkeypatch.setattr(F, "write_events", lambda sid, recs, **k: saves.append(json.dumps([recs, k], default=str)))

    class Resp:
        def __init__(self, text):
            self.text = text

        def raise_for_status(self):
            pass

    class Sess:
        headers = {}

        def get(self, url, **k):
            return Resp(listing.replace(">Notification of Sanitary Sewer Overflow", ">" + bad[:40]) if "city-news" in url
                        else page)
    monkeypatch.setattr(F.requests, "Session", Sess)
    assert F.main(["--pages", "1"]) == 0
    assert len(saves) == 3                                   # the state, the raw archive and the records
    _assert_clean("\n".join(saves))
    assert "Jeffries Creek" in "\n".join(saves)
    # the --file path (a saved state) too
    saves.clear()
    f = tmp_path / "carried.json"
    f.write_text(json.dumps(carried))
    assert F.main(["--file", str(f)]) == 0
    _assert_clean("\n".join(saves))


def test_a_scrubbed_carried_title_is_rehashed_so_an_unchanged_page_is_no_revision():
    from ingest import sc_florence_sso as F
    fix = Path(__file__).resolve().parent / "fixtures" / "sc"
    nid, title, paras = F.article((fix / "florence_notice.html").read_text())
    p = F.parse_notice(title + " call 843-555-0142", paras)
    st = {"notices": {}}
    F.update_notice(st, "/news/x", nid, p, "2026-11-01T00:00:00Z")
    raw_state = json.loads(json.dumps(st))
    raw_state["notices"]["/news/x"]["versions"][0]["parsed"]["title"] = title + " call 843-555-0142"   # as an old run saved it
    st2 = F.scrub_carried(raw_state)
    assert F.update_notice(st2, "/news/x", nid, p, "2026-11-02T00:00:00Z") == "same"


def test_a_delaware_unit_name_with_a_name_never_reaches_a_save(monkeypatch, tmp_path):
    s = json.loads((Path(__file__).resolve().parent / "fixtures" / "de" / "recwater.json").read_text())
    rows, stations = copy.deepcopy(s["advisories"]), copy.deepcopy(s["stations"])
    sentence = " For questions call Robin Sample at 302-555-0142 or pat@example.org."
    stations[0]["UnitName"] += sentence
    stations[0]["CurrentAdvisory"] = 0                       # shown on the map: a poll record carries the name
    rows[0]["unitname"] += sentence
    carried = {"polls": {"station-1-2026": {"unit_id": "1", "code": 0, "name": "Old Beach" + sentence,
                                            "started_at": "2026-11-01T00:00:00Z", "lat": 38.7, "lon": -75.1}},
               "history": {"adv-old": {"event_id": "de-dnrec-recreational-water:adv-old", "source_record_id": "adv-old",
                                       "outfall_name": "Old Beach" + sentence, "waterbody_text": "Old Beach" + sentence,
                                       "advice_text": "Call Robin Sample.", "status": "advisory_lifted",
                                       "started_at": "2020-07-01", "ended_at": "2020-07-02",
                                       "raw": {"unit_name": "Old Beach" + sentence}}}}
    (tmp_path / "state.json").write_text(json.dumps(carried))
    saves = []
    monkeypatch.setattr(W, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(W, "save_raw", lambda *a, **k: saves.append(json.dumps(a, default=str)))
    monkeypatch.setattr(W, "write_json", lambda path, obj, *a, **k: saves.append(json.dumps(obj, default=str)))
    monkeypatch.setattr(W, "write_events", lambda sid, recs, **k: saves.append(json.dumps([recs, k], default=str)))

    class Resp:
        def __init__(self, js):
            self._js = js

        def raise_for_status(self):
            pass

        def json(self):
            return self._js
    monkeypatch.setattr(W.requests, "get", lambda url, **k: Resp(rows) if url == W.SOCRATA else
                        Resp({"features": [{"attributes": a} for a in stations]}))
    assert W.main(["--at", "2026-11-14T18:00:00Z"]) == 0
    assert len(saves) == 3                                   # the raw archive, the state and the records
    blob = "\n".join(saves)
    _assert_clean(blob)
    assert "[name removed]" in blob
    assert W.scrub_unit_name("3 R's Road Beach (Delaware Seashore State Park)") == \
        "3 R's Road Beach (Delaware Seashore State Park)"      # a beach's own name keeps its number


# ------------------------------------------------- P2-1: a new bloom episode leaves the earlier record as it was

def _hab_feat(gid, x, y, day, name):
    ms = int(datetime.fromisoformat(day + "T04:00:00+00:00").timestamp() * 1000)
    return {"attributes": {"OBJECTID": 9, "NAME": name, "Algal_Bloom": "Microcystis", "Date": ms,
                           "Advisory_Tier": "Watch", "Recreational_Guidance": None, "GlobalID": gid},
            "centroid": {"x": x, "y": y}}


def test_a_new_episode_with_a_new_water_and_point_leaves_the_earlier_record_as_it_was():
    recs, st, _ = A.hab_records([_hab_feat("gy", -81.101, 34.101, "2026-07-04", "Lake Example")], [], {},
                                "2026-07-06T12:00:00Z")
    assert recs[0]["waterbody_text"] == "Lake Example"
    # August: the same GlobalID, a later date, another water and point at once: a new episode
    recs, st, _ = A.hab_records([_hab_feat("gy", -81.201, 34.201, "2026-08-10", "Other Example Lake")], [],
                                {"hab": st}, "2026-08-11T12:00:00Z")
    by = {r["started_at"]: r for r in recs}
    july, aug = by["2026-07-04"], by["2026-08-10"]
    assert july["waterbody_text"] == "Lake Example" and (july["lat"], july["lon"]) == (34.101, -81.101)
    assert not july["raw"].get("revisions") and july["ended_at"] == "2026-08-11T12:00:00Z"
    assert aug["waterbody_text"] == "Other Example Lake" and (aug["lat"], aug["lon"]) == (34.201, -81.201)
    assert aug["ended_at"] is None and aug["raw"]["follows"] == july["source_record_id"]


def test_a_corrected_water_with_an_earlier_date_is_still_a_correction():
    recs, st, _ = A.hab_records([_hab_feat("gz", -81.101, 34.101, "2026-07-04", "Lake Example")], [], {},
                                "2026-07-06T12:00:00Z")
    recs, st, _ = A.hab_records([_hab_feat("gz", -81.101, 34.101, "2026-07-03", "Lake Example Arm")], [],
                                {"hab": st}, "2026-07-07T12:00:00Z")
    assert len(recs) == 1 and recs[0]["waterbody_text"] == "Lake Example Arm" and recs[0]["started_at"] == "2026-07-03"
    assert {x["field"] for x in recs[0]["raw"]["revisions"]} == {"water", "started_at"}
