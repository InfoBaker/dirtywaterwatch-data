"""Georgia: the EPD daily spills workbook (keys, snapshot history, points, EPA pairing, privacy) and the Georgia rules
of the EPA overflow tables (no network; the workbooks are built here in the same layout as EPD's)."""
import json
import zipfile
from io import BytesIO
from pathlib import Path

import common
from ingest import echo_sewer_overflow_events as E
from ingest import ga_epd_spills as G

FIX = Path(__file__).parent / "fixtures"
HDR = ["FACILITY_NAME", "SPILL_BEGIN_DATE", "COUNTY", "CITY", "OVERFLOW_LOCATION", "QUANTITY_GALLONS",
       "OVERFLOW_TYPE", "PERMIT_NUMBER", "SPILL_SOURCE", "CAUSE", "RIVER_BASIN", "WATERWAY_IMPACTED",
       "OVERFLOW_DESTINATION"]
SERIAL = {"2026-10-30": 46325, "2026-11-02": 46328, "2026-11-03": 46329}


def col(i: int) -> str:
    return chr(65 + i)


def workbook(posting: str, rows: list[dict], header=HDR) -> bytes:
    """An .xlsx like EPD's: shared strings, row 1 'Posting Date' with a date serial, row 2 the headers."""
    strings: list[str] = []

    def s(v):
        if v not in strings:
            strings.append(v)
        return strings.index(v)
    xml_rows = [f'<row r="1"><c r="A1" t="s"><v>{s("Posting Date")}</v></c><c r="B1" s="2"><v>{SERIAL[posting]}</v></c></row>']
    cells = "".join(f'<c r="{col(i)}2" t="s"><v>{s(h)}</v></c>' for i, h in enumerate(header))
    xml_rows.append(f'<row r="2">{cells}</row>')
    for n, r in enumerate(rows, start=3):
        vals = [r.get(h, "") for h in HDR]
        xml_rows.append(f'<row r="{n}">' + "".join(f'<c r="{col(i)}{n}" t="s"><v>{s(v)}</v></c>'
                                                  for i, v in enumerate(vals)) + "</row>")
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    sheet = f'<?xml version="1.0"?><worksheet {ns}><sheetData>{"".join(xml_rows)}</sheetData></worksheet>'
    esc = lambda t: t.replace("&", "&amp;").replace("<", "&lt;")   # noqa: E731
    sst = f'<?xml version="1.0"?><sst {ns}>' + "".join(f"<si><t>{esc(t)}</t></si>" for t in strings) + "</sst>"
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", sheet)
        z.writestr("xl/sharedStrings.xml", sst)
    return buf.getvalue()


def row(**kw) -> dict:
    base = {"FACILITY_NAME": "Test County Water (Test Creek WRF)", "SPILL_BEGIN_DATE": "2026-10-29",
            "COUNTY": "Test", "CITY": "Testville", "OVERFLOW_LOCATION": "12 Elm Street Testville, Georgia 30000",
            "QUANTITY_GALLONS": "", "OVERFLOW_TYPE": "", "PERMIT_NUMBER": "GA0000001", "SPILL_SOURCE": "",
            "CAUSE": "", "RIVER_BASIN": "", "WATERWAY_IMPACTED": "", "OVERFLOW_DESTINATION": "Spill Waters of the State"}
    base.update(kw)
    return base


def posting(day: str, rows: list[dict]):
    ymd = day.replace("-", "")
    return (ymd, G.FILE_URL.format(ymd=ymd), workbook(day, rows), None)


def run(postings, prev=(), layer=None, epa=(), permits=None):
    return G.build(list(postings), list(prev), layer, list(epa), permits or {"GA0000001": "ga-test-water"},
                   "2026-11-04T00:00:00Z")


def by_id(records):
    return {r["source_record_id"]: r for r in records}


# ---------------------------------------------------------------- the workbook

def test_posting_date_serial_and_both_header_spellings():
    p, rows = G.read_posting(workbook("2026-11-03", [row()]))
    assert p == "2026-11-03" and rows[0]["begin_date"] == "2026-10-29" and rows[0]["permit_number"] == "GA0000001"
    old = ["BEGIN_DATE" if h == "SPILL_BEGIN_DATE" else h for h in HDR]
    p, rows = G.read_posting(workbook("2026-10-30", [row()], header=old))
    assert p == "2026-10-30" and rows[0]["begin_date"] == "2026-10-29"


