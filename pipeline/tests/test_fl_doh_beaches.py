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
