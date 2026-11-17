"""The City of Memphis's consent-decree quarterly SSO reports (ingest/tn_memphis_cd_quarterly.py).

Fixtures: tn_memphis_cd_index.html (the reports index, trimmed to its quarterly links and one semi-annual link) and
tn_memphis_cd_quarterly_pages.json (the text pypdf reads from the Q2 2026 and Q1 2023 reports, trimmed to a few
real rows with every house number replaced by 100; the certification page's name removed).
"""
import json
from pathlib import Path

import pytest

from ingest import tn_memphis_cd_quarterly as M

FIX = Path(__file__).parent / "fixtures"
PAGES = json.loads((FIX / "tn_memphis_cd_quarterly_pages.json").read_text())
INDEX = (FIX / "tn_memphis_cd_index.html").read_text()


def recs(key, quarter, period):
    rep = M.parse_report(PAGES[key])
    rep.update(url=f"https://sarp10.com/wp-content/uploads/2026/07/{key}.pdf", period=period, read_at="2026-11-17T12:00:00Z")
    return rep, {r["source_record_id"]: r for r in M.to_records(quarter, rep)}


def test_index_lists_quarterly_reports_only():
    links = M.report_links(INDEX)
    assert links["2026Q2"]["period"] == ["2026-04-01", "2026-06-30"]
    assert links["2026Q2"]["url"].endswith("07.24.26-Quarterly-Report-Q2-2026-Memphis.pdf")
    assert links["2023Q1"]["period"] == ["2023-01-01", "2023-03-31"]
    assert not any("SemiAnnual" in v["url"] for v in links.values())
    # the older titles without the first year ("October 1 through December 31, 2020") read too
    old = M.report_links('<a href="/a.pdf">City of Memphis Quarterly Report- October 1 through December 31, 2020</a>')
    assert old["2020Q4"]["period"] == ["2020-10-01", "2020-12-31"]
    assert old["2020Q4"]["url"] == "https://sarp10.com/a.pdf"


def test_rows_read_and_footnotes():
    rep = M.parse_report(PAGES["q2_2026"])
    assert rep["not_read"] == 0 and len(rep["rows"]) == 9
    assert rep["ampm"] is True and rep["signed"] is None          # the Q2 2026 certification date is blank
    assert set(rep["notes"]) == {"?", "*", "**", "†"}
    assert rep["notes"]["*"].startswith("These overflows are believed to have reached a storm sewer inlet")
    assert "locations" in rep["notes"]["†"]                      # the font ligature read as letters
    assert M.parse_report(PAGES["q1_2023"])["signed"] == "2023-04-28"


def test_times_volume_end_and_water():
    _, r = recs("q2_2026", "2026Q2", ["2026-04-01", "2026-06-30"])
    pate = r["2026Q2:2026-04-27T0300PM:PATERD"]
    assert pate["started_at"] == "2026-04-27T15:00:00-05:00" and pate["time_precision"] == "minute"
    assert pate["ended_at"] == "2026-04-28T14:30:00-05:00" and pate["status"] == "ended"   # 23.5 hours, the report's
    assert pate["waterbody_text"] == "Fletcher Creek" and pate["raw"]["_placement"] == "named_water_only"
    assert pate["raw"]["flags_as_written"] == ["YES", "NO", "NO"]
    assert pate["volume_gal"] == 260000 and pate["estimate_flag"] == "estimated"
    assert pate["outfall_name"] == "[house number removed] PATE RD"
    assert pate["discharger_id"] == "tn-memphis" and pate["lat"] is None and pate["water_slugs"] == []
    assert pate["published_at"] is None and pate["fetched_at"] == "2026-11-17T12:00:00Z"
    assert pate["raw"]["report_posted_folder"] == "2026-07"
    # a two-digit year
    assert r["2026Q2:2026-04-29T0700AM:AMERICANWAY"]["volume_gal"] == 14200000


def test_bare_time_in_ampm_report_is_a_day():
    _, r = recs("q2_2026", "2026Q2", ["2026-04-01", "2026-06-30"])
    c = r["2026Q2:2026-04-29T0149:CHICKASAWCOVE"]
    assert c["time_precision"] == "day" and c["started_at"] == "2026-04-29T00:00:00-05:00"
    assert "no AM or PM" in c["raw"]["time_note"]
    assert c["ended_at"] == "2026-04-30T00:00:00-05:00"          # the latest day 5.2 hours allows


def test_marked_rows_name_no_water_and_keep_the_citys_words():
    _, r = recs("q2_2026", "2026Q2", ["2026-04-01", "2026-06-30"])
    star = r["2026Q2:2026-06-18T0236PM:FORRESTAVE"]
    assert star["waterbody_text"] is None and star["raw"]["reach_mark"] == "*"
    assert "unable to determine" in star["raw"]["reach_note"]
    assert "reached_water" not in star["raw"]               # the City does not say it reached no water
    base = r["2026Q2:2026-06-13T1200PM:SYCAMOREVIEWRD"]
    assert base["raw"]["overflow_source"] == "BASEMENT" and base["waterbody_text"] is None