def test_a_404_page_is_not_a_posting():
    try:
        G.read_posting(b"<html>not found</html>")
    except (zipfile.BadZipFile, ValueError):
        return
    raise AssertionError("an HTML page was read as a posting")


def test_record_fields_day_precision_and_undetermined_volume():
    recs, _ = run([posting("2026-11-02", [row(), row(OVERFLOW_LOCATION="9 Oak Rd Testville, Georgia 30000",
                                               QUANTITY_GALLONS="0")])])
    r = by_id(recs)["ga0000001-20261029-12-elm-st-testville-ga-30000"]
    assert r["event_id"] == "ga-epd-spills:ga0000001-20261029-12-elm-st-testville-ga-30000"
    assert r["started_at"] == "2026-10-29" and r["time_precision"] == "day" and r["ended_at"] is None
    assert r["status"] == "unknown" and r["event_type"] == "sso"
    assert r["published_at"] == "2026-11-02" and r["reported_at"] is None
    assert r["source_url"].endswith("sewagespillsreport20261102/download")
    assert r["volume_gal"] is None and "not yet determined" in r["volume_text"]
    assert r["discharger_id"] == "ga-test-water" and r["npdes_permit"] == "GA0000001"
    zero = by_id(recs)["ga0000001-20261029-9-oak-rd-testville-ga-30000"]
    assert zero["volume_gal"] is None and "not yet determined" in zero["volume_text"]


def test_later_postings_fill_in_the_same_record_and_keep_the_old_values():
    first = posting("2026-11-02", [row()])
    second = posting("2026-11-03", [row(QUANTITY_GALLONS="4,024", OVERFLOW_TYPE="Raw Sewage",
                                         WATERWAY_IMPACTED="Test Creek")])
    recs, stats = run([first, second])
    assert len(recs) == 1 and stats["history"] == {"new": 1, "revised": 1}
    r = recs[0]
    assert r["volume_gal"] == 4024 and r["waterbody_text"] == "Test Creek" and r["material"] == "untreated sewage"
    assert r["published_at"] == "2026-11-02"                 # first published in the earlier posting
    assert r["raw"]["_first_seen_posting"] == "2026-11-02" and r["raw"]["_last_seen_posting"] == "2026-11-03"
    rev = r["raw"]["_revisions"][0]
    assert rev["posting_before"] == "2026-11-02" and rev["old_values"]["quantity_gallons"] == ""


def test_repeated_rows_get_a_suffix_and_stay():
    recs, _ = run([posting("2026-11-02", [row(), row()])])
    ids = sorted(r["source_record_id"] for r in recs)
    assert ids[1] == ids[0] + "~2" and not any(r["duplicate_of"] for r in recs)


def test_aged_out_withdrawn_and_corrected_rows_are_kept():
    old_row = row(SPILL_BEGIN_DATE="2026-10-01", OVERFLOW_LOCATION="1 Pine Ln Testville, Georgia 30000")
    withdrawn = row(SPILL_BEGIN_DATE="2026-10-20", OVERFLOW_LOCATION="2 Ash Ct Testville, Georgia 30000")
    moved = row(SPILL_BEGIN_DATE="2026-10-25", OVERFLOW_LOCATION="3 Fir Dr Testville, Georgia 30000")
    keep = row(SPILL_BEGIN_DATE="2026-10-05")
    p1 = posting("2026-11-02", [old_row, withdrawn, moved, keep])
    p2 = posting("2026-11-03", [keep, row(SPILL_BEGIN_DATE="2026-10-22", OVERFLOW_LOCATION="3 Fir Drive Testville, Georgia 30000")])
    recs, stats = run([p1, p2])
    r = by_id(recs)
    assert len(recs) == 5
    assert r["ga0000001-20261001-1-pine-ln-testville-ga-30000"]["raw"]["_aged_out_after"] == "2026-11-02"
    w = r["ga0000001-20261020-2-ash-ct-testville-ga-30000"]
    assert w["raw"]["_missing_from_source_since"] == "2026-11-03" and w["duplicate_of"] is None
    m = r["ga0000001-20261025-3-fir-dr-testville-ga-30000"]
    assert m["duplicate_of"] == "ga-epd-spills:ga0000001-20261022-3-fir-dr-testville-ga-30000"
    assert stats["history"]["aged_out"] == 1 and stats["history"]["superseded_by_corrected_row"] == 1
    # a third posting changes nothing for the settled records
    recs3, _ = run([posting("2026-11-03", [keep])], prev=recs)
    assert by_id(recs3)["ga0000001-20261020-2-ash-ct-testville-ga-30000"]["raw"]["_missing_from_source_since"] == "2026-11-03"


