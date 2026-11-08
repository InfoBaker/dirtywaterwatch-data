"""Kentucky's standing swimming advisories (ingest/ky_dow_swimming_advisories.py; review 2026-11-08 P1-1): the list of
the agencies' page (tests/fixtures/ky_dow_swimming_advisories.html: the advisory part of the page read on 2026-11-07,
the contact block left out) read as standing advisories in the agencies' own words, with no invented date."""
import json
from pathlib import Path

import common
from ingest import ky_dow_swimming_advisories as M

FIX = Path(__file__).parent / "fixtures" / "ky_dow_swimming_advisories.html"


def _state(*pages):
    st = {}
    for at, page in pages:
        M.update(st, M.list_text(page), at)
    return st


def test_the_pages_stretches_are_standing_advisories_in_the_agencies_words():
    recs = M.records(_state(("2026-11-07T12:00:00Z", FIX.read_text())))
    by = {r["source_record_id"]: r for r in recs}
    assert len(recs) == 12 and all(r["status"] == "advisory_active" for r in recs)
    assert {r["waterbody_text"] for r in recs} == {
        "Cumberland River", "Martins Fork Cumberland River", "Catron Creek", "Clover Fork of the Cumberland River",
        "Straight Creek", "Poor Fork of the Cumberland River", "Looney Creek", "North Fork of Kentucky River",
        "Licking River", "Banklick Creek", "Three Mile Creek"}
    r = by["licking-banklick-to-ohio"]
    assert r["event_type"] == "beach_advisory" and "untreated or inadequately treated sewage" in r["advice_text"]
    assert r["started_at"] == "2026-11-07T12:00:00Z" and r["time_precision"] == "poll"
    assert r["reported_at"] is None and r["published_at"] is None and r["source_updated_at"] is None
    assert "several years" in r["raw"]["start_basis"] and r["raw"]["_last_seen_in_source"] == "2026-11-07T12:00:00Z"
    assert r["raw"]["stretch_text"] == "from Banklick Creek to the confluence with the Ohio River"
    assert r["lat"] is None and r["water_slugs"] == [] and "stretch" not in r       # a marker, never a whole water


def test_a_stretch_the_page_drops_ends_at_that_read():
    page = FIX.read_text()
    fewer = page.replace("Looney Creek from the mouth to Lynch Water Plant Bridge", "")
    recs = M.records(_state(("2026-11-07T12:00:00Z", page), ("2026-11-08T12:00:00Z", fewer)))
    by = {r["source_record_id"]: r for r in recs}
    gone = by["looney-creek-mouth-to-lynch"]
    assert gone["status"] == "advisory_lifted" and gone["ended_at"] == "2026-11-08T12:00:00Z"
    assert gone["raw"]["ended_at_precision"] == "poll"
    assert by["catron-creek"]["status"] == "advisory_active"
    assert by["catron-creek"]["raw"]["_last_seen_in_source"] == "2026-11-08T12:00:00Z"


def test_a_new_listed_sentence_is_kept_as_unknown():
    page = FIX.read_text().replace("<li>Looney Creek", "<li>All of Example Creek</li><li>Looney Creek")
    recs = M.records(_state(("2026-11-07T12:00:00Z", page)))
    unk = [r for r in recs if r["event_type"] == "unknown"]
    assert len(unk) == 1 and "Example Creek" in unk[0]["parse_error"]


def test_a_page_without_the_list_is_not_a_withdrawal(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(M, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(M, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    assert M.main(["--file", str(FIX), "--at", "2026-11-07T12:00:00Z"]) == 0
    bad = tmp_path / "bad.html"
    bad.write_text("<html><body>Page not available</body></html>")
    assert M.main(["--file", str(bad), "--at", "2026-11-08T12:00:00Z"]) == 1
    doc = json.loads((tmp_path / "events" / f"{M.SOURCE_ID}.json").read_text())
    assert doc["ok"] is False and doc["count"] == 12 and {r["status"] for r in doc["records"]} == {"advisory_active"}
