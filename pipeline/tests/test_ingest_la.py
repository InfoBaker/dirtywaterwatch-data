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


def test_every_failed_layout_check_is_an_error_and_named_unread(monkeypatch, tmp_path):
    """Re-review P1-2: a first-time failure, a repeated failure with no accepted copy, a failed replacement and a
    recovery; the run's health and exit code as well as the records kept."""
    import common
    bad = [SUMMARY, TABLE_N]
    _pdf_state(monkeypatch, {b"good": [SUMMARY, TABLE_N, TABLE_S], b"bad": bad, b"bad2": bad})
    state_path, events = tmp_path / "state.json", tmp_path / "events"
    events.mkdir()
    monkeypatch.setattr(Q, "STATE_PATH", state_path)
    monkeypatch.setattr(common, "EVENTS_DIR", events)

    def run(content, url, number=98):
        f = tmp_path / f"{number}-{url[-6:]}"
        f.write_bytes(content)
        code = Q.main(["--file", str(f), "--report", str(number), "--url", url])
        return code, json.loads((events / f"{Q.SOURCE_ID}.json").read_text())

    code, out = run(b"bad", "https://example.org/r98.pdf")                 # first acquisition fails
    assert code == 1 and out["ok"] is False and "98" in out["error"] and out["count"] == 0
    assert out["meta"]["failed_checks"] == ["98"] and "summary's count" in out["meta"]["unread"]["98"]["reason"]
    code, out = run(b"bad2", "https://example.org/r98-b.pdf")              # fails again, still no accepted copy
    assert code == 1 and out["ok"] is False and out["count"] == 0 and "98" in out["meta"]["unread"]
    code, out = run(b"good", "https://example.org/r98-c.pdf")              # recovery
    assert code == 0 and out["ok"] is True and out["count"] == 3 and out["meta"]["unread"] == {}
    code, out = run(b"bad", "https://example.org/r98-d.pdf")               # a failed replacement keeps the rows
    assert code == 1 and out["ok"] is False and out["count"] == 3
    assert {r["source_url"] for r in out["records"]} == {"https://example.org/r98-c.pdf"}


def test_a_report_with_no_accepted_copy_is_tried_again_on_the_reread_cadence():
    state = {"reports": {"91": {"number": 91, "url": "https://example.org/r91.pdf", "layout_ok": False, "rows": [],
                                "read_at": "2026-11-01T00:00:00Z", "check": {}, "summary": {}}}}
    links = {91: "https://example.org/r91.pdf", 95: "https://example.org/r95.pdf", 96: "https://example.org/r96.pdf"}
    state["reports"]["95"] = {"number": 95, "url": links[95], "layout_ok": True, "rows": [], "read_at": "2026-11-01T00:00:00Z"}
    state["reports"]["96"] = {"number": 96, "url": links[96], "layout_ok": True, "rows": [], "read_at": "2026-11-01T00:00:00Z"}
    assert Q.due(state, links, "2026-11-10T00:00:00Z") == []
    assert (91, links[91]) in Q.due(state, links, "2026-12-05T00:00:00Z")


def test_the_25_km_cap_is_measured_from_a_point_set_aside_as_suspect():
    """Re-review P2-6: apply() clears a suspect point (coords_problem) before measuring; in WV and LA the cap is
    measured from that point, so a 30 km name-only tie is refused and a 20 km one kept. Texas and other states keep
    the earlier behaviour (no distance, no cap)."""
    from ingest import outfall_waters as OW

    class MT:
        def __init__(self, d):
            self.d = d
        waters = {"example-bayou-la": {"name": "Example Bayou", "kind": "river"}}

        def dist(self, s, lat, lon):
            return None if lat is None or lon is None else self.d

        def source_of(self, s):
            return "nhd"

        def no_outline(self, s):
            return False

        def evidence_of(self):
            return {}
    res = {"slug": "example-bayou-la", "step": "name", "how": "the only record of that name",
           "coords_problem": "point 12 km from its named water"}

    def row(st):
        return {"state": st, "npdes_permit": f"{st}0000001", "lat": 30.4, "lon": -91.1,
                "receiving_water_echo": "EXAMPLE BAYOU"}
    for st in ("WV", "LA"):
        o = row(st)
        OW.apply(o, res, MT(30_000.0))
        assert o["water_slug"] is None and "30 km" in o["no_water_reason"] and o["echo_lat"] == 30.4
        o = row(st)
        OW.apply(o, res, MT(20_000.0))
        assert o["water_slug"] == "example-bayou-la" and o["lat"] is None and o["match"] == "name_only"
    for st in ("TX", "OK"):
        o = row(st)
        OW.apply(o, res, MT(30_000.0))
        assert o["water_slug"] == "example-bayou-la" and o["distance_m"] is None          # unchanged