def test_24_hour_report_and_midnight():
    rep, r = recs("q1_2023", "2023Q1", ["2023-01-01", "2023-03-31"])
    assert rep["ampm"] is False and rep["not_read"] == 0
    a = r["2023Q1:2023-01-02T1525:CHICKASAWCV"]
    assert a["started_at"] == "2023-01-02T15:25:00-06:00" and a["volume_text"] == "354.76 gallons (estimated)"
    assert a["ended_at"] == "2023-01-02T17:35:00-06:00"          # 2.16 hours rounded up to the minute
    assert r["2023Q1:2023-01-03T0928:CINCINNATIPERSON"]["waterbody_text"] == "CANE CREEK"
    assert r["2023Q1:2023-01-03T1707:NPKWY"]["raw"]["overflow_source"] == "4 AND 6"
    mid = r["2023Q1:2023-03-03T0000:JONETTA"]
    assert mid["time_precision"] == "day" and "0:00" in mid["raw"]["time_note"]


def test_house_and_suite_numbers_never_kept():
    pages = ["x", "y", PAGES["q2_2026"][2].replace("100 PATE RD", "3287 AUSTIN PEAY HIGHWAY STE 101")]
    rows = M.parse_report(pages)["rows"]
    loc = [r["location"] for r in rows if "AUSTIN" in (r["location"] or "")][0]
    assert "3287" not in loc and "101" not in loc and "STE" not in loc


def test_broken_time_line_and_unread_row_counted_never_quoted():
    page = PAGES["q2_2026"][2].replace("6/18/2026 2:36PM", "6/18/2026 2:\n36PM")
    rep = M.parse_report(["x", "y", page])
    assert rep["not_read"] == 0 and any(r["date"] == "2026-06-18" and r["time"] == "2:36" for r in rep["rows"])
    bad = PAGES["q2_2026"][2].replace("GREASE 798 M/L 1.3 ?", "GREASE")
    rep = M.parse_report(["x", "y", bad])
    assert rep["not_read"] == 1 and len(rep["rows"]) == 8
    assert "COOPER" not in json.dumps(rep)


def test_no_table_is_a_read_error():
    with pytest.raises(M.ReadError):
        M.parse_report(["City of Memphis", "Quarterly Report"])


def test_date_outside_quarter_noted():
    page = PAGES["q2_2026"][2].replace("4/2/2026", "3/30/2026")
    rep = M.parse_report(["x", "y", page])
    rep.update(url="u", period=["2026-04-01", "2026-06-30"])
    r = [x for x in M.to_records("2026Q2", rep) if x["started_at"].startswith("2026-03-30")][0]
    assert "outside the report's quarter" in r["raw"]["date_note"]


class Resp:
    def __init__(self, text=None, content=None, status=200):
        self.text, self.content, self.status_code = text, content, status

    def raise_for_status(self):
        if self.status_code >= 400:
            import requests
            raise requests.HTTPError(f"{self.status_code}")


def _fake_pdf(monkeypatch):
    monkeypatch.setattr(M, "pdf_pages", lambda content: PAGES[content.decode()])


def test_run_hourly_reads_newest_and_names_failures(tmp_path, monkeypatch):
    _fake_pdf(monkeypatch)
    calls = []

    def get(url):
        calls.append(url)
        if url == M.INDEX:
            return Resp(text=INDEX)
        if "Q2-2026" in url:
            return Resp(content=b"q2_2026")
        return Resp(status=503)
    out = tmp_path / "ev.json"
    assert M.run("2026-11-17T12:00:00Z", tmp_path / "st.json", out, get=get, tdec=[]) == 0
    doc = json.loads(out.read_text())
    assert doc["ok"] is True and doc["count"] == 9
    assert set(doc["meta"]["pending"]) == {"2026Q1"}               # the newest two only, hourly
    assert "2023Q1" in doc["meta"]["listed_not_read"]
    assert len(calls) == 3
    # the next run tries the pending report again and not the one read
    calls.clear()
    M.run("2026-11-17T13:00:00Z", tmp_path / "st.json", out, get=get, tdec=[])
    assert [c for c in calls if c != M.INDEX] == [M.report_links(INDEX)["2026Q1"]["url"]]


def test_run_backfill_reads_from_2023_only(tmp_path, monkeypatch):
    _fake_pdf(monkeypatch)
    calls = []

    def get(url):
        calls.append(url)
        return Resp(text=INDEX) if url == M.INDEX else Resp(content=b"q1_2023")
    assert M.run("2026-11-17T12:00:00Z", tmp_path / "st.json", tmp_path / "ev.json", get=get, backfill=True,
                 tdec=[]) == 0
    assert len(calls) == 1 + 14 and not any("2022" in c for c in calls[1:] if "2023/01" in c)


