"""Louisiana: Baton Rouge's consent-decree quarterly reports (ingest/la_baton_rouge_quarterly.py) on synthetic pages in
the layout pypdf gives the real reports (a summary page and a collection-system table with wrapped cells, a centred row,
'None' for the water, gallons with a comma; example streets only, never kept), the layout check, the records, the
index links; the operator and register rows, the industrial "CSO" rows, the parish outlines and county-aware placement,
the rules row, the state text and the missing-waters list."""
import json
import re
from pathlib import Path

from build import status as S
from ingest import la_baton_rouge_quarterly as Q
from ingest import notification_pages as NP

ROOT = Path(__file__).resolve().parents[2]

SUMMARY = """Part D.           Reporting of Unauthorized Discharges
                 Summary of Unauthorized Discharges                                            Number
 North Plant -LA0036439 AI# 4843 Collection System                                                  2
 North Plant -LA0036439 AI# 4843 Treatment Plant                                                    1
 South Plant-LA0036412 AI# 4841 Collection System                                                  1
 South Plant-LA0036412 AI# 4841 Treatment Plant                                                     0
                                                                             Total                 4
Issued: October 30, 2026                                                                                  Page | D-1
"""
HEADER = ("     Date                Address                                Cause                                    "
          "               Action                                           Prevention                     Rec. Waters  "
          "           Amt. Gals          PS      BOD       TSS        pH      ARD")


def _row(date, addr, cause, water, gal, action="Recorded discharge and dispatched wash"):
    cols = Q.COLUMNS
    h = Q._columns(HEADER)
    line = [" "] * 400

    def put(text, at):
        for i, ch in enumerate(text):
            line[at + i] = ch
    put(date, 3)
    put(addr, h["Address"])
    put(cause, h["Cause"] - 4)
    put(action, h["Action"] - 20)
    put(water, h["Rec. Waters"])
    put(gal, h["Amt. Gals"] + 2)
    put("129       87       18       7.51      0.07", h["PS"])
    assert cols
    return "".join(line).rstrip()


def _cont(addr="", water=""):
    h = Q._columns(HEADER)
    line = [" "] * 400
    for text, at in ((addr, h["Address"]), ("truck to clean the area.", h["Action"] - 20), (water, h["Rec. Waters"])):
        for i, ch in enumerate(text):
            line[at + i] = ch
    return "".join(line).rstrip()


TABLE_N = "\n".join([
    "NORTH Sewer District Collection System LPDES LA0036439AI# 4843", "07/01/2026 To 09/30/2026", HEADER, "",
    _row("7/14/2026", "100 Example Dr", "Force Main Failure", "None", "290"),
    _cont(),
    _row("9/4/2026", "200 Sample Ave", "Blockage - Collection Line", "Example", "1,130"),
    _cont(addr="Unit", water="Bayou"),
    "BOD = biochemical oxygen demand", "Issued: October 30, 2026   Page | D-2"])
TABLE_S = "\n".join([
    "SOUTH Sewer District Collection System LPDES LA0036412 AI#4841", "07/01/2026 To 09/30/2026", HEADER,
    _cont(),
    _row("8/12/2026", "300 Model St", "Grease", "Example Creek", "9,000"),
    _cont(), "Issued: October 30, 2026   Page | D-3"])


def _parsed(pages=None):
    return Q.parse_report(pages or [SUMMARY, TABLE_N, TABLE_S])


def test_rows_dates_waters_gallons_and_layout_check():
    rep = _parsed()
    assert rep["layout_ok"] and rep["issued"] == "2026-10-30" and rep["period"] == ["2026-07-01", "2026-09-30"]
    rows = {r["date"]: r for r in rep["rows"]}
    assert rows["2026-07-14"]["receiving_water"] == "None" and rows["2026-07-14"]["gallons"] == 290
    assert rows["2026-09-04"]["receiving_water"] == "Example Bayou" and rows["2026-09-04"]["gallons"] == 1130
    assert rows["2026-08-12"]["permit"] == "LA0036412" and rows["2026-08-12"]["gallons"] == 9000
    assert rows["2026-09-04"]["cause"] == "Blockage - Collection Line" and rows["2026-08-12"]["cause"] == "Grease"
    assert rep["check"]["LA0036439"] == {"read": 2, "summary_collection": 2, "summary_plant": 1}


def test_a_report_whose_rows_do_not_match_its_summary_makes_no_records():
    rep = _parsed([SUMMARY.replace("Collection System                                                  1",
                                   "Collection System                                                  2"),
                   TABLE_N, TABLE_S])
    assert not rep["layout_ok"]
    state = {"reports": {"https://example.org/r.pdf": {**rep, "number": 99}}}
    assert Q.records(state) == []


