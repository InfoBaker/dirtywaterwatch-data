"""Puerto Rico: DRNA's weekly beach notices (ingest/pr_drna_beaches.py) on seven real notices
(tests/fixtures/pr_drna_beach_posts.json: 2019-10-11 a PDF-only post, 2020-06-30 the list of beaches fit for bathers,
2026-08-19 all fit, 2026-10-16 to 2026-11-13 four lists of beaches over the value)."""
import json
import re
from pathlib import Path

import common
from ingest import pr_drna_beaches as P

FIX = Path(__file__).parent / "fixtures"
AT = "2026-11-14T12:00:00Z"


def _posts():
    return json.loads((FIX / "pr_drna_beach_posts.json").read_text())


def _records():
    recs, meta = P.records([P.parse_notice(p) for p in _posts()], AT)
    return {r["source_record_id"]: r for r in recs}, meta


def test_notices_are_read_by_kind_and_a_fit_list_is_never_an_advisory():
    kinds = {p["id"]: P.parse_notice(p)["kind"] for p in _posts()}
    assert kinds == {50846: "unread", 52939: "fit_list", 103861: "all_fit", 104868: "exceed", 105112: "exceed",
                     105202: "exceed", 105307: "exceed"}
    recs, meta = _records()
    assert not any(r["raw"]["notices"][0]["id"] in (52939, 103861, 50846) for r in recs.values())
    assert meta["by_kind"] == {"exceed": 4, "all_fit": 1, "fit_list": 1, "unread": 1} and meta["unread_notices"] == [50846]


def test_a_beach_listed_in_consecutive_notices_is_one_advisory_from_the_first_publication():
    recs, _ = _records()
    r = recs["RW-31:105202"]          # Tropical Beach, listed 2026-11-06 and 2026-11-13
    assert r["event_type"] == "beach_advisory" and r["status"] == "advisory_active" and r["ended_at"] is None
    assert r["started_at"] == r["published_at"] == "2026-11-06T16:39:10Z" and r["time_precision"] == "minute"
    assert r["sampled_at"] == "2026-11-02" and r["raw"]["sample_dates"] == "2 y 3 de noviembre de 2026"
    assert [n["id"] for n in r["raw"]["notices"]] == [105202, 105307]
    assert r["raw"]["_last_seen_in_source"] == AT and r["raw"]["time_zone"] == "America/Puerto_Rico"
    assert r["waterbody_text"] == "Tropical Beach (Naguabo)"


def test_the_sample_date_is_never_the_start():
    recs, _ = _records()
    for r in recs.values():
        assert r["sampled_at"] is None or not r["started_at"].startswith(r["sampled_at"])
        assert r["started_at"] == r["raw"]["notices"][0]["published"]


def test_an_advisory_ends_at_the_next_notice_that_does_not_list_it():
    recs, _ = _records()
    r = recs["RW-23:105202"]
    assert r["status"] == "advisory_lifted" and r["ended_at"] == "2026-11-13T19:07:56Z"
    assert r["raw"]["ended_at_precision"] == "minute" and "does not list this beach" in r["raw"]["end_basis"]
    assert "_last_seen_in_source" not in r["raw"]


def test_an_all_fit_notice_ends_every_open_advisory_and_an_unread_one_ends_none():
    posts = _posts()
    exceed = next(p for p in posts if p["id"] == 105112)
    fit = next(p for p in posts if p["id"] == 103861)
    unread = next(p for p in posts if p["id"] == 50846)
    later = lambda p, t: {**p, "id": p["id"] + 1000000, "date_gmt": t, "modified_gmt": t}
    ns = [P.parse_notice(p) for p in (exceed, later(unread, "2026-11-01T12:00:00"), later(fit, "2026-11-02T12:00:00"))]
    recs, _ = P.records(ns, AT)
    assert len(recs) == 2 and all(r["ended_at"] == "2026-11-02T12:00:00Z" for r in recs)
    assert all("fit for bathers" in r["raw"]["end_basis"] for r in recs)


def test_the_beachs_name_decides_a_wrong_station_number():
    recs, meta = _records()
    r = recs["RW-34:104868"]
    assert r["waterbody_text"] == "Playa Cabullón (Ponce)" and r["raw"]["listed_as"] == ["RW-30"]
    assert "is that of RW-34" in r["raw"]["station_note"] and r["lat"] == 17.969
    assert P.station_of("RW-06", "Balneario de Patillas") == ("RW-6", None)
    assert P.station_of("RWW-28", "Playa El Alambique")[0] == "RW-28"
    assert P.station_of("RW14A", "Playa Mojacasabe")[0] == "RW-14"
    assert P.station_of("RW-28", "Muelle de Arecibo")[0] == "RW-38"
    assert P.station_of("RW-4", "Balneario Punta Santiago")[0] == "RW-4"


def test_every_station_has_one_cited_point_rounded_to_three_decimals():
    assert len(P.STATIONS) == 36
    for k, (name, town, wqx, lat, lon, rule) in P.STATIONS.items():
        assert 17.8 < lat < 18.6 and -67.3 < lon < -65.2, k
        assert round(lat, 3) == lat and round(lon, 3) == lon
        assert re.search(rule, P.fold(name)), k
    recs, _ = _records()
    for r in recs.values():
        assert r["coord_source"] == "station_point" and r["raw"]["point_url"].startswith(
            "https://www.waterqualitydata.us/provider/STORET/PR_BEACH_WQX/")


def test_drnas_words_are_quoted_as_written():
    recs, _ = _records()
    r = recs["RW-31:105202"]
    assert "no son aptas para bañistas" in r["advice_text"] and "Enterococos (70 colonias/100 mL)" in r["advice_text"]
    assert not re.search(r"\b(safe|clean)\b", json.dumps(list(recs.values())), re.I)


def test_an_unknown_station_is_kept_with_no_point():
    post = dict(_posts()[0])
    post["content"] = {"rendered": post["content"]["rendered"].replace("Tropical Beach", "Playa Ejemplo").replace(
        "RW-31", "RW-99")}
    recs, _ = P.records([P.parse_notice(post)], AT)
    assert len(recs) == 1 and recs[0]["lat"] is None and "not in DRNA's station table" in recs[0]["parse_error"]


def test_main_reads_saved_posts(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(P, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(P, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / f"{sid}.json", **kw))
    f = tmp_path / "posts.json"
    f.write_text(json.dumps(_posts()))
    assert P.main(["--file", str(f), "--at", AT]) == 0
    doc = json.loads((tmp_path / "pr-drna-beach-notices.json").read_text())
    assert doc["ok"] and doc["count"] == 8 and doc["meta"]["notices"] == 7
