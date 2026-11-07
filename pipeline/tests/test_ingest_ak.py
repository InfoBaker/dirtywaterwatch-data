"""Alaska: the Alaska rules of EPA's overflow tables (the zone by the event's point, the 'which flowed to' receiving
water, a place named after a water), kept and dropped rows by reason, the stable record id, a saved ZIP, and the
other states' records unchanged. The rows are Alaska's own from the 2026-11-04 extract (permits, times, points,
volumes and texts as filed; they carry no personal names or addresses); no network."""
import csv
import io
import json
import zipfile
from pathlib import Path

import pytest

import common
from ingest import echo_sewer_overflow_events as E


def _row(key, permit, form_set, start, end, struct, struct_desc, desc, lat, lon, vol, received, other="", req="1"):
    return {"permit_identifier": permit, "program_report_form_set_id": form_set, "program_report_form_id": "1",
            "sewer_overflow_bypass_event_key": key, "sewer_overflow_bypass_event_id_ext": "1",
            "sewer_overflow_bypass_description_text": desc, "sewer_overflow_structure_type_code": struct,
            "sewer_overflow_structure_type_desc": struct_desc, "sewer_overflow_structure_type_code_other_text": other,
            "sewer_overflow_bypass_reporting_requirement_code": req, "collection_system_identifier": "001",
            "permitted_feature_identifier": "", "latitude_measure": lat, "longitude_measure": lon,
            "sewer_overflow_bypass_start_datetime": start, "sewer_overflow_bypass_end_datetime": end,
            "discharge_quantification_method_desc": "Best Professional Judgement",
            "sewer_overflow_bypass_discharge_volume_gallons": vol, "program_report_received_date": received,
            "program_report_npdes_data_group_number_code": "G9A", "program_report_start_date": "",
            "program_report_end_date": ""}


# key: (row, type, receiving waters, impact codes)
AK = {
    "28038": (_row("28038", "AK0022551", "43", "2026-10-26 05:33:00", "2026-10-26 18:10:00", "MAN", "Manhole",
                   "SSO caused from grease and rag issue", "61.145893", "-149.936183", "555.00", "2026-10-27"),
              "SSO", ["Birch Lake"], ["NOI"]),
    "7093": (_row("7093", "AK0022551", "37", "2026-03-31 11:00:00", "2026-04-01 19:00:00", "BRO", "Broken Pipe",
                  'SSO caused by a Ruptured 30" Sewer Force main', "61.200844", "-149.934130", "9600.00", "2026-04-01"),
             "SSO", ["Fish Creek which flowed to Travels to Cook Inlet"], ["NOI"]),
    "5543": (_row("5543", "AK0021440", "2", "2026-01-09 00:00:00", "2026-01-09 12:00:00", "", "",
                  "Bypass Pumpstation # 2 ", "55.357196", "-131.696532", "252000.00", "2025-12-24", req="4"),
             "BYP", ["Tongass Narrows "], ["NOI"]),
    "2778": (_row("2778", "AK0022551", "6", "2023-09-14 08:10:00", "2023-09-14 08:40:00", "PUM", "Pumping Station",
                  "SSO", "61.210157", "-149.922598", "10.00", "2023-09-14"), "SSO", [], ["NOI"]),
    "9001": (_row("9001", "AK0022551", "40", "2026-05-02 02:45:00", "", "BAS", "Basement Backup",
                  "Flushable wipes and rags", "61.15", "-149.90", "", "2026-05-04"), "SSO", [], ["NOI"]),
    "7496": (_row("7496", "AK0022551", "38", "2026-04-19 19:00:00", "2026-04-19 20:00:00", "OTH", "Other", "FOG ",
                  "61.173064", "-149.885566", "50.00", "2026-04-23", other="Toilet"), "SSO", [], ["NOI"]),
    "26995": (_row("26995", "AK0053775", "1", "2026-08-03 18:30:00", "2026-08-03 19:30:00", "MAN", "Manhole",
                   "Sewer Overflow out of manhole at Riley Creek Mercantile", "63.733132", "-148.897370", "100.00",
                   "2026-08-05"), "SSO", [], ["SLS"]),
}


