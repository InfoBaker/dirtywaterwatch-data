"""The City of Houston's monthly SSO reports (ingest/tx_houston_sso_monthly.py).

Fixtures: tx_houston_sso_index.html (Houston Public Works' consent decree page, trimmed to eleven of its document links)
and tx_houston_sso_monthly_pages.json (the text pypdf reads from eight monthly reports, January 2024 to September 2026,
trimmed to a few real rows each, with every house number replaced by an invented 1234; the "Total Number of SSOs" set
to the rows kept; the signing envelope's id replaced by zeros). Page 1 of every report, the cover letter to EPA with
officials' names and e-mail addresses, is not in the fixture (null): the reader never reads it. The map page is null
as pypdf fails on it for some months.
"""
import json
from pathlib import Path

import pytest
import requests

from ingest import tx_houston_sso_monthly as H

FIX = Path(__file__).parent / "fixtures"
PAGES = json.loads((FIX / "tx_houston_sso_monthly_pages.json").read_text())
INDEX = (FIX / "tx_houston_sso_index.html").read_text()


def rep(month):
    r = H.parse_report(PAGES[month]["pages"])
    r.update(url=f"https://www.houstonpublicworks.org/doc/{month}.pdf", title=f"Monthly SSO Report - {month}",
             sha256="x", read_at="2026-11-17T16:00:00Z", last_modified="2026-10-16T18:43:09Z", created=None)
    return r


def recs(month):
    return {r["source_record_id"]: r for r in H.to_records(month, rep(month))}


# ---------------------------------------------------------------- the index

def test_index_reads_the_month_from_the_title_never_the_file_name():
    links = H.report_links(INDEX)
    assert sorted(links) == ["2023-12", "2024-01", "2024-03", "2024-10", "2025-01", "2025-12", "2026-07", "2026-08",
                             "2026-09"]
    assert links["2026-09"]["url"] == ("https://www.houstonpublicworks.org/sites/g/files/nwywnm456/files/doc/"
                                       "005_monthly_sso_report_september_2026.pdf")
    assert links["2024-03"]["url"].endswith("005_monthly_sso_report_march_29_2024.pdf")
    assert links["2024-10"]["url"].endswith("005_monthly_sso_report_october_2024..pdf")
    assert links["2025-01"]["url"].endswith("055_monthly_sso_report_january_2025.pdf")
    assert not any("annual" in v["url"] or "consent_decree" in v["url"] for v in links.values())


# ---------------------------------------------------------------- the table

def test_every_fixture_month_reads_whole_and_matches_its_total():
    for month, doc in PAGES.items():
        r = H.parse_report(doc["pages"])
        assert r["not_read"] == 0, month
        assert r["total_stated"] == len(r["rows"]), month


def test_september_2026_rows_times_volume_and_flag():
    r = recs("2026-09")
    assert len(r) == 7
    g = r["68784"]                      # 4002 GRAUSTARK ST in the report; the house number is not kept
    assert g["event_id"] == "tx-houston-sso-monthly:68784"
    assert g["started_at"] == "2026-09-10T09:33:00-05:00" and g["ended_at"] == "2026-09-10T12:15:00-05:00"
    assert g["time_precision"] == "minute" and g["status"] == "ended"
    assert g["volume_gal"] == 567 and g["volume_text"] == "567 gallons (estimated)" and g["estimate_flag"] == "estimated"
    assert g["outfall_name"] == "GRAUSTARK ST" and g["raw"]["location"] == "GRAUSTARK ST"
    assert g["raw"]["reached_waters_of_us"] == "Yes" and g["raw"]["reached_water"] is True
    assert g["raw"]["flow_location"] == "Storm Sewer (not contained)"
    assert g["raw"]["structure_type"] == "Manhole" and g["raw"]["cause"] == "Grease Blockage"
    assert g["raw"]["average_flow_gpm"] == "4"
    assert g["raw"]["corrective_action"] == "Cleaned and Disinfected; Cleared Main Line"
    assert g["raw"]["tpdes_permit"] == "WQ0010495003" and g["npdes_permit"] is None
    assert g["discharger_id"] == "tx-city-of-houston" and g["raw"]["city"] == "Houston"
    assert g["published_at"] == "2026-10-16T18:43:09Z" and g["fetched_at"] == "2026-11-17T16:00:00Z"
    assert g["reported_at"] is None
    assert g["lat"] is None and g["water_slugs"] == [] and g["waterbody_text"] is None
    assert g["raw"]["_placement"] == "named_water_only" and g["raw"]["time_zone"] == "America/Chicago"
    assert "Paragraph 61" in g["raw"]["legal_basis"] and "4:18-cv-03368" in g["raw"]["legal_basis"]


