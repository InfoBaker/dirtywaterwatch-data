"""Round-4 fixes for Delaware and South Carolina (verify3 review), on invented data."""
import copy
import json
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

import pytest

from build import status as S
from ingest import de_dnrec_recwater as W
from ingest import sc_des_advisories as A
from tests.test_de_sc_fix3 import _beach, _build, _de_station, _hab_layer, _point_colour

J1, J6, N1, N3 = "2026-07-01T14:00:00Z", "2026-07-06T14:00:00Z", "2026-11-01T14:00:00Z", "2026-11-03T14:00:00Z"
SEP1 = datetime(2026, 9, 1, 12, tzinfo=timezone.utc)


def _rules():
    from tests.test_status import TEST_RULES
    return TEST_RULES


def _real_rules():
    return json.loads((Path(__file__).resolve().parents[2] / "data" / "rules.json").read_text())


def _days(rec, until, rules=None):
    ivs = S.event_intervals(rec, None, until, None, rules or _rules())
    out, t = {}, datetime(2026, 7, 1, 18, tzinfo=timezone.utc)
    while t < until:
        on = [i["color"] for i in ivs if i["start"] <= t and (i["end"] is None or i["end"] > t)]
        out[t.date().isoformat()] = max(on, key=lambda c: S.RANK[c]) if on else "grey"
        t += timedelta(days=1)
    return out


def _d(s):
    return date.fromisoformat(s[:10])


# --------------------------------------------- P1-1: listed again after an unread gap, then withdrawn

def _de_stages(code=0):
    out, prev = [], {}
    for at, c in ((J1, code), (J6, code), (N1, code), (N3, 1)):
        recs, prev = W.poll_records(_de_station(c), [], prev, at, _d(at))
        out.append(recs)
    return W.SOURCE_ID, out


def _sc_beach_stages(adv="Short Term Advisory"):
    out, prev = [], {}
    for at, a in ((J1, adv), (J6, adv), (N1, adv), (N3, "No Advisory")):
        recs, st, _ = A.beach_records(_beach(a), {"beach": prev}, at)
        prev = st
        out.append(recs)
    return A.BEACH_ID, out


def _sc_hab_stages():
    out, prev = [], {}
    for at, feats in ((J1, _hab_layer()), (J6, _hab_layer()), (N1, _hab_layer()), (N3, [])):
        recs, st, _ = A.hab_records(feats, [], {"hab": prev}, at)
        prev = st
        out.append(recs)
    return A.HAB_ID, out


STAGES = {"de-map": _de_stages, "sc-beach": _sc_beach_stages, "sc-hab": _sc_hab_stages}


@pytest.mark.parametrize("feed", sorted(STAGES))
def test_a_reconfirmation_after_an_unread_gap_never_turns_the_gap_red(feed, monkeypatch):
    monkeypatch.setattr(S, "_RULES", _rules())
    sid, (s1, s2, s3, s4) = STAGES[feed]()
    assert len(s3) == 1 and len(s4) == 1 and s3[0]["event_id"] == s2[0]["event_id"] == s4[0]["event_id"]
    eid = s2[0]["event_id"]
    assert len(s3[0]["raw"]["listed_periods"]) == 2
    assert s4[0]["status"] == "advisory_lifted" and s4[0]["raw"]["ended_at_precision"] == "poll"
    # through the status build, at each stage: September 1 is grey, and stays grey after the reconfirmation and the end
    assert _point_colour(_build(sid, s2, datetime(2026, 9, 2, tzinfo=timezone.utc)), eid, SEP1) == "grey"
    built3 = _build(sid, s3, datetime(2026, 11, 2, tzinfo=timezone.utc))
    assert _point_colour(built3, eid, SEP1) == "grey"
    assert _point_colour(built3, eid, datetime(2026, 11, 1, 18, tzinfo=timezone.utc)) == "red"
    built4 = _build(sid, s4, datetime(2026, 11, 4, tzinfo=timezone.utc))
    assert _point_colour(built4, eid, SEP1) == "grey"
    assert _point_colour(built4, eid, datetime(2026, 11, 2, 12, tzinfo=timezone.utc)) == "red"
    # every day before the reconfirmation keeps the colour it had before it
    oct31 = datetime(2026, 10, 31, 13, tzinfo=timezone.utc)
    c2 = _days(s2[0], oct31)
    assert c2 == {k: v for k, v in _days(s3[0], oct31).items()} == {k: v for k, v in _days(s4[0], oct31).items()}
    assert c2["2026-07-19"] == "red" and "red" not in [c for d, c in c2.items() if d > "2026-07-20"]