def test_records_are_day_precision_sso_with_no_end_and_no_address():
    rep = _parsed()
    recs = Q.records({"reports": {"https://example.org/r98.pdf": {**rep, "number": 98}}})
    assert len(recs) == 3
    for r in recs:
        assert r["event_type"] == "sso" and r["status"] == "unknown" and r["ended_at"] is None
        assert r["time_precision"] == "day" and r["published_at"] == "2026-10-30" and r["raw"]["time_zone"] == Q.TZ
        assert r["raw"]["county"] == "East Baton Rouge Parish"
        text = json.dumps(r)
        assert "Example Dr" not in text and "Sample Ave" not in text and "Model St" not in text
        assert not re.search(r"\b[123]00\b", json.dumps(r["raw"]).replace('"report": 98', ""))
    none = next(r for r in recs if r["started_at"] == "2026-07-14")
    assert none["waterbody_text"] is None and none["water_slugs"] == [] and none["lat"] is None
    assert "placed on no water" in none["raw"]["placement_note"]
    named = next(r for r in recs if r["started_at"] == "2026-09-04")
    assert named["waterbody_text"] == "Example Bayou" and named["volume_gal"] == 1130
    assert named["source_record_id"] == "r98-LA0036439-2026-09-04-1"


def test_a_date_outside_the_quarter_is_kept_and_noted():
    rep = _parsed()
    rep["rows"][0]["date"] = "2025-07-14"
    recs = Q.records({"reports": {"u": {**rep, "number": 98}}})
    r = next(x for x in recs if x["started_at"] == "2025-07-14")
    assert "outside the report's quarter" in r["raw"]["date_note"]


def test_index_links():
    page = ('<a href="http://brprojects.com/wp-content/uploads/2026/10/98thQuarterlyRpt_Final.pdf">98</a>'
            '<a href="/wp-content/uploads/2026/01/95th_Quarterly_Report_Final.pdf">95</a>'
            '<a href="/wp-content/uploads/2016/10/BR_Consent_Decree-1.pdf">decree</a>')
    links = Q.report_links(page)
    assert links == {98: "https://brprojects.com/wp-content/uploads/2026/10/98thQuarterlyRpt_Final.pdf",
                     95: "https://brprojects.com/wp-content/uploads/2026/01/95th_Quarterly_Report_Final.pdf"}


def test_day_start_caution_and_rules_row():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    assert Q.SOURCE_ID in rules["unresolved"]["day_start_caution"]["sources"]
    assert "ga-epd-spills" in rules["unresolved"]["day_start_caution"]["sources"]
    row = rules["red"]["by_state"]["LA"]
    assert row["hours"] is None and "Central" in row["basis"]


def test_parish_outlines_and_county_aware_placement():
    assert S.COUNTY_STATES["LA"] == "la-counties.json" and "LA" in S.COUNTY_FIELD_STATES
    assert S.COUNTY_STATES["TX"] == "tx-counties.json" and "TX" in S.COUNTY_FIELD_STATES
    assert S.named_county("LA", "East Baton Rouge Parish")[1] == "East Baton Rouge Parish"
    doc = json.loads((ROOT / "data" / "reference" / "la-counties.json").read_text())
    assert len(doc["counties"]) == 64


def test_industrial_cso_rows_are_other():
    rows = json.loads((ROOT / "data" / "outfalls-la.json").read_text())["outfalls"]
    assert {r["npdes_permit"] for r in rows if r["supersedes"].startswith("data/outfalls-us.json")} == {"LA0005754",
                                                                                                         "LA0127268"}
    assert all(r["outfall_kind"] == "other" and r["kind_note"] for r in rows)
    # the sediment-dewatering pond and a permit with no outfall number are no sewage outfall (rule 6)
    assert "LA0117161" in {r["npdes_permit"] for r in rows}
    import common
    reg = [r for r in common.load_outfall_registry(provisional=False) if r.get("state") == "LA"]
    assert not [r for r in reg if r["outfall_kind"] == "cso"]


def test_operators_and_register():
    dis = json.loads((ROOT / "data" / "dischargers.json").read_text())
    la = [r for r in dis if r.get("state") == "LA"]
    held = [p for r in la for p in r["npdes_permits"]]
    assert len(held) == len(set(held)) and len({r["id"] for r in la}) == len(la)
    by = {r["id"]: r for r in la}
    br = by["la-city-of-baton-rouge-and-parish-of-east-baton-rouge"]
    assert {"LA0036439", "LA0036412"} <= set(br["npdes_permits"]) and br["kind"] == "sso" and "la-baton-rouge" in br["aliases"]
    assert "la-swbno" in by["la-sewerage-and-water-board-of-new-orleans"]["aliases"]
    doc = NP.load_register(ROOT / "data" / "notice-channels")
    assert NP.validate_register(doc, dis, ROOT) == []
    ids = {r["id"] for r in doc["channels"] if r["state"] == "LA"}
    assert all(f"{o['id']}-ldeq-report" in ids for o in la)
    assert {"la-ldeq-edms", "la-ldh-beach-monitoring", "la-baton-rouge-quarterly-reports"} <= ids


