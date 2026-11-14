"""Indiana: the county rule of the clock (49 CFR 71.5(b), pipeline/zones.py and the eRule module's point rule), EPA's
overflow tables' Indiana rows (tests/fixtures/in_sobe_rows.json: the one real report of the 2026-11-12 extract and one
synthetic Central-time report), and the proof that adding the state changes no other state's record. The other
Indiana feeds are tested further down this file."""
import copy
import json
from pathlib import Path

import common
import zones
from ingest import echo_sewer_overflow_events as E
from tests.test_ingest_ne import _zip

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------------------------------------ the clock

def test_the_central_counties_file_cites_the_boundary_and_holds_the_twelve_counties():
    doc = json.loads((ROOT / "data" / "reference" / "in-central-time-counties.json").read_text())
    assert doc["state"] == "IN" and doc["law"]["cite"] == "49 CFR 71.5(b)" and "ecfr.gov" in doc["law"]["url"]
    assert doc["zone"] == "America/Chicago" and doc["other_zone"] == "America/New_York"
    names = {c["county"] for c in doc["counties"]}
    assert names == {f"{n} County" for n in ("Gibson", "Jasper", "Lake", "LaPorte", "Newton", "Perry", "Porter",
                                             "Posey", "Spencer", "Starke", "Vanderburgh", "Warrick")}
    assert doc["split_counties"] == []
    assert "tigerweb.geo.census.gov" in doc["source"]["url"] and "NTAD_Time_Zones" in doc["checked_against"]["url"]
    assert {zones.in_county_key(n) for n in names} == zones.IN_CENTRAL_COUNTIES


def test_the_county_name_decides_the_zone():
    for c in ("LaPorte", "La Porte County", "Laporte", "Lake County", "Porter", "Starke", "Jasper", "Newton",
              "Gibson", "Posey", "Vanderburgh County", "Warrick", "Spencer", "Perry"):
        assert zones.indiana_zone(county=c) == "America/Chicago", c
    for c in ("Marion", "St. Joseph", "St Joseph County", "Allen", "Elkhart", "Pulaski", "Marshall", "Pike", "Dubois",
              "Crawford", "Benton"):
        assert zones.indiana_zone(county=c) == "America/New_York", c
    assert zones.indiana_zone() == "America/New_York" and zones.zone_for("IN") == "America/New_York"


def test_the_point_decides_the_zone_when_no_county_is_given():
    central = [(41.61, -86.72), (41.59, -87.35), (41.47, -87.06), (37.97, -87.57), (37.95, -86.76), (38.05, -87.27)]
    eastern = [(39.77, -86.16), (41.08, -85.14), (41.68, -86.25), (41.68, -85.98), (38.49, -87.28), (40.42, -86.89)]
    for lat, lon in central:   # La Porte, Hammond, Valparaiso, Evansville, Tell City (Perry), Boonville (Warrick)
        assert zones.zone_for("IN", lat, lon) == "America/Chicago", (lat, lon)
        assert E.point_zone("IN", lat, lon)[0] == "America/Chicago"
    for lat, lon in eastern:   # Indianapolis, Fort Wayne, South Bend, Mishawaka, Petersburg (Pike), Lafayette
        assert zones.zone_for("IN", lat, lon) == "America/New_York", (lat, lon)
        assert E.point_zone("IN", lat, lon)[0] == "America/New_York"
    tz, basis = E.point_zone("IN", 37.97, -87.57)
    assert basis == "the zone of Vanderburgh County, where the event's point lies (49 CFR 71.5(b))"
    assert "outside the twelve Central-time counties" in E.point_zone("IN", 39.77, -86.16)[1]


def test_other_states_zones_are_unchanged():
    assert zones.zone_for("KY", 36.99, -86.44) == "America/Chicago" and zones.zone_for("KY") == "America/New_York"
    assert zones.zone_for("OH", 41.5, -81.7) == "America/New_York" and zones.zone_for("IL", 41.88, -87.63) == "America/Chicago"
    assert zones.zone_for("TN", 36.16, -86.78) == "America/Chicago"


# ------------------------------------------------------------------------------------------------ EPA's overflow tables

def _fixture() -> dict:
    return json.loads((FIX / "in_sobe_rows.json").read_text())


def _build(tables=None):
    t = copy.deepcopy(tables or _fixture())
    return E.build(t, {"extract_date": "2026-11-12", "last_modified": None, "now": "2026-11-14T00:00:00Z"})


