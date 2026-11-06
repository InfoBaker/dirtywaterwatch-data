"""EPA ECHO sewer overflow: the current-version ZIP of 2026-11-05 held no events table (only the metadata CSV and the
ERD PDF), so the module reads the current version of each report from the all-versions ZIP (module docstring,
2026-11-05). Synthetic ZIPs, no network."""
from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest
import requests

import common
from ingest import echo_sewer_overflow_events as E

REPORT_COLS = ["permit_identifier", "program_report_form_set_id", "program_report_form_id",
               "program_report_received_date", "program_report_start_date", "program_report_end_date",
               "electronic_submission_type_code", "electr_submission_type_desc",
               "program_report_npdes_data_group_number_code", "payload_id", "transaction_id", "transaction_type",
               "current_report_form_flag", "replaced_date", "replacing_payload_id"]
EVENT_COLS = ["permit_identifier", "program_report_form_set_id", "program_report_form_id",
              "sewer_overflow_bypass_event_key", "sewer_overflow_bypass_event_id_ext",
              "sewer_overflow_bypass_description_text", "sewer_overflow_bypass_reporting_requirement_code",
              "sewer_overflow_reporting_requirement_desc", "wet_weather_occurance_indicator",
              "sewer_overflow_structure_type_code", "sewer_overflow_structure_type_desc",
              "sewer_overflow_structure_type_code_other_text", "collection_system_identifier",
              "permitted_feature_identifier", "latitude_measure", "longitude_measure",
              "sewer_overflow_bypass_duration_hours", "sewer_overflow_bypass_start_datetime",
              "sewer_overflow_bypass_end_datetime", "discharge_quantification_method_code",
              "discharge_quantification_method_desc", "sewer_overflow_bypass_discharge_volume_gallons",
              "sewer_overflow_bypass_discharge_rate_gph", "anticipated_bypass_text",
              "anticipated_bypass_expect_limit_violation", "anticipated_bypass_expect_limit_violation_text",
              "payload_id", "transaction_type", "current_report_form_flag", "replaced_date", "replacing_payload_id"]
CHILD = ["permit_identifier", "program_report_form_set_id", "program_report_form_id",
         "sewer_overflow_bypass_event_key", "sewer_overflow_bypass_event_id_ext"]
VERS = ["payload_id", "transaction_type", "current_report_form_flag", "replaced_date", "replacing_payload_id"]
P = "RI0000001"


def _csv(cols, rows) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    for r in rows:
        w.writerow({c: r.get(c, "") for c in cols})
    return buf.getvalue()


def _event(key, form, flag, start, vol, ttype):
    return {"permit_identifier": P, "program_report_form_set_id": "S1", "program_report_form_id": form,
            "sewer_overflow_bypass_event_key": key, "sewer_overflow_bypass_event_id_ext": "1",
            "sewer_overflow_structure_type_code": "MH", "sewer_overflow_structure_type_desc": "Manhole",
            "collection_system_identifier": "CS1", "latitude_measure": "41.8", "longitude_measure": "-71.4",
            "sewer_overflow_bypass_start_datetime": start, "sewer_overflow_bypass_end_datetime": "2026-10-20 14:00:00",
            "discharge_quantification_method_desc": "Best Professional Judgement",
            "sewer_overflow_bypass_discharge_volume_gallons": vol, "payload_id": f"PL{form}",
            "transaction_type": ttype, "current_report_form_flag": flag}


