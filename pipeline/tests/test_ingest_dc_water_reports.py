"""DC Water's quarterly CSO reports (ingest/dc_water_cso_quarterly.py) and sanitary sewer overflow file
(ingest/dc_water_sso.py). The table text below is copied from the reports' own Table 2-7 and Table 2-1 (the third
quarter of 2026, September, page 57; the second quarter of 2026; the third and first quarters of 2020; August 2024),
with no signature, name or address. The SSO rows are invented in the file's own shape: no real premise id or house.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import re
from datetime import UTC, datetime

import pytest

from ingest import dc_water_cso_quarterly as Q
from ingest import dc_water_sso as S

SEP_2026 = """
I:\\SEWER\\CSO QUARTERLY REPORT\\CSO 3rd Quarter Report 2026\\CSO Monthly Report September 2026.docx
  13 Report for September 2026
Table 2-7
Inflatable Dams & SCADA Sites - Wet Weather Operations

Notes:

3. DRY WEATHER OVERFLOWS

There was no dry weather combined sewer overflow reported during September 2026.

Inflatable Dam Structure No. Overflow Dates Estimated Duration of Overflow  Inflatable Dam Operational Status
14 (E & W) None N/A Inflated
15 9/4/26 3hrs 5mins De flated
15A None  N/A Inflated
16 (E & W) None  N/A Inflated
34 None  N/A Inflated
35 9/11/26 47mins Deflated
52 None N/A Inflated

N/A
Structures on Outfall Sewers Overflow Dates Estimated Duration of Overflow
Outfall Structure 1 None This structure has been bulk headed. Overflows are no longer possible.
Outfall Structure 1A None This structure has been bulk headed. Overflows are no longer possible.
Outfall Structure 2 None N/A
Outfall Sewer Control Gates Operational Status Position
Outfall Sewer Control Gate No.1 Operational Open
4. SOLIDS AND FLOATABLES CONTROL
"""

SEP_2020 = """
  13 Report for September 2020