def test_cso_dry_land_and_no_water_rows():
    recs, _ = run([posting("2026-11-02", [
        row(OVERFLOW_DESTINATION="CSO Dry-weather", OVERFLOW_TYPE="Raw Sewage", WATERWAY_IMPACTED="Test Creek"),
        row(OVERFLOW_LOCATION="5 Elm St", OVERFLOW_DESTINATION="Dry Land Overflow"),
        row(OVERFLOW_LOCATION="6 Elm St", WATERWAY_IMPACTED="Storm ditch"),
        row(OVERFLOW_LOCATION="7 Elm St", OVERFLOW_DESTINATION="Dry Land Overflow,Spill Waters of the State")])])
    r = {x["outfall_name"].split()[0]: x for x in recs}
    assert r["12"]["event_type"] == "cso" and r["12"]["material"] == "combined sewage (dry weather)"
    assert r["5"]["raw"]["reached_water"] is False
    assert r["6"]["waterbody_text"] is None and "no surface water" in r["6"]["raw"]["_water"]["why_none"]
    assert "reached_water" not in r["7"]["raw"]


def test_map_layer_lends_its_point_to_the_same_permit_and_address():
    layer = json.loads((FIX / "ga_epd_spills_layer.json").read_text())
    recs, _ = run([posting("2026-11-02", [row(), row(OVERFLOW_LOCATION="9 Oak Rd Testville, Georgia 30000"),
                                          row(OVERFLOW_LOCATION="4 Bay St Testville, Georgia 30000")])], layer=layer)
    r = {x["outfall_name"].split()[0]: x for x in recs}
    assert (r["12"]["lat"], r["12"]["lon"], r["12"]["coord_source"]) == (33.75, -84.39, "geocode")
    assert r["9"]["lat"] is None and "2 different points" in r["9"]["raw"]["_coords"]
    assert r["4"]["lat"] is None                              # the layer's point lies outside Georgia


# ---------------------------------------------------------------- EPA's copy

def epa(eid, day, water, permit="GA0000001"):
    return {"event_id": f"echo-sewer-overflow:{eid}", "npdes_permit": permit, "started_at": f"{day}T10:00:00",
            "ended_at": f"{day}T11:00:00", "time_precision": "minute", "event_type": "sso", "status": "ended",
            "waterbody_text": water,
            "lat": 33.0, "lon": -84.0, "duplicate_of": None, "raw": {}}


PAIR_ROWS = [row(WATERWAY_IMPACTED="Test Creek", QUANTITY_GALLONS="4024"),
             row(OVERFLOW_LOCATION="8 Elm St", WATERWAY_IMPACTED="Other Creek"),
             row(SPILL_BEGIN_DATE="2026-10-28", OVERFLOW_LOCATION="1 A St"),
             row(SPILL_BEGIN_DATE="2026-10-28", OVERFLOW_LOCATION="2 A St"),
             row(SPILL_BEGIN_DATE="2026-10-27", OVERFLOW_LOCATION="3 A St")]


def pair_run(reports, prev=()):
    layer = {"features": [{"attributes": {"PERMIT_NUMBER": "GA0000001", "LATITUDE": 33.75, "LONGITUDE": -84.39,
                                          "OVERFLOW_LOCATION": "12 Elm Street Testville, Georgia 30000"}}]}
    recs, stats = run([posting("2026-11-02", PAIR_ROWS)], prev=prev, layer=layer, epa=reports)
    return {x["outfall_name"].split()[0]: x for x in recs}, stats