@pytest.mark.parametrize("feed", sorted(STAGES))
def test_regular_reads_keep_one_period(feed):
    # read every few days, never a gap over the horizon: one period, the record as before (no listed_periods)
    sid, _ = STAGES[feed]()
    times = [f"2026-07-{d:02d}T14:00:00Z" for d in (1, 5, 9, 13, 17, 21)]
    prev, recs = {}, []
    for at in times:
        if feed == "de-map":
            recs, prev = W.poll_records(_de_station(0), [], prev, at, _d(at))
        elif feed == "sc-beach":
            recs, prev, _ = A.beach_records(_beach("Short Term Advisory"), {"beach": prev}, at)
        else:
            recs, prev, _ = A.hab_records(_hab_layer(), [], {"hab": prev}, at)
    assert "listed_periods" not in recs[0]["raw"]


def test_a_station_missing_from_the_layer_then_back_is_not_confirmed_while_missing(monkeypatch):
    # absent (not a lift) from July 6 to November 1, then listed again: the absence is an unread gap, never red
    prev, out = {}, []
    for at, feats in ((J1, _beach("Short Term Advisory")), (J6, _beach("Short Term Advisory")),
                      ("2026-08-01T14:00:00Z", []), (N1, _beach("Short Term Advisory"))):
        out, prev, _ = A.beach_records(feats, {"beach": prev}, at)
    assert _days(out[0], datetime(2026, 11, 2, 13, tzinfo=timezone.utc))["2026-09-01"] == "grey"


def test_a_delaware_resampling_label_listed_again_after_a_gap_keeps_the_gap_grey():
    _, (s1, s2, s3, s4) = _de_stages(code=2)
    oct31 = datetime(2026, 10, 31, 13, tzinfo=timezone.utc)
    R = _real_rules()
    c2 = _days(s2[0], oct31, R)
    assert c2["2026-07-08"] == "yellow" and c2["2026-09-01"] == "grey"
    assert _days(s3[0], oct31, R) == c2 == _days(s4[0], oct31, R)
    assert _days(s3[0], datetime(2026, 11, 2, 13, tzinfo=timezone.utc), R)["2026-11-01"] == "yellow"


def test_a_delaware_resampling_label_closed_after_an_unread_gap_never_turns_the_gap_yellow():
    # listed July 1 and 6, unread, then another status on November 1: the closure is a poll, the gap stays grey
    prev = {}
    for at, c in ((J1, 2), (J6, 2), (N1, 1)):
        recs, prev = W.poll_records(_de_station(c), [], prev, at, _d(at))
    r = recs[0]
    assert r["ended_at"] == N1 and r["raw"]["_notice_closed_at"] == "2026-07-09T14:00:00Z"
    c = _days(r, datetime(2026, 11, 2, 13, tzinfo=timezone.utc), _real_rules())
    assert c["2026-07-08"] == "yellow" and c["2026-09-01"] == "grey"
    # closed at the next hourly read: the closure itself
    prev = {}
    for at, cc in ((J1, 2), ("2026-07-01T15:00:00Z", 1)):
        recs, prev = W.poll_records(_de_station(cc), [], prev, at, _d(at))
    assert recs[0]["raw"]["_notice_closed_at"] == "2026-07-01T15:00:00Z"


def _hist_row(start):
    return {"advisoryid": "901", "advstartdate": f"{start}T00:00:00.000", "advtype": "Recreational Water Quality Advisory",
            "advreason": "Bacteria", "unitname": "Invented Beach"}