def test_a_row_that_did_not_reach_water_is_kept_with_the_citys_flag():
    y = recs("2026-09")["68719"]
    assert y["raw"]["reached_waters_of_us"] == "No" and y["raw"]["reached_water"] is False
    assert y["raw"]["flow_location"] == "Contained On Site, not within 5 ft. of Bayou/Surface Water/Drainage Ditch"
    assert "did not reach waters of the United States" in y["raw"]["_no_water_reason"]
    from build import status as S
    assert S.no_water_flag(y) == y["raw"]["_no_water_reason"]
    assert y["raw"]["structure_type"] == "City Cleanout" and y["raw"]["cause"] == "Collection system structural failure"


def test_a_zero_volume_has_no_figure_and_says_why():
    z = recs("2026-09")["68726"]
    assert z["raw"]["volume_as_written"] == "0" and z["volume_gal"] is None and z["estimate_flag"] == "unknown"
    assert "no active overflow" in z["volume_text"]
    assert "could not be calculated" in z["raw"]["volume_note"]
    # its start and end are the City's as given (the minute it was observed)
    assert z["started_at"] == "2026-09-02T08:05:00-05:00" and z["ended_at"] == "2026-09-02T08:06:00-05:00"
    assert rep("2026-09")["notes"]["zero_note"]


def test_rows_continue_across_pages_and_footers_are_skipped():
    r = recs("2026-09")
    assert {"68835", "68838", "68937"} <= set(r)
    assert r["68835"]["outfall_name"] == "N WAYSIDE DR"
    assert not any("Docusign" in json.dumps(x) or "Additional Comments" in json.dumps(x) for x in r.values())


def test_split_words_blank_flag_and_glued_flow():
    m = recs("2026-05")
    assert m["67656"]["raw"]["reached_waters_of_us"] == "Yes"                 # "Ye s"
    assert m["67811"]["ended_at"] == "2026-05-21T21:45:00-05:00"              # "5 /21/2026"
    blank = m["67592"]                                                         # the flag cell left blank
    assert blank["raw"]["reached_waters_of_us"] is None and "reached_water" not in blank["raw"]
    assert "blank" in blank["raw"]["reached_waters_note"]
    assert blank["volume_gal"] == 5850 and blank["outfall_name"] == "SAGEDOWNE LN"
    j = recs("2026-06")
    assert j["68128"]["raw"]["average_flow_gpm"] == "11"                      # "1:00:00 PM11Cleared"
    assert j["68128"]["raw"]["corrective_action"].startswith("Cleared Main Line")
    assert j["68128"]["ended_at"] == "2026-06-25T13:00:00-05:00"


def test_24_hour_clock_non_city_rows_and_values_before_labels():
    r = rep("2024-01")
    assert r["clock24"] is True and r["total_stated"] == 2
    x = recs("2024-01")
    a = x["57707"]                       # "57707" / "NON-COH (14418-" / "001) 2555 WESTHOLLOW DR"
    assert a["raw"]["tpdes_permit"] == "WQ0014418001" and a["raw"]["tpdes_as_written"].startswith("NON-COH")
    assert "NON-COH" in a["raw"]["system_note"] and a["discharger_id"] != "tx-city-of-houston"
    assert "city" not in a["raw"]
    assert a["started_at"] == "2024-01-29T08:25:00-06:00" and a["ended_at"] == "2024-01-29T15:00:00-06:00"
    assert a["outfall_name"] == "WESTHOLLOW DR" and a["volume_gal"] == 1185


