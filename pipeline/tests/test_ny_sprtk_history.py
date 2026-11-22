"""New York: DEC's older SPRTK workbook, 2013 to August 2021 (pipeline/ingest/ny_sprtk_history.py).
The workbooks are synthetic, built here in the file's four layouts with invented facilities, permits and people; the
texts planted in the narrative columns must never reach a record or the saved raw page.
Run from pipeline/: python -m pytest tests/test_ny_sprtk_history.py -q
"""
from __future__ import annotations

import io
import json
import zipfile
from datetime import UTC, date, datetime, timedelta
from xml.sax.saxutils import escape

import pytest

import common
from common import event
from ingest import ny_sprtk as S
from ingest import ny_sprtk_history as M

# the review's planted texts (Astra 2026-11-22 P1-1): uncued names, capital variants, a phone typed as ten digits
PLANTS = ["Jane Roe repaired the pump.", "operator jane roe inspected the spill.", "JANE ROE responded.",
          "Staff callback: 5185550142."]
P1, P2, P3, P4 = PLANTS

REPORT_HDR = ["Discovery Date and Time", "Facility Name", "Closest Address or Landmark", "Town/City", "County",
              "Estimate or Actual", "Volume", "Treated State", "Other Explained", "Ending Date and Time",
              "Expected Ending Date and Time", "Duration_Hours and Minutes", "Corrective Actions", "Receiving Water Body",
              "Reason For Discharge", "Other Explanation"]
ALERT15_HDR = ["Organization(Facility)", "Facility ID", "Date of Discharge", "Time of Discharge", "Location of Discharge",
               "Additional Address Info", "Name of Waterbody Affected", "Description of Discharge", "Duration of Discharge",
               "Reason for Discharge", "Description", "Volume or Rate of Discharge", "Units", "Estimate/Actual"]
ALERT16_HDR = ["facility_name", "sprtk_id", "start_time", "duration", "address", "city", "zipcode", "location_desc",
               "affectd_water_body", "treated_state", "quantity", "volume_rate_units", "estimated_ind",
               "reason for discharge1", "reason description1", "discharge_desc", "additional_instrctns"]
ALERT18_HDR = ["facility name", "sprtk id", "start time", "headline", "duration", "units", "address", None, "city",
               "county", "location description", "affected water body", "treated state", "quantity", None,
               "estimated indicator", "reasons for discharge", None, None, "reason description", "discharge description",
               "additional instructions"]


def a18(start, headline="Erie, Sampleton, Sewage Discharge, Sample Creek, Unknown", water="Sample Creek",
        fac="Sampleton (V) WWTP NY0999903", fid="NY0999903", qty="65", reason="Weather Conditions",
        street=("12", "Harbor Rd")):
    """An alert18 row; every narrative column holds a planted text, and so does an unnamed column past the header."""
    return [fac, fid, start, headline, "24", "Hours", street[0], street[1], "Sampleton", "Erie", P4, water,
            "Untreated", qty, "Gallons per Minute", "Estimated", reason, None, None, P1, P2, P3, P1]


def report(start, end=None, expected=None, estimate="Estimate", volume="1000"):
    return [start, "Sampleton (V) WWTP", "Sample Pump Station", "Sampleton", "Erie", estimate, volume, "Untreated", P2,
            end, expected, "1:30" if end else None, P3, "Sample Creek", "Blockage;", P1]