def test_a_delaware_history_row_confirmed_again_after_a_gap_keeps_the_gap_grey():
    # DNREC's row (no end) starts October 1; the map confirms it October 2, then nothing is read until October 29
    st = W.station_index(_de_station(0))
    prev, recs = {}, None
    for at in ("2026-10-02T14:00:00Z", "2026-10-29T14:00:00Z"):
        hist, _ = W.history_records([_hist_row("2026-10-01")], st, _d(at), at)
        _, prev = W.poll_records(_de_station(0), hist, prev, at, _d(at))
        recs = hist
    r = recs[0]
    assert r["status"] == "advisory_active" and len(r["raw"]["listed_periods"]) == 2
    c = _days(r, datetime(2026, 10, 30, 13, tzinfo=timezone.utc))
    assert c["2026-10-15"] == "red" and c["2026-10-20"] == "grey" and c["2026-10-29"] == "red"
    # the first confirmation from DNREC's start is one period, as before
    hist, _ = W.history_records([_hist_row("2026-10-01")], st, _d("2026-10-02"), "2026-10-02T14:00:00Z")
    W.poll_records(_de_station(0), hist, {}, "2026-10-02T14:00:00Z", _d("2026-10-02"))
    assert "listed_periods" not in hist[0]["raw"]


def test_an_explicit_end_of_dnrec_takes_no_periods():
    # an advisory row with DNREC's own end date is DNREC's window, red throughout, whatever the map reads were
    r = {"event_id": "de-dnrec-recreational-water:adv-1", "source_id": W.SOURCE_ID, "event_type": "beach_advisory",
         "status": "advisory_lifted", "started_at": "2026-07-01", "ended_at": "2026-08-20", "time_precision": "day",
         "raw": {"ended_at_precision": "day", "listed_periods": [{"from": J1, "to": J1}, {"from": N1, "to": N1}]}}
    assert _days(r, datetime(2026, 9, 1, tzinfo=timezone.utc))["2026-08-10"] == "red"


def test_other_states_records_with_listed_periods_are_unchanged(monkeypatch):
    # keyed on the three sources: another feed's record carrying the same field is coloured as on c123f36
    _, (_, _, s3, _) = _sc_beach_stages()
    a = copy.deepcopy(s3[0])
    a.update(source_id="xx-invented-beach", event_id="xx-invented-beach:1")
    now = datetime(2026, 11, 2, tzinfo=timezone.utc)
    ivs = S.event_intervals(a, None, now, None, _rules())
    monkeypatch.setattr(S, "_observed_period_intervals", None)
    assert ivs == S.event_intervals(a, None, now, None, _rules())


# --------------------------------------------- invariance: the observation periods reach no other feed's output
# (The check against c123f36's status module, loaded from git history, was retired on 2026-11-15: that module read the
# repository's current rules, waters and states, so its answer moved with the data and the state other tests left,
# and failed in the whole suite once Missouri's waters existed; and a frozen base breaks on every later change to
# status.py. The change it guarded, 6b7e576, is the keyed branch into _observed_period_intervals and nothing else in
# build/status.py, so the same records are checked here on their own: no other feed ever takes that branch, and its
# listed_periods change nothing in the intervals or in the serialised build.)


