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
            "ended_at": f"{day}T11:00:00", "event_type": "sso", "waterbody_text": water, "duplicate_of": None}


def test_epd_rows_are_duplicates_of_the_epa_report_of_the_same_permit_and_day():
    rows = [row(WATERWAY_IMPACTED="Test Creek"), row(OVERFLOW_LOCATION="8 Elm St", WATERWAY_IMPACTED="Other Creek"),
            row(SPILL_BEGIN_DATE="2026-10-28", OVERFLOW_LOCATION="1 A St"), row(SPILL_BEGIN_DATE="2026-10-28", OVERFLOW_LOCATION="2 A St"),
            row(SPILL_BEGIN_DATE="2026-10-27", OVERFLOW_LOCATION="3 A St")]
    reports = [epa("a", "2026-10-29", "TEST CREEK"), epa("b", "2026-10-29", "Unnamed tributary"),
               epa("c", "2026-10-28", "X Creek"), epa("d", "2026-10-28", "Y Creek")]
    recs, stats = run([posting("2026-11-02", rows)], epa=reports)
    r = {x["outfall_name"].split()[0]: x for x in recs}
    assert r["12"]["duplicate_of"] == "echo-sewer-overflow:a"            # same receiving water
    assert r["8"]["duplicate_of"] == "echo-sewer-overflow:b"             # the only one left on each side
    assert r["1"]["duplicate_of"] is None and r["1"]["raw"]["_epa_candidates"] == ["echo-sewer-overflow:c",
                                                                                     "echo-sewer-overflow:d"]
    assert r["3"]["duplicate_of"] is None
    assert stats["epa_pairing"] == {"paired_by_water": 1, "paired_alone": 1, "not_paired": 2, "no_epa_report": 1}
    # recomputed each run: when EPA's report goes, the mark goes with it
    again, _ = run([posting("2026-11-02", rows)], prev=recs, epa=[])
    assert not any(x["duplicate_of"] for x in again)


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