def all_versions_zip() -> bytes:
    """One report filed twice: version 1 (form 10, event key 100) replaced by version 2 (form 11, event key 101)."""
    reports = [
        {"permit_identifier": P, "program_report_form_set_id": "S1", "program_report_form_id": "10",
         "program_report_received_date": "2026-10-21", "program_report_npdes_data_group_number_code": "G9A",
         "payload_id": "PL10", "transaction_id": "T10", "transaction_type": "N", "current_report_form_flag": "N",
         "replaced_date": "2026-10-25", "replacing_payload_id": "PL11"},
        {"permit_identifier": P, "program_report_form_set_id": "S1", "program_report_form_id": "11",
         "program_report_received_date": "2026-10-25", "program_report_start_date": "2026-10-20",
         "program_report_end_date": "2026-10-20", "program_report_npdes_data_group_number_code": "G9A",
         "electronic_submission_type_code": "ER", "electr_submission_type_desc": "Electronic",
         "payload_id": "PL11", "transaction_id": "T11", "transaction_type": "R", "current_report_form_flag": "Y"}]
    events = [_event("100", "10", "N", "2026-10-20 09:00:00", "500", "N"),
              _event("101", "11", "Y", "2026-10-20 08:30:00", "1200", "R")]
    types = [{**{c: e[c] for c in CHILD}, "sewer_overflow_bypass_type_code_id": "1", "sewer_overflow_bypass_type_code": "SSO",
              "sewer_overflow_bypass_type_desc": "Sanitary Sewer Overflow", "sewer_overflow_bypass_type_code_sequence": "1",
              "payload_id": e["payload_id"], "transaction_type": e["transaction_type"],
              "current_report_form_flag": e["current_report_form_flag"]} for e in events]
    waters = [{**{c: e[c] for c in CHILD}, "sewer_overflow_bypass_receiving_water_id": "1",
               "name_receiving_water": name, "current_report_form_flag": e["current_report_form_flag"]}
              for e, name in zip(events, ["Old Brook", "Woonasquatucket River"])]
    impacts = [{**{c: e[c] for c in CHILD}, "sewer_overflow_bypass_impact_id": "1", "sewer_overflow_bypass_impact_code": "ALI",
                "sewer_overflow_bypass_impact_desc": "Aquatic Life", "current_report_form_flag": e["current_report_form_flag"]}
               for e in events]
    systems = [{"permit_identifier": P, "collection_system_identifier": "CS1", "collection_system_name": "Sample Sewer District",
                "collection_system_owner_type_code": "MUN", "collection_system_owner_type_desc": "Municipal",
                "collection_system_population": "1000", "percent_collection_system_css": "0", "current_report_flag": flag}
               for flag in ("N", "Y")]
    files = {
        "sewer_overflow_bypass_report.csv": _csv(REPORT_COLS, reports),
        "sewer_overflow_bypass_event.csv": _csv(EVENT_COLS, events),
        "sewer_overflow_bypass_type.csv": _csv(CHILD + ["sewer_overflow_bypass_type_code_id", "sewer_overflow_bypass_type_code",
                                                        "sewer_overflow_bypass_type_desc", "sewer_overflow_bypass_type_code_sequence"] + VERS, types),
        "sewer_overflow_bypass_receiving_water.csv": _csv(CHILD + ["sewer_overflow_bypass_receiving_water_id", "name_receiving_water"] + VERS, waters),
        "sewer_overflow_bypass_impact.csv": _csv(CHILD + ["sewer_overflow_bypass_impact_id", "sewer_overflow_bypass_impact_code",
                                                          "sewer_overflow_bypass_impact_desc", "sewer_overflow_bypass_impact_other_text"] + VERS, impacts),
        "sewer_overflow_bypass_cause.csv": _csv(CHILD + ["sewer_overflow_bypass_cause_id", "sewer_overflow_bypass_cause_code",
                                                         "sewer_overflow_bypass_cause_desc", "sewer_overflow_bypass_cause_other_text"] + VERS, []),
        "sewer_overflow_bypass_corrective_action.csv": _csv(CHILD + ["sewer_overflow_bypass_corrective_action_id",
                                                                     "sewer_overflow_bypass_corrective_action_code",
                                                                     "sewer_overflow_bypass_corrective_action_desc",
                                                                     "sewer_overflow_bypass_corrective_action_other_text"] + VERS, []),
        "sewer_overflow_treatment_code.csv": _csv(CHILD + ["sewer_overflow_treatment_id", "sewer_overflow_treatment_code",
                                                           "sewer_overflow_treatment_desc", "bypass_treatment_plant_equipment_code",
                                                           "bypass_treatment_plant_equipment_desc"] + VERS, []),
        "collection_system_permit.csv": _csv(["permit_identifier", "collection_system_identifier", "collection_system_name",
                                              "collection_system_owner_type_code", "collection_system_owner_type_desc",
                                              "collection_system_population", "percent_collection_system_css", "payload_id",
                                              "received_date", "transaction_type", "current_report_flag", "replaced_date",
                                              "replacing_payload_id", "replacing_transaction_type"], systems),
    }
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for n, t in files.items():
            zf.writestr(zipfile.ZipInfo(n, (2026, 11, 4, 7, 21, 0)), t)
    return buf.getvalue()