def test_permit_forms_of_early_2025():
    f = recs("2025-02")
    assert f["62079"]["raw"]["tpdes_permit"] == "WQ0010495090"
    assert f["62307"]["raw"]["tpdes_permit"] == "WQ0010495002" and "10495-02" in f["62307"]["raw"]["tpdes_note"]
    blank = f["62541"]                                                         # no permit in the cell
    assert blank["raw"]["tpdes_permit"] is None and "no permit" in blank["raw"]["system_note"]
    assert blank["outfall_name"] == "PANNELL ST"
    # the report writes no AM or PM; a time after 12:59 (62087, 14:15) shows its clock is the 24-hour one
    assert rep("2025-02")["clock24"] is True
    assert f["62079"]["started_at"] == "2025-02-01T08:14:00-06:00"
    assert f["62087"]["started_at"] == "2025-02-01T14:15:00-06:00"
    # without such a time the clock is not known: the rows are dated to the day
    r = rep("2025-02")
    r["rows"] = [x for x in r["rows"] if x["sso_id"] != "62087"]
    r["clock24"] = H.parse_report([None] + [p.replace("14:15 2/1/2025 14:16", "x") if p else p
                                            for p in PAGES["2025-02"]["pages"][1:]])["clock24"]
    day = {x["source_record_id"]: x for x in H.to_records("2025-02", r)}["62079"]
    assert day["started_at"] == "2025-02-01" and day["time_precision"] == "day" and "no AM or PM" in day["raw"]["time_note"]


def test_voided_sso_is_left_out_and_named():
    state = {"reports": {"2026-03": rep("2026-03"), "2026-04": rep("2026-04")}}
    records, voided = H.build(state)
    assert "tx-houston-sso-monthly:67077" not in {r["event_id"] for r in records}
    assert voided["67077"]["reported_in"] == "March 2026" and voided["67077"]["noted_in"] == "2026-04"
    assert "154 instead of 155" in voided["67077"]["note"]
    assert len(records) == 2


def test_act_of_god_exhibit_is_kept_on_its_row():
    r = recs("2024-07")["59533"]
    assert r["raw"]["act_of_god_defense"]["as_written"] == "Power Outage Hurricane Beryl"
    assert "7.251" in r["raw"]["act_of_god_defense"]["basis"]
    assert r["volume_gal"] == 46800


def test_house_numbers_never_kept():
    for month in PAGES:
        for r in recs(month).values():
            text = json.dumps(r)
            assert "1234" not in text, (month, r["source_record_id"])


@pytest.mark.parametrize("cell,street", [
    ("1234 MAIN ST", "MAIN ST"), ("1234A MAIN ST", "MAIN ST"), ("1234 1/2 MAIN ST", "MAIN ST"),
    ("1234-B MAIN ST", "MAIN ST"), ("1234 W 18TH ST", "W 18TH ST"), ("1234 FM 1960 RD", "FM 1960 RD"),
    ("1234 HIGHWAY 6", "HIGHWAY 6"), ("1234 MAIN ST & 5678 ELM ST", "MAIN ST & ELM ST"), ("W 34TH ST", "W 34TH ST"),
])
def test_street_of_strict_house_number_drop(cell, street):
    assert H.street_of(cell) == street


