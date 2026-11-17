"""ingest/me_cbep_portland_cso.py: Portland's storm-by-storm overflow filings, 2015 to 2019.

Run from pipeline/:  python -m pytest tests/test_me_cbep_portland_cso.py -q
"""
from __future__ import annotations

import hashlib
import io
import json
import zipfile

import common
from build import charts
from ingest import me_cbep_portland_cso as m


def run(tmp_path, monkeypatch) -> dict:
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    assert m.main([]) == 0
    return json.loads((tmp_path / "events" / f"{m.SOURCE_ID}.json").read_text())


def test_every_storm_and_outfall_from_the_tracked_files(tmp_path, monkeypatch):
    out = run(tmp_path, monkeypatch)
    recs = out["records"]
    assert out["ok"] is True and out["count"] == 2091 == len({r["event_id"] for r in recs})
    by_year = {}
    for r in recs:
        by_year.setdefault(r["raw"]["year"], []).append(r)
    gal = {y: sum(r["volume_gal"] for r in rs) for y, rs in by_year.items()}
    assert sorted(gal) == [2015, 2016, 2017, 2018, 2019]
    assert 185_000_000 < gal[2019] < 185_200_000          # the filing (DEP's 2019 report: 184.5 million)
    assert 318_300_000 < gal[2016] < 318_500_000          # equal to DEP's 2016 figure
    assert len({r["started_at"] for r in by_year[2019]}) == 46
    # 2019 comes from the filing only, never from CBEP's merged file
    assert {r["raw"]["file"] for r in by_year[2019]} == {m.FILING_PATH}
    assert {r["raw"]["file"] for y in (2015, 2016, 2017, 2018) for r in by_year[y]} == {m.MERGED_PATH}
    # every outfall is a registry outfall of the two Portland permits, placed on its water
    assert {r["npdes_permit"] for r in recs} == set(m.PERMITS)
    assert all(r["water_match"] == "outfall_registry" and r["water_slugs"] and r["lat"] is not None for r in recs)
    assert not [r for r in recs if r["parse_error"]] and out["meta"]["counts"]["not_in_registry"] == []
    r = next(x for x in recs if x["event_id"] == "me-cbep-portland-cso:2015-01-18:005")
    assert (r["started_at"], r["ended_at"], r["time_precision"], r["volume_gal"]) == ("2015-01-18", "2015-01-19", "day", 80000)
    assert r["event_type"] == "cso" and r["status"] == "ended" and r["estimate_flag"] == "estimated"
    assert r["source_url"].endswith("#L2") and m.COMMIT in r["source_url"]


def test_the_storm_the_filing_dates_2020_is_read_in_its_reporting_year(tmp_path, monkeypatch):
    recs = run(tmp_path, monkeypatch)["records"]
    dec = [r for r in recs if r["raw"]["file"] == m.FILING_PATH and r["raw"]["storm"] == 46]
    assert dec and {(r["started_at"], r["ended_at"]) for r in dec} == {("2019-12-13", "2019-12-15")}
    assert all(r["raw"]["date_as_filed"] == {"first": "2020-12-13", "last": "2020-12-15"} for r in dec)
    assert all("filing dates this storm 2020-12-13 to 2020-12-15" in r["volume_text"] for r in dec)
    assert 56_000_000 < sum(r["volume_gal"] for r in dec) < 57_000_000
    # a storm filed with the right dates carries no such note
    jan = [r for r in recs if r["raw"]["file"] == m.FILING_PATH and r["raw"]["storm"] == 1]
    assert jan and all("date_as_filed" not in r["raw"] and "(" not in r["volume_text"] for r in jan)


def test_cells_that_are_not_a_positive_figure_make_no_record():
    for cell in ("", "NA", "--", "Removed                     Apr 8", "BLOCK", None):
        assert m.gallons(cell) is None, cell
    assert m.gallons("0") == 0 and m.gallons("1,200") == 1200
    counts = {"storms": 0, "outfall_columns": 0, "zero": 0, "blank_na_or_note": 0, "no_date": 0, "not_in_registry": []}
    text = ("storm,row,first_day,last_day,first_as_filed,last_as_filed,outfall,cell\n"
            "1,12,2019-01-01,2019-01-01,2019-01-01,2019-01-01,005,0\n"
            "1,12,2019-01-01,2019-01-01,2019-01-01,2019-01-01,006,--\n"
            "1,12,2019-01-01,2019-01-01,2019-01-01,2019-01-01,007,1000\n")
    place = m.Placer({}, {}, {})
    recs = m.filing_records(text, place, counts)
    assert [r["outfall_id"] for r in recs] == ["007"] and counts["zero"] == 1 and counts["blank_na_or_note"] == 1
    # an outfall the registry lacks keeps its number, gets no point and says why
    assert recs[0]["lat"] is None and recs[0]["water_slugs"] == [] and "not in the outfall registry" in recs[0]["parse_error"]
    assert counts["not_in_registry"] == ["007"]