def test_dash_variants_and_parish_departments_name_the_permittee():
    """Re-review P2-8: spaced, unspaced and doubled dashes; a parish department under its governing body."""
    import sys as _s
    _s.path.insert(0, str(ROOT / "scripts"))
    import wv_la_operator_rules as R
    for pn in ("Example Parish Council - Example WWTP", "Example Parish Council-Example WWTP",
               "Example Parish Council--Example WWTP", "Example Parish Council -- Example WWTP",
               "Example Parish Council --Example WWTP", "EXAMPLE PARISH COUNCIL--EXAMPLE WWTP"):
        assert R.owner_text(pn, "LA").lower() == "example parish council", pn
    assert R.owner_text("City of Example-Sample WWTP", "LA") == "City of Example"
    assert R.owner_text("EXAMPLE UTILITIES INC-SAMPLE PINES STP", "LA") == "EXAMPLE UTILITIES INC"
    assert R.owner_text("EXAMPLE-SAMPLE SEWERAGE DISTRICT", "LA") == "EXAMPLE-SAMPLE SEWERAGE DISTRICT"
    name, form, how = R.owner("Example Parish Wastewater Dept--Example WWTP", "EXAMPLE PARISH COUNCIL--EXAMPLE WWTP",
                              "Municipal or Water District", "LA", "LA0000009", [])
    assert (name, form) == ("Example Parish Council", "county") and "WWTP" not in name and "Dept" not in name
    # the committed rows: no operator name keeps a plant suffix after a dash, and every permit is held once
    dis = json.loads((ROOT / "data" / "dischargers.json").read_text())
    rows = [o for o in (dis if isinstance(dis, list) else dis.get("dischargers") or dis.get("operators")) if o.get("state") == "LA"]
    assert not [o["name"] for o in rows if re.search(r"-{1,2}\s*\S.*\b(?:WWTP|STP|Plant)\b", o["name"])]
    held = [p for o in rows for p in o.get("npdes_permits") or []]
    assert len(held) == len(set(held)) and "LA0073539" in held
    owner_row = [o for o in rows if "LA0073539" in (o.get("npdes_permits") or [])][0]
    assert owner_row["id"] == "la-st-charles-parish-council"


def test_baton_rouge_source_descriptions_follow_the_counts_and_the_reread_rule():
    """Re-review P2-10: the YAMLs' counts add up and their cadence is the code's."""
    feed = (ROOT / "data" / "sources" / "la-baton-rouge-quarterly.yaml").read_text()
    reports = (ROOT / "data" / "sources" / "la-baton-rouge-quarterly-reports.yaml").read_text()
    pairs = re.search(r"\((\d+) discharges: ([\d+, ]+)\)", feed)
    assert int(pairs.group(1)) == sum(int(x) for x in re.findall(r"\d+", pairs.group(2))) == 219
    assert "102 of the 219 rows" in feed and "(most rows)" not in feed
    for text in (feed, reports):
        assert "fetched once each" not in text and "each report fetched once" not in text
        assert f"every {Q.REREAD_DAYS} days" in text
    state = ROOT / "data" / "build" / "la-baton-rouge-state.json"
    if state.is_file():                       # the fetched reports, where this clone holds them
        recs = Q.records(json.loads(state.read_text()))
        none = [r for r in recs if (r.get("waterbody_text") or "").strip().lower() in Q.NO_WATER]
        assert len(recs) == 219 and len(none) == 102


# --- last review round (verification pass) ---