def test_clock_and_time_rules():
    assert H._clock("8:30:00 AM") == (8, 30, True) and H._clock("12:15:00 PM") == (12, 15, True)
    assert H._clock("12:05 AM") == (0, 5, True) and H._clock("15:00") == (15, 0, False)
    assert H._clock("25:00") is None and H._clock("13:00 PM") is None
    # a time with no AM or PM in a report whose clock is not known is dated to the day
    row = {"start_day": "2026-03-02", "start_clock": [8, 30], "start_ampm": False, "start_as_written": "3/2/2026 8:30"}
    t, why = H._when(row, "start", clock24=False)
    assert t is None and "no AM or PM" in why
    # the hour skipped when daylight time begins (2026-03-08 02:30 in Houston)
    row = {"start_day": "2026-03-08", "start_clock": [2, 30], "start_ampm": True, "start_as_written": "3/8/2026 2:30 AM"}
    assert H._when(row, "start", clock24=False)[0] is None


def test_an_end_before_the_start_is_not_used():
    r = rep("2026-09")
    row = dict(r["rows"][0])
    row["end_clock"] = [7, 0]
    row["end_as_written"] = "9/1/2026 7:00:00 AM"
    r["rows"] = [row]
    x = H.to_records("2026-09", r)[0]
    assert x["ended_at"] is None and x["status"] == "unknown" and "before the start" in x["raw"]["end_note"]


def test_two_rows_run_together_are_not_read():
    text = ("68719 WQ0010495002 1234 YELLOWSTONE BLVD Storm Sewer (not contained) Yes 0 Manhole Grease Blockage 9/1/2026 "
            "8:30:00 AM 9/1/2026 8:31:00 AM 0 Cleaned 68720 1234 ELM ST Storm Sewer (not contained) Yes 0 Manhole "
            "Grease Blockage 9/1/2026 8:30:00 AM 9/1/2026 8:31:00 AM 0 Cleaned")
    assert H.parse_row(text) is None


def test_no_table_or_no_totals_is_a_read_error():
    with pytest.raises(H.ReadError):
        H.parse_report([None, "a letter", None])
    pages = [None, PAGES["2026-09"]["pages"][1]]            # the first table page alone: no totals block
    with pytest.raises(H.ReadError):
        H.parse_report(pages)
    with pytest.raises(H.ReadError):                         # a table page pypdf could not read
        H.parse_report([None, PAGES["2026-09"]["pages"][1], None, PAGES["2026-09"]["pages"][3]])


# ---------------------------------------------------------------- one event, one record

def tceq_rec(eid, day, permits, vol, name=None, water=None, did="tx-city-of-houston"):
    return {"event_id": f"tx-tceq-sso-opendata:{eid}", "source_id": "tx-tceq-sso-opendata", "source_record_id": eid,
            "event_type": "sso", "started_at": f"{day}T00:00:00-05:00", "reported_at": f"{day}T00:00:00-05:00",
            "discharger_id": did, "volume_gal": vol, "outfall_name": name, "waterbody_text": water,
            "duplicate_of": None, "raw": {"state_permits": permits, "county": "Harris County",
                                          "_placement": "named_water_only"}}


def test_link_tceq_by_system_day_street_and_volume():
    records = list(recs("2026-09").values())
    tceq = [tceq_rec("1", "2026-09-10", ["WQ0010495090"], 567, "Manhole at [house number removed] Graustark St"),
            tceq_rec("2", "2026-09-10", ["WQ0010495003"], 567, "Manhole at [house number removed] Yoakum Blvd"),
            tceq_rec("3", "2026-09-01", ["WQ0010495002"], 0, "City Cleanout",
                     water="Contained On Site, not within 5 ft. of Bayou/Surface Water/ Drainage Ditch")]
    links = H.link_tceq(records, tceq)
    by = {r["source_record_id"]: r for r in records}
    # another of the City's permits in TCEQ's record, the same street, day and volume: one overflow
    assert by["68784"]["raw"]["tceq_record"] == "tx-tceq-sso-opendata:1"
    assert tceq[0]["duplicate_of"] == "tx-houston-sso-monthly:68784"
    assert tceq[0]["raw"]["_duplicate_basis"].startswith(H.LINK_BASIS)
    assert by["68784"]["raw"]["_other_source_record"] == "tx-tceq-sso-opendata:1"
    assert by["68784"]["raw"]["county"] == "Harris County"
    assert "same City system" in by["68784"]["raw"]["tceq_match"]["basis"]
    # a different street: never linked
    assert tceq[1]["duplicate_of"] is None
    # TCEQ gives no street, its permit, day and a placeholder volume: not linked on so little
    assert tceq[2]["duplicate_of"] is None and links["linked"] == 1