Table 2-7
Inflatable Dams & SCADA Sites - Wet Weather Operations
Inflatable Dam Structure No. Overflow Dates Estimated Duration of Overflow
14 (E & W)2, 5,6 9/3/20
9/9/20
9/10/20
0 hrs. 28 mins
0 hrs. 7 mins
3 hrs. 24 mins
151 9/1/20
9/10/20
0 hrs. 20 mins
3 hrs. 54 mins
15A None N/A
16 (E & W) None N/A
344 9/7/20 4 hrs. 53 mins
357 9/1/20
9/30/20
0 hrs. 34 mins
0 hrs. 37 mins
52 None N/A
Structures on Outfall Sewers Overflow Dates Estimated Duration of Overflow
Outfall Structure 1 None This structure has been bulk headed. Overflows are no longer possible.
Outfall Structure 1A None This structure has been bulk headed. Overflows are no longer possible.
Outfall Structure 2 None N/A
Outfall Sewer Control Gates Operational Status Position
Notes:
1. On 9/1/20, Structure 15 deflated for approximately 20 minutes. This was not an overflow to the river as any overflow
from Structure 15 goes to O Street Pumping Station and is not discharged to the river unless the storm pumps are on.
2. On 9/03/20, Structure 14 (E & W) had scheduled preventive maintenance performed on the pressure sensors which
resulted in a pressure drop. This was not an overflow to the river as the downstream levels were higher.
4. On 9/7/2020, Structure 34 (E & W) deflated due to a compressor belt failure. This was not an overflow to the river as
the upstream levels were significantly lower than the low-level threshold.
5. On 9/9/20, a power outage occurred in the area that caused Structure 14 and 16 to deflate. This was not an
overflow to the river as the upstream levels were significantly lower than the low-level threshold.
6. On 9/10/20, the structure deflated during a storm and the overflow reached the river.
7. On 9/30/20, Structure 35 deflated due to a blower failure. This was not an overflow to the river.
4. SOLIDS AND FLOATABLES CONTROL
"""


def month_text(rows: str, notes: str = "", month: str = "February 2020") -> str:
    return (f"  13 Report for {month}\nTable 2-7\nInflatable Dams & SCADA Sites - Wet Weather Operations\n"
            "Inflatable Dam Structure No. Overflow Dates Estimated Duration of Overflow\n" + rows +
            "\nStructures on Outfall Sewers Overflow Dates Estimated Duration of Overflow\n"
            "Outfall Structure 1 None N/A\nOutfall Structure 1A None N/A\nOutfall Structure 2 None N/A\n"
            "Outfall Sewer Control Gates Operational Status Position\nNotes:\n" + notes)


QUIET = "14 (E & W) None N/A\n15A None N/A\n16 (E & W) None N/A\n34 None N/A\n35 None N/A\n52 None N/A\n"

TABLE_2_1 = """  2 Report for April 2026
Table 2-1
Regulator Structures
Structure
Number Location
Associated NPDES
Outfall
14 2nd Street, 250 ft. north of N Place, SE 011(a) 04/21/2026  *
15 South Capitol and E Streets 010 04/09/2026  *
15a Half and L Streets, SE 010 04/09/2026  *
16 North of Main Sewage Pumping Station 012 04/21/2026  *
34 23rd Street, north of Constitution Ave, NW 020 04/09/2026  *
35 Northeast of Roosevelt Bridge, NW 021 04/09/2026  *
52 22nd Street between M and N Streets, NW 034 04/09/2026  *
"""
GLYPH_PAGE = " ".join(f"/{i % 40}" for i in range(200)) + " /i255\n/i255"
MODEL_PAGE = """District of Columbia Water and Sewer Authority
Combined Sewer System Model Results
Period: Q3 2026 (July, August, September)
021 Northeast ofRoosevelt Bridge, NW Modeled 5 16.41 7.00 1.40 2.50 0.75
010 O Street SewagePumping Station, SE Metered 1 5.54 3.00 3.00 3.00 3.00
"""

REGISTRY = {"21": {"outfall": "021", "lat": 38.888611, "lon": -77.053055, "water_slug": "potomac-river-dc",
                   "outfall_name": "N.E. of Roosevelt Bridge, NW"},
            "10": {"outfall": "010", "lat": 38.873055, "lon": -77.003891, "water_slug": "anacostia-river-dc",
                   "outfall_name": "O Street Sewage Pumping Station, SE"}}


# ---------------------------------------------------------------- Table 2-7

def test_september_2026_rows_as_the_report_gives_them():
    m = Q.parse_month(SEP_2026, "2026-09")
    assert m["status"] == "read" and m["set_apart"] == [] and m["dwo"] is None
    got = [(r["structure"], r["date"], r["duration_as_given"], r["duration_minutes"]) for r in m["rows"]]
    assert got == [("15", "2026-09-04", "3hrs 5mins", 185), ("35", "2026-09-11", "47mins", 47)]


def test_multi_date_rows_footnote_marks_and_notes_that_deny_an_overflow():
    m = Q.parse_month(SEP_2020, "2020-09")
    assert m["status"] == "read", m.get("reason")
    kept = {(r["structure"], r["date"]): r["duration_as_given"] for r in m["rows"]}
    # note 6 says the overflow reached the river: an affirmative statement keeps the row
    assert kept == {("14", "2020-09-10"): "3 hrs. 24 mins", ("15", "2020-09-10"): "3 hrs. 54 mins",
                    ("35", "2020-09-01"): "0 hrs. 34 mins"}
    apart = {(a["structure"], a["date"], a["note"]) for a in m["set_apart"]}
    assert apart == {("14", "2020-09-03", 2), ("14", "2020-09-09", 5), ("15", "2020-09-01", 1),
                     ("34", "2020-09-07", 4), ("35", "2020-09-30", 7)}
    assert all("not an overflow to the river" in a["basis"] for a in m["set_apart"])


def test_a_dateless_denial_is_tied_through_its_footnote_mark_or_the_month_is_unread():
    one = month_text("152 2/14/20 0 hrs. 1 mins\n" + QUIET,
                     "2. Structure 15 manually deflated for testing. This was not an overflow to the river.\n")
    m = Q.parse_month(one, "2020-02")
    assert m["status"] == "read" and m["rows"] == []
    assert [(a["structure"], a["date"]) for a in m["set_apart"]] == [("15", "2020-02-14")]
    two = month_text("15 None N/A\n" + QUIET.replace("14 (E & W) None N/A\n", "").replace("15A None N/A\n", "")
                     + "14 (E & W) None N/A\n15A2 1/11/20\n1/16/20\n1 hr. 21 mins\n0 hrs. 7 mins\n",
                     "2. Structure 15A manually deflated due to testing. This was not an overflow to the river.\n",
                     "January 2020")
    m = Q.parse_month(two, "2020-01")
    assert m["status"] == "unread" and "note 2" in m["reason"]


def test_a_duration_line_never_starts_a_row():
    m = Q.parse_month(month_text("15 2/14/20\n2/20/20\n15 mins\n34 mins\n" + QUIET.replace("34 None N/A\n", "34 None N/A\n")),
                      "2020-02")
    assert m["status"] == "read", m.get("reason")
    assert [(r["structure"], r["duration_minutes"]) for r in m["rows"]] == [("15", 15), ("15", 34)]


def test_bad_dates_unpaired_durations_changed_headers_and_missing_structures_leave_the_month_unread():
    typo = month_text("15 None N/A\n" + QUIET.replace("35 None N/A\n", "35 8/3/20024\n8/8/2024\n36mins\n20mins\n"),
                      month="August 2024")
    m = Q.parse_month(typo, "2024-08")
    assert m["status"] == "unread" and "8/3/20024" in m["reason"] and "rows" not in m
    unpaired = month_text("15 2/1/20\n2/2/20\n3 mins\n" + QUIET)
    assert "2 dates and 1 durations" in Q.parse_month(unpaired, "2020-02")["reason"]
    renamed = month_text("15 None N/A\n" + QUIET).replace("Estimated Duration of Overflow\n15", "Duration (h)\n15", 1)
    assert "changed" in Q.parse_month(renamed, "2020-02")["reason"]
    missing = month_text(QUIET)
    assert "lacks structure(s) 15" in Q.parse_month(missing, "2020-02")["reason"]


def test_seconds_in_a_duration():
    m = Q.parse_month(month_text("15 None N/A\n" + QUIET.replace("35 None N/A\n", "35 10/30/25  26mins 43s Deflated\n"),
                                 month="October 2025"), "2025-10")
    assert m["rows"][0]["duration_minutes"] == pytest.approx(26 + 43 / 60, abs=0.01)


def test_dry_weather_statement_is_listed_not_itemised():
    t = month_text("15 None N/A\n" + QUIET, month="February 2024").replace(
        "Notes:\n", "Notes:\n3. DRY WEATHER OVERFLOWS\nThere was one (1) dry weather combined sewer overflow reported "
                    "during February 2024 at Outfall #024 - 30th Street & K Street, NW. See attached.\n")
    m = Q.parse_month(t, "2024-02")
    assert m["status"] == "read" and m["rows"] == []
    assert m["dwo"] == {"month": "2024-02", "stated": "one", "outfalls": ["024"]}


# ---------------------------------------------------------------- a whole report

def test_pages_without_a_text_layer_leave_their_months_unread_and_the_rest_read():
    pages = [GLYPH_PAGE] * 20 + [SEP_2026, MODEL_PAGE]
    r = Q.parse_report(pages, 2026, 3)
    assert r["months"]["2026-09"]["status"] == "read"
    assert {m: v["status"] for m, v in r["months"].items()} == {"2026-07": "unread", "2026-08": "unread",
                                                               "2026-09": "read"}
    assert "no Unicode map" in r["months"]["2026-07"]["reason"]
    assert r["structures"] is None                 # Table 2-1 unreadable: the reference transcription is used
    # the model results table gives no record: only Table 2-7's two dated overflows
    assert len(r["months"]["2026-09"]["rows"]) == 2
    # a page of dated rain figures is not a page without text
    assert not Q.no_text_layer("\n".join(f"4/{d}/2026 0 0 0.04 0 0.19" for d in range(1, 31)))
    assert Q.no_text_layer(GLYPH_PAGE)


def test_structure_table_ties_and_a_disagreement_ties_nothing():
    assert Q.structure_table([TABLE_2_1]) == Q.STRUCTURE_OUTFALL
    other = TABLE_2_1.replace("35 Northeast of Roosevelt Bridge, NW 021", "35 Northeast of Roosevelt Bridge, NW 022")
    st = Q.structure_table([TABLE_2_1, other])
    assert st["35"] is None and st["34"] == "020"
    assert Q.tie({"structures": st}, "35")[0] is None
    assert Q.tie({"structures": None}, "35") == ("021", Q.STRUCTURE_OUTFALL_BASIS + "; this report's Table 2-1 has "
                                                        "no text layer")
    assert Q.tie({"structures": st}, "OS2")[0] is None
    assert Q.structure_table([GLYPH_PAGE]) is None


def _state_with(pages_by_copy, at="2026-11-16T12:00:00Z"):
    state = {}
    entry = {"quarter": "2026Q3", "year": 2026, "q": 3, "url": "https://example.invalid/q3.pdf",
             "published": "2026-10-28"}
    probs = []
    for i, pages in enumerate(pages_by_copy):
        orig = Q.pdf_pages
        Q.pdf_pages = lambda content, _p=pages: _p
        try:
            probs.append(Q.read_quarter(state, {**entry, "url": f"https://example.invalid/q3-{i}.pdf"},
                                        f"copy {i}".encode(), at))
        finally:
            Q.pdf_pages = orig
    return state, probs


def test_records_dates_no_invented_times_publication_and_registry_point():
    state, probs = _state_with([[GLYPH_PAGE, SEP_2026]])
    assert any("2026-07" in p for p in probs[0])
    recs = Q.records(state, REGISTRY)
    by = {r["source_record_id"]: r for r in recs}
    assert set(by) == {"s15-2026-09-04-1", "s35-2026-09-11-1"}
    r = by["s35-2026-09-11-1"]
    assert r["started_at"] == "2026-09-11" and r["ended_at"] is None and r["time_precision"] == "day"
    assert r["published_at"] == "2026-10-28" and r["reported_at"] is None       # the report's date, not the overflow's
    assert r["event_type"] == "cso" and r["status"] == "ended" and r["volume_gal"] is None
    assert r["outfall_id"] == "021" and r["water_slugs"] == ["potomac-river-dc"] and r["waterbody_text"] == "Potomac River"
    assert (r["lat"], r["lon"]) == (38.888611, -77.053055) and r["coord_source"] == "outfall_layer"
    assert r["raw"]["duration_minutes"] == 47 and "reference" not in r["raw"]["tie_basis"]
    assert by["s15-2026-09-04-1"]["outfall_id"] == "010" and by["s15-2026-09-04-1"]["waterbody_text"] == "Anacostia River"


def test_a_revised_copy_updates_never_duplicates_and_a_failed_copy_keeps_the_read_month():
    revised = SEP_2026.replace("35 9/11/26 47mins", "35 9/11/26 49mins")
    dropped = revised.replace("15 9/4/26 3hrs 5mins De flated", "15 None N/A Inflated")
    state, probs = _state_with([[SEP_2026], [revised], [GLYPH_PAGE], [dropped]])
    recs = Q.records(state, REGISTRY)
    ids = [r["source_record_id"] for r in recs]
    assert sorted(ids) == ["s15-2026-09-04-1", "s35-2026-09-11-1"]            # one record each, never two
    by = {r["source_record_id"]: r for r in recs}
    assert by["s35-2026-09-11-1"]["raw"]["duration_as_given"] == "49mins"
    # the row the last copy no longer lists stays, marked
    assert by["s15-2026-09-04-1"]["raw"]["not_in_revision"]["sha256"]
    # the unreadable third copy changed nothing and was named
    assert any("2026-09" in p for p in probs[2])


def test_an_unreadable_file_reads_nothing_and_says_why():
    state = {}
    orig = Q.pdf_pages

    def boom(content):
        raise Q.UnreadableReport("the file is encrypted with a cipher this reader cannot open")
    Q.pdf_pages = boom
    try:
        probs = Q.read_quarter(state, {"quarter": "2023Q2", "year": 2023, "q": 2, "url": "u", "published": None},
                               b"x", "2026-11-16T00:00:00Z")
    finally:
        Q.pdf_pages = orig
    assert probs and Q.records(state, REGISTRY) == []
    assert set(Q.unread_months(state)) == {"2023-04", "2023-05", "2023-06"}


def test_same_outfall_same_day_epa_row_is_the_duplicate_and_nothing_else():
    state, _ = _state_with([[SEP_2026]])
    recs = Q.records(state, REGISTRY)
    epa = [{"event_id": "echo:1", "outfall_id": "021", "started_at": "2026-09-11T03:10", "npdes_permit": "DC0021199"},
           {"event_id": "echo:2", "outfall_id": "021", "started_at": "2026-09-12T03:10", "npdes_permit": "DC0021199"},
           {"event_id": "echo:3", "outfall_id": "020", "started_at": "2026-09-04T01:00", "npdes_permit": "DC0021199"}]
    assert Q.link_duplicates(recs, epa) == 1
    by = {r["source_record_id"]: r["duplicate_of"] for r in recs}
    assert by == {"s35-2026-09-11-1": "echo:1", "s15-2026-09-04-1": None}
    assert Q.link_duplicates(recs, epa + [{**epa[0], "event_id": "echo:9"}]) == 0     # two candidates: no link


def test_the_previous_records_are_kept_when_the_state_is_empty():
    state, _ = _state_with([[SEP_2026]])
    prev = {"records": Q.records(state, REGISTRY)}
    kept = Q.retained(prev, {})
    assert len(kept) == 2 and all(r["raw"]["retained_from"] for r in kept)
    assert Q.retained(prev, state) == []


# ---------------------------------------------------------------- the list, cadence, backfill

INDEX_HTML = """<table><tr><td>October 28, 2026</td><td>CSO Division Quarterly Operation Reports 2026 3RD QUARTER
COMBINED SEWER OVERFLOW FACILITIES QUARTERLY REPORT <a href="/sites/default/files/document/2026-10/documents/q3.pdf">
pdf</a></td></tr><tr><td>July 28, 2026</td><td>CSO Division Quarterly Operation Reports 2026 2ND QUARTER COMBINED
SEWER OVERFLOW FACILITIES QUARTERLY REPORT <a href="/sites/default/files/document/2026-07/documents/q2.pdf">pdf</a>
</td></tr><tr><td>April 28, 2017</td><td>CSO Division Quarterly Operation Reports Combined Sewer Overflow Facilities
Quarterly Report <a href="/x.pdf">pdf</a></td></tr></table>
<a href="?term_node_tid_depth=50&amp;page=1">2</a><a href="?term_node_tid_depth=50&amp;page=3">4</a>"""


def test_the_list_and_what_is_due():
    listed, odd = Q.parse_index(INDEX_HTML)
    assert [(e["quarter"], e["published"]) for e in listed] == [("2026Q3", "2026-10-28"), ("2026Q2", "2026-07-28")]
    assert listed[0]["url"] == "https://www.dcwater.com/sites/default/files/document/2026-10/documents/q3.pdf"
    assert len(odd) == 1 and Q.index_pages(INDEX_HTML) == 4
    old = [{"quarter": "2019Q4", "year": 2019, "q": 4, "url": "o", "published": None}]
    assert [e["quarter"] for e in Q.due({}, listed + old, "2026-11-16T00:00:00Z")] == ["2026Q2", "2026Q3"]
    state, _ = _state_with([[SEP_2026]])
    state["reports"]["2026Q3"]["url"] = listed[0]["url"]
    state["reports"]["2026Q2"] = {"url": listed[1]["url"], "parser_version": Q.PARSER_VERSION,
                                  "months": {m: {"status": "read"} for m in ("2026-04", "2026-05", "2026-06")},
                                  "attempts": [{"read_at": "2026-11-15T00:00:00Z"}]}
    assert Q.due(state, listed, "2026-11-16T13:00:00Z") == []                         # read yesterday
    # thirty days on, the newest two (and 2026Q3's unread months) are read again
    assert [e["quarter"] for e in Q.due(state, listed, "2026-12-20T00:00:00Z")] == ["2026Q2", "2026Q3"]


def test_backfill_is_accepted_and_reads_every_list_page(tmp_path, monkeypatch):
    pages = {Q.INDEX: INDEX_HTML.encode()}
    for n in (1, 2, 3):
        pages[f"{Q.INDEX}&page={n}"] = b"<table></table>"
    asked = []

    def fake_fetch(url, timeout=300):
        asked.append(url)
        if url in pages:
            return pages[url]
        return b"%PDF"
    monkeypatch.setattr(Q, "fetch", fake_fetch)
    monkeypatch.setattr(Q, "pdf_pages", lambda c: [SEP_2026])
    monkeypatch.setattr(Q, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(Q, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(Q, "ECHO_FILE", tmp_path / "none.json")
    monkeypatch.setattr(Q.common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(Q, "registry_rows", lambda: REGISTRY)
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    rc = Q.main(["--backfill"])
    assert f"{Q.INDEX}&page=3" in asked
    out = json.loads((tmp_path / f"{Q.SOURCE_ID}.json").read_text())
    # the fake copy gives September only for two quarters' worth of months: unread months fail health, records kept
    assert rc == 1 and out["ok"] is False and out["count"] >= 2
    assert out["meta"]["unread"] and out["meta"]["totals_rule"]


# ---------------------------------------------------------------- the status build's reading

def test_the_site_caution_runs_from_the_start_of_the_overflow_day():
    from build import status as SB
    rules = json.loads((SB.ROOT / "data" / "rules.json").read_text()) if hasattr(SB, "ROOT") else SB.load_rules()
    assert Q.SOURCE_ID in rules["unresolved"]["day_start_caution"]["sources"]
    state, _ = _state_with([[SEP_2026]])
    rec = next(r for r in Q.records(state, REGISTRY) if r["started_at"] == "2026-09-11")
    soon = SB._event_intervals(rec, "DC", datetime(2026, 9, 12, 12, tzinfo=UTC), None, rules)
    assert soon and soon[0]["rule"] == "day_start_caution"
    assert SB.parse_time(soon[0]["start"]) == datetime(2026, 9, 11, 4, tzinfo=UTC)     # midnight, Eastern time
    # today (2026-11-16) no caution or unresolved colour covers the District's water from this overflow
    now = SB._event_intervals(rec, "DC", datetime(2026, 11, 16, 12, tzinfo=UTC), None, rules)
    at = datetime(2026, 11, 16, 12, tzinfo=UTC)
    assert not [iv for iv in now if iv["rule"] in ("day_start_caution", "unresolved", "caution")
                and SB.parse_time(iv["start"]) <= at < SB.parse_time(iv["end"])]


# ---------------------------------------------------------------- the SSO file

SSO_CSV = ("\ufeffPremiseNo,Date Reported,SpillVolInGal,Location,Description\r\n"
           "9999991,2026-01-20 00:44:24.6070000,833333,@SAMPLE PKY @MARYLAND LINE NW,(SSO @ 1 Sample Pkwy )main break\r\n"
           "9999992,2025-10-20 09:08:29.7300000,40,12 EXAMPLE AVE NE,SSO @ 12 Example Ave NE\r\n"
           "9999993,2024-04-03 13:30:00.0000000,,@TEST AVE @TRIAL ST NE,SSO @ Test Avenue & Trial Street\\,NE\r\n"
           "9999994,2024-01-12 09:24:00.0000000,700,7 KENT ST NW,SSO @ 7 Kent St\r\n"
           "9999995,2024-01-12 09:24:00.0000000,700,8 FERN ST SE,SSO @ 8 Fern Street\r\n"
           "9999996,2023-05-08 11:54:00.0000000,50,5 UNIT 4 RD NW,x\r\n")


def test_sso_rows_keep_only_the_safe_fields():
    rows, bad = S.parse(SSO_CSV)
    assert bad == 0 and len(rows) == 6
    recs = S.to_records(rows, "2026-11-16T00:00:00Z")
    text = json.dumps(recs)
    for gone in ("9999991", "9999992", "main break", "12 EXAMPLE", "12 Example", "7 KENT", "8 FERN", "Description"
                 " repeats"):
        assert gone not in text
    by = {r["reported_at"]: r for r in recs}
    a = by["2025-10-20T09:08"]
    assert a["raw"]["location_streets"] == "[house number removed] EXAMPLE AVE NE" and a["volume_gal"] == 40
    assert a["started_at"] is None and a["event_type"] == "sso" and a["status"] == "unknown"
    assert a["lat"] is None and a["water_slugs"] == [] and a["waterbody_text"] is None
    assert by["2024-04-03T13:30"]["raw"]["location_streets"] == "TEST AVE and TRIAL ST NE"
    assert by["2024-04-03T13:30"]["volume_gal"] is None
    assert by["2023-05-08T11:54"]["raw"]["location_streets"] is None
    assert "withheld" in by["2023-05-08T11:54"]["raw"]["location_withheld"]
    # two rows reported in the same second keep distinct ids that do not hold a house number
    same = [r["source_record_id"] for r in recs if r["reported_at"] == "2024-01-12T09:24"]
    assert len(set(same)) == 2 and all(not any(c in x for c in ("7 ", "8 ")) for x in same)
    [pi] = [r["source_record_id"] for r in recs if r["reported_at"] == "2026-01-20T00:44"]
    assert re.fullmatch(r"2026-01-20T00:44:24\.607-[0-9a-f]{8}", pi)


def test_sso_changed_columns_or_an_empty_file_fail():
    with pytest.raises(ValueError, match="columns changed"):
        S.parse(SSO_CSV.replace("SpillVolInGal", "Gallons"))
    with pytest.raises(ValueError, match="no rows"):
        S.parse(SSO_CSV.split("\r\n")[0] + "\r\n")
    rows, bad = S.parse(SSO_CSV + "9999997,not a date,1,@A ST @B ST NE,x\r\n")
    assert bad == 1 and len(rows) == 6


def test_sso_a_row_that_leaves_the_file_stays_and_a_failed_read_keeps_everything(tmp_path, monkeypatch):
    rows, _ = S.parse(SSO_CSV)
    prev = {"records": S.to_records(rows, "2026-11-01T00:00:00Z")}
    now_rows = S.to_records(rows[1:], "2026-11-16T00:00:00Z")
    kept = S.carry_forward(prev, now_rows, "2026-11-16T00:00:00Z")
    assert [r["reported_at"] for r in kept] == ["2026-01-20T00:44"] and kept[0]["raw"]["not_listed_since"]
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(S, "EVENTS_DIR", tmp_path)
    (tmp_path / f"{S.SOURCE_ID}.json").write_text(json.dumps({**prev, "ok": True, "last_ok_at": "x"}))

    class Bad:
        status_code = 200
        content = SSO_CSV.replace("Location", "Where").encode()

        def raise_for_status(self):
            return None
    monkeypatch.setattr(S.requests, "get", lambda *a, **k: Bad())
    assert S.main([]) == 1
    out = json.loads((tmp_path / f"{S.SOURCE_ID}.json").read_text())
    assert out["ok"] is False and out["count"] == 6 and "columns changed" in out["error"]


def test_sso_duplicate_of_an_epa_row_needs_the_same_days_and_a_shared_street():
    rows, _ = S.parse(SSO_CSV)
    recs = S.to_records(rows, "2026-11-16T00:00:00Z")
    epa = [{"event_id": "echo:pi", "started_at": "2026-01-19T17:03", "ended_at": None,
            "location_text": "Sample Interceptor along Sample Parkway just east of the line"},
           {"event_id": "echo:other", "started_at": "2025-10-20T08:00", "ended_at": None,
            "location_text": "SSO AT ELM ST NE"}]
    assert S.link_duplicates(recs, epa) == 1
    by = {r["reported_at"]: r["duplicate_of"] for r in recs}
    assert by["2026-01-20T00:44"] == "echo:pi" and by["2025-10-20T09:08"] is None


def test_safe_location_forms():
    assert S.safe_location("1234-B FIRST ST NW") == ("[house number removed] FIRST ST NW", None)
    assert S.safe_location("@41ST ST @AMES ST NE") == ("41ST ST and AMES ST NE", None)
    assert S.safe_location("")[0] is None
    assert S.streets("41ST ST and AMES ST NE") == {"41ST STREET NE", "AMES STREET NE"}


# ---------------------------------------------------------------- review fixes (Astra, 2026-11-16)

def test_review_sso_location_and_volume_keep_only_validated_text():
    assert S.safe_location("12 ELM ST NW PAT EXAMPLE")[0] is None              # words after the street: withheld
    assert S.safe_location("@CLARA BARTON PKY @MARYLAND LINE NW")[0] == "CLARA BARTON PKY and MARYLAND LINE NW"
    rows, _ = S.parse(SSO_CSV.replace(",40,12 EXAMPLE AVE NE", ",near 12 Example Ave,12 EXAMPLE AVE NE"))
    r = next(x for x in S.to_records(rows, "t") if x["reported_at"] == "2025-10-20T09:08")
    assert r["raw"]["volume_as_given"] is None and r["volume_gal"] is None and "Example" not in json.dumps(r)


def test_review_sso_ids_do_not_depend_on_other_rows():
    rows, _ = S.parse(SSO_CSV)
    full = {r["reported_at"] + r["raw"]["location_streets"]: r["source_record_id"]
            for r in S.to_records(rows, "t") if r["reported_at"] == "2024-01-12T09:24"}
    one = [r for r in rows if not (r["reported_at"] == "2024-01-12T09:24" and "FERN" in (r["location"] or ""))]
    alone = {r["reported_at"] + r["raw"]["location_streets"]: r["source_record_id"]
             for r in S.to_records(one, "t") if r["reported_at"] == "2024-01-12T09:24"}
    k = next(iter(alone))
    assert alone[k] == full[k]
    prev = {"records": S.to_records(rows, "t")}
    now = S.to_records(one, "t2")
    assert len(now) + len(S.carry_forward(prev, now, "t2")) == len(rows)
    # an exact repeat of the kept fields is one report
    rows2, _ = S.parse(SSO_CSV + "9999998,2024-01-12 09:24:00.0000000,700,8 FERN ST SE,again\r\n")
    assert len({r["source_record_id"] for r in S.to_records(rows2, "t")}) == len(rows)


def test_review_sso_quadrants_must_agree():
    rows, _ = S.parse(SSO_CSV.replace("7 KENT ST NW", "7 K ST NW"))
    recs = S.to_records(rows, "t")
    epa = [{"event_id": "echo:se", "started_at": "2024-01-12T08:00", "ended_at": None, "location_text": "SSO AT K ST SE"}]
    assert S.link_duplicates(recs, epa) == 0
    epa[0]["location_text"] = "SSO AT K ST NW"
    assert S.link_duplicates(recs, epa) == 1


def test_review_retention_by_month_when_only_some_months_are_read():
    oct_ = SEP_2026.replace("September 2026", "October 2026").replace("9/4/26", "10/4/26").replace("9/11/26", "10/11/26")
    st_all, _ = _state_with([[SEP_2026]])
    prev = {"records": Q.records(st_all, REGISTRY) + [
        {**r, "source_record_id": r["source_record_id"].replace("09", "08"), "event_id": r["event_id"] + "x",
         "raw": {**r["raw"], "month_table": "2026-08"}} for r in Q.records(st_all, REGISTRY)]}
    st_part, _ = _state_with([[GLYPH_PAGE, SEP_2026]])
    kept = Q.retained(prev, st_part)
    assert {r["raw"]["month_table"] for r in kept} == {"2026-08"} and len(kept) == 2
    del oct_


def test_review_an_unreadable_continuation_page_leaves_the_month_unread():
    head, notes = SEP_2020.split("Notes:")
    m = Q.parse_report([head.replace("Report for September 2020", "Report for September 2020"), GLYPH_PAGE], 2020, 3)
    assert m["months"]["2020-09"]["status"] == "unread"
    # a footnote mark with no note in the section is unresolved
    marked = month_text("152 2/14/20 0 hrs. 1 mins\n" + QUIET)
    assert Q.parse_month(marked, "2020-02")["status"] == "unread"
    assert Q.parse_month(month_text("15 None N/A\n" + QUIET.replace("35 None N/A", "351 None N/A")), "2020-02")[
        "status"] == "read"


def test_review_an_unknown_structure_row_fails_the_month():
    t = month_text("15 None N/A\n" + QUIET + "36 9/12/26 5mins Deflated\n")
    assert "unknown structure" in Q.parse_month(t, "2020-02")["reason"]
    t = month_text("15 None N/A\n" + QUIET + "36 None N/A\n")
    assert "unknown structure" in Q.parse_month(t, "2020-02")["reason"]


def test_review_a_revision_that_denies_a_date_removes_its_record():
    denied = SEP_2026.replace("Notes:\n", "Notes:\n1. On 9/11/26, Structure 35 deflated. This was not an overflow to the "
                                          "river.\n").replace("35 9/11/26 47mins", "351 9/11/26 47mins")
    state, _ = _state_with([[SEP_2026], [denied]])
    ids = {r["source_record_id"] for r in Q.records(state, REGISTRY)}
    assert ids == {"s15-2026-09-04-1"}


def test_review_a_readable_table_2_1_without_the_structure_ties_nothing():
    st = Q.structure_table([TABLE_2_1.replace("35 Northeast of Roosevelt Bridge, NW 021 04/09/2026  *\n", "")])
    of, basis = Q.tie({"structures": st}, "35")
    assert of is None and "text layer" not in basis


def test_review_a_failed_reread_keeps_health_false(tmp_path, monkeypatch):
    state, _ = _state_with([[SEP_2026]])
    Q.read_quarter(state, {"quarter": "2026Q3", "year": 2026, "q": 3, "url": "u2", "published": None}, None,
                   "2026-12-20T00:00:00Z", "report not fetched: ConnectionError")
    assert "2026Q3" in state["pending"]
    orig = Q.pdf_pages
    Q.pdf_pages = lambda c: [SEP_2026]
    try:
        Q.read_quarter(state, {"quarter": "2026Q3", "year": 2026, "q": 3, "url": "u2", "published": None}, b"x",
                       "2026-12-21T00:00:00Z")
    finally:
        Q.pdf_pages = orig
    assert "2026Q3" not in state["pending"]


def test_review_backfill_follows_pages_to_the_end(monkeypatch):
    nav = lambda n: "".join(f'<a href="?term_node_tid_depth=50&amp;page={k}">{k}</a>' for k in range(n + 2))
    pages = {Q.INDEX: (INDEX_HTML.split("<a href=\"?")[0] + nav(0)).encode()}
    for n in range(1, 12):
        pages[f"{Q.INDEX}&page={n}"] = ("<table></table>" + (nav(n) if n < 11 else nav(9))).encode()
    asked = []
    monkeypatch.setattr(Q, "fetch", lambda u, timeout=120: asked.append(u) or pages[u])
    listed, odd = Q.read_index(True)
    assert f"{Q.INDEX}&page=11" in asked