def test_an_incomplete_summary_or_a_missing_district_never_passes_or_replaces(monkeypatch):
    """Verification P1-1: the South summary line unreadable and its table gone; a district table under a permit the
    summary does not give; a table whose heading names the other district. None passes the layout check, and none
    replaces an accepted copy."""
    south_gone = "\n".join(ln for ln in SUMMARY.split("\n") if "South" not in ln)
    assert not _parsed([south_gone, TABLE_N])["layout_ok"]
    assert "LA0036412" in Q.unread_reason(_parsed([south_gone, TABLE_N]))
    stray = TABLE_S.replace("LA0036412", "LA0099999")
    assert not _parsed([SUMMARY, TABLE_N, stray])["layout_ok"]
    swapped = TABLE_S.replace("SOUTH Sewer", "NORTH Sewer")
    assert not _parsed([SUMMARY, TABLE_N, swapped])["layout_ok"]
    assert _parsed()["layout_ok"]
    _pdf_state(monkeypatch, {b"good": [SUMMARY, TABLE_N, TABLE_S], b"short": [south_gone, TABLE_N]})
    state = {}
    Q.read_report(state, "https://example.org/r98.pdf", 98, b"good", "2026-11-01T00:00:00Z")
    _, err = Q.read_report(state, "https://example.org/r98-b.pdf", 98, b"short", "2026-11-14T00:00:00Z")
    assert err and len(Q.records(state)) == 3


class _Resp:
    def __init__(self, text="", content=b""):
        self.text, self.content = text, content

    def raise_for_status(self):
        pass


def _live(monkeypatch, tmp_path, links, contents):
    """main() against a fake index and fake PDFs: links {n: url}, contents {url: bytes or an exception}."""
    import common
    state_path, events = tmp_path / "state.json", tmp_path / "events"
    events.mkdir(exist_ok=True)
    monkeypatch.setattr(Q, "STATE_PATH", state_path)
    monkeypatch.setattr(common, "EVENTS_DIR", events)
    index = " ".join(f'<a href="{u}">' for u in links.values())

    def get(url, **kw):
        if url == Q.INDEX:
            return _Resp(text=index)
        c = contents[url]
        if isinstance(c, Exception):
            raise c
        return _Resp(content=c)
    monkeypatch.setattr(Q.requests, "get", get)


def _run_at(monkeypatch, tmp_path, at):
    monkeypatch.setattr(Q, "now_iso", lambda: at)
    import common
    monkeypatch.setattr(common, "now_iso", lambda: at)
    code = Q.main([])
    return code, json.loads((tmp_path / "events" / f"{Q.SOURCE_ID}.json").read_text())


def test_failure_health_holds_until_a_successful_recovery(monkeypatch, tmp_path):
    """Verification P1-2 (Baton Rouge): failure, a run that retries nothing, a repeated failure, then recovery; the
    records, the run's health and last_ok_at at each step."""
    url = "https://example.org/98th-Quarterly-Report.pdf"
    _pdf_state(monkeypatch, {b"good": [SUMMARY, TABLE_N, TABLE_S], b"bad": [SUMMARY, TABLE_N]})
    _live(monkeypatch, tmp_path, {98: url}, {url: b"bad"})
    code, out = _run_at(monkeypatch, tmp_path, "2026-11-01T00:00:00Z")
    assert code == 1 and out["ok"] is False and out["count"] == 0 and out["last_ok_at"] is None
    code, out = _run_at(monkeypatch, tmp_path, "2026-11-02T00:00:00Z")      # nothing due: still not ok
    assert code == 1 and out["ok"] is False and "98" in out["error"] and out["last_ok_at"] is None
    assert "98" in out["meta"]["pending"]
    code, out = _run_at(monkeypatch, tmp_path, "2026-12-05T00:00:00Z")      # retried, fails again
    assert code == 1 and out["ok"] is False and out["meta"]["pending"]["98"]["since"] == "2026-11-01T00:00:00Z"
    _live(monkeypatch, tmp_path, {98: url}, {url: b"good"})
    code, out = _run_at(monkeypatch, tmp_path, "2027-01-10T00:00:00Z")      # recovered
    assert code == 0 and out["ok"] is True and out["count"] == 3 and out["last_ok_at"] == "2027-01-10T00:00:00Z"
    assert out["meta"]["pending"] == {}


