"""SFPUC beach map snapshot (pipeline/ingest/ca_sfpuc_beaches.py). The fixture is the service's answer of 2026-11-04
(20 stations, no flag); the tests set flags on copies of it.
Run from pipeline/: python -m pytest tests/test_ca_sfpuc_beaches.py -q
"""
from __future__ import annotations

import copy
from pathlib import Path

from ingest import ca_sfpuc_beaches as M

FIX = Path(__file__).resolve().parent / "fixtures" / "ca_sfpuc_getbeaches.xml"


def stations():
    return M.parse(FIX.read_text())


def with_flags(cso=(), post=()):
    out = copy.deepcopy(stations())
    for s in out:
        if s["stationid"] in cso:
            s["cso"] = "Y"
        if s["stationid"] in post:
            s["s_color"] = "R"
    return out


def by_id(recs):
    return {r["source_record_id"]: r for r in recs}


def test_the_answer_is_read_from_the_xml_string():
    st = stations()
    assert len(st) == 20 and st[0]["stationid"] == "4601" and st[0]["stationname"] == "Fort Funston"
    assert not any(M.flagged(s) or M.posted(s) for s in st)


def test_a_cso_flag_is_red_while_it_shows_and_ends_at_the_first_poll_without_it():
    state = {}
    M.step(state, stations(), "2026-11-04T10:00:00Z")
    M.step(state, with_flags(cso={"4615"}), "2026-11-04T11:00:00Z")
    M.step(state, with_flags(cso={"4615"}), "2026-11-04T12:00:00Z")
    recs = by_id(M.records(state, "2026-11-04T12:00:00Z"))
    r = recs["4615-cso-20261104T1100Z"]
    assert r["event_type"] == "cso" and r["status"] == "ongoing" and r["ended_at"] is None
    assert r["started_at"] == "2026-11-04T11:00:00Z" and r["time_precision"] == "poll"
    assert r["raw"]["occurred_after"] == "2026-11-04T10:00:00Z" and r["discharger_id"] == "ca-sfpuc"
    assert r["npdes_permit"] == "CA0037664" and r["advice_text"].startswith("Combined Sewer Discharge")
    M.step(state, stations(), "2026-11-04T13:00:00Z")
    r = by_id(M.records(state, "2026-11-04T13:00:00Z"))["4615-cso-20261104T1100Z"]
    assert r["status"] == "ended" and r["ended_at"] == "2026-11-04T13:00:00Z"
    assert r["raw"]["flag_last_seen_at"] == "2026-11-04T12:00:00Z"


def test_a_flag_seen_on_the_first_poll_may_have_happened_72_hours_before_and_westside_is_oceanside():
    state = {}
    M.step(state, with_flags(cso={"4601"}), "2026-11-04T10:00:00Z")
    r = M.records(state, "2026-11-04T10:00:00Z")[0]
    assert r["raw"]["occurred_after"] == "2026-11-01T10:00:00Z" and r["npdes_permit"] == "CA0037681"
    assert r["waterbody_text"] == "Pacific Ocean"


def test_a_posting_is_an_advisory_and_its_lifting_ends_it():
    state = {}
    M.step(state, with_flags(post={"4607"}), "2026-11-04T10:00:00Z")
    M.step(state, stations(), "2026-11-05T10:00:00Z")
    r = M.records(state, "2026-11-05T10:00:00Z")[0]
    assert r["event_type"] == "beach_advisory" and r["status"] == "advisory_lifted"
    assert r["started_at"] == "2026-11-04T10:00:00Z" and r["ended_at"] == "2026-11-05T10:00:00Z"
    assert r["discharger_id"] is None


def test_a_short_answer_is_an_outage_that_keeps_the_records(tmp_path):
    state = tmp_path / "s.json"
    out = tmp_path / "e.json"
    assert M.main(["--file", str(FIX), "--state", str(state), "--out", str(out)]) == 0
    short = tmp_path / "short.xml"
    short.write_text('<string xmlns="http://tempuri.org/">[{"stationid":"4601","stationname":"Fort Funston"}]</string>')
    assert M.main(["--file", str(short), "--state", str(state), "--out", str(out)]) == 1
    import json
    assert json.loads(out.read_text())["ok"] is False