def test_state_text_and_missing_waters():
    t = (ROOT / "research" / "la" / "state-text.md").read_text()
    heads = re.findall(r"^\*\*(.+?)\*\*", t, re.M)
    assert heads == ["What the law requires.", "What is published.", "What is not published.",
                     "What stands in the way.", "Known problems in the data.", "What this site does about it."]
    assert "{{share_line}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t.replace("never clean", ""), re.I)
    doc = json.loads((ROOT / "research" / "la" / "receiving-waters-missing.json").read_text())
    assert doc["state"] == "LA" and doc["waters"] == len(doc["rows"])
    assert all("East Baton Rouge Parish" in r["counties"] for r in doc["rows"])
    assert not [r for r in doc["rows"] if r["name"].lower() in ("none", "lateral", "canal")]


def test_named_water_only_so_a_none_row_never_takes_the_plants_water():
    recs = Q.records({"reports": {"98": {**_parsed(), "number": 98, "url": "https://example.org/r98.pdf"}}})
    assert all(S.named_water_only(r) for r in recs)


def _pdf_state(monkeypatch, pages_by_content):
    monkeypatch.setattr(Q, "pdf_pages", lambda content: pages_by_content[content])


def test_a_failed_copy_never_replaces_an_accepted_report(monkeypatch):
    bad = [SUMMARY, TABLE_N]                       # the South table missing: 0 read against 1
    _pdf_state(monkeypatch, {b"good": [SUMMARY, TABLE_N, TABLE_S], b"bad": bad})
    state = {}
    _, err = Q.read_report(state, "https://example.org/r98.pdf", 98, b"good", "2026-11-01T00:00:00Z")
    assert err is None and len(Q.records(state)) == 3
    _, err = Q.read_report(state, "https://example.org/r98-amended.pdf", 98, b"bad", "2026-11-14T00:00:00Z")
    assert err and "kept" in err
    recs = Q.records(state)
    assert len(recs) == 3 and all(r["source_url"] == "https://example.org/r98.pdf" for r in recs)
    assert recs[0]["fetched_at"] == "2026-11-01T00:00:00Z"
    assert [a["layout_ok"] for a in state["reports"]["98"]["attempts"]] == [True, False]
    # recovery: a good copy under the new address replaces it, with no duplicate ids
    _pdf_state(monkeypatch, {b"good2": [SUMMARY, TABLE_N, TABLE_S]})
    Q.read_report(state, "https://example.org/r98-v2.pdf", 98, b"good2", "2026-11-20T00:00:00Z")
    recs = Q.records(state)
    assert len(recs) == len({r["source_record_id"] for r in recs}) == 3


def test_reports_are_kept_by_number_and_due_rules():
    state = {"reports": {"https://example.org/r95.pdf": {"number": 95, "layout_ok": True, "rows": [],
                                                        "read_at": "2026-11-14T00:00:00Z"}}}
    Q.migrate(state)
    assert list(state["reports"]) == ["95"] and state["reports"]["95"]["url"] == "https://example.org/r95.pdf"
    links = {95: "https://example.org/r95.pdf", 96: "https://example.org/r96.pdf", 90: "https://example.org/r90.pdf"}
    assert Q.due(state, links, "2026-11-15T00:00:00Z") == [(96, "https://example.org/r96.pdf")]
    assert (95, "https://example.org/r95.pdf") in Q.due(state, links, "2026-12-30T00:00:00Z")   # re-read after 30 days
    assert (95, "https://example.org/r95-b.pdf") in Q.due(state, {95: "https://example.org/r95-b.pdf"},
                                                         "2026-11-15T00:00:00Z")


def test_a_name_only_tie_beyond_25_km_is_refused_in_wv_and_la():
    from ingest import outfall_waters as OW

    class MT:
        def __init__(self, d):
            self.d = d
        waters = {"example-bayou-la": {"name": "Example Bayou", "kind": "river"}}

        def dist(self, s, lat, lon):
            return self.d

        def source_of(self, s):
            return "nhd"

        def no_outline(self, s):
            return False

        def evidence_of(self):
            return {}
    res = {"slug": "example-bayou-la", "step": "name", "how": "the only record of that name"}
    for st in ("WV", "LA"):
        o = {"state": st, "npdes_permit": f"{st}0000001", "lat": 30.4, "lon": -91.1, "receiving_water_echo": "EXAMPLE BAYOU"}
        OW.apply(o, res, MT(30_000.0))
        assert o["water_slug"] is None and "30 km" in o["no_water_reason"]
        o = {**o, "water_slug": None}
        OW.apply(o, res, MT(20_000.0))
        assert o["water_slug"] == "example-bayou-la"
    o = {"state": "OK", "npdes_permit": "OK0000001", "lat": 35.0, "lon": -97.0, "receiving_water_echo": "EXAMPLE BAYOU"}
    OW.apply(o, res, MT(30_000.0))
    assert o["water_slug"] == "example-bayou-la"                                # other states unchanged