def test_a_fetch_error_is_pending_until_read(monkeypatch, tmp_path):
    import requests
    url = "https://example.org/98th-Quarterly-Report.pdf"
    _pdf_state(monkeypatch, {b"good": [SUMMARY, TABLE_N, TABLE_S]})
    _live(monkeypatch, tmp_path, {98: url}, {url: requests.ConnectionError("down")})
    code, out = _run_at(monkeypatch, tmp_path, "2026-11-01T00:00:00Z")
    assert code == 1 and "98" in out["meta"]["pending"]
    _live(monkeypatch, tmp_path, {98: url}, {url: b"good"})
    code, out = _run_at(monkeypatch, tmp_path, "2026-11-02T00:00:00Z")
    assert code == 0 and out["ok"] is True and out["count"] == 3


def test_a_failed_amendment_to_an_older_report_is_retried(monkeypatch, tmp_path):
    """Verification P2-6: an accepted report 95, a failed amended copy, newer reports 97 and 98; the amendment is
    tried again on the re-read cadence and, once read, replaces 95 with no duplicate."""
    links = {95: "https://example.org/95th-Quarterly-Report.pdf", 97: "https://example.org/97th-Quarterly-Report.pdf",
             98: "https://example.org/98th-Quarterly-Report.pdf"}
    amended = "https://example.org/95th-Quarterly-Report-amended.pdf"
    _pdf_state(monkeypatch, {b"good": [SUMMARY, TABLE_N, TABLE_S], b"bad": [SUMMARY, TABLE_N]})
    _live(monkeypatch, tmp_path, links, {u: b"good" for u in links.values()})
    assert _run_at(monkeypatch, tmp_path, "2026-11-01T00:00:00Z")[0] == 0
    _live(monkeypatch, tmp_path, {**links, 95: amended}, {**{u: b"good" for u in links.values()}, amended: b"bad"})
    code, out = _run_at(monkeypatch, tmp_path, "2026-11-02T00:00:00Z")
    assert code == 1 and "95" in out["meta"]["pending"] and out["count"] == 9
    state = json.loads((tmp_path / "state.json").read_text())
    assert (95, amended) in Q.due(state, {**links, 95: amended}, "2027-03-01T00:00:00Z")
    _live(monkeypatch, tmp_path, {**links, 95: amended}, {**{u: b"good" for u in links.values()}, amended: b"good"})
    code, out = _run_at(monkeypatch, tmp_path, "2027-03-01T00:00:00Z")
    assert code == 0 and out["ok"] is True and out["count"] == 9
    assert len({r["source_record_id"] for r in out["records"]}) == 9
    assert {r["source_url"] for r in out["records"] if r["raw"]["report"] == 95} == {amended}


def test_a_receiving_water_cell_with_an_address_or_a_name_is_withheld_before_the_state(monkeypatch, tmp_path):
    """Verification P1-4: an address or a reporting name in the Rec. Waters cell never reaches the state file or a
    record; the row is kept, placed on no water, with no water name invented."""
    table = TABLE_N.replace(_row("9/4/2026", "200 Sample Ave", "Blockage - Collection Line", "Example", "1,130"),
                            _row("9/4/2026", "200 Sample Ave", "Blockage - Collection Line", "123 Example Ln", "1,130"))
    table = table.replace(_cont(addr="Unit", water="Bayou"), _cont(addr="Unit"))
    table_s = TABLE_S.replace("Example Creek", "Reported by: Example Person")
    url = "https://example.org/98th-Quarterly-Report.pdf"
    _pdf_state(monkeypatch, {b"pdf": [SUMMARY, table, table_s]})
    _live(monkeypatch, tmp_path, {98: url}, {url: b"pdf"})
    code, out = _run_at(monkeypatch, tmp_path, "2026-11-01T00:00:00Z")
    assert code == 0 and out["count"] == 3
    for blob in ((tmp_path / "state.json").read_text(), json.dumps(out)):
        for bad in ("123 Example", "Example Ln", "Example Person"):
            assert bad not in blob, bad
    w = {r["started_at"]: r for r in out["records"]}
    for d in ("2026-09-04", "2026-08-12"):
        assert w[d]["waterbody_text"] is None and w[d]["raw"]["receiving_water_as_given"] is None
        assert "withheld" in w[d]["raw"]["placement_note"]