def test_index_failure_is_unhealthy_and_keeps_records(tmp_path, monkeypatch):
    _fake_pdf(monkeypatch)
    out = tmp_path / "ev.json"
    ok = lambda u: Resp(text=INDEX) if u == M.INDEX else Resp(content=b"q2_2026")
    M.run("2026-11-17T12:00:00Z", tmp_path / "st.json", out, get=ok, tdec=[])
    assert M.run("2026-11-17T13:00:00Z", tmp_path / "st.json", out, get=lambda u: Resp(status=403), tdec=[]) == 1
    doc = json.loads(out.read_text())
    assert doc["ok"] is False and doc["count"] == 18
    assert M.run("2026-11-17T14:00:00Z", tmp_path / "st.json", out, get=lambda u: Resp(text="<html></html>"),
                 tdec=[]) == 1


def test_link_tdec_same_day_and_street():
    rep, r = recs("q2_2026", "2026Q2", ["2026-04-01", "2026-06-30"])
    records = list(r.values())
    tdec = [{"event_id": "tn-tdec-events-report:x", "npdes_permit": "TN0020711", "started_at": "2026-04-27",
             "outfall_name": "PATE RD, MEMPHIS", "raw": {"_outfall_name_basis": "street"}},
            {"event_id": "tn-tdec-events-report:y", "npdes_permit": "TN0099999", "started_at": "2026-05-12",
             "outfall_name": "N HOMER ST", "raw": {"_outfall_name_basis": "street"}}]
    links = M.link_tdec(records, tdec)
    assert links["linked"] == 1
    assert r["2026Q2:2026-04-27T0300PM:PATERD"]["duplicate_of"] == "tn-tdec-events-report:x"


def test_ids_stable_and_distinct():
    rep = M.parse_report(PAGES["q2_2026"])
    ids = M.row_ids(rep["rows"] + rep["rows"][:1], "2026Q2")
    assert len(set(ids)) == len(ids) and ids[-1].endswith("~2")


def test_layout_variants_read_or_counted():
    head = PAGES["q2_2026"][2].split("\n")[:5]
    rows = ["100 VANCE 10/01/2024, 10:01 AM GREASE 100 M/L 32.2 *",
            "100 COOPER ST 10/20/2025,11:02 AM BROKEN 2315 M/L 7.7 *",
            "100 GALLOWAY DR 10/17/2024, 5:33 AM GREASE & PAPER 100 M/L 9 NO",
            "100 DEBBY DR 7/7/2024 9:48 GREASE 2310 M/L 7.7 ** NO NO",
            "100 AUBURN RD 4/25/2024 9:30 GREASE/RAGS/MUD/ROCKS 300 M/L 5?",
            "100 HEALEY RD 5/7/2023 21:36 GREASE/SAND/DEBRIS 1,572 M/L 13.1 BLACK BAYOU YES",
            "100 SCOTT ST 1/8/2026 1:00:00 PM MUD 100 M/L 9.25 *",
            # two events in one row, the next row's address on this line, a stream with no flag: counted, not read
            "100 BUTTERNUT COVE 5/11/2023 20:12 5/13/2023 16:00 BYPASS MALFUNCTION 34200 40500 M/L 3.8 4.5 FLETCHER CREEK YES",
            "100 UNION AVE 10/14/2023 12:00 PAPER 930 M/L 2.2 * 100 W WESLEY FOREST PL",
            "100 W Dianne Cir 12/27/2023 8:49 GREASE/RAGS 879 M/L 2.93 CANE CREEK **"]
    rep = M.parse_report(["x", "y", "\n".join(head + rows)])
    assert rep["not_read"] == 3 and len(rep["rows"]) == 7
    by = {r["location"].split("] ")[-1]: r for r in rep["rows"]}
    assert by["VANCE"]["time"] == "10:01" and by["VANCE"]["ampm"] == "AM"
    assert by["COOPER ST"]["time"] == "11:02"
    assert by["GALLOWAY DR"]["flags"] == ["NO"] and by["GALLOWAY DR"]["water"] is None
    assert by["DEBBY DR"]["mark"] == "**" and by["DEBBY DR"]["flags"] == ["NO", "NO"]
    assert by["AUBURN RD"]["mark"] == "?" and by["AUBURN RD"]["duration"] == "5"
    assert by["HEALEY RD"]["water"] == "BLACK BAYOU" and by["HEALEY RD"]["volume"] == "1,572"
    assert by["SCOTT ST"]["time"] == "1:00" and by["SCOTT ST"]["ampm"] == "PM"
    assert "WESLEY" not in json.dumps(rep)


def test_certification_date_before_quarter_end_is_not_the_publication_date():
    rep = M.parse_report(PAGES["q1_2023"])
    rep.update(url="u", period=["2023-01-01", "2023-03-31"])
    assert M.to_records("2023Q1", rep)[0]["published_at"] == "2023-04-28"
    rep["signed"] = "2023-03-29"
    r = M.to_records("2023Q1", rep)[0]
    assert r["published_at"] is None and r["raw"]["report_signed_on"] == "2023-03-29"
    assert "before the quarter ended" in r["raw"]["published_note"]