def _invented_other_records():
    """Records under other states' sources over every advisory and discharge path the change could reach: each status,
    end precision and flag, with and without listed_periods and _last_seen_in_source."""
    out, n = [], 0
    for sid, st_code in (("ne-dwee-beachwatch", "NE"), ("mo-dnr-hab", "MO"), ("xx-invented-feed", "XX"),
                         ("hi-doh-cwb-events-api", "HI")):
        for et in ("beach_advisory", "hab_advisory", "beach_closure", "sso", "cso"):
            for st in ("advisory_active", "advisory_lifted", "unknown", "ongoing", "ended"):
                for end, prec in ((None, None), (N1, "poll"), ("2026-07-20", "day")):
                    for extra in ({}, {"listed_periods": [{"from": J1, "to": J6}, {"from": N1, "to": N1}]},
                                  {"_agency_label_only": True, "_caution_to_notice_end": True, "_last_seen_in_source": J6},
                                  {"_poll_confirmed": True, "_last_seen_in_source": J6}):
                        n += 1
                        raw = {"state": st_code, **copy.deepcopy(extra)}
                        if prec:
                            raw["ended_at_precision"] = prec
                        out.append({"event_id": f"{sid}:inv-{n}", "source_id": sid, "source_record_id": f"inv-{n}",
                                    "event_type": et, "status": st, "started_at": J1, "ended_at": end,
                                    "time_precision": "poll" if n % 2 else "exact", "fetched_at": N3,
                                    "lat": 38.7 + (n % 7) / 1000, "lon": -75.08, "coord_source": "station",
                                    "waterbody_text": "Invented Water", "authority": "Invented authority",
                                    "source_url": "https://example.org/", "raw": raw})
    return out


def _without_periods(r: dict) -> dict:
    return {**r, "raw": {k: v for k, v in r["raw"].items() if k != "listed_periods"}}


def _never(*a, **k):
    raise AssertionError("another feed's record took the observation-period branch")


def test_no_other_feed_takes_the_observation_period_branch(monkeypatch):
    recs = _invented_other_records()
    assert sum(1 for r in recs if "listed_periods" in r["raw"]) >= 200
    rules = _real_rules()
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(S, "_observed_period_intervals", _never)
    for r in recs:
        assert S.event_intervals(r, None, now, None, rules) == \
            S.event_intervals(_without_periods(r), None, now, None, rules), r["event_id"]


# the status module's state a build sets or fills; the comparison below must leave every one as it found it
STATUS_GLOBALS = ("_STATES", "_SHORE_REACHES", "_STRETCH_REACHES", "_RULES", "WITHHELD", "NOT_LIVE", "ALIAS_PROBLEMS",
                  "_GEOM_CACHE", "_REACH_WATERS", "_COUNTIES", "_RECORD_COUNTIES")
_SNAPSHOT: dict = {}


def _status_globals() -> dict:
    return {k: (id(getattr(S, k)), copy.copy(getattr(S, k))) for k in STATUS_GLOBALS}


@pytest.fixture
def seeded_status_globals():
    """Known values in the module's state before the build test (as another test, or a run, may leave them); the test
    after it checks they are still there."""
    seeds = {"_STATES": {"NE"}, "_SHORE_REACHES": {"seed-shore"}, "_STRETCH_REACHES": {"seed-stretch"}}
    old = {k: getattr(S, k) for k in seeds}
    for k, v in seeds.items():
        setattr(S, k, v)
    _SNAPSHOT.clear()
    _SNAPSHOT.update(_status_globals())
    yield
    _SNAPSHOT["after"] = _status_globals()
    for k, v in old.items():
        setattr(S, k, v)