def test_an_older_state_row_with_an_address_in_the_water_cell_is_cleaned_before_any_record():
    rep = _parsed()
    rep["rows"][1]["receiving_water"] = "123 EXAMPLE LANE"
    state = {"reports": {"98": {**rep, "number": 98, "url": "https://example.org/r98.pdf"}}}
    recs = Q.records(state)
    assert "123 EXAMPLE" not in json.dumps(state) and "123 EXAMPLE" not in json.dumps(recs)


# --- round 3 (Astra verify2 P1-1) ---

def test_suffixed_house_numbers_contact_and_honorific_forms_never_reach_the_state_or_the_events(monkeypatch, tmp_path):
    """Astra verify2 P1-1: '123-A Example Lane', '12 1/2 Example St', 'Contact Example Person' and 'Dr. Example
    Person' in the Rec. Waters cell of an accepted report: withheld before the state file and every events write (a
    good run, and a later run whose index read fails), the rows kept and placed on no water."""
    import requests
    cells = ["123-A Example Lane", "12 1/2 Example St", "Contact Example Person", "Dr. Example Person",
             "dr. example person", "Example Person", "Ward Creek, contact Example Person"]
    for cell in cells:
        assert Q.receiving_water(cell)[0] is None, cell
    for ok in ("Ward Creek", "Bayou Fountain", "Clay Cut Bayou", "Harelson Lateral", "University Lake", "Canal", "None"):
        assert Q.receiving_water(ok) == (ok, None), ok
    table = TABLE_N.replace(_row("9/4/2026", "200 Sample Ave", "Blockage - Collection Line", "Example", "1,130"),
                            _row("9/4/2026", "200 Sample Ave", "Blockage - Collection Line", "123-A Example Lane", "1,130"))
    table = table.replace(_cont(addr="Unit", water="Bayou"), _cont(addr="Unit"))
    table_s = TABLE_S.replace("Example Creek", "Contact Example Person")
    url = "https://example.org/98th-Quarterly-Report.pdf"
    _pdf_state(monkeypatch, {b"pdf": [SUMMARY, table, table_s]})
    _live(monkeypatch, tmp_path, {98: url}, {url: b"pdf"})
    code, out = _run_at(monkeypatch, tmp_path, "2026-11-01T00:00:00Z")
    assert code == 0 and out["count"] == 3
    blobs = [(tmp_path / "state.json").read_text(), json.dumps(out)]
    # an older state written before this check, then an index read that fails: the state and the retained events
    # are cleaned before they are written again
    state = json.loads(blobs[0])
    state["reports"]["98"]["rows"][0]["receiving_water"] = "Dr. Example Person"
    state["reports"]["98"]["rows"][0].pop("receiving_water_withheld", None)
    (tmp_path / "state.json").write_text(json.dumps(state))
    ev = json.loads(blobs[1])
    ev["records"][0]["waterbody_text"] = ev["records"][0]["raw"]["receiving_water_as_given"] = "Dr. Example Person"
    (tmp_path / "events" / f"{Q.SOURCE_ID}.json").write_text(json.dumps(ev))

    def down(url, **kw):
        raise requests.ConnectionError("index down")
    monkeypatch.setattr(Q.requests, "get", down)
    code, out2 = _run_at(monkeypatch, tmp_path, "2026-11-02T00:00:00Z")
    assert code == 1 and out2["ok"] is False and out2["count"] == 3 and "index" in out2["error"]
    blobs += [(tmp_path / "state.json").read_text(), json.dumps(out2)]
    for blob in blobs:
        for bad in ("123-A", "Example Lane", "Example Person", "example person"):
            assert bad not in blob, (bad, blob[:300])
    w = {r["started_at"]: r for r in out2["records"]}
    for d in ("2026-09-04", "2026-08-12"):
        assert w[d]["waterbody_text"] is None and "withheld" in w[d]["raw"]["placement_note"]