def broken_current_zip() -> bytes:
    """What the current-version ZIP held on 2026-11-05: the metadata CSV and the ERD, no table."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("sewer_overflow_bypass_columns_metadata.csv", "table_name,column_name\n")
        zf.writestr("sewer_overflow_public_erd.pdf", b"%PDF-1.4\n")
    return buf.getvalue()


class Resp:
    def __init__(self, content: bytes, lm: str):
        self.content, self.headers, self.status_code = content, {"Last-Modified": lm}, 200

    def raise_for_status(self):
        pass


def _raw_tables():
    zf = zipfile.ZipFile(io.BytesIO(all_versions_zip()))
    return E._zip_tables(zf, E.ALL_TABLES)


def test_current_rows_from_all_versions():
    t = E.current_from_all_versions(_raw_tables())
    assert set(t) == set(E.TABLES)          # every table the build reads
    [ev] = t["events"]                      # the replaced version is gone
    assert ev["sewer_overflow_bypass_event_key"] == "101"
    assert ev["program_report_received_date"] == "2026-10-25"   # joined from the current report row
    assert ev["program_report_start_date"] == "2026-10-20"
    assert ev["event_transaction_type"] == "R" and ev["transaction_type"] == "R"
    assert ev["collection_system_owner_type_desc"] == "Municipal"
    assert not set(ev) & E.VERSION_COLUMNS
    assert [w["name_receiving_water"] for w in t["waters"]] == ["Woonasquatucket River"]   # version 1's water dropped
    assert len(t["types"]) == len(t["impacts"]) == 1
    assert len(t["systems"]) == 1 and "current_report_flag" not in t["systems"][0]


def test_missing_column_is_a_failed_read_not_a_blank():
    raw = _raw_tables()
    for r in raw["event"]:
        r.pop("latitude_measure")
    with pytest.raises(RuntimeError, match="latitude_measure"):
        E.current_from_all_versions(raw)


def test_read_zip_accepts_an_all_versions_file(tmp_path):
    p = tmp_path / "all.zip"
    p.write_bytes(all_versions_zip())
    tables, info = E.read_zip(p)
    assert info["url"] == E.ALL_URL and info["extract_date"] == "2026-11-04"
    kept, dropped, why = E.build(tables, info)
    [r] = kept
    assert r["source_record_id"] == f"{P}:S1:1"          # stable across versions
    assert r["started_at"] == "2026-10-20T08:30:00" and r["volume_gal"] == 1200
    assert r["reported_at"] == "2026-10-25" and r["published_at"] == "2026-11-04"
    assert r["waterbody_text"] == "Woonasquatucket River"


def _isolate(monkeypatch, tmp_path):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "build" / "events")
    monkeypatch.setattr(common, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(E, "BUILD_DIR", tmp_path / "build")
    monkeypatch.setattr(E, "ROOT", tmp_path)
    monkeypatch.setattr(E, "FALLBACK_DIR", tmp_path / "no-research-copy")


def test_broken_current_zip_falls_back_to_all_versions(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    served = {E.URL: Resp(broken_current_zip(), "Thu, 05 Nov 2026 12:13:23 GMT"),
              E.ALL_URL: Resp(all_versions_zip(), "Wed, 04 Nov 2026 12:21:15 GMT")}
    monkeypatch.setattr(E.requests, "get", lambda url, **kw: served[url])
    assert E.main([]) == 0
    out = json.loads((tmp_path / "build" / "events" / "echo-sewer-overflow.json").read_text())
    assert out["ok"] is True and out["count"] == 1
    assert out["meta"]["url"] == E.ALL_URL and out["meta"]["last_modified"] == "2026-11-04T12:21:15Z"
    assert "no sewer_overflow_bypass_report_events.csv" in out["meta"]["note"]
    assert out["records"][0]["source_updated_at"] == "2026-11-04T12:21:15Z"


def test_both_downloads_failing_is_reported(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)

    def get(url, **kw):
        if url == E.URL:
            return Resp(broken_current_zip(), "Thu, 05 Nov 2026 12:13:23 GMT")
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(E.requests, "get", get)
    assert E.main([]) == 1
    out = json.loads((tmp_path / "build" / "events" / "echo-sewer-overflow.json").read_text())
    assert out["ok"] is False
    assert "no sewer_overflow_bypass_report_events.csv" in out["error"] and "all-versions ZIP" in out["error"]


# ---------------------------------------------------------------- review 2026-11-06 (docs/reviews/2026-11-06-stale-sources-review.md)

def current_zip() -> bytes:
    """A repaired current-version ZIP: the all-versions fixture's current rows under the current tables' names."""
    t = E.current_from_all_versions(_raw_tables())
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for k, name in E.TABLES.items():
            rows = t.get(k) or []
            cols = list(rows[0]) if rows else ["sewer_overflow_bypass_event_key"]
            zf.writestr(zipfile.ZipInfo(name, (2026, 11, 7, 7, 15, 0)), _csv(cols, rows))
    return buf.getvalue()


@pytest.mark.parametrize("table,column", [("event", "sewer_overflow_bypass_description_text"),
                                          ("impacts", "sewer_overflow_bypass_impact_other_text"),
                                          ("event", "sewer_overflow_structure_type_code_other_text")])
def test_a_renamed_column_the_water_rule_reads_is_a_failed_read(table, column):
    # these columns decide whether an event reached a water: a rename must not silently drop events
    raw = _raw_tables()
    for r in raw[table]:
        r.pop(column)
    with pytest.raises(RuntimeError, match=column):
        E.current_from_all_versions(raw)


@pytest.mark.parametrize("table", ["event", "report", "types", "waters", "impacts", "systems"])
def test_an_empty_all_versions_table_is_a_failed_read_not_no_events(table):
    raw = _raw_tables()
    raw[table] = []
    with pytest.raises(RuntimeError, match="no rows"):
        E.current_from_all_versions(raw)


def test_a_repaired_current_zip_is_preferred_again(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    asked = []
    served = {E.URL: Resp(current_zip(), "Sat, 07 Nov 2026 12:15:00 GMT"),
              E.ALL_URL: Resp(all_versions_zip(), "Wed, 04 Nov 2026 12:21:15 GMT")}
    monkeypatch.setattr(E.requests, "get", lambda url, **kw: asked.append(url) or served[url])
    assert E.main([]) == 0
    out = json.loads((tmp_path / "build" / "events" / "echo-sewer-overflow.json").read_text())
    assert asked == [E.URL] and out["ok"] is True and out["count"] == 1
    assert out["meta"]["url"] == E.URL and out["meta"]["via"] == "live" and "note" not in out["meta"]
    assert out["records"][0]["published_at"] == "2026-11-07"


def test_a_current_zip_with_an_empty_events_table_falls_back(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(E.TABLES["events"], "sewer_overflow_bypass_event_key,permit_identifier\n")
    served = {E.URL: Resp(buf.getvalue(), "Sat, 07 Nov 2026 12:15:00 GMT"),
              E.ALL_URL: Resp(all_versions_zip(), "Wed, 04 Nov 2026 12:21:15 GMT")}
    monkeypatch.setattr(E.requests, "get", lambda url, **kw: served[url])
    assert E.main([]) == 0
    out = json.loads((tmp_path / "build" / "events" / "echo-sewer-overflow.json").read_text())
    assert out["count"] == 1 and out["meta"]["url"] == E.ALL_URL and "has no rows" in out["meta"]["note"]


def test_both_failing_reads_the_research_copy_marked_not_ok_and_keeps_previous_records(monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path)
    research = tmp_path / "research-copy"
    research.mkdir()
    with zipfile.ZipFile(io.BytesIO(current_zip())) as zf:
        zf.extractall(research)
    monkeypatch.setattr(E, "FALLBACK_DIR", research)

    def get(url, **kw):
        raise requests.ConnectionError("refused")
    monkeypatch.setattr(E.requests, "get", get)
    assert E.main([]) == 1                       # first run, nothing to keep: the research copy's records, not ok
    path = tmp_path / "build" / "events" / "echo-sewer-overflow.json"
    out = json.loads(path.read_text())
    assert out["ok"] is False and out["count"] == 1 and out["meta"]["via"] == "research copy"
    assert "all-versions ZIP" in out["error"]
    out["records"] = [{"event_id": "previous"}]
    path.write_text(json.dumps(out))
    assert E.main([]) == 1                       # a later failing run keeps what was there
    assert [r["event_id"] for r in json.loads(path.read_text())["records"]] == ["previous"]