def test_the_epd_record_is_primary_when_the_receiving_water_matches():
    reports = [epa("a", "2026-10-29", "TEST CREEK"), epa("b", "2026-10-29", "Unnamed tributary")]
    r, _ = pair_run(reports)
    p = r["12"]
    assert p["duplicate_of"] is None and reports[0]["duplicate_of"] == p["event_id"]
    assert p["ended_at"] == "2026-10-29T11:00:00" and p["status"] == "ended"
    assert "EPA eRule report" in p["raw"]["_end_basis"] and "echo-sewer-overflow:a" in p["raw"]["_end_basis"]
    assert p["volume_gal"] == 4024 and p["waterbody_text"] == "Test Creek"          # its own figures stay
    assert (p["lat"], p["lon"]) == (33.75, -84.39)                                  # EPD's point, not EPA's
    assert p["started_at"] == "2026-10-29" and p["time_precision"] == "day"
    assert "Georgia EPD spill list record" in reports[0]["raw"]["_duplicate_basis"]


def test_the_only_row_and_the_only_report_of_a_permit_and_day_pair():
    reports = [epa("a", "2026-10-29", "TEST CREEK"), epa("b", "2026-10-29", "Unnamed tributary")]
    r, _ = pair_run(reports)
    assert reports[1]["duplicate_of"] == r["8"]["event_id"] and r["8"]["status"] == "ended"


def test_several_left_on_both_sides_stay_unpaired_and_pairs_are_recomputed():
    reports = [epa("a", "2026-10-29", "TEST CREEK"), epa("b", "2026-10-29", "Unnamed tributary"),
               epa("c", "2026-10-28", "X Creek"), epa("d", "2026-10-28", "Y Creek"), epa("e", "2026-10-20", "Z Creek")]
    r, stats = pair_run(reports)
    assert r["1"]["ended_at"] is None and r["1"]["raw"]["_epa_candidates"] == ["echo-sewer-overflow:c",
                                                                                 "echo-sewer-overflow:d"]
    assert reports[2]["duplicate_of"] is None and reports[4]["duplicate_of"] is None   # unpaired EPA records stay
    assert r["3"]["ended_at"] is None and not any(x["duplicate_of"] for x in r.values())
    assert stats["epa_pairing"] == {"paired_by_water": 1, "paired_alone": 1, "epd_without_epa": 3,
                                    "epa_without_epd": 3}
    # the next run without EPA's reports clears the end taken from them
    again, _ = pair_run([], prev=list(r.values()))
    assert again["12"]["ended_at"] is None and again["12"]["status"] == "unknown" and "_end_basis" not in again["12"]["raw"]


# ---------------------------------------------------------------- privacy

def test_personal_details_in_free_text_never_reach_the_record():
    cause = "Blockage Rags wipes, reported by Mr. Jonathan Testperson at 404-555-0123 or jt@example.com"
    recs, _ = run([posting("2026-11-02", [row(CAUSE=cause)])])
    text = json.dumps(recs)
    assert "Testperson" not in text and "404-555-0123" not in text and "jt@example.com" not in text
    assert "Blockage Rags wipes" in text


def test_main_reads_saved_files_and_writes_the_events_file(tmp_path, monkeypatch):
    ev = tmp_path / "events"
    monkeypatch.setattr(common, "EVENTS_DIR", ev)
    monkeypatch.setattr(G, "EVENTS_DIR", ev)
    monkeypatch.setattr(G, "EPA_EVENTS", ev / "echo-sewer-overflow.json")
    f = tmp_path / "sewagespillsreport20261103.xlsx"
    f.write_bytes(workbook("2026-11-03", [row()]))
    assert G.main(["--file", str(f)]) == 0
    out = json.loads((ev / "ga-epd-spills.json").read_text())
    assert out["ok"] and out["count"] == 1 and out["meta"]["last_posting_read"] == "2026-11-03"
    assert out["records"][0]["source_url"].endswith("sewagespillsreport20261103/download")
    (ev / "echo-sewer-overflow.json").write_text(json.dumps({"source_id": "echo-sewer-overflow", "meta": {},
                                                             "records": [epa("a", "2026-10-29", "x")]}))
    assert G.main(["--file", str(f)]) == 0
    back = json.loads((ev / "echo-sewer-overflow.json").read_text())
    assert back["records"][0]["duplicate_of"] == out["records"][0]["event_id"]


# ---------------------------------------------------------------- the EPA tables in Georgia

def test_georgia_is_read_from_the_epa_tables():
    assert "GA" in E.STATES and E.REPEATED_POINT_STATES == {"GA"}


