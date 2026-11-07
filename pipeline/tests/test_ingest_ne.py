"""Nebraska: the Nebraska rules of EPA's overflow tables (the zone by the event's point against the Mountain-time
counties, the free-text scrub, --file), on real Nebraska rows (tests/fixtures/ne_sobe_rows.json: thirteen events of the
2026-11-04 extract; one house address replaced by a placeholder), the proof that adding the state changes no other
state's record, and the Beach Watch fetch block (tests/fixtures/ne_dwee_beachwatch.json: real rows of the layer)."""
import copy
import csv
import io
import json
import zipfile
from pathlib import Path

import common
from ingest import echo_sewer_overflow_events as E

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]


def _fixture() -> dict:
    return json.loads((FIX / "ne_sobe_rows.json").read_text())


def _build(tables=None):
    t = copy.deepcopy(tables or _fixture())
    return E.build(t, {"extract_date": "2026-11-04", "last_modified": "2026-11-04T12:21:15Z"})


def test_nebraska_is_read_with_the_point_zone_and_the_scrub():
    assert "NE" in E.STATES and E.STATE_TZ["NE"] == "America/Chicago" and E.STATE_TZ["IL"] == "America/Chicago"
    assert E.POINT_ZONE_FILES["NE"] == "ne-mountain-time-counties.json"
    assert "NE" in E.FREE_TEXT_STATES and "NE" not in E.REPEATED_POINT_STATES and "NE" not in E.STATE_NO_WATER


def test_the_mountain_counties_file_cites_the_boundary_and_holds_eighteen_counties_and_cherrys_west():
    doc = json.loads((ROOT / "data" / "reference" / "ne-mountain-time-counties.json").read_text())
    assert doc["law"]["cite"] == "49 CFR 71.7(c)" and doc["zone"] == "America/Denver"
    assert sorted(c["county"] for c in doc["counties"]) == sorted(
        [f"{n} County" for n in ("Arthur", "Banner", "Box Butte", "Chase", "Cheyenne", "Dawes", "Deuel", "Dundy",
                                 "Garden", "Grant", "Hooker", "Keith", "Kimball", "Morrill", "Perkins",
                                 "Scotts Bluff", "Sheridan", "Sioux")] + ["Cherry County, western part"])
    assert [c["county"] for c in doc["split_counties"]] == ["Cherry County"]
    assert "tigerweb.geo.census.gov" in doc["source"]["url"] and "NTAD_Time_Zones" in doc["checked_against"]["url"]


def test_the_zone_is_the_zone_of_the_events_own_point():
    assert E.point_zone("NE", 41.866, -103.667)[0] == "America/Denver"        # Scottsbluff, Scotts Bluff County
    assert E.point_zone("NE", 41.128, -101.719)[0] == "America/Denver"        # Ogallala, Keith County
    assert E.point_zone("NE", 41.123, -100.765)[0] == "America/Chicago"       # North Platte, Lincoln County
    assert E.point_zone("NE", 41.257, -95.935)[0] == "America/Chicago"        # Omaha
    tz, basis = E.point_zone("NE", 42.917, -101.700)                         # Merriman, western Cherry County
    assert tz == "America/Denver" and "Cherry County, western part" in basis
    tz, basis = E.point_zone("NE", 42.873, -100.551)                         # Valentine, eastern Cherry County
    assert tz == "America/Chicago" and "Cherry County" in basis and "split" in basis
    tz, basis = E.point_zone("NE", None, None)
    assert tz == "America/Chicago" and basis.startswith("no point given")
    assert E.point_zone("IL", 41.9, -87.6) == (None, None)                    # a one-zone state is not read by point
    assert E.zoned("2026-07-04T19:26:00", "NE", "America/Denver") == "2026-07-04T19:26:00-06:00"
    assert E.zoned("2026-07-04T19:26:00", "NE") == "2026-07-04T19:26:00-05:00"
    assert E.zoned("2026-07-04T19:26:00", "IL") == "2026-07-04T19:26:00-05:00"  # unchanged for Illinois


def test_real_rows_kept_and_dropped_by_reason():
    kept, dropped, why = _build()
    assert sorted(r["source_record_id"] for r in kept) == sorted([
        "NE0112810:63:1", "NE0036358:7:1", "NE0021245:3:1", "NE0021148:6:1", "NE0133680:8:1", "NE0023965:1:1",
        "NE0112810:11:1", "NE0021199:2:1", "NE0021199:1:2", "NE0021199:1:1", "NE0133680:1:1"])
    assert {d["source_record_id"]: d["reason"] for d in dropped} == {
        "NE0043702:10:1": "building backup",                                  # a basement backup in Grand Island
        "NE0112488:1:1": "no evidence the discharge reached a water",         # a manhole SSO naming no water
    }
    assert {(o, r): n for (st, o, r), n in why.items() if st == "NE"} == {
        ("kept", "receiving water named"): 9, ("kept", "impact to a water (AHI)"): 1,
        ("kept", "CSO at a CSO outfall or regulator"): 1,
        ("dropped", "building backup"): 1, ("dropped", "no evidence the discharge reached a water"): 1}
    by = {r["source_record_id"]: r for r in kept}
    assert by["NE0023965:1:1"]["event_type"] == "bypass" and by["NE0023965:1:1"]["volume_gal"] == 300000   # kept
    assert by["NE0133680:1:1"]["event_type"] == "cso" and by["NE0133680:1:1"]["raw"]["reached_water_rule"] == \
        "CSO at a CSO outfall or regulator"                                   # Omaha's CSO permit, at outfall 204
    assert by["NE0021148:6:1"]["time_precision"] == "day"                     # an extreme-event report: the period