def _tables(spec):
    ev, ty, rw, im = [], [], [], []
    for k, (row, t, waters, impacts) in spec.items():
        ev.append(row)
        ty.append({"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_type_code": t,
                   "sewer_overflow_bypass_type_desc": t, "sewer_overflow_bypass_type_code_sequence": "1"})
        rw += [{"sewer_overflow_bypass_event_key": k, "name_receiving_water": w} for w in waters]
        im += [{"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_impact_code": c,
                "sewer_overflow_bypass_impact_desc": c, "sewer_overflow_bypass_impact_other_text": ""} for c in impacts]
    return {"events": ev, "types": ty, "waters": rw, "impacts": im, "causes": [], "actions": [], "treatment": [],
            "systems": []}


def _build(spec):
    kept, dropped, why = E.build(_tables(spec), {"extract_date": "2026-11-04"})
    return {r["source_record_id"]: r for r in kept}, {d["source_record_id"]: d for d in dropped}, why


def test_alaska_is_read_in_its_zone_and_in_no_other_state_set():
    assert "AK" in E.STATES and E.STATE_TZ["AK"] == "America/Anchorage"
    assert "AK" not in E.FREE_TEXT_STATES and "AK" not in E.REPEATED_POINT_STATES


def test_kept_and_dropped_rows_by_reason():
    kept, dropped, why = _build(AK)
    assert set(kept) == {"AK0022551:43:1", "AK0022551:37:1", "AK0021440:2:1"}
    assert why[("AK", "kept", "receiving water named")] == 3
    assert dropped["AK0022551:40:1"]["reason"] == "building backup"            # a basement backup
    assert dropped["AK0022551:38:1"]["reason"] == "building backup"            # 'Other': Toilet
    assert dropped["AK0022551:6:1"]["reason"] == "no evidence the discharge reached a water"
    # a store named after a creek is not a water; the report gives land-surface impact only
    assert dropped["AK0053775:1:1"]["reason"] == "no evidence the discharge reached a water"


def test_alaska_times_carry_alaska_offsets():
    kept, _, _ = _build(AK)
    birch = kept["AK0022551:43:1"]
    assert birch["started_at"] == "2026-10-26T05:33:00-08:00" and birch["ended_at"] == "2026-10-26T18:10:00-08:00"
    assert kept["AK0021440:2:1"]["started_at"] == "2026-01-09T00:00:00-09:00"          # winter: AKST
    assert "America/Anchorage" in birch["raw"]["timezone_note"]
    assert birch["reported_at"] == "2026-10-27" and birch["time_precision"] == "minute"
    assert E.zoned("2026-11-01T01:30:00", "AK") == "2026-11-01T01:30:00-08:00"        # the first of the two 1:30s
    assert E.zoned("2026-07-04", "AK") == "2026-07-04"


def test_an_event_west_of_169_30_is_read_in_hawaii_aleutian_time():
    assert E.event_tz("AK", 57.12, -170.26) == "America/Adak"          # St. Paul's point
    assert E.event_tz("AK", 52.72, 174.09) == "America/Adak"           # Shemya Island, east of 180
    assert E.event_tz("AK", 53.87, -166.54) == "America/Anchorage"     # Unalaska lies east of the line
    assert E.event_tz("AK", None, None) == "America/Anchorage"
    assert E.event_tz("WA", 47.0, -170.0) is None and E.event_tz("IL", 40.0, -89.0) == "America/Chicago"
    row = dict(AK["28038"][0], latitude_measure="57.12", longitude_measure="-170.26")
    kept, _, _ = _build({"28038": (row, "SSO", ["Birch Lake"], ["NOI"])})
    r = kept["AK0022551:43:1"]
    assert r["started_at"] == "2026-10-26T05:33:00-09:00"              # HADT
    assert "America/Adak" in r["raw"]["timezone_note"] and "49 CFR 71.10" in r["raw"]["timezone_note"]


def test_receiving_water_text_and_where_it_went():
    kept, _, _ = _build(AK)
    fish = kept["AK0022551:37:1"]
    assert fish["waterbody_text"] == "Fish Creek; Cook Inlet"
    assert fish["raw"]["receiving_waters"] == ["Fish Creek which flowed to Travels to Cook Inlet"]
    assert fish["raw"]["receiving_water_aliases"] == {"Fish Creek which flowed to Travels to Cook Inlet":
                                                      "Fish Creek; Cook Inlet"}
    assert kept["AK0022551:43:1"]["waterbody_text"] == "Birch Lake"
    assert "receiving_water_aliases" not in kept["AK0022551:43:1"]["raw"]
    assert E.split_water("Fish Creek which flows into Ship Creek", "AK") == ["Fish Creek", "Ship Creek"]
    assert E.split_water("Fish Creek which flowed to Cook Inlet", "MA") == ["Fish Creek which flowed to Cook Inlet"]