def test_did_not_enter_state_waters_is_no_water():
    for t in ("DID NOT ENTER STATE WATERS", "did not reach waters", "didnit enter state water",
              "Did not enter waters of the state."):
        assert E.NO_WATER_TEXT.match(t), t
    assert not E.NO_WATER_TEXT.match("Peachtree Creek")
    ok, why = E.reached_water({}, ["SSO"], ["DID NOT ENTER STATE WATERS"], [])
    assert not ok and why == "receiving water stated as none"
    ok, _ = E.reached_water({}, ["SSO"], ["DID NOT ENTER STATE WATERS", "Utoy Creek"], [])
    assert ok


def test_a_point_shared_by_many_reports_of_a_permit_is_not_the_spills():
    def rec(i, etype="sso", lat=33.66, permit="GA0000001"):
        return {"npdes_permit": permit, "lat": lat, "lon": -84.21, "coord_source": "source", "event_type": etype,
                "raw": {}, "event_id": str(i)}
    kept = [rec(i) for i in range(5)] + [rec(9, "bypass"), rec(10, lat=33.70), rec(11, permit="MA0000001")]
    kept += [rec(20 + i, permit="MA0000001") for i in range(5)]
    assert E.repeated_points(kept) == 5
    assert kept[0]["lat"] is None and kept[0]["raw"]["reported_point"] == [33.66, -84.21]
    assert kept[5]["lat"] == 33.66                               # a bypass happens at the plant
    assert kept[6]["lat"] == 33.70                               # a point of its own
    assert all(k["lat"] == 33.66 for k in kept[7:])              # a live state is not touched


# ---------------------------------------------------------------- Healthy Beaches

def beach_doc(**changes):
    from ingest import ga_dnr_beaches as B   # noqa: F401
    doc = json.loads((FIX / "ga_dnr_beaches.geojson").read_text())
    for f in doc["features"]:
        f["properties"].update(changes.get(f["properties"]["beachId"], {}))
    return doc


def test_beach_advisories_open_continue_and_lift_on_the_map_legend():
    from ingest import ga_dnr_beaches as B
    recs, n = B.apply_snapshot([], beach_doc(), {"fetched_at": "2026-11-04T10:00:00Z", "last_modified": None})
    r = {x["source_record_id"]: x for x in recs}
    assert set(r) == {"GA000001-2026-10-05", "GA000002-permanent"} and n["opened"] == 2   # green and gray: none
    t = r["GA000001-2026-10-05"]
    assert t["event_type"] == "beach_advisory" and t["status"] == "advisory_active"
    assert t["started_at"] == "2026-10-05" and t["time_precision"] == "day" and t["advice_text"] == B.TEMP_TEXT
    assert abs(t["lat"] - 32.001) < 0.001 and t["waterbody_text"] == "Test Beach North"
    p = r["GA000002-permanent"]
    assert p["time_precision"] == "poll" and "not published" in p["raw"]["start_basis"]
    # a new sample while the advisory stands continues it; a missing beach is not a lift
    doc = beach_doc(GA000001={"dateCollected": "10/12/2026", "entero": "120"})
    doc["features"] = [f for f in doc["features"] if f["properties"]["beachId"] != "GA000002"]
    recs, n = B.apply_snapshot(recs, doc, {"fetched_at": "2026-11-05T10:00:00Z", "last_modified": None})
    r = {x["source_record_id"]: x for x in recs}
    assert n == {"opened": 0, "continued": 1, "lifted": 0, "missing": 1}
    assert [s["date"] for s in r["GA000001-2026-10-05"]["raw"]["samples"]] == ["2026-10-05", "2026-10-12"]
    assert r["GA000002-permanent"]["status"] == "advisory_active" and r["GA000002-permanent"]["raw"]["missing_since"]
    # green lifts it at the poll that saw it
    recs, n = B.apply_snapshot(recs, beach_doc(GA000001={"status": "Green", "dateCollected": "10/19/2026"}),
                               {"fetched_at": "2026-11-06T10:00:00Z", "last_modified": None})
    t = {x["source_record_id"]: x for x in recs}["GA000001-2026-10-05"]
    assert t["status"] == "advisory_lifted" and t["ended_at"] == "2026-11-06T10:00:00Z"
    assert t["raw"]["lift_observed_between"] == ["2026-11-05T10:00:00Z", "2026-11-06T10:00:00Z"]
    assert n["lifted"] == 1 and n["opened"] == 0