def workbook(*, short=False, extra_tab=False, cut=False) -> bytes:
    tabs = [
        ("PDFs through May 2015", [
            ["SPRTK Discharge Report Summary"], ["Updated 10/29/15"], REPORT_HDR,
            report("2014/08/13 10:30 AM", end="08/13/2014 12:00 PM"),
            report("2014/09/01 08:00 AM", expected="09/02/2014 08:00 AM", estimate="Unknown", volume=None),
            report("2014/10/01 09:00 AM", end="10/1/2014 :"),            # the end's date only, the same day
            report("2014/10/05 09:00 AM", end="10/06/2014"),             # the end's date only, the next day
        ]),
        ("NYAlerts Through 5_10_16", [
            ["UPDATED 5/10/16"], ALERT15_HDR,
            ["Example Falls WWTP,", "NY0999902", "42286", "07:25:0", "1 Example Road, Example Falls, NY", P1,
             "Example River", P2, "6.0 hours ended.", ", Weather Conditions, ,", P3, "500", "Gallons Per Minute",
             "(Estimated)", "Untreated", P4],
            ["Example Falls WWTP", "NY0999902", "42290", "08:00", "1 Example Road, Example Falls, NY", None,
             "Example River", None, "2.0 hours ended.", "Blockage", "10000 Gallons"],   # the volume under Description
            [None, None, "01/06/2016", "3:00 AM", f"r{P1}"],                            # a fragment, no facility
        ]),
        ("NYALERTS May2017 thru July2017", [
            ALERT16_HDR,
            ["Example Falls WWTP", "NY0999902", "18/JUN/2017 15:25:00", "2", "1 Example Road", "Example Falls", "14000",
             P1, "Example River", "Untreated", "300", "Gallons", "0", "Weather Conditions", P2, P3, P4],
        ]),
        ("NYALERTS NOVEMBER 2018", [ALERT18_HDR, a18("17/NOV/2014 01:00:00")]),
        ("NYALERTS DECEMBER 2018", [ALERT18_HDR, a18("21/DEC/2018 04:15:00")]),
        ("NYALERTS MARCH 2019", [ALERT18_HDR, a18("09/MAR/2019 21:30:00"), a18("09/MAR/2019 22:30:00")]),  # spring
        ("NYALERTS JUNE 2019", [
            ALERT18_HDR,
            a18("21/JUN/2019 10:00:00"),
            a18("21/JUN/2019 10:00:00", headline="UPDATE: Erie, Sampleton, Sewage Discharge, Sample Creek, Unknown",
                qty="70"),
            a18("21/JUN/2019 10:00:00", headline="ENDED: Erie, Sampleton, Sewage Discharge, Sample Creek, Unknown",
                qty="0"),
            a18("21/JUN/2019 10:00:00"),                          # a copy of the first row
        ] + ([a18("22/JUN/2019 10:00:00")[:3]] if cut else [a18("22/JUN/2019 10:00:00")])),
        ("NYALERTS NOVEMBER 2019", [ALERT18_HDR, a18("02/NOV/2019 20:30:00")]),          # fall: two readings
        ("NYALERT March 2021", [
            ALERT18_HDR,
            a18("02/MAR/2021 21:30:00"),                          # 2021-03-03 02:30 EST; the newer workbook: 2021-03-02
            a18("05/MAR/2021 10:00:00"),                          # the newer workbook names another water
            a18("06/MAR/2021 10:00:00", fac="Otherton (C) STP NY0999904", fid="NY0999904"),
            a18("08/MAR/2021 10:00:00", street=("99", "Other Rd")),   # the newer workbook: 12 Harbor Rd
        ]),
        ("NYALERT July 2021", [ALERT18_HDR, a18("01/JUL/2021 14:00:07")] + ([] if short else [
            a18("02/JUL/2021 14:00:07", water="Other River",
                headline="ENDED: Erie, Sampleton, Sewage Discharge, Other River, Unknown")])),
        ("NYALERT August 2021", [a18("01/AUG/2021 08:50:26"), a18("02/AUG/2021 09:10:00")]),   # no header row
    ]
    if extra_tab:
        tabs.append(("NYALERT September 2021", [ALERT18_HDR, a18("01/SEP/2021 08:00:00")]))
    return xlsx(tabs)


N_TABS, N_ROWS, N_RECORDS = 11, 26, 25


def _col(i: int) -> str:
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def xlsx(tabs) -> bytes:
    ns = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
    rns = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        sheets = "".join(f'<sheet name="{escape(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>' for i, (n, _) in enumerate(tabs))
        z.writestr("xl/workbook.xml", f'<workbook xmlns="{ns}" xmlns:r="{rns}"><sheets>{sheets}</sheets></workbook>')
        rels = "".join(f'<Relationship Id="rId{i + 1}" Type="{rns}/worksheet" Target="worksheets/sheet{i + 1}.xml"/>'
                       for i in range(len(tabs)))
        z.writestr("xl/_rels/workbook.xml.rels",
                   f'<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">{rels}</Relationships>')
        for i, (_n, rows) in enumerate(tabs):
            xml = []
            for r, row in enumerate(rows, 1):
                cells = "".join(f'<c r="{_col(j)}{r}" t="inlineStr"><is><t>{escape(str(v))}</t></is></c>'
                                for j, v in enumerate(row) if v is not None)
                xml.append(f'<row r="{r}">{cells}</row>')
            z.writestr(f"xl/worksheets/sheet{i + 1}.xml", f'<worksheet xmlns="{ns}"><sheetData>{"".join(xml)}</sheetData></worksheet>')
    return buf.getvalue()