def test_link_tceq_takes_the_named_water_and_never_a_conflicting_one():
    records = list(recs("2026-09").values())
    tceq = [tceq_rec("1", "2026-09-10", ["WQ0010495003"], 567, "[house number removed] GRAUSTARK ST, HOUSTON, TX 77006",
                     water="Brays Bayou"),
            tceq_rec("2", "2026-09-01", ["WQ0010495002"], 0, "[house number removed] YELLOWSTONE 77021 (1,1) / City "
                                                             "Cleanout", water="Brays Bayou")]
    links = H.link_tceq(records, tceq)
    by = {r["source_record_id"]: r for r in records}
    assert by["68784"]["waterbody_text"] == "Brays Bayou" and "TCEQ's record" in by["68784"]["raw"]["water_basis"]
    # the City says the overflow reached no water and TCEQ names one: both stand (err on the side of safety)
    assert tceq[1]["duplicate_of"] is None and "tceq_record" not in by["68719"]["raw"]
    assert links["not linked: the City says no water was reached, TCEQ names one"] == 1
    # a second run clears and recomputes: the same result, nothing doubled
    records2 = list(recs("2026-09").values())
    H.link_tceq(records2, tceq)
    assert tceq[0]["duplicate_of"] == "tx-houston-sso-monthly:68784"


def test_link_tceq_segment_number_is_not_a_water_and_other_systems_need_their_permit():
    def tq():
        return [tceq_rec("1", "2024-01-29", ["WQ0014418001"], 1185, "[house number removed] Westhollow Dr",
                         water="1007 of the San Jacinto River Basin", did="tx-chelford-city-mud"),
                tceq_rec("2", "2024-01-29", ["WQ0010495002"], 1185, "[house number removed] Westhollow Dr")]
    # the report's two NON-COH rows (57707, 57770) are at one street, that day, 1,185 gallons each: TCEQ's one record
    # of that permit fits both, so neither is linked
    both = list(recs("2024-01").values())
    tceq = tq()
    assert H.link_tceq(both, tceq)["not linked: two equally good candidates"] == 2 and tceq[0]["duplicate_of"] is None
    one = [recs("2024-01")["57707"]]
    tceq = tq()
    links = H.link_tceq(one, tceq)
    assert links["linked"] == 1 and one[0]["raw"]["tceq_record"] == "tx-tceq-sso-opendata:1"
    assert one[0]["waterbody_text"] is None              # a segment number is no water's name
    assert one[0]["raw"]["tceq_match"]["tceq_water_text"] == "1007 of the San Jacinto River Basin"
    assert tceq[1]["duplicate_of"] is None                # a City permit never stands for a NON-COH system


def test_link_tceq_tie_of_unlike_records_links_neither():
    records = list(recs("2026-09").values())
    tceq = [tceq_rec("1", "2026-09-10", ["WQ0010495003"], 567, "[house number removed] Graustark St", water="Brays Bayou"),
            tceq_rec("2", "2026-09-10", ["WQ0010495003"], 567, "[house number removed] Graustark St",
                     water="Buffalo Bayou")]
    links = H.link_tceq(records, tceq)
    assert links["linked"] == 0 and links["not linked: two equally good candidates"] == 1


# ---------------------------------------------------------------- runs

class Resp:
    def __init__(self, text=None, content=None, status=200, headers=None):
        self.text, self.content, self.status_code = text, content, status
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code}", response=self)


def _fake_pages(content):
    return PAGES[content.decode()]


