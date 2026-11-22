"""Annual workbook headers, trimmed from the saved 2023 SSO workbook rows."""
import json
from pathlib import Path

import pytest

import common
from ingest import ct_deep_annual as M

HEADERS = json.loads((Path(__file__).parent / "fixtures/ct_annual_headers.json").read_text())


@pytest.mark.parametrize("raw", HEADERS)
def test_real_repeated_headers_are_not_events(raw):
    row = M.to_dashboard_row("sso", raw)
    assert not M.is_event_row("sso", row)
    cols = [k for k in raw if not k.startswith("_")]
    assert M.sheet_rows([cols, [raw[k] for k in cols]]) == []


@pytest.mark.parametrize("kind,cols", [
    ("cso", ["Utility", "Regulator activated", "Regulator Stopped"]),
    ("sso", ["Utility", "Bypass Began or Discovered", "Bypass Ended"]),
    ("cso", ["Request ID", "Report Type", "Date Activated"]),
])
def test_parser_header_shapes_are_skipped_before_and_after_translation(kind, cols):
    assert M.sheet_rows([cols, cols]) == []
    raw = dict(zip(cols, cols))
    row = M.translate_old(kind, raw) or raw
    assert not M.is_event_row(kind, M.to_dashboard_row(kind, row))


def test_section_labels_are_skipped_but_unreadable_incidents_survive():
    assert not M.is_event_row("sso", {"Date Bypass Began or was Discovered": "NO REPORTED BYPASSES AT 002-1"})
    assert M.is_event_row("sso", {"Request ID": "90001", "Date Bypass Began or was Discovered": "unreadable"})
    assert M.is_event_row("sso", {"Date Bypass Began or was Discovered": "unreadable"})
    assert M.is_event_row("sso", {"Date Bypass Began or was Discovered": "01/02/2025",
                                  "Reporting Utility": "REPORTED THROUGH MOR"})


def test_saved_header_records_are_removed_even_if_workbook_read_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(M, "EVENTS_DIR", tmp_path)
    real = common.event(source_id=M.SOURCE_ID, source_record_id="90001", event_type="sso",
                        raw={"Request ID": "90001", "Date Bypass Began or was Discovered": "unreadable"})
    records = [real] + [common.event(source_id=M.SOURCE_ID, source_record_id=f"header-{i}", raw=raw)
                        for i, raw in enumerate(HEADERS)]
    path = tmp_path / f"{M.SOURCE_ID}.json"
    path.write_text(json.dumps({"records": records, "last_ok_at": "2026-11-04T02:34:21Z"}))
    def fail(*args):
        raise ValueError("workbook unavailable")
    monkeypatch.setattr(M, "fetch", fail)
    assert M.main(["--cached"]) == 1
    doc = json.loads(path.read_text())
    assert [r["event_id"] for r in doc["records"]] == [real["event_id"]]
    assert doc["ok"] is False and doc["last_ok_at"] == "2026-11-04T02:34:21Z"


def test_workbook_header_whitespace_is_normalized():
    cols = ["Reporting\nUtility", "Date Bypass Began\n or was Discovered"]
    rows = M.sheet_rows([cols, ["Example Utility", "01/02/2025"], cols])
    assert len(rows) == 1
    assert rows[0]["Reporting Utility"] == "Example Utility"
    assert M.is_event_row("sso", rows[0])


@pytest.mark.parametrize("date_text", ["Date Bypass Began or was Discovered", "NO REPORTED BYPASSES AT 002-1"])
def test_identifiable_incident_survives_header_text_in_date_and_failed_fetch(tmp_path, monkeypatch, date_text):
    from collections import Counter
    from datetime import datetime

    raw = {"Request ID": "90001", "Reporting Utility": "Example Utility",
           "Date Bypass Began or was Discovered": date_text}
    assert M.is_event_row("sso", raw)
    r = M.make_record("sso", raw, raw, 2, "test.xlsx", "SSO", 2026, None,
        "2026-11-22T14:00:00Z", datetime.now(M.TZ), set(), Counter())
    assert r["parse_error"] and r["source_record_id"] == "90001"
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(M, "EVENTS_DIR", tmp_path)
    path = tmp_path / f"{M.SOURCE_ID}.json"
    path.write_text(json.dumps({"records": [r], "last_ok_at": "2026-11-21T14:00:00Z"}))
    def fail(*args):
        raise ValueError("workbook unavailable")
    monkeypatch.setattr(M, "fetch", fail)
    assert M.main([]) == 1
    assert json.loads(path.read_text())["records"] == [r]


def test_header_like_cells_do_not_replace_sheet_header_when_incident_evidence_remains():
    cols = ["Request ID", "Reporting Utility", "Date Bypass Began or was Discovered"]
    rows = M.sheet_rows([cols, ["90001", cols[1], cols[2]], ["90002", "Example Utility", "01/02/2025"]])
    assert [r["Request ID"] for r in rows] == ["90001", "90002"]
    assert all(M.is_event_row("sso", r) for r in rows)
    assert M.is_event_row("sso", {cols[1]: "Example Utility", cols[2]: cols[2]})


@pytest.mark.parametrize("initial_cols,initial_values,replacement_cols,replacement_values", [
    (["Reporting Utility", "Date Bypass Began or was Discovered"],
     ["Example Utility", "11/20/2026"],
     ["Request ID", "Reporting Utility", "Date Bypass Began or was Discovered"],
     ["90001", "Example Utility", "11/21/2026"]),
    (["Request ID", "Reporting Utility", "Date Bypass Began or was Discovered"],
     ["90000", "Example Utility", "11/20/2026"],
     ["Date Bypass Began or was Discovered", "Request ID", "Reporting Utility"],
     ["11/21/2026", "90001", "Example Utility"]),
])
def test_replacement_header_remaps_added_or_reordered_columns(
        initial_cols, initial_values, replacement_cols, replacement_values):
    from collections import Counter
    from datetime import datetime

    rows = M.sheet_rows([initial_cols, initial_values, replacement_cols, replacement_values])
    assert rows == [dict(zip(initial_cols, initial_values), _row=2),
                    dict(zip(replacement_cols, replacement_values), _row=4)]
    raw = rows[1]
    row = M.to_dashboard_row("sso", raw)
    assert M.is_event_row("sso", row)
    record = M.make_record("sso", row, raw, raw["_row"], "test.xlsx", "SSO", 2026, None,
                           "2026-11-22T14:00:00Z", datetime(2026, 11, 22, tzinfo=M.TZ), set(), Counter())
    assert record["source_record_id"] == "90001"
    assert record["started_at"] == "2026-11-21T00:00:00-05:00"


@pytest.mark.parametrize("cols,values", [
    (["Reporting Utility", "Date Bypass Began or was Discovered"],
     ["Reporting Utility", "11/21/2026"]),
    (["Request ID", "Reporting Utility", "Date Bypass Began or was Discovered"],
     ["90001", "Reporting Utility", "unreadable"]),
    (["Request ID", "Reporting Utility", "Date Bypass Began or was Discovered"],
     ["Request ID", "Reporting Utility", "11/21/2026"]),
])
def test_incident_header_words_preserve_id_or_date_evidence(cols, values):
    following = ["Example Utility" if col == "Reporting Utility" else
                 "90002" if col == "Request ID" else "11/22/2026" for col in cols]
    rows = M.sheet_rows([cols, values, following])
    assert rows == [dict(zip(cols, values), _row=2), dict(zip(cols, following), _row=3)]
    assert all(M.is_event_row("sso", row) for row in rows)