def test_other_feeds_status_output_is_the_same_with_and_without_listed_periods(seeded_status_globals, monkeypatch,
                                                                                 tmp_path):
    from build import rain_likely as R
    recs = _invented_other_records()
    rules = _real_rules()
    now = datetime(2026, 11, 15, tzinfo=timezone.utc)
    monkeypatch.setattr(S, "_observed_period_intervals", _never)
    # every input given, none read from the repository or data/build: a loader called here fails the test
    for mod, name in ((S, "load_waters"), (S, "load_outfalls"), (S, "load_registry_outfalls"), (S, "load_registry"),
                      (S, "load_discharger_towns"), (S, "load_discharger_waters"), (S, "discharger_aliases"),
                      (R, "load_inputs")):
        monkeypatch.setattr(mod, name, lambda *a, _n=name, **k: pytest.fail(f"the build read {_n}"))
    rain = {"rainfall": {}, "history": {}, "thresholds": {}, "dischargers": {}, "site_flags": {}, "levels": {}}
    outs = []
    for name, rr in (("with", recs), ("without", [_without_periods(r) for r in recs])):
        d = tmp_path / name
        d.mkdir()
        by = {}
        for r in rr:
            by.setdefault(r["source_id"], []).append(r)
        for sid, xs in by.items():
            (d / f"{sid}.json").write_text(json.dumps({"source_id": sid, "ok": True, "last_ok_at": N3, "meta": {},
                                                       "records": xs}))
        for k in STATUS_GLOBALS:                         # fresh copies: whatever a build sets or fills is undone
            v = getattr(S, k)
            monkeypatch.setattr(S, k, copy.deepcopy(v))
        o, _ = S.build(now=now, write=False, events_dir=d, waters={}, outfalls=[], registry={}, reaches={},
                       flows=({}, {}), rules=rules, placement_cache=None, rain=copy.deepcopy(rain),
                       discharger_towns={}, discharger_waters={}, discharger_aliases_map={})
        o = json.loads(json.dumps(o, default=str))
        for v in o.values():                           # the build's own wall-clock stamp ("built") is not output
            if isinstance(v, dict):
                v.pop("built", None)
        o.pop("built", None)
        outs.append(json.dumps(o, sort_keys=True))
    assert '"advisory_points": []' not in outs[0]
    assert outs[0] == outs[1]


def test_the_build_comparison_left_the_status_modules_state_as_it_found_it():
    if "after" not in _SNAPSHOT:
        pytest.skip("runs after the build comparison above")
    before, after = {k: v for k, v in _SNAPSHOT.items() if k != "after"}, _SNAPSHOT["after"]
    changed = sorted(k for k in STATUS_GLOBALS if after[k] != before[k])
    assert changed == []


# --------------------------------------------- P1-2: a Delaware beach name's house number never reaches a save

ADDR = " at 1234 W Sample Street"
ADDR_SENT = ("1234 W", "12-A Sample", "56 1/2 Sample", "1234")


def _de_capture(monkeypatch, tmp_path, rows, stations_js, carried):
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
    monkeypatch.setattr(W.requests, "get", lambda url, **k: Resp(rows) if url == W.SOCRATA else Resp(stations_js))
    return saves


def test_a_delaware_beach_name_with_an_address_never_reaches_a_save(monkeypatch, tmp_path):
    s = json.loads((Path(__file__).resolve().parent / "fixtures" / "de" / "recwater.json").read_text())
    rows, stations = copy.deepcopy(s["advisories"]), copy.deepcopy(s["stations"])
    stations[0]["UnitName"] = "Invented Beach" + ADDR
    stations[0]["CurrentAdvisory"] = 0                       # shown on the map: a poll record carries the name
    stations[1]["UnitName"] = "Invented 12-A Sample Lane Beach"
    rows[0]["unitname"] = "Invented Beach" + ADDR
    rows[1]["unitname"] = "Beach by 56 1/2 Sample Road"
    carried = {"polls": {"station-1-2026": {"unit_id": "1", "code": 0, "name": "Old Beach" + ADDR,
                                            "started_at": "2026-11-01T00:00:00Z", "lat": 38.7, "lon": -75.1,
                                            "listed_periods": [{"from": "2026-11-01T00:00:00Z",
                                                                "to": "2026-11-01T00:00:00Z"}]}},
               "history": {"adv-old": {"event_id": "de-dnrec-recreational-water:adv-old", "source_record_id": "adv-old",
                                       "outfall_name": "Old Beach" + ADDR, "waterbody_text": "Old Beach" + ADDR,
                                       "advice_text": "Posted at 1234 W Sample Street.", "status": "advisory_lifted",
                                       "started_at": "2020-07-01", "ended_at": "2020-07-02",
                                       "raw": {"unit_name": "Old Beach" + ADDR,
                                               "advisory_description": "Beach at 1234 W Sample Street"}}}}
    saves = _de_capture(monkeypatch, tmp_path, rows, {"features": [{"attributes": a} for a in stations]}, carried)
    assert W.main(["--at", "2026-11-14T18:00:00Z"]) == 0
    assert len(saves) == 3                                   # the raw archive, the state and the records
    blob = "\n".join(saves)
    for x in ADDR_SENT:
        assert x not in blob, x
    assert "[house number removed]" in blob
    # the records held before the run are all still there
    recs = json.loads(saves[-1])[0]
    assert "de-dnrec-recreational-water:adv-old" in {r["event_id"] for r in recs}