def test_the_state_law_sentence_keeps_the_georgia_citation_whole():
    from export import coverage as C
    rules = json.loads((common.DATA_DIR / "rules.json").read_text())
    assert rules["red"]["by_state"]["GA"]["hours"] is None
    assert "GA" not in rules["live_states"]
    s = C.duty_sentence(rules, "GA")
    assert s.endswith("(Ga. Comp. R. & Regs. 391-3-6-.05(3)).") and "safe" not in s.lower()


def test_georgias_own_no_water_wordings_are_read_for_georgia_only():
    for t in ("Dry land", "Dryland", "N/A dry land", "dry land spill", "Not Appicable", "Non Applicable",
              "n0t applicable", "Bulding Basement", "DID NOT DISCHARGE TO STATE WATERS"):
        assert E.no_water(t, "GA"), t
    assert not E.no_water("Dry land", "MA") and not E.no_water("Private Pond", "GA")
    assert not E.no_water("MS4 stormwater system", "GA")
    ok, why = E.reached_water({}, ["SSO"], ["Dry land"], [], "GA")
    assert not ok and why == "receiving water stated as none"


# ---------------------------------------------------------------- review fixes (2026-11-04)

def test_only_a_dry_land_destination_says_the_spill_stayed_out_of_the_water():
    recs, _ = run([posting("2026-11-02", [
        row(OVERFLOW_LOCATION="5 Elm St", OVERFLOW_DESTINATION="Storm Sewer System"),
        row(OVERFLOW_LOCATION="6 Elm St", OVERFLOW_DESTINATION="Dry Land Overflow", WATERWAY_IMPACTED="Test Creek"),
        row(OVERFLOW_LOCATION="7 Elm St", OVERFLOW_DESTINATION="Dry Land Overflow", WATERWAY_IMPACTED="Ditch")])])
    r = {x["outfall_name"].split()[0]: x for x in recs}
    assert "reached_water" not in r["5"]["raw"] and "not a wording" in r["5"]["raw"]["_destination_not_read"]
    assert "reached_water" not in r["6"]["raw"] and "Test Creek" in r["6"]["raw"]["_destination_not_read"]
    assert r["7"]["raw"]["reached_water"] is False


def test_a_map_layer_outage_keeps_the_point_read_earlier():
    layer = json.loads((FIX / "ga_epd_spills_layer.json").read_text())
    first, _ = run([posting("2026-11-02", [row()])], layer=layer)
    assert first[0]["lat"] == 33.75
    again, _ = run([posting("2026-11-03", [row()])], prev=first, layer=None)
    assert (again[0]["lat"], again[0]["lon"], again[0]["coord_source"]) == (33.75, -84.39, "geocode")
    assert again[0]["raw"]["_coords_kept_from_earlier_read"] is True


def test_an_empty_posting_withdraws_nothing():
    first, _ = run([posting("2026-11-02", [row()])])
    again, stats = run([posting("2026-11-03", [])], prev=first)
    assert "_missing_from_source_since" not in again[0]["raw"] and stats["history"] == {"empty_posting": 1}


def test_a_vanished_row_is_not_made_a_duplicate_of_a_row_already_listed():
    a = row(SPILL_BEGIN_DATE="2026-10-20", OVERFLOW_LOCATION="3 Fir Dr Testville, Georgia 30000")
    b = row(SPILL_BEGIN_DATE="2026-10-23", OVERFLOW_LOCATION="3 Fir Dr Testville, Georgia 30000")
    keep = row(SPILL_BEGIN_DATE="2026-10-05")                 # the window still reaches back past 10-20
    recs, stats = run([posting("2026-11-02", [keep, a, b]), posting("2026-11-03", [keep, b])])
    gone = by_id(recs)["ga0000001-20261020-3-fir-dr-testville-ga-30000"]
    assert gone["duplicate_of"] is None and gone["raw"]["_missing_from_source_since"] == "2026-11-03"
    assert gone["ended_at"] is None and gone["status"] == "unknown"          # a vanished row gets no end
    assert stats["history"]["withdrawn_within_window"] == 1


