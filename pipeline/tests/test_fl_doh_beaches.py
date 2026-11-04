"""Florida Healthy Beaches: the Caspio result rows and per-sample advisories (no network; a trimmed page)."""
from pathlib import Path

from ingest import fl_doh_beaches as B

PAGE = (Path(__file__).resolve().parent / "fixtures" / "fl_doh_beach_page.html").read_text()
POINT = {"County": "Bay", "EPAbeachID": "FL289095", "SPLocation": "8TH STREET", "SPLat": 29.93689167,
         "SPLong": -85.40334143, "Link": "https://www.floridahealth.gov/x/beach-detail/?County=Bay&SPLocation=8TH+STREET"}


def test_rows_parse():
    rows = B.parse_page(PAGE)
    assert [r["date"] for r in rows] == ["2026-10-26", "2026-10-12", "2026-09-28", "2026-09-21"]
    assert rows[1] == {"period": "1317", "location": "8TH STREET", "date": "2026-10-12", "enterococcus": "122",
                       "advisory": "Yes"}


def test_advisory_opens_on_a_yes_sample_and_lifts_on_the_next_no():
    recs, stats = B.build([POINT], {B.point_key(POINT): PAGE}, [], "2026-11-04T00:00:00Z")
    assert len(recs) == 1 and stats["samples_read"] == 4
    r = recs[0]
    assert r["event_type"] == "beach_advisory" and r["status"] == "advisory_lifted"
    assert r["started_at"] == "2026-10-12T00:00:00-04:00" and r["ended_at"] == "2026-10-26T00:00:00-04:00"
    assert r["time_precision"] == "day" and r["event_id"] == "fl-doh-beaches:FL289095-8th-street:1317"
    # the same advisory is one record across runs
    again, _ = B.build([POINT], {B.point_key(POINT): PAGE}, recs, "2026-11-05T00:00:00Z")
    assert [x["event_id"] for x in again] == [r["event_id"]]


def test_open_advisory_is_active():
    page = PAGE.split("</tr>", 1)[1]          # drop the newest (Advisory No) row
    recs, _ = B.build([POINT], {B.point_key(POINT): "<table>" + page}, [], "x")
    assert recs[0]["status"] == "advisory_active" and recs[0]["ended_at"] is None
    assert recs[0]["source_updated_at"] == "2026-10-12T00:00:00-04:00"


# ---------------------------------------------------------------- review 2026-11-04

def test_a_corrected_sample_replaces_the_kept_copy_and_drops_the_advisory():
    recs, _ = B.build([POINT], {B.point_key(POINT): PAGE}, [], "2026-11-04T00:00:00Z")
    assert len(recs) == 1
    corrected = PAGE.replace('<span style="color:#FF0000">Yes</span>', '<span style="color:#218429">No</span>')
    assert corrected != PAGE and not any(r["advisory"] == "Yes" for r in B.parse_page(corrected))
    again, _ = B.build([POINT], {B.point_key(POINT): corrected}, recs, "2026-11-05T00:00:00Z")
    assert again == []                    # the fresh rows win over the copy kept from the earlier run


def test_lifted_advisory_says_how_its_end_was_set():
    recs, _ = B.build([POINT], {B.point_key(POINT): PAGE}, [], "x")
    assert "lifts the advisory when" in recs[0]["raw"]["end_basis"]


def test_no_rows_on_any_page_is_a_failure_that_keeps_the_records(tmp_path, monkeypatch):
    import json

    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(B, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(B, "STATE_FILE", tmp_path / "state.json")
    pts = [{**POINT, "SPLocation": f"P{i}"} for i in range(12)]
    good = tmp_path / "good.json"
    good.write_text(json.dumps({"points": [POINT], "pages": {B.point_key(POINT): PAGE}}))
    assert B.main(["--file", str(good)]) == 0
    empty = tmp_path / "empty.json"
    empty.write_text(json.dumps({"points": pts, "pages": {B.point_key(p): "<p>No records found.</p>" for p in pts}}))
    assert B.main(["--file", str(empty)]) == 1
    d = json.loads((tmp_path / f"{B.SOURCE_ID}.json").read_text())
    assert d["ok"] is False and d["count"] == 1