def test_a_failed_station_read_quotes_no_station_text(monkeypatch, tmp_path):
    s = json.loads((Path(__file__).resolve().parent / "fixtures" / "de" / "recwater.json").read_text())
    bad = {"error": {"code": 400, "message": "Invented Beach" + ADDR, "details": ["Invented Beach" + ADDR]}}
    saves = _de_capture(monkeypatch, tmp_path, s["advisories"], bad, {})
    assert W.main(["--at", "2026-11-14T18:00:00Z"]) == 1
    blob = "\n".join(saves)
    assert "1234" not in blob and "error code 400" in blob


@pytest.mark.parametrize("name,kept", [
    ("3 R's Road Beach", "3 R's Road Beach"),
    ("3 R’s Road Beach (Delaware Seashore State Park)", "3 R’s Road Beach (Delaware Seashore State Park)"),
    ("Delaware Bay 3", "Delaware Bay 3"),
    ("Rehoboth Bay 1", "Rehoboth Bay 1"),
    ("3 R's Road Beach at 77 Sample Rd", "3 R's Road Beach at [house number removed] Sample Rd"),
    ("Invented Beach at 1234 W Sample Street", "Invented Beach at [house number removed] W Sample Street"),
    ("Invented 12-A Sample Lane Beach", "Invented [house number removed] Sample Lane Beach"),
    ("Beach by 56 1/2 Sample Road", "Beach by [house number removed] Sample Road"),
    ("Invented 33 R's Road Beach", "Invented [house number removed] R's Road Beach"),
])
def test_only_dnrecs_own_numbered_name_keeps_its_number(name, kept):
    assert W.scrub_unit_name(name) == kept


# --------------------------------------------- P2: Florence's cached export is the current format

FLORENCE_EVENTS = Path(__file__).resolve().parents[2] / "data" / "build" / "events" / "sc-florence-sso-notices.json"
FLORENCE_STATE = sorted((Path(__file__).resolve().parents[2] / "data" / "raw" / "sc").glob("florence-state-*.json"))


def _florence_checks(recs):
    ids = {r["event_id"] for r in recs}
    blob = json.dumps(recs).lower()
    assert "no threat to public health" not in blob and "no threat to" not in blob
    advice = [r for r in recs if r["event_id"].endswith("-advice")]
    for r in recs:
        if r.get("advice_text") and not r["event_id"].endswith("-advice"):
            assert r["status"] != "advisory_active"          # the advice is its own record, never the overflow's
    for a in advice:
        assert a["raw"]["_advice_not_a_discharge"] is True and a["raw"]["overflow_record"] in ids
        assert a["raw"]["_ages_after_confirmation"] is True
    spills = [r for r in recs if not (r.get("raw") or {}).get("_advice_not_a_discharge")]
    assert len({r["event_id"] for r in spills}) == len(spills)
    return advice


@pytest.mark.skipif(not FLORENCE_STATE, reason="no saved Florence state on this machine")
def test_florence_records_rebuilt_from_the_saved_state_are_the_current_format(tmp_path):
    from ingest import sc_florence_sso as F
    out = tmp_path / "florence.json"
    assert F.main(["--file", str(FLORENCE_STATE[-1]), "--out", str(out)]) == 0
    recs = json.loads(out.read_text())["records"]
    assert _florence_checks(recs)                              # at least one advice record, kept apart


@pytest.mark.skipif(not FLORENCE_EVENTS.is_file(), reason="no cached Florence export on this machine")
def test_the_cached_florence_export_is_the_current_format():
    # a generated file older than the advice split fails here: regenerate it before the export
    _florence_checks(json.loads(FLORENCE_EVENTS.read_text())["records"])
