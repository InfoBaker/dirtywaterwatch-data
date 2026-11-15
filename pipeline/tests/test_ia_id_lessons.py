"""Iowa and Idaho against the fifteen failure classes of docs/reviews/2026-11-15-expansion/lessons-from-reviews.md (site
repository), one test on invented data per case that applies. Every name, street and number here is invented."""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from ingest import ia_dnr_focomp as F
from ingest import ia_dnr_news as N
from ingest import ia_waterloo_sso as W
from ingest import id_deq_cyanohab as H
from ingest.ia_id_privacy import WITHHELD, home_place, scrub, scrub_sentences

FIX = Path(__file__).resolve().parent / "fixtures"
AT = "2026-11-14T23:00:00Z"
FAC = {"st_fac_id": "399999001", "name": "Example City Of Stp", "city": "Exampleton", "county": "Polk"}
OPS = {"IA0099999": ("ia-exampleton", "City of Exampleton")}


def focomp_rep(**kw):
    rep = F.parse_report((FIX / "ia" / "focomp-report-900002.html").read_text())
    return {**rep, **kw}


# ------------------------------------------------------------------ 6. privacy on every save path

@pytest.mark.parametrize("text", ["Contact Example Person at the plant.", "Dr. Example Person inspected the main.",
                                  "Example Person reported the overflow.", "Backup at the home of Example Person.",
                                  "Mr. Example called the office."])
def test_6_text_that_may_name_a_person_is_withheld(text):
    assert scrub(text) == WITHHELD


@pytest.mark.parametrize("text,gone", [("Overflow at 123-A Example St into the creek.", "123-A"),
                                       ("Overflow at 1234 1/2 Example Ave.", "1234"),
                                       ("Call (515) 555-0100 for the lift station.", "555-0100")])
def test_6_house_numbers_with_a_suffix_or_fraction_and_phones_are_cut(text, gone):
    assert gone not in (scrub(text) or "")


def test_6_coordinates_in_text_are_rounded_and_a_block_is_kept():
    assert scrub("Manhole near 41.59123, -93.61234 overflowed.") == "Manhole near 41.591, -93.612 overflowed."
    assert scrub("Lift station (200-blk Example Ave) overflowed.") == "Lift station (200-blk Example Ave) overflowed."
    assert scrub("Sanitary sewer at Sample Rd and Example Dr. The overflow ended.").startswith("Sanitary sewer")


def test_6_a_release_keeps_its_facts_when_its_contact_line_names_someone():
    t = scrub_sentences("The Department has been contacted regarding a discharge into Example Creek. For more "
                        "information, contact Example Person at 515-555-0100.")
    assert "Example Creek" in t and "Example Person" not in t and "555" not in t


def test_6_focomp_a_private_home_loses_point_and_street_and_carried_state_is_scrubbed_again():
    rep = focomp_rep(details="Overflow in the yard of a private home at 12-B Example Ln.", lat=41.51234, lon=-93.49876,
                     address="[house number removed] Example Ln")
    r = F.make_record(rep, FAC, {"label": "x"}, ("IA0099999", "basis"), AT, ops=OPS)
    assert r["lat"] is None and r["lon"] is None and r["raw"]["incident_address"] is None
    assert "private home" in r["raw"]["privacy_cut"] and "12-B" not in json.dumps(r)
    old = focomp_rep(details="Contact Example Person for the report.", steps_taken="Example Person reported it.")
    r = F.make_record(old, FAC, {"label": "x"}, (None, None), AT, ops=OPS)
    assert r["raw"]["details"] == WITHHELD and r["raw"]["steps_taken"] == WITHHELD
    state = {"reports": {"1": {"fac": "399999001", "fields": dict(old, lat=41.5, lon=-93.5,
                                                                  location="at the home of Example Person")}}}
    f = F.scrub_state(state)["reports"]["1"]["fields"]
    assert f["details"] == WITHHELD and f["lat"] is None and f["location"] is None