def test_indiana_is_read_with_the_point_zone_and_the_scrub():
    assert "IN" in E.STATES and E.STATE_TZ["IN"] == "America/New_York"
    assert E.POINT_ZONE_FILES["IN"] == "in-central-time-counties.json"
    assert "IN" in E.FREE_TEXT_STATES and "IN" in E.ZONE_ALWAYS_STATES
    assert "IN" not in E.REPEATED_POINT_STATES and "IN" not in E.STATE_NO_WATER and "IN" not in E.PLANT_POINT_STATES


def test_the_shelbyville_bypass_is_kept_with_its_times_volume_and_water():
    kept, dropped, why = _build()
    by = {r["source_record_id"]: r for r in kept}
    assert not [r for r in dropped if str(r.get("npdes_permit")).startswith("IN")]
    r = by["IN0032867:1:1"]
    assert r["event_type"] == "bypass" and r["status"] == "ended" and r["time_precision"] == "minute"
    assert r["started_at"] == "2026-08-12T21:30:00-04:00" and r["ended_at"] == "2026-08-13T14:55:00-04:00"
    assert r["reported_at"] == "2026-08-13" and r["volume_gal"] == 5055000 and r["estimate_flag"] == "measured"
    assert r["waterbody_text"] == "Big Blue River"
    assert r["raw"]["time_zone"] == "America/New_York" and "twelve Central-time counties" in r["raw"]["timezone_note"]
    assert why[("IN", "kept", "receiving water named")] == 2


def test_a_report_in_a_central_county_is_read_on_central_time():
    kept, _, _ = _build()
    r = {x["source_record_id"]: x for x in kept}["IN0000001:9:1"]
    assert r["event_type"] == "sso" and r["started_at"] == "2026-07-04T19:00:00-05:00"
    assert r["raw"]["time_zone"] == "America/Chicago" and "Vanderburgh County" in r["raw"]["timezone_note"]


def test_adding_indiana_changes_no_other_states_record(monkeypatch):
    """The same tables built with and without IN give identical records for every other state (also checked on the
    real 2026-11-12 extract: 2,278 kept and 2,485 dropped records of the other states identical)."""
    from tests.test_ingest_dc import _row
    fx = _fixture()
    other = [_row(sewer_overflow_bypass_event_key="o1", latitude_measure="38.9300", longitude_measure="-77.0400"),
             _row(sewer_overflow_bypass_event_key="o2", permit_identifier="IL0000001", program_report_form_set_id="2",
                  sewer_overflow_bypass_description_text="Operator Jane Example reported a break at a manhole."),
             _row(sewer_overflow_bypass_event_key="o3", permit_identifier="KY0000001", program_report_form_set_id="3",
                  latitude_measure="36.99", longitude_measure="-86.44",
                  sewer_overflow_bypass_description_text="Manhole overflowing. Receiving into an unnamed tributary? Yes.")]
    fx["events"] += other
    fx["types"] += [{"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_type_code": c,
                     "sewer_overflow_bypass_type_desc": "", "sewer_overflow_bypass_type_code_sequence": "1"}
                    for k, c in (("o1", "SSO"), ("o2", "SSO"), ("o3", "BYP"))]
    fx["waters"] += [{"sewer_overflow_bypass_event_key": "o1", "name_receiving_water": "Rock Creek"},
                     {"sewer_overflow_bypass_event_key": "o2", "name_receiving_water": "Sample Creek"},
                     {"sewer_overflow_bypass_event_key": "o3", "name_receiving_water": "Unnamed"}]

    def others(states):
        monkeypatch.setattr(E, "STATES", states)
        kept, dropped, _ = _build(fx)
        return sorted(json.dumps({k: v for k, v in r.items() if k != "fetched_at"}, sort_keys=True)
                      for r in kept + dropped if not str(r.get("npdes_permit") or r.get("permit")).startswith("IN"))
    with_in, without_in = others(set(E.STATES)), others(set(E.STATES) - {"IN"})
    assert with_in == without_in and len(with_in) == 3


def test_main_reads_a_saved_zip_of_indiana_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(E, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(E, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    assert E.main(["--file", str(_zip(tmp_path, _fixture()))]) == 0
    doc = json.loads((tmp_path / "events" / "echo-sewer-overflow.json").read_text())
    assert doc["count"] == 2 and "IN" in doc["meta"]["states"]