def live_record(nid, start_date, water, fid="NY0999903", status="New", street=("12", "Harbor Rd"), chain=None):
    raw = {"row": {"POTW/POSS ID": fid, "Notification Status": status, "Street Number": street[0],
                   "Street Name": street[1], "City": "Sampleton"}}
    if chain:
        raw["_chain"] = {"id": chain}
    return event(source_id=S.SOURCE_ID, source_record_id=nid, event_type="cso", status="unknown",
                 discharger_name="Sampleton (V) WWTP", npdes_permit=fid, waterbody_text=water,
                 started_at=f"{start_date}T00:00:00-05:00", time_precision="day", raw=raw)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    events = tmp_path / "events"
    events.mkdir()
    monkeypatch.setattr(common, "EVENTS_DIR", events)
    monkeypatch.setattr(common, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(M, "EVENTS_DIR", events)
    monkeypatch.setattr(M, "ROOT", tmp_path)
    monkeypatch.setattr(M, "STATE_FILE", tmp_path / "build" / "state.json")
    monkeypatch.setattr(M, "LIVE_EVENTS", events / "live.json")
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    common.write_json(events / "live.json", {"records": [live_record("9001", "2021-03-02", "Sample Creek"),
                                                         live_record("9002", "2021-03-05", "Other Creek"),
                                                         live_record("9003", "2021-03-08", "Sample Creek")]})
    wb = tmp_path / "Sewage_Discharge_Reports.xlsx"
    wb.write_bytes(workbook())
    return tmp_path, events, wb


def run_file(env):
    tmp, events, wb = env
    assert M.main(["--file", str(wb)]) == 0
    return json.loads((events / f"{M.SOURCE_ID}.json").read_text())


def by_start(doc, layout=None):
    out = {}
    for r in doc["records"]:
        if layout is None or r["raw"]["_layout"] == layout:
            out.setdefault(r["raw"].get("_start_stored"), []).append(r)
    return out


def test_layouts_clocks_and_status(env):
    doc = run_file(env)
    recs = doc["records"]
    # every distinct row is a record; the copy is listed on its twin; the fragment row is kept
    assert doc["meta"]["rows"] == N_ROWS and doc["meta"]["identical_rows"] == 1 and len(recs) == N_RECORDS
    assert doc["meta"]["frozen"] is True and doc["meta"]["statewide"] is False
    # report tab: local time as typed, the discovery time as the start, an ending time makes it ended
    rep = by_start(doc, "report")
    r = rep["2014-08-13T10:30"][0]
    assert r["started_at"] == "2014-08-13T10:30:00-04:00" and r["status"] == "ended"
    assert r["ended_at"] == "2014-08-13T12:00:00-04:00" and "discovery" in r["raw"]["_start_basis"]
    assert r["volume_gal"] == 1000 and r["estimate_flag"] == "estimated" and r["raw"]["_duration_text"] == "1:30"
    r = rep["2014-09-01T08:00"][0]
    assert r["status"] == "unknown" and r["ended_at"] is None and r["raw"]["_projected_end"] == "2014-09-02T08:00:00-04:00"
    # alert15: an Excel serial date and a typed time, the duration's own word for the state, the volume words
    r = by_start(doc, "alert15")["2015-10-09T07:25"][0]
    assert r["started_at"] == "2015-10-09T07:25:00-04:00" and r["status"] == "ended" and r["ended_at"] is None
    assert r["discharger_name"] == "Example Falls WWTP" and r["volume_gal"] is None
    assert r["volume_text"] == "500 Gallons Per Minute Estimated"
    r = by_start(doc, "alert15")["2015-10-13T08:00"][0]
    assert r["volume_gal"] == 10000 and r["raw"]["row"]["Description"] == "10000 Gallons"
    frag = by_start(doc, "alert15")["2016-01-06T03:00"][0]
    assert "names no facility" in frag["parse_error"] and "Location of Discharge" in frag["raw"]["_withheld"]["columns"]
    # alert16: local time (the text says "started at 3:25 PM"), quantity flag 0 read as Actual
    r = by_start(doc, "alert16")["2017-06-18T15:25"][0]
    assert r["started_at"] == "2017-06-18T15:25:00-04:00" and r["estimate_flag"] == "measured"
    assert "match the stored" in r["raw"]["_time_basis"]["start"]
    # alert18: stored = local - 4 h (EDT) / 5 h (EST)
    a = by_start(doc, "alert18")
    assert a["2018-12-21T04:15"][0]["started_at"] == "2018-12-21T09:15:00-05:00"
    june = sorted(a["2019-06-21T10:00"], key=lambda x: x["raw"]["_chain"]["position"])
    assert [x["started_at"] for x in june] == ["2019-06-21T14:00:00-04:00"] * 3
    assert [x["raw"]["_notice_kind"]["status"] for x in june] == ["New", "Update", "Close"]
    assert [x["status"] for x in june] == ["unknown", "unknown", "ended"] and june[2]["ended_at"] is None
    assert june[0]["raw"]["_copies"] == [{"tab": "NYALERTS JUNE 2019", "row": 5}]
    assert june[1]["parent_event_id"] == june[0]["event_id"] and june[2]["parent_event_id"] == june[1]["event_id"]
    assert june[0]["volume_text"] == "65 Gallons per Minute Estimated" and june[0]["raw"]["_duration_text"] == "24 Hours"
    assert "placeholder" in june[0]["raw"]["_volume_note"]
    assert all(x["source_id"] == M.SOURCE_ID and x["event_id"].startswith(f"{M.SOURCE_ID}:h") for x in recs)
    # a start years before its tab's month is kept as written, with a note
    old = a["2014-11-17T01:00"][0]
    assert old["started_at"] == "2014-11-17T06:00:00-05:00" and "more than a year before" in old["raw"]["_dww_note"][0]
    # the August 2021 tab has no header row: read with July's columns
    assert a["2021-08-01T08:50"][0]["waterbody_text"] == "Sample Creek"
    tabs = {t["tab"]: t for t in doc["meta"]["tabs"]}
    assert "no header row" in tabs["NYALERT August 2021"]["header_note"] and tabs["NYALERT August 2021"]["rows"] == 2
    assert tabs["PDFs through May 2015"]["title"] == ["SPRTK Discharge Report Summary", "Updated 10/29/15"]


def test_an_end_known_only_to_the_day_is_the_end_of_that_day(env):
    """docs/generic-ingesters.md: an end known only to the day on a record timed to the minute is the end of that
    day; a same-day date-only end is not before the start (report rows 2410, 2411 and 2566)."""
    rep = by_start(run_file(env), "report")
    same = rep["2014-10-01T09:00"][0]
    assert same["status"] == "ended" and same["ended_at"] == "2014-10-02T00:00:00-04:00" and same["parse_error"] is None
    assert "end of that day" in same["raw"]["_end_basis"] and "_end_before_start" not in same["raw"]
    nxt = rep["2014-10-05T09:00"][0]
    assert nxt["ended_at"] == "2014-10-07T00:00:00-04:00" and nxt["time_precision"] == "minute"


def test_clock_change_readings_are_kept_to_the_day(env):
    """A stored time that fits the stored + 4 h (EDT) / + 5 h (EST) rule twice (fall) or not at all (spring) is
    published at day precision with the candidates in raw._time_notes."""
    a = by_start(run_file(env), "alert18")
    fall = a["2019-11-02T20:30"][0]
    assert fall["started_at"] == "2019-11-03T00:00:00-04:00" and fall["time_precision"] == "day"
    notes = fall["raw"]["_time_notes"]["start"]
    assert notes["candidates"] == ["2019-11-03T00:30:00-04:00", "2019-11-03T01:30:00-05:00"] and "two" in notes["why"]
    for stored in ("2019-03-09T21:30", "2019-03-09T22:30"):
        spring = a[stored][0]
        assert spring["started_at"] == "2019-03-10T00:00:00-05:00" and spring["time_precision"] == "day"
        assert "no reading" in spring["raw"]["_time_notes"]["start"]["why"]
    assert a["2018-12-21T04:15"][0]["time_precision"] == "minute" and "_time_notes" not in a["2018-12-21T04:15"][0]["raw"]


def test_a_closing_notice_into_another_water_is_its_own_discharge(env):
    """No edited-start merge in this feed (Astra P1-3): a July 1 first notice into Sample Creek and a July 2 closing
    notice into Other River at the same facility and address stay two chains."""
    a = by_start(run_file(env), "alert18")
    first, close = a["2021-07-01T14:00"][0], a["2021-07-02T14:00"][0]
    assert first["raw"]["_chain"]["id"] != close["raw"]["_chain"]["id"]
    assert close["parent_event_id"] is None and "edited" not in (close["raw"]["_chain"]["basis"] or "")


def test_copies_in_the_newer_workbook(env):
    doc = run_file(env)
    a = by_start(doc, "alert18")
    dup = a["2021-03-02T21:30"][0]
    # stored 21:30 on March 2 is 02:30 EST on March 3; the newer workbook's date is the stored date
    assert dup["started_at"] == "2021-03-03T02:30:00-05:00"
    assert dup["duplicate_of"] == f"{S.SOURCE_ID}:9001" and "stored clock" in dup["raw"]["_duplicate_basis"]
    weak = a["2021-03-05T10:00"][0]
    assert weak["duplicate_of"] is None
    assert weak["raw"]["_possible_copy_of"]["event_id"] == f"{S.SOURCE_ID}:9002"
    assert "another water" in weak["raw"]["_possible_copy_of"]["reason"]
    # Astra P1-2: 99 Other Rd against 12 Harbor Rd, same facility, date and water: never a duplicate
    addr = a["2021-03-08T10:00"][0]
    assert addr["duplicate_of"] is None and addr["raw"]["_possible_copy_of"]["event_id"] == f"{S.SOURCE_ID}:9003"
    assert "another address" in addr["raw"]["_possible_copy_of"]["reason"]
    other = a["2021-03-06T10:00"][0]
    assert other["duplicate_of"] is None and "_possible_copy_of" not in other["raw"]
    assert doc["meta"]["overlap_with_newer_workbook"]["duplicate_of"] == 1


def hist_record(nid, kind, chain="key:x", street=("12", "Harbor Rd"), water="Sample Creek", fid="NY0999903"):
    row = a18("02/MAR/2021 21:30:00", street=street, water=water, fid=fid)
    return event(source_id=M.SOURCE_ID, source_record_id=nid, npdes_permit=fid, waterbody_text=water,
                 started_at="2021-03-03T02:30:00-05:00", time_precision="minute",
                 raw={"_layout": "alert18", "_facility_id": fid, "_start_stored": "2021-03-02T21:30",
                      "_notice_kind": {"status": kind}, "_chain": {"id": chain},
                      "row": dict(zip([h or f"col{i + 1}" for i, h in enumerate(ALERT18_HDR)], row))})


def test_one_to_one_pairing_within_one_discharge():
    """Three notices of one discharge in this workbook, two of one discharge in the newer one: two pairs, one possible
    copy; links are made again from scratch."""
    hist = [hist_record("a", "New"), hist_record("b", "Update"), hist_record("c", "Close")]
    live = [live_record("1", "2021-03-02", "Sample Creek", status="New", chain="incident:7"),
            live_record("2", "2021-03-02", "Sample Creek", status="Close", chain="incident:7")]
    out = M.link_copies(hist, live)
    assert out == {"duplicate_of": 2, "possible_copy_of": 1, "newer_workbook_records": 2}
    assert [x["duplicate_of"] for x in hist] == [f"{S.SOURCE_ID}:1", None, f"{S.SOURCE_ID}:2"]
    assert "paired with another notice" in hist[1]["raw"]["_possible_copy_of"]["reason"]
    assert M.link_copies(hist, []) == {"duplicate_of": 0, "possible_copy_of": 0, "newer_workbook_records": 0}
    assert all(x["duplicate_of"] is None and "_possible_copy_of" not in x["raw"] for x in hist)


def test_contradictions_and_ambiguity_rule_out_duplicate_of():
    # another address (Astra's 99 Other Rd case), another water, another permit: possible copies only
    for h, word in ((hist_record("a", "New", street=("99", "Other Rd")), "address"),
                    (hist_record("b", "New", water="Other River"), "water")):
        assert M.link_copies([h], [live_record("1", "2021-03-02", "Sample Creek", chain="incident:7")])["duplicate_of"] == 0
        assert word in h["raw"]["_possible_copy_of"]["reason"]
    # two discharges in the newer workbook fit one date-only notice: ambiguous, so a possible copy
    h = hist_record("c", "New")
    live = [live_record("1", "2021-03-02", "Sample Creek", chain="incident:7"),
            live_record("2", "2021-03-02", "Sample Creek", chain="incident:8")]
    assert M.link_copies([h], live) == {"duplicate_of": 0, "possible_copy_of": 1, "newer_workbook_records": 2}
    assert "more than one discharge" in h["raw"]["_possible_copy_of"]["reason"]


def test_narrative_columns_never_reach_a_record_or_the_saved_page(env):
    """Astra P1-1: the operator narrative columns are never read; their names are listed in raw._withheld."""
    tmp, events, _wb = env
    doc = run_file(env)
    pages = list((tmp / "raw" / M.SOURCE_ID).glob("*.json"))
    assert len(pages) == 1 and doc["meta"]["raw_path"] == str(pages[0].relative_to(tmp))
    page = pages[0].read_text()
    for text in (json.dumps(doc), page):
        low = text.lower()
        for plant in PLANTS:
            assert plant.lower() not in low
        assert "jane roe" not in low and "5185550142" not in low and "callback" not in low
    assert "Sample Creek" in page and len(json.loads(page)["tabs"]) == N_TABS
    a = by_start(doc, "alert18")["2018-12-21T04:15"][0]
    assert set(a["raw"]["_withheld"]["columns"]) == {"location description", "reason description",
                                                     "discharge description", "additional instructions", "col23"}
    assert a["advice_text"] is None and a["outfall_name"] is None
    assert set(by_start(doc, "report")["2014-08-13T10:30"][0]["raw"]["_withheld"]["columns"]) == {
        "Other Explained", "Corrective Actions", "Other Explanation"}


class Resp:
    def __init__(self, status=200, content=b"", headers=None, url=M.DEC_URLS[0]):
        self.status_code, self.content, self.headers, self.url = status, content, headers or {}, url

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class Session:
    """A stand-in for requests.Session: answers from a list, records what was asked."""
    asked: list = []
    answers: list = []

    def __init__(self):
        self.headers = {}

    def get(self, url, headers=None, timeout=None):
        Session.asked.append((url, dict(headers or {})))
        a = Session.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return a


LM = "Tue, 11 Jul 2023 14:00:00 GMT"


def test_reading_weekly_304_failure_and_shape(env, monkeypatch):
    tmp, events, wb = env
    monkeypatch.setattr(M.requests, "Session", Session)
    content = wb.read_bytes()
    path = events / f"{M.SOURCE_ID}.json"

    def run(answers, args=()):
        Session.asked, Session.answers = [], list(answers)
        return M.main(list(args))

    assert run([Resp(content=content, headers={"Last-Modified": LM})]) == 0
    first = json.loads(path.read_text())
    assert first["ok"] and len(first["records"]) == N_RECORDS and Session.asked[0][1] == {}
    state = json.loads(M.STATE_FILE.read_text())
    assert state["last_modified_http"] == LM and len(state["tabs"]) == N_TABS and all(t["cells"] for t in state["tabs"])
    # within the week: nothing asked, records kept, links made again
    assert run([]) == 0 and Session.asked == []
    assert len(json.loads(path.read_text())["records"]) == N_RECORDS
    # a week on: If-Modified-Since, a 304 keeps the records
    state["read_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    common.write_json(M.STATE_FILE, state)
    assert run([Resp(status=304)]) == 0 and Session.asked[0][1] == {"If-Modified-Since": LM}
    doc = json.loads(path.read_text())
    assert doc["ok"] and len(doc["records"]) == N_RECORDS
    assert doc["meta"]["workbook_not_modified_since"] == "2023-07-11T14:00:00Z"
    # --backfill reads now, without If-Modified-Since
    assert run([Resp(content=content, headers={"Last-Modified": LM})], ["--backfill"]) == 0 and Session.asked[0][1] == {}

    def stale():
        s = json.loads(M.STATE_FILE.read_text())
        s["read_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
        return s

    # DEC and the archive do not answer: the records are kept, ok false
    common.write_json(M.STATE_FILE, stale())
    assert run([ConnectionError("refused")] * 4) == 1
    doc = json.loads(path.read_text())
    assert doc["ok"] is False and len(doc["records"]) == N_RECORDS and len(Session.asked) == 4
    # a file cut short, fewer rows in a tab, a row cut to its first three cells: each fails and keeps the records
    for bad, why in ((content[: len(content) // 2], ""), (workbook(short=True), "fewer rows"),
                     (workbook(cut=True), "fewer filled cells")):
        common.write_json(M.STATE_FILE, stale())
        assert run([Resp(content=bad, headers={"Last-Modified": "Wed, 12 Jul 2023 14:00:00 GMT"})]) == 1
        doc = json.loads(path.read_text())
        assert doc["ok"] is False and len(doc["records"]) == N_RECORDS and why in (doc["error"] or "")
    s = stale()
    s["tabs"].append({"tab": "NYALERT September 2021", "rows": 1})
    common.write_json(M.STATE_FILE, s)
    assert run([Resp(content=content, headers={"Last-Modified": "Wed, 12 Jul 2023 14:00:00 GMT"})]) == 1
    assert "NYALERT September 2021" in (json.loads(path.read_text())["error"] or "")


def test_a_lost_tab_replaced_by_a_new_one_fails():
    """Astra P2-5: every tab of the last good read must still be there, whatever the count."""
    with pytest.raises(ValueError, match="lost"):
        M.check_shape([{"tab": "new", "rows": [(2, {"a": "1"})], "cells": 1}], {"tabs": [{"tab": "lost", "rows": 1}]})


def test_archive_fallback_unchanged_counts_as_not_modified(env, monkeypatch):
    tmp, events, wb = env
    monkeypatch.setattr(M.requests, "Session", Session)
    Session.asked, Session.answers = [], [Resp(content=wb.read_bytes(), headers={"Last-Modified": LM})]
    assert M.main([]) == 0
    s = json.loads(M.STATE_FILE.read_text())
    s["read_at"] = (datetime.now(UTC) - timedelta(days=8)).isoformat()
    common.write_json(M.STATE_FILE, s)
    cap = Resp(content=wb.read_bytes(), headers={"x-archive-orig-last-modified": LM},
               url="https://web.archive.org/web/20261012004317id_/https://www.dec.ny.gov/fs/data/Sewage_Discharge_Reports.xlsx")
    Session.asked, Session.answers = [], [ConnectionError("timeout"), ConnectionError("timeout"), cap]
    assert M.main([]) == 0
    doc = json.loads((events / f"{M.SOURCE_ID}.json").read_text())
    assert doc["ok"] and doc["meta"]["last_read_via"] == "archive.org" and len(doc["records"]) == N_RECORDS


def test_reader_helpers():
    assert M.tab_period("NYALERTS NOVEMBER 2018", None)[:2] == (date(2018, 11, 1), date(2018, 11, 30))
    assert M.tab_period("NYAlerts May2016 thru May2017", None)[:2] == (date(2016, 5, 1), date(2017, 5, 31))
    assert M.tab_period("NYALERTS June 13 thru 30", 2018)[:2] == (None, date(2018, 6, 30))
    assert M.tab_period("PDFs through May 2015", None)[:2] == (None, date(2015, 5, 31))
    assert M.tab_period("NYALERT Janury 2021", None)[0] == date(2021, 1, 1)
    assert M.split_time("42286", "6:00PM") == ("2015-10-09T18:00", None)
    assert M.split_time("April 1, 20162", "2:43AM") == ("2016-04-01T02:43", None)
    assert M.split_time("42429", "-02-29T1") == ("2016-02-29", "time of day '-02-29T1' not understood: the date only")
    assert M.split_time(None, ":00") == (None, None)
    assert M.typed_time("8/13/2014 :") == "2014-08-13" and M.typed_time(": AM") is None
    # a header row standing after two data rows: the two rows are data
    wb = xlsx([("NYALERT August 2021", [a18("01/AUG/2021 08:50:26"), a18("01/AUG/2021 08:50:44"), ALERT18_HDR,
                                         a18("01/AUG/2021 08:50:57")])])
    t = M.read_tabs(wb)[0]
    assert t["header_row"] == 3 and [n for n, _r in t["rows"]] == [1, 2, 4] and t["title"] == []
    with pytest.raises(ValueError, match="no header row"):
        M.read_tabs(xlsx([("Mystery", [["a", "b"], ["c", "d"]])]))