def test_a_changed_or_missing_reference_file_is_not_ok_and_keeps_the_records(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    (tmp_path / "events").mkdir()
    prev = {"source_id": m.SOURCE_ID, "ok": True, "last_ok_at": "2026-11-17T00:00:00Z", "records": [{"event_id": "x"}]}
    (tmp_path / "events" / f"{m.SOURCE_ID}.json").write_text(json.dumps(prev))
    changed = tmp_path / "merged.csv"
    changed.write_text(m.MERGED_REF.read_text().replace("80000", "80001", 1))
    monkeypatch.setattr(m, "MERGED_REF", changed)
    assert m.main([]) == 1
    out = json.loads((tmp_path / "events" / f"{m.SOURCE_ID}.json").read_text())
    assert out["ok"] is False and "differs from the pinned file" in out["error"] and out["records"] == [{"event_id": "x"}]
    monkeypatch.setattr(m, "FILING_REF", tmp_path / "absent.csv")
    monkeypatch.setattr(m, "MERGED_REF", m.DATA_DIR / "reference" / "cbep-portland-cso-2015-2019.csv")
    assert m.main([]) == 1
    out = json.loads((tmp_path / "events" / f"{m.SOURCE_ID}.json").read_text())
    assert "missing absent.csv" in out["error"] and out["records"] == [{"event_id": "x"}]


def xlsx(rows: dict[int, dict[str, object]]) -> bytes:
    """A one-sheet workbook with inline strings and numbers: {row: {"A": value}}."""
    def cell(ref, v):
        if isinstance(v, (int, float)):
            return f'<c r="{ref}"><v>{v}</v></c>'
        return f'<c r="{ref}" t="inlineStr"><is><t>{v}</t></is></c>'
    sheet = "".join(f'<row r="{rn}">' + "".join(cell(f"{c}{rn}", v) for c, v in cells.items()) + "</row>"
                    for rn, cells in sorted(rows.items()))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rel = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", f'<workbook {ns} {rel}><sheets><sheet name="S" sheetId="1" r:id="rId1"/></sheets></workbook>')
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml" Type="x"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", f"<worksheet {ns}><sheetData>{sheet}</sheetData></worksheet>")
    return buf.getvalue()


def test_the_extract_reads_the_filing_layout_and_reads_a_mistyped_year_in_the_reporting_year():
    data = xlsx({
        5: {"B": "CONTACT PERSON:", "E": "A Person"},          # never extracted
        11: {"B": "DATE", "C": "DATE", "D": "CSO 002", "E": "CSO 017"},
        12: {"A": "1", "B": 43466, "C": 43466, "D": 1000, "E": "--"},        # 2019-01-01
        13: {"A": "46", "B": 44178, "C": 44180, "E": 2500},                 # filed 2020-12-13 to 2020-12-15
        14: {"C": "TOTALS", "D": 1000},
    })
    rows = m.extract_filing(data)
    assert [(r["storm"], r["outfall"], r["cell"]) for r in rows] == [(1, "002", "1000"), (1, "017", "--"), (46, "017", "2500")]
    last = rows[-1]
    assert (last["first_day"], last["last_day"], last["first_as_filed"], last["last_as_filed"]) == (
        "2019-12-13", "2019-12-15", "2020-12-13", "2020-12-15")
    assert "Person" not in json.dumps(rows)


def keep_previous(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    (tmp_path / "events").mkdir(exist_ok=True)
    prev = {"source_id": m.SOURCE_ID, "ok": True, "last_ok_at": "2026-11-17T00:00:00Z", "records": [{"event_id": "x"}]}
    (tmp_path / "events" / f"{m.SOURCE_ID}.json").write_text(json.dumps(prev))


def result(tmp_path) -> dict:
    return json.loads((tmp_path / "events" / f"{m.SOURCE_ID}.json").read_text())


def test_a_changed_or_truncated_2019_extract_is_not_ok_and_keeps_the_records(tmp_path, monkeypatch):
    keep_previous(tmp_path, monkeypatch)
    text = m.FILING_REF.read_text()
    for name, body in (("changed.csv", text.replace(",448000", ",448001", 1)),
                       ("header-only.csv", "\n".join(text.splitlines()[:2]) + "\n")):
        f = tmp_path / name
        f.write_text(body)
        monkeypatch.setattr(m, "FILING_REF", f)
        assert m.main([]) == 1, name
        out = result(tmp_path)
        assert out["ok"] is False and "differs from the pinned extract" in out["error"], name
        assert out["records"] == [{"event_id": "x"}], name


def test_an_extract_that_cannot_be_read_is_not_ok_and_keeps_the_records(tmp_path, monkeypatch):
    keep_previous(tmp_path, monkeypatch)
    f = tmp_path / "malformed.csv"
    f.write_text(m.FILING_REF.read_text().replace("\n1,12,", "\n1,twelve,", 1))
    monkeypatch.setattr(m, "FILING_REF", f)
    monkeypatch.setattr(m, "FILING_SHA256", hashlib.sha256(f.read_bytes()).hexdigest())
    assert m.main([]) == 1
    out = result(tmp_path)
    assert out["ok"] is False and "could not be read" in out["error"] and out["records"] == [{"event_id": "x"}]


def test_the_tracked_files_match_their_pins():
    assert hashlib.sha256(m.MERGED_REF.read_bytes()).hexdigest() == m.MERGED_SHA256
    assert hashlib.sha256(m.FILING_REF.read_bytes()).hexdigest() == m.FILING_SHA256


def test_the_charts_name_the_source_and_carry_its_limits_on_both_charts():
    assert m.SOURCE_ID in charts.SOURCE_LABEL and "Casco Bay Estuary Partnership" in charts.SOURCE_LABEL[m.SOURCE_ID]
    notes = charts.SOURCE_NOTES[m.SOURCE_ID]
    assert "not metered in 2015" in notes["events"] and "no measured volume" in notes["volume"]
    assert m.SOURCE_ID in charts.VOLUME_NOTE_ALWAYS