def test_times_carry_the_zone_of_the_point_and_say_which_county_decided():
    by = {r["source_record_id"]: r for r in _build()[0]}
    om = by["NE0112810:63:1"]                                                 # Omaha, September: CDT
    assert om["started_at"] == "2026-09-11T14:34:00-05:00" and om["ended_at"] == "2026-09-11T14:35:00-05:00"
    assert "America/Chicago" in om["raw"]["timezone_note"] and "49 CFR 71.7(c)" in om["raw"]["timezone_note"]
    assert by["NE0133680:8:1"]["started_at"] == "2026-03-05T12:10:00-06:00"   # March 5: CST
    assert by["NE0021148:6:1"]["started_at"] == "2026-06-05"                  # a date stays a date
    fx = _fixture()                                                           # the same row filed from Scottsbluff
    ev = next(e for e in fx["events"] if e["permit_identifier"] == "NE0112810" and e["program_report_form_set_id"] == "63")
    ev["latitude_measure"], ev["longitude_measure"] = "41.866", "-103.667"
    moved = next(r for r in _build(fx)[0] if r["source_record_id"] == "NE0112810:63:1")
    assert moved["started_at"] == "2026-09-11T14:34:00-06:00"
    assert "America/Denver" in moved["raw"]["timezone_note"] and "Scotts Bluff County" in moved["raw"]["timezone_note"]


def test_the_receiving_water_text_is_kept_as_reported():
    by = {r["source_record_id"]: r for r in _build()[0]}
    assert by["NE0112810:63:1"]["waterbody_text"] == "Big Papillion Creek"
    assert by["NE0021245:3:1"]["waterbody_text"] == "Missouri River at South Table Creek"
    assert by["NE0021148:6:1"]["waterbody_text"] == "Big Nemaha River (Segment NE2-10000)"
    assert by["NE0112810:11:1"]["waterbody_text"] == "Unknown"                # a storm inlet; the water not named
    assert by["NE0021199:2:1"]["waterbody_text"] is None                      # kept by its aquatic-habitat impact
    assert by["NE0021245:3:1"]["raw"]["receiving_waters"] == ["Missouri River at South Table Creek"]


def test_source_record_ids_are_stable_and_name_the_report():
    a, b = _build()[0], _build()[0]
    assert [r["event_id"] for r in a] == [r["event_id"] for r in b]
    assert all(r["source_record_id"].count(":") == 2 and r["source_record_id"].startswith("NE") for r in a)
    fx = _fixture()
    for e in fx["events"]:
        if e["permit_identifier"] == "NE0021199" and e["program_report_form_set_id"] == "1":
            e["program_report_form_id"] = "999"                               # a later version of the same report
    ids = {r["source_record_id"] for r in _build(fx)[0]}
    assert {"NE0021199:1:1", "NE0021199:1:2"} <= ids                          # two events of one report stay two


def test_a_house_address_never_reaches_a_nebraska_record():
    kept, dropped, _ = _build()
    blob = json.dumps(kept) + json.dumps(dropped)
    assert "1234" not in blob and "located at [house number removed] Sample Street" in blob
    fx = _fixture()
    ev = next(e for e in fx["events"] if e["permit_identifier"] == "NE0133680" and e["program_report_form_set_id"] == "8")
    ev["sewer_overflow_bypass_description_text"] = "Water Main break near 4321 Sample St caused an overflow at CSO 204"
    one = next(r for r in _build(fx)[0] if r["source_record_id"] == "NE0133680:8:1")
    assert one["raw"]["sewer_overflow_bypass_description_text"] == (
        "Water Main break near [house number removed] Sample St caused an overflow at CSO 204")   # the outfall stays