def test_6_waterloo_carried_records_are_scrubbed_again_and_a_home_keeps_no_street():
    prev = {"source_record_id": "2024-05-01T0800", "event_id": "x", "raw": {"notice": "Contact Example Person.",
                                                                           "location": "1234-A Example St"}}
    recs, _ = W.build([], AT, [prev])
    raw = recs[0]["raw"]
    assert raw["notice"] == WITHHELD and "1234" not in raw["location"]
    para = ("October 2, 2026 at 5:52 AM, WMSD began Sanitary Sewer bypass pumping at a Sanitary Sewer Overflow "
            "located at the basement backup on Example Ct. The duration of the event was 2 hours.")
    recs, _ = W.build([para], AT, [])
    assert recs[0]["raw"]["location"] is None


# ------------------------------------------------------------------ operators named from the permittee

def test_operators_are_the_permittees_row_never_the_plant():
    r = F.make_record(focomp_rep(), FAC, {"label": "x"}, ("IA0099999", "basis"), AT, ops=OPS)
    assert (r["discharger_id"], r["discharger_name"]) == ("ia-exampleton", "City of Exampleton")
    assert r["raw"]["facility"] == "Example City Of Stp"
    r = F.make_record(focomp_rep(), FAC, {"label": "x"}, (None, None), AT, ops=OPS)
    assert r["discharger_name"] is None and "not established" in r["raw"]["_discharger_basis"]
    recs, _ = W.build([], AT, [])
    assert W.OPERATOR_ID == "ia-waterloo"


# ------------------------------------------------------------------ 1. negation and conditions; 11. both types

ART = {"title": "Wastewater bypass in Exampleton", "date": "2026-08-04", "body": ""}


def news_rec(text, county="Example County"):
    return N.record_from(text, ART, "https://www.iowadnr.gov/news-release/x", "x", county, False, AT)


@pytest.mark.parametrize("text", ["Crews have not stopped the bypass.", "The bypass will be stopped when the river falls.",
                                  "The discharge is expected to have ended April 27th around 4 p.m.",
                                  "The advisory will be lifted if results allow."])
def test_1_a_negated_or_conditional_stop_is_not_an_end(text):
    r = news_rec("On Saturday, July 25th around 2:00 pm, the plant began bypassing to the Sample River. " + text)
    assert r["status"] == "unknown" and r["ended_at"] is None


def test_1_an_affirmative_completed_stop_is_an_end():
    r = news_rec("The plant began bypassing to the Sample River. The bypass was stopped Monday.")
    assert r["status"] == "ended" and r["ended_at"] is None        # no date given: no end time invented
    r = news_rec("The bypass ended July 27th around 4 p.m.")
    assert r["ended_at"] == "2026-07-27T16:00:00-05:00"


def test_11_both_types_in_one_sentence_are_two_records_and_a_denied_type_is_not_one():
    art = {**ART, "body": "A combined sewer overflow and a sanitary sewer overflow reached Example Creek in Example County."}
    recs = N.records_for(art, "https://www.iowadnr.gov/news-release/2026-08-04/x", AT)
    assert sorted(r["event_type"] for r in recs) == ["cso", "sso"]
    assert len({r["source_record_id"] for r in recs}) == 2
    assert N.classify("This was not a combined sewer overflow; a lift station failed.")[0] == "sso"
    assert F.event_type({"location_type": None, "details": "Not a combined sewer outfall: a main broke."}) == "bypass"
    assert F.event_type({"location_type": None, "details": "Overflow at combined sewer outfall 004."}) == "cso"


# ------------------------------------------------------------------ 4. a bad read changes nothing; 5. unread items

def test_4_a_facility_page_whose_rows_cannot_be_read_is_a_failure():
    page = ("<html>Field Office Compliance Action Date <div><a href='/x?incomingReportID=900001'>Report</a></div>"
            "</html>")
    with pytest.raises(ValueError):
        F.parse_facility(page)