def test_the_only_row_and_report_do_not_pair_when_they_name_different_waters():
    reports = [epa("a", "2026-10-29", "TEST CREEK"), epa("b", "2026-10-29", "Big River")]
    r, stats = pair_run(reports)
    assert r["8"]["ended_at"] is None and r["8"]["status"] == "unknown" and reports[1]["duplicate_of"] is None
    assert "'Other Creek'" in r["8"]["raw"]["_epa_not_paired"] and stats["epa_pairing"]["not_paired_contradiction"] == 1
    # a generic name ("UT", "Unnamed tributary") or one name inside the other is no contradiction
    for w in ("UT", "Unnamed Tributary to Other Creek"):
        reports = [epa("a", "2026-10-29", "TEST CREEK"), epa("b", "2026-10-29", w)]
        r, _ = pair_run(reports)
        assert reports[1]["duplicate_of"] == r["8"]["event_id"], w


def test_dry_land_on_epds_list_does_not_take_the_end_of_a_report_naming_a_water():
    rows = [row(OVERFLOW_DESTINATION="Dry Land Overflow")]
    reports = [epa("a", "2026-10-29", "Test Creek")]
    recs, _ = run([posting("2026-11-02", rows)], epa=reports)
    assert recs[0]["ended_at"] is None and reports[0]["duplicate_of"] is None
    assert "did not reach a water" in recs[0]["raw"]["_epa_not_paired"]


def test_two_spills_on_one_water_do_not_take_each_others_end():
    rows = [row(WATERWAY_IMPACTED="Test Creek"), row(OVERFLOW_LOCATION="9 Oak Rd", WATERWAY_IMPACTED="Test Creek")]
    reports = [epa("a", "2026-10-29", "Test Creek"), epa("b", "2026-10-29", "Test Creek")]
    recs, stats = run([posting("2026-11-02", rows)], epa=reports)
    assert all(x["ended_at"] is None for x in recs) and not any(e["duplicate_of"] for e in reports)
    assert stats["epa_pairing"]["same_water_ambiguous"] == 2
    assert all(len(x["raw"]["_epa_candidates"]) == 2 for x in recs)


def test_an_extreme_weather_reporting_period_is_not_the_spills_end():
    rep = {**epa("a", "2026-10-29", "Test Creek"), "started_at": "2026-10-29", "ended_at": "2026-10-31",
           "time_precision": "day"}
    recs, _ = run([posting("2026-11-02", [row(WATERWAY_IMPACTED="Test Creek")])], epa=[rep])
    assert recs[0]["ended_at"] is None and recs[0]["status"] == "unknown"
    assert rep["duplicate_of"] == recs[0]["event_id"] and "reporting period" in recs[0]["raw"]["_epa_end_not_used"]


def test_an_unreadable_older_posting_is_skipped_but_the_newest_must_be_read():
    bad = ("20261030", G.FILE_URL.format(ymd="20261030"), b"<html>moved</html>", None)
    recs, stats = run([bad, posting("2026-11-02", [row()])])
    assert len(recs) == 1 and stats["unreadable_postings"][0].startswith("20261030")
    try:
        run([posting("2026-11-02", [row()]), bad])
    except (ValueError, zipfile.BadZipFile):
        return
    raise AssertionError("an unreadable newest posting was accepted")


class _Resp:
    def __init__(self, status, content=b"", text="", headers=None):
        self.status_code, self.content, self.text, self.headers = status, content, text, headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def test_a_catch_up_day_that_fails_is_named_not_silently_skipped():
    ok = workbook("2026-11-03", [row()])
    answers = {G.PAGE_URL: _Resp(200, text='<a href="/document/document/sewagespillsreport20261103/download">'),
               G.FILE_URL.format(ymd="20261030"): _Resp(503, headers={"content-type": "text/html"}),
               G.FILE_URL.format(ymd="20261102"): _Resp(404),
               G.FILE_URL.format(ymd="20261103"): _Resp(200, content=ok)}

    class Sess:
        def get(self, url, **kw):
            return answers[url]
    errors: list = []
    got, linked = G.fetch_postings(Sess(), "2026-10-29", None, errors)
    assert linked == "20261103" and [p[0] for p in got] == ["20261103"]
    assert len(errors) == 1 and "20261030" in errors[0] and "503" in errors[0]