def test_adding_nebraska_changes_no_other_states_record(monkeypatch):
    """The same tables built with and without NE give identical records for every other state (also checked on the
    real 2026-11-04 extract: 1,809 kept and 1,741 dropped records of the other states identical)."""
    from tests.test_ingest_dc import _row
    fx = _fixture()
    other = [_row(sewer_overflow_bypass_event_key="o1", latitude_measure="38.9300", longitude_measure="-77.0400"),
             _row(sewer_overflow_bypass_event_key="o2", permit_identifier="IL0000001", program_report_form_set_id="2",
                  sewer_overflow_bypass_description_text="Break at 4521 Sample Prairie Dr."),
             _row(sewer_overflow_bypass_event_key="o3", permit_identifier="NH0000001", program_report_form_set_id="3",
                  sewer_overflow_bypass_description_text="Overflow at a manhole")]
    fx["events"] += other
    fx["types"] += [{"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_type_code": "SSO",
                     "sewer_overflow_bypass_type_desc": "", "sewer_overflow_bypass_type_code_sequence": "1"}
                    for k in ("o1", "o2", "o3")]
    fx["waters"] += [{"sewer_overflow_bypass_event_key": "o1", "name_receiving_water": "Rock Creek"},
                     {"sewer_overflow_bypass_event_key": "o2", "name_receiving_water": "Unknown"},
                     {"sewer_overflow_bypass_event_key": "o3", "name_receiving_water": "Sample Brook"}]

    def others(states):
        monkeypatch.setattr(E, "STATES", states)
        kept, dropped, _ = _build(fx)
        return sorted(json.dumps({k: v for k, v in r.items() if k != "fetched_at"}, sort_keys=True)
                      for r in kept + dropped if not str(r.get("npdes_permit") or r.get("permit")).startswith("NE"))
    with_ne, without_ne = others(set(E.STATES)), others(set(E.STATES) - {"NE"})
    assert with_ne == without_ne and len(with_ne) == 3
    nh = json.loads(next(r for r in with_ne if "NH0000001" in r))
    assert nh["started_at"] == "2026-01-19T17:03:00" and nh["raw"]["timezone_note"] == E.TZ_NOTE   # naive, as before


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
                buf.write("sewer_overflow_bypass_event_key\n")
            z.writestr(name, buf.getvalue())
    return p


def test_main_reads_a_saved_zip_of_nebraska_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(E, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(E, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    assert E.main(["--file", str(_zip(tmp_path, _fixture()))]) == 0
    doc = json.loads((tmp_path / "events" / "echo-sewer-overflow.json").read_text())
    assert doc["count"] == 11 and "NE" in doc["meta"]["states"]
    assert sum(x["count"] for x in doc["meta"]["by_rule"] if x["state"] == "NE" and x["outcome"] == "kept") == 11
    dropped = json.loads((tmp_path / "echo-sewer-overflow-dropped.json").read_text())
    assert dropped["count"] == 2


# ---------------------------------------------------------------- DWEE Beach Watch (generic ArcGIS block)

def _beachwatch():
    from ingest.generic import arcgis, runner
    _, block = runner.load_source("ne-dwee-beachwatch")
    rows = arcgis.parse(block, (FIX / "ne_dwee_beachwatch.json").read_bytes())
    return runner.build("ne-dwee-beachwatch", block, rows, "2026-11-07T01:14:00Z", [])


def test_beachwatch_block_asks_only_for_alert_and_e_coli_rows_and_safe_fields():
    from ingest.generic import runner
    _, block = runner.load_source("ne-dwee-beachwatch")
    assert block["live"] is True and block["platform"] == "arcgis" and not runner.validate_block(block)
    assert "HealthAlert = 'YES'" in block["where"] and "EColiRisk" in block["where"]
    assert block["time_zone"] == "America/Chicago"


def test_beachwatch_health_alert_is_the_authoritys_bloom_advisory_and_e_coli_a_caution():
    recs, stats = _beachwatch()
    by = {r["source_record_id"]: r for r in recs}
    rock = by["LBB1ROCKFD04-2026-w23"]
    assert rock["event_type"] == "hab_advisory" and rock["status"] == "advisory_active"
    assert rock["started_at"] == "2026-06-08" and rock["time_precision"] == "day" and rock["ended_at"] is None
    assert rock["waterbody_text"] == "Rockford Lake" and rock["outfall_name"] == "Rockford Lake at Beach"
    assert rock["advice_text"].startswith("This beach is under health alert") and "13.78" in rock["advice_text"]
    assert rock["lat"] == 40.223196 and rock["published_at"] is None
    both = by["LNE2IRONHT04-2026-w23"]                                       # alert and E. coli: the alert
    assert both["event_type"] == "hab_advisory" and both["raw"]["_ecoli_risk"].startswith("Elevated")
    oak = by["LLP2BRNOAK09-2026-w21"]
    assert oak["event_type"] == "beach_advisory" and oak["status"] == "unknown" and "no advisory issued" in oak["advice_text"]
    assert oak["waterbody_text"] == "Branched Oak Lake" and oak["started_at"] == "2026-05-26"
    other = by["GPTLKBACT1-2026-w21"]                                        # neither: only from a whole-layer copy
    assert other["event_type"] == "unknown" and other["parse_error"]
    assert stats["by_type"] == {"hab_advisory": 3, "beach_advisory": 2, "unknown": 1}


def test_beachwatch_records_keep_only_the_safe_fields():
    recs, _ = _beachwatch()
    for r in recs:
        assert set(r["raw"]["row"]) <= {"OBJECTID", "StationID", "StationName", "Latitude", "Longitude", "SampleYear",
                                        "WeekNumber", "ActivityStartDate", "EColi", "Microcystin", "HealthAlert",
                                        "EColiRisk", "HealthDescription"}