def _get(calls, fail=()):
    def get(url, headers=None):
        calls.append((url, dict(headers or {})))
        if url == H.INDEX:
            return Resp(text=INDEX)
        if headers and headers.get("If-Modified-Since"):
            return Resp(status=304)
        for month, name in (("2026-09", "september_2026"), ("2026-08", "august_2026"), ("2026-07", "july_2026"),
                            ("2024-01", "january_2024")):
            if name in url and month not in fail:
                return Resp(content=month.encode() if month in PAGES else b"2026-06",
                            headers={"Last-Modified": "Fri, 16 Oct 2026 18:43:09 GMT"})
        return Resp(status=503)
    return get


def test_run_hourly_reads_the_newest_and_asks_again_with_a_conditional_request(tmp_path):
    calls = []
    out, st = tmp_path / "ev.json", tmp_path / "st.json"
    tq = tmp_path / "tceq.json"
    tq.write_text(json.dumps({"ok": True, "records": [tceq_rec("1", "2026-09-10", ["WQ0010495003"], 567,
                                                               "Manhole at [house number removed] Graustark St")]}))
    assert H.run("2026-11-17T16:00:00Z", st, out, get=_get(calls), tceq_path=tq, pages_of=_fake_pages) == 0
    doc = json.loads(out.read_text())
    assert doc["ok"] is True
    assert sorted(doc["meta"]["reports_read"]) == ["2026-07", "2026-08", "2026-09"]     # the newest three only
    assert "2024-01" in doc["meta"]["listed_not_read"] and "2023-12" not in doc["meta"]["listed_not_read"]
    assert doc["meta"]["reports_read"]["2026-09"]["last_modified"] == "2026-10-16T18:43:09Z"
    assert doc["meta"]["tceq_links"]["linked"] == 1
    t = json.loads(tq.read_text())
    assert t["records"][0]["duplicate_of"] == "tx-houston-sso-monthly:68784" and t["meta"]["houston_monthly_links"]
    # the next hour: a conditional request each, answered 304; nothing read again, the records the same
    calls.clear()
    assert H.run("2026-11-17T17:00:00Z", st, out, get=_get(calls), tceq_path=tq, pages_of=_fake_pages) == 0
    assert all(h.get("If-Modified-Since") == "Fri, 16 Oct 2026 18:43:09 GMT" for u, h in calls if u != H.INDEX)
    assert json.loads(out.read_text())["count"] == doc["count"]


def test_run_backfill_reads_from_2024_and_exits_0_naming_what_failed(tmp_path):
    calls = []
    out = tmp_path / "ev.json"
    code = H.run("2026-11-17T16:00:00Z", tmp_path / "st.json", out, get=_get(calls), backfill=True, tceq_path=None,
                 pages_of=_fake_pages)
    assert code == 0
    doc = json.loads(out.read_text())
    asked = [u for u, _ in calls if u != H.INDEX]
    assert len(asked) == 8 and not any("december_2023" in u for u in asked)            # January 2024 onward
    assert doc["ok"] is False and "2025-01" in doc["meta"]["pending"]                   # 503: named, retried
    assert "HTTP 503" in doc["meta"]["pending"]["2025-01"]["reason"]
    assert "2024-01" in doc["meta"]["reports_read"]
    # the hourly run that follows retries the pending months and fails while one stays unread
    assert H.run("2026-11-17T17:00:00Z", tmp_path / "st.json", out, get=_get([]), tceq_path=None,
                 pages_of=_fake_pages) == 1