def _focomp_main(tmp_path, monkeypatch, fac_page, reports=("900001", "900002")):
    fl = tmp_path / "facilities.json"
    fl.write_text(json.dumps({"facilities": [FAC]}))
    monkeypatch.setattr(F, "FACILITIES", fl)
    monkeypatch.setattr(F, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(F, "iowa_plants", lambda: [])
    monkeypatch.setattr(F, "_OPERATORS", {})
    out = {}
    monkeypatch.setattr(F, "write_events", lambda sid, recs, **kw: out.update(recs=recs, **kw) or tmp_path)
    args = ["--at", AT, "--facility-file", f"399999001={fac_page}"]
    for rid in reports:
        args += ["--report-file", f"{rid}={FIX / 'ia' / f'focomp-report-{rid}.html'}"]
    return F.main(args), out


def test_4_5_an_empty_facility_page_fails_and_an_unreadable_report_keeps_records_and_fails_health(tmp_path, monkeypatch):
    rc, out = _focomp_main(tmp_path, monkeypatch, FIX / "ia" / "focomp-facility.html")
    assert rc == 0 and out.get("ok", True)
    before = json.loads((tmp_path / "state.json").read_text())
    empty = tmp_path / "empty.html"
    empty.write_text("<html>Field Office Compliance <table><tr><th>Action Date</th></tr></table></html>")
    rc, out = _focomp_main(tmp_path, monkeypatch, empty, reports=())
    assert rc == 1 and out["ok"] is False and out["recs"] == []          # write_events keeps the previous records
    state = json.loads((tmp_path / "state.json").read_text())
    assert state["facilities"]["399999001"]["listed"] == before["facilities"]["399999001"]["listed"]
    assert not any(r.get("unlisted_since") for r in state["reports"].values())
    # the facility read, one report page unreadable: the readable records are written, health stays false
    bad = tmp_path / "focomp-report-900001.html"
    bad.write_text("<html>Service unavailable</html>")
    real = F._files
    monkeypatch.setattr(F, "_files", lambda argv, flag: ({"900001": bad.read_text()} if flag == "--report-file"
                                                         else real(argv, flag)))
    rc, out = _focomp_main(tmp_path, monkeypatch, FIX / "ia" / "focomp-facility.html", reports=("900001",))
    assert rc == 0 and out["ok"] is False and out["partial"] is True and out["meta"]["unread"]
    assert {r["source_record_id"] for r in out["recs"]} >= {"900001", "900002"}


def test_4_5_news_an_empty_feed_fails_and_an_unreadable_release_fails_health(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "STATE_PATH", tmp_path / "state.json")
    out = {}
    monkeypatch.setattr(N, "write_events", lambda sid, recs, **kw: out.update(recs=recs, **kw) or tmp_path)
    rss = tmp_path / "rss.xml"
    rss.write_text("<rss><channel></channel></rss>")
    assert N.main(["--rss-file", str(rss), "--at", AT]) == 1 and out["ok"] is False
    rss.write_text("<rss><channel><item><title>Wastewater bypass in Exampleton</title>"
                   "<link>https://www.iowadnr.gov/news-release/2026-08-04/x</link></item></channel></rss>")
    page = tmp_path / "bad.html"
    page.write_text("<html>Error</html>")
    assert N.main(["--rss-file", str(rss), "--at", AT, "--article-file",
                   f"https://www.iowadnr.gov/news-release/2026-08-04/x={page}"]) == 0
    assert out["ok"] is False and out["partial"] is True and out["meta"]["errors"]


def test_4_5_waterloo_an_empty_list_fails_and_an_unreadable_notice_fails_health(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "EVENTS_DIR", tmp_path)
    out = {}
    monkeypatch.setattr(W, "write_events", lambda sid, recs, **kw: out.update(recs=recs, **kw) or tmp_path)
    (tmp_path / f"{W.SOURCE_ID}.json").write_text(json.dumps({"records": [{"source_record_id": "2026-10-01T0552"}]}))
    empty = tmp_path / "empty.html"
    empty.write_text("<p>Recent SSO and Bypass Events</p><p>Terms:</p>")
    assert W.main(["--file", str(empty), "--at", AT]) == 1 and out["ok"] is False
    assert W.main(["--file", str(FIX / "ia" / "waterloo-notices.html"), "--at", AT]) == 0
    assert out["ok"] is False and out["partial"] is True                  # one paragraph the reader cannot read


# ------------------------------------------------------------------ 7. stable ids

def test_7_waterloo_ids_do_not_depend_on_page_order_or_on_reading_together():
    a = ("October 1, 2026 at 7:40 AM, WMSD began Sanitary Sewer bypass pumping located at Example St. The estimated "
         "volume of sewer discharged is unknown; the duration of the event was 2 hours.")
    b = ("October 1, 2026 at 7:40 AM, WMSD began Sanitary Sewer bypass pumping at Sample Rd and Example Ct. The "
         "duration of the event was 3 hours.")
    ids1 = {r["source_record_id"] for r in W.build([a, b], AT, [])[0]}
    ids2 = {r["source_record_id"] for r in W.build([b, a], AT, [])[0]}
    assert ids1 == ids2 and len(ids1) == 2
    first, _ = W.build([b], AT, [])                       # only one of the two on the page at first
    both, _ = W.build([a, b], AT, first)
    assert len(both) == 2 and first[0]["source_record_id"] in {r["source_record_id"] for r in both}
    fixed, _ = W.build([b.replace("Example Ct", "Example Ct North")], AT, first)     # a corrected location
    assert [r["source_record_id"] for r in fixed] == [first[0]["source_record_id"]]


# ------------------------------------------------------------------ 9. the local calendar day and clock changes

def test_9_waterloo_a_duration_across_the_fall_change_is_elapsed_time():
    p = ("November 1, 2026 at 12:30 AM, WMSD began Sanitary Sewer bypass pumping at Example St. The duration of the "
         "event was 2 hours.")
    r = W.build([p], AT, [])[0][0]
    assert r["started_at"] == "2026-11-01T00:30:00-05:00" and r["ended_at"] == "2026-11-01T01:30:00-06:00"
    p = ("March 8, 2026 at 1:30 AM, WMSD began Sanitary Sewer bypass pumping at Example St. The duration of the "
         "event was 1 hours.")
    assert W.build([p], AT, [])[0][0]["ended_at"] == "2026-03-08T03:30:00-05:00"


def test_9_focomp_times_take_the_offset_of_their_own_day():
    assert F.local_time("03/07/2026", "23:59")[0].endswith("-06:00")
    assert F.local_time("03/08/2026", "03:00")[0].endswith("-05:00")
    assert F.local_time("11/15/2026", "00:00")[0] == "2026-11-15T00:00:00-06:00"
    assert F.local_time("11/15/2026", "")[0] == "2026-11-15T00:00:00-06:00"        # a day only: no time invented


def test_9_idaho_county_listing_takes_its_points_side_of_the_salmon_river():
    row = {"level": "Health Advisory", "water": "Example Reservoir", "county": "Idaho", "data_type": "Toxin",
           "collection_date": "10/01/2026", "info": ""}
    south = {H.key("Example Reservoir"): {"name": "Example Reservoir", "tier": None, "shown": None, "lat": 45.0,
                                          "lon": -115.5}}
    state = H.update({}, [row], AT, south)
    assert H.records(state)[0]["raw"]["time_zone"] == "America/Denver"
    north = {H.key("Example Reservoir"): dict(south[H.key("Example Reservoir")], lat=45.93, lon=-116.12)}
    state = H.update({}, [row], AT, north)
    assert H.records(state)[0]["raw"]["time_zone"] == "America/Los_Angeles"


# ------------------------------------------------------------------ 2. an end seen by polling; 3. a reissue

ROW = {"level": "Health Advisory", "water": "Example Lake", "county": "Kootenai", "data_type": "Toxin",
       "collection_date": "06/01/2026", "info": "Avoid contact."}
PT = {H.key("Example Lake"): {"name": "Example Lake", "tier": None, "shown": None, "lat": 47.5, "lon": -116.7}}


def test_2_an_advisory_whose_withdrawal_is_seen_weeks_later_is_not_red_over_the_gap():
    from build import status as S
    from tests.test_status import TEST_RULES
    state = H.update({}, [ROW], "2026-06-02T12:00:00Z", PT)
    state = H.update(state, [ROW], "2026-06-20T12:00:00Z", None)          # last confirmed
    state = H.update(state, [], "2026-08-01T12:00:00Z", None)             # first read after a six-week outage
    r = H.records(state)[0]
    assert r["status"] == "advisory_lifted" and r["raw"]["ended_at_precision"] == "poll"
    assert r["ended_at"] == "2026-08-01T12:00:00Z" and r["raw"]["_last_seen_in_source"] == "2026-06-20T12:00:00Z"
    ivs = S.event_intervals(r, None, datetime(2026, 9, 1, tzinfo=timezone.utc), None, TEST_RULES)
    red = [i for i in ivs if i["color"] == "red"]
    # red stops CONFIRM_DAYS after the last read that listed it; the gap is never red after the fact
    assert red and max(i["end"] for i in red) == datetime(2026, 7, 4, 12, tzinfo=timezone.utc)


def test_3_a_reissue_is_a_new_record_and_never_moves_the_earlier_one():
    state = H.update({}, [ROW], "2026-06-02T12:00:00Z", PT)
    state = H.update(state, [], "2026-06-10T12:00:00Z", None)
    moved = {H.key("Example Lake"): dict(PT[H.key("Example Lake")], lat=47.6, lon=-116.8)}
    state = H.update(state, [dict(ROW, collection_date="09/01/2026")], "2026-09-02T12:00:00Z", moved)
    recs = sorted(H.records(state), key=lambda r: r["started_at"])
    assert len(recs) == 2 and recs[0]["ended_at"] == "2026-06-10T12:00:00Z" and recs[1]["status"] == "advisory_active"
    assert (recs[0]["lat"], recs[0]["lon"]) == (47.5, -116.7) and (recs[1]["lat"], recs[1]["lon"]) == (47.6, -116.8)


def test_4_5_idaho_a_table_with_no_readable_row_fails_and_one_unreadable_row_fails_health(tmp_path, monkeypatch):
    monkeypatch.setattr(H, "STATE_PATH", tmp_path / "state.json")
    out = {}
    monkeypatch.setattr(H, "write_events", lambda sid, recs, **kw: out.update(recs=recs, **kw) or tmp_path)
    head = "".join(f"<th>{h}</th>" for h in H.HEADERS_EXPECTED)
    bad = tmp_path / "bad.html"
    bad.write_text(f"<table><tr>{head}</tr><tr><td>Renamed level</td><td>Example Lake</td><td>Kootenai</td><td>x</td>"
                   "<td>06/01/2026</td><td></td></tr></table>")
    assert H.main(["--file", str(bad), "--at", AT]) == 1 and out["ok"] is False
    assert not (tmp_path / "state.json").exists()                    # nothing saved, nothing ended
    one = tmp_path / "one.html"
    one.write_text(f"<table><tr>{head}</tr><tr><td>Health Advisory</td><td>Example Lake</td><td>Kootenai</td>"
                   "<td>Toxin</td><td>06/01/2026</td><td></td></tr><tr><td>Renamed level</td><td>Other Lake</td>"
                   "<td>Kootenai</td><td>x</td><td>06/01/2026</td><td></td></tr></table>")
    assert H.main(["--file", str(one), "--at", AT]) == 0
    assert out["ok"] is False and out["partial"] is True and len(out["recs"]) == 2