def test_a_bypass_is_kept_with_its_volume_and_stable_id():
    kept, _, _ = _build(AK)
    byp = kept["AK0021440:2:1"]
    assert byp["event_type"] == "bypass" and byp["status"] == "ended" and byp["volume_gal"] == 252000
    assert byp["waterbody_text"] == "Tongass Narrows" and byp["lat"] == 55.357196
    assert byp["event_id"] == "echo-sewer-overflow:AK0021440:2:1"
    # a later version of the same report (form id 2) keeps the id
    again, _, _ = _build({"5543": (dict(AK["5543"][0], program_report_form_id="2"), "BYP", ["Tongass Narrows"], ["NOI"])})
    assert set(again) == {"AK0021440:2:1"}


def _strip(records):
    return [json.dumps({k: v for k, v in r.items() if k != "fetched_at"}, sort_keys=True) for r in records]


def test_other_states_records_are_byte_identical_with_and_without_the_alaska_rules(monkeypatch):
    others = {
        "1": (_row("1", "MA0100001", "1", "2026-07-04 19:26:00", "2026-07-04 20:06:00", "MAN", "Manhole",
                   "Overflow at Riley Creek Mercantile", "42.3", "-71.1", "500", "2026-07-06"), "SSO", [], ["NOI"]),
        "2": (_row("2", "IL0000001", "1", "2026-07-04 19:26:00", "2026-07-04 20:06:00", "MAN", "Manhole", "SSO",
                   "40.1", "-89.1", "500", "2026-07-06"), "SSO", ["Sample Creek which flowed to Sample River"], []),
        "3": (_row("3", "NH0000001", "1", "2026-01-04 10:00:00", "", "", "", "Bypass", "43.0", "-171.0", "50",
                   "2026-01-05"), "BYP", ["Sample River"], []),
        "4": (_row("4", "GA0000001", "1", "2026-03-01 10:00:00", "2026-03-01 11:00:00", "MAN", "Manhole", "SSO",
                   "33.7", "-84.4", "", "2026-03-02"), "SSO", ["Dry land"], []),
    }
    spec = {**others, **AK}
    with_ak, _, _ = E.build(_tables(spec), {"extract_date": "2026-11-04"})
    with_ak = [r for r in with_ak if not r["npdes_permit"].startswith("AK")]
    monkeypatch.setattr(E, "STATES", E.STATES - {"AK"})
    monkeypatch.setattr(E, "STATE_TZ", {k: v for k, v in E.STATE_TZ.items() if k != "AK"})
    for name in ("STATE_TZ_WEST", "STATE_WATER_SPLIT", "STATE_PLACE_NAMES"):
        monkeypatch.setattr(E, name, {})
    without, _, _ = E.build(_tables(others), {"extract_date": "2026-11-04"})
    assert _strip(with_ak) == _strip(without)
    by = {r["npdes_permit"]: r for r in with_ak}
    assert by["IL0000001"]["waterbody_text"] == "Sample Creek which flowed to Sample River"
    assert by["NH0000001"]["started_at"] == "2026-01-04T10:00:00"          # naive, whatever its longitude


def _zip(tmp_path, tables) -> Path:
    p = tmp_path / "sobe.zip"
    with zipfile.ZipFile(p, "w") as z:
        for k, name in E.TABLES.items():
            rows = tables.get(k) or []
            buf = io.StringIO()
            if rows:
                w = csv.DictWriter(buf, fieldnames=list(rows[0]))
                w.writeheader()
                w.writerows(rows)
            else:
                buf.write("sewer_overflow_bypass_event_key,permit_identifier,collection_system_identifier\n")
            z.writestr(name, buf.getvalue())
    return p


def test_main_reads_a_saved_zip_with_alaska_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(E, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(E, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    assert E.main(["--file", str(_zip(tmp_path, _tables(AK)))]) == 0
    out = json.loads((tmp_path / "events" / f"{E.SOURCE_ID}.json").read_text())
    assert out["count"] == 3 and "AK" in out["meta"]["states"]
    rules = {(r["outcome"], r["reason"]): r["count"] for r in out["meta"]["by_rule"] if r["state"] == "AK"}
    assert rules == {("kept", "receiving water named"): 3, ("dropped", "building backup"): 2,
                     ("dropped", "no evidence the discharge reached a water"): 2}
    dropped = json.loads((tmp_path / "echo-sewer-overflow-dropped.json").read_text())
    assert dropped["count"] == 4