def test_index_failure_keeps_the_records_and_errors_carry_no_row_text(tmp_path):
    out, st = tmp_path / "ev.json", tmp_path / "st.json"
    H.run("2026-11-17T16:00:00Z", st, out, get=_get([]), tceq_path=None, pages_of=_fake_pages)
    n = json.loads(out.read_text())["count"]
    assert H.run("2026-11-17T17:00:00Z", st, out, get=lambda u, h=None: Resp(status=403), tceq_path=None) == 1
    doc = json.loads(out.read_text())
    assert doc["ok"] is False and doc["count"] == n and "HTTP 403" in doc["error"]
    assert H.run("2026-11-17T18:00:00Z", st, out, get=lambda u, h=None: Resp(text="<html></html>"), tceq_path=None) == 1

    def bad_pages(content):
        raise ValueError("1234 MAIN ST was in this message")
    calls = []
    H.run("2026-11-17T19:00:00Z", tmp_path / "st2.json", tmp_path / "ev2.json", get=_get(calls), tceq_path=None,
          pages_of=bad_pages)
    doc = json.loads((tmp_path / "ev2.json").read_text())
    assert "1234" not in json.dumps(doc) and "could not be read (ValueError)" in json.dumps(doc["meta"]["pending"])


def test_a_lost_state_keeps_the_earlier_records(tmp_path):
    out, st = tmp_path / "ev.json", tmp_path / "st.json"
    H.run("2026-11-17T16:00:00Z", st, out, get=_get([]), backfill=True, tceq_path=None, pages_of=_fake_pages)
    before = {r["event_id"] for r in json.loads(out.read_text())["records"]}
    st.unlink()
    H.run("2026-11-17T17:00:00Z", st, out, get=_get([]), tceq_path=None, pages_of=_fake_pages)
    doc = json.loads(out.read_text())
    assert {r["event_id"] for r in doc["records"]} == before
    assert "2024-01" in doc["meta"]["retained_from_previous_events"]


def test_a_revision_that_reads_less_fully_keeps_the_held_copy():
    state = {}
    month, info = "2026-09", {"url": "https://x/s.pdf", "title": "t"}
    assert H.read_report(state, month, info, b"a", "t1", None, pages_of=lambda c: PAGES["2026-09"]) == "new"
    worse = json.loads(json.dumps(PAGES["2026-09"]))
    worse["pages"][1] = worse["pages"][1].replace("Yes 567", "Maybe 567")
    assert H.read_report(state, month, info, b"b", "t2", None, pages_of=lambda c: worse) == "kept"
    assert state["reports"][month]["sha256"] == __import__("hashlib").sha256(b"a").hexdigest()
    assert H.read_report(state, month, info, b"a", "t3", None, pages_of=lambda c: PAGES["2026-09"]) == "same"


def test_detail_fields_and_both_records_reach_each_other():
    from export import detail as D
    records = list(recs("2026-09").values())
    tceq = [tceq_rec("1", "2026-09-10", ["WQ0010495003"], 567, "Manhole at [house number removed] Graustark St")]
    H.link_tceq(records, tceq)
    by = {r["source_record_id"]: r for r in records}
    d = D.detail_of(by["68784"])
    assert d == {"report_kind": "Monthly SSO Report", "cause": "Grease Blockage", "overflow_point": "Manhole",
                 "town": "Houston", "volume_qualifier": "estimated"}
    z = D.detail_of(by["68726"])
    assert "volume_qualifier" not in z and z["volume_method"].startswith("Where estimated volume and average flow")
    links = D.links_of(records + tceq)
    assert links["tx-houston-sso-monthly:68784"]["linked_records"][0] == {
        "event_id": "tx-tceq-sso-opendata:1", "relation": "other_source", "source_id": "tx-tceq-sso-opendata"}
    assert links["tx-tceq-sso-opendata:1"]["linked_records"][0]["event_id"] == "tx-houston-sso-monthly:68784"


def test_corrective_actions_split_by_pypdf_are_written_as_the_city_writes_them():
    assert H.actions("Cleaned and D isinfected; Cleared M ain Line; Throttled down a lift station") == (
        "Cleaned and Disinfected; Cleared Main Line; Throttled down a lift station")
    assert H.actions("") is None


@pytest.fixture(autouse=True)
def monthly_transport_only(monkeypatch):
    """These existing cases isolate the PDF/link transport; history paging has its own integration tests."""
    monkeypatch.setattr(H, "read_history", lambda held, at, get: held)
