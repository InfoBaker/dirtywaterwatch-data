"""Kentucky: the Kentucky rules of EPA's overflow tables (the zone by the event's point against the forty-one
Central-time counties, the type read from the description, the form's placeholders and answers, the people scrub,
the incident number, --file), on real Kentucky rows (tests/fixtures/ky_sobe_rows.json: fourteen reports of the
2026-11-04 extract, names replaced by Example names, and one synthetic basement backup), and the proof that adding the
state changes no other state's record."""
import copy
import json
from pathlib import Path

import common
import zones
from ingest import echo_sewer_overflow_events as E
from tests.test_ingest_ne import _zip

FIX = Path(__file__).parent / "fixtures"
ROOT = Path(__file__).resolve().parents[2]


def _fixture() -> dict:
    return json.loads((FIX / "ky_sobe_rows.json").read_text())


def _build(tables=None):
    t = copy.deepcopy(tables or _fixture())
    return E.build(t, {"extract_date": "2026-11-04", "last_modified": None, "now": "2026-11-07T00:00:00Z"})


def _by_id():
    kept, dropped, why = _build()
    return {r["source_record_id"]: r for r in kept}, {r["source_record_id"]: r for r in dropped}, why


def test_kentucky_is_read_with_the_point_zone_the_scrub_and_its_own_rules():
    assert "KY" in E.STATES and E.STATE_TZ["KY"] == "America/New_York"
    assert E.POINT_ZONE_FILES["KY"] == "ky-central-time-counties.json"
    assert "KY" in E.FREE_TEXT_STATES and "KY" not in E.REPEATED_POINT_STATES and "KY" not in E.STATE_NO_WATER
    assert E.TYPE_FROM_TEXT_STATES == {"KY"} and set(E.STATE_PERSON_SCRUB) == {"KY"}
    assert set(E.STATE_TEXT_DENIAL) == {"KY"} and E.ZONE_ALWAYS_STATES == {"KY"}


def test_the_central_counties_file_cites_the_boundary_and_holds_forty_one_counties():
    doc = json.loads((ROOT / "data" / "reference" / "ky-central-time-counties.json").read_text())
    assert doc["law"]["cite"] == "49 CFR 71.5(c)" and doc["zone"] == "America/Chicago"
    assert doc["other_zone"] == "America/New_York" and doc["zone_label"] == "Central"
    names = {c["county"] for c in doc["counties"]}
    assert len(names) == 41 and doc["split_counties"] == []
    assert {"Warren County", "McCracken County", "Daviess County", "Henderson County", "Russell County",
            "Clinton County", "Breckinridge County"} <= names
    # the boundary runs along the west lines of Meade and Hardin and around Taylor, Casey, Pulaski and Wayne
    assert not names & {"Meade County", "Hardin County", "Larue County", "Taylor County", "Casey County",
                        "Pulaski County", "Wayne County", "Jefferson County"}
    assert "tigerweb.geo.census.gov" in doc["source"]["url"] and "NTAD_Time_Zones" in doc["checked_against"]["url"]


def test_the_zone_is_the_zone_of_the_events_own_point():
    central = [(36.99, -86.44), (37.08, -88.60), (37.77, -87.11), (37.84, -87.59), (36.93, -85.06)]
    eastern = [(38.25, -85.76), (37.99, -86.17), (37.69, -85.86), (37.09, -84.60), (36.83, -84.85), (38.05, -84.50),
               (39.08, -84.51)]
    for lat, lon in central:     # Bowling Green, Paducah, Owensboro, Henderson, Jamestown (Russell County)
        assert E.point_zone("KY", lat, lon)[0] == "America/Chicago", (lat, lon)
        assert zones.zone_for("KY", lat, lon) == "America/Chicago"
    for lat, lon in eastern:     # Louisville, Brandenburg (Meade), Elizabethtown (Hardin), Somerset, Monticello,
        assert E.point_zone("KY", lat, lon)[0] == "America/New_York", (lat, lon)   # Lexington, Covington
        assert zones.zone_for("KY", lat, lon) == "America/New_York"
    tz, basis = E.point_zone("KY", 36.99, -86.44)
    assert basis == "the zone of Warren County, where the event's point lies (49 CFR 71.5(c))"
    tz, basis = E.point_zone("KY", 38.25, -85.76)
    assert "outside the forty-one Central-time counties" in basis
    assert E.point_zone("KY", None, None)[0] == "America/New_York" and zones.zone_for("KY") == "America/New_York"


def test_kept_and_dropped_by_reason_and_the_stable_record_id():
    kept, dropped, why = _by_id()
    assert len(kept) == 8 and len(dropped) == 7
    ky = {(o, r): n for (s, o, r), n in why.items() if s == "KY"}
    assert ky[("kept", "receiving water named")] == 4
    assert ky[("kept", "text names a water (receiving into an unnamed tributary? yes)")] == 2
    assert ky[("kept", "text names a water (creek)")] == 2
    assert ky[("dropped", "no evidence the discharge reached a water")] == 4
    assert ky[("dropped", "the report says no water was reached")] == 2          # 'No waterways impacted', 'did not reach'
    assert ky[("dropped", "building backup")] == 1                                # the synthetic basement backup
    # permit:form set:event id, as for every state
    assert "KY0021466:KY-11276:1545" in kept and "KY0021466:KY-11256:1914" in dropped
    # 'River City Controls' is a firm, not a river: no evidence of a water
    assert dropped["KY0090956:KY-11286:395"]["reason"] == "no evidence the discharge reached a water"


def test_the_form_placeholders_are_no_name_and_the_tributary_answer_is_a_water():
    kept, _, _ = _by_id()
    msd = kept["KY0022411:KY-11286:394"]       # 'Unnamed ' with 'Receiving into an unnamed tributary? Yes.'
    assert msd["waterbody_text"] is None and msd["water_slugs"] == [] and msd["raw"]["receiving_waters"] == ["Unnamed "]
    sd1 = kept["KY0021466:KY-11276:1545"]
    assert sd1["waterbody_text"] == "Banklick Creek"
    assert E.named(["Unnamed Tributary or Unknown", "Unnamed ", "Banklick Creek "], "KY") == ["Banklick Creek "]
    assert E.named(["Unnamed Tributary or Unknown"], "NE") == ["Unnamed Tributary or Unknown"]   # Kentucky's only


def test_the_type_is_read_from_the_description_and_a_plant_bypass_stays_a_bypass():
    kept, _, _ = _by_id()
    sso = kept["KY0021466:KY-11276:1545"]      # 'Wet weather release at Lakeview pump station'
    assert sso["event_type"] == "sso" and sso["raw"]["type_as_filed"] == "BYP"
    assert "pump station" in sso["raw"]["type_note"] and sso["raw"]["types"] == ["Bypass Event"]
    byp = kept["KY0098540:KY-11286:1552"]      # 'LOUISVILLE - BYPASS AT WQTC'
    assert byp["event_type"] == "bypass" and "type_as_filed" not in byp["raw"]
    assert byp["material"] == E.MATERIAL["bypass"]


def test_times_carry_the_points_zone_and_raw_time_zone():
    kept, _, _ = _by_id()
    muhlenberg = kept["KY0023540:KY-11286:1553"]   # Muhlenberg County: Central
    assert muhlenberg["started_at"] == "2025-12-31T07:00:00-06:00" and muhlenberg["raw"]["time_zone"] == "America/Chicago"
    assert "Muhlenberg County" in muhlenberg["raw"]["timezone_note"]
    assert muhlenberg["time_precision"] == "minute" and muhlenberg["ended_at"] == "2025-12-31T16:00:00-06:00"
    sd1 = kept["KY0021466:KY-11276:1545"]
    assert sd1["started_at"] == "2025-12-18T23:28:00-05:00" and sd1["raw"]["time_zone"] == "America/New_York"
    assert sd1["reported_at"] == "2025-12-19" and sd1["published_at"] == "2026-11-04"
    assert sd1["source_updated_at"] is None                                       # never the fetch time


def test_people_phone_and_house_numbers_never_reach_a_record():
    kept, dropped, _ = _build()
    blob = json.dumps(kept + dropped)
    for name in ("Jane Example", "Sam Example", "Pat Sample", "Lee Example", "Kim Sample", "555-0100", "123 Example"):
        assert name not in blob, name
    by = {r["source_record_id"]: r for r in kept}
    txt = by["KYR003103:KY-11286:9"]["raw"]["sewer_overflow_bypass_description_text"]
    assert txt.startswith("Incident ID: 2558615 [name removed] responded.[name removed], Example Brands, [phone removed]")
    assert "DO notified [name removed], KY DEP-ERT" in txt and "Duty Officer - [name removed] at" in txt
    assert "Collections operator [name removed] reported" in by["KY0106283:KY-11286:1937"]["raw"][
        "sewer_overflow_bypass_description_text"]
    # firms and places stay
    assert E.ky_scrub_people("Blue Licks State Park reported a lift station overflow") == (
        "Blue Licks State Park reported a lift station overflow")
    assert E.ky_scrub_people("Called Example Pipe Cleaners to jet the line") == "Called Example Pipe Cleaners to jet the line"


def test_the_incident_number_is_kept():
    kept, _, _ = _by_id()
    assert kept["KY0021466:KY-11276:1545"]["raw"]["ky_incident_id"] == "2559248"


def test_adding_kentucky_changes_no_other_states_record(monkeypatch):
    """The same tables built with and without KY give identical records for every other state (also checked on the
    real 2026-11-04 extract: 2,225 kept and 2,445 dropped records of the other states identical)."""
    from tests.test_ingest_dc import _row
    fx = _fixture()
    other = [_row(sewer_overflow_bypass_event_key="o1", latitude_measure="38.9300", longitude_measure="-77.0400"),
             _row(sewer_overflow_bypass_event_key="o2", permit_identifier="IL0000001", program_report_form_set_id="2",
                  sewer_overflow_bypass_description_text="Operator Jane Example reported a break at a manhole."),
             _row(sewer_overflow_bypass_event_key="o3", permit_identifier="NH0000001", program_report_form_set_id="3",
                  sewer_overflow_bypass_description_text="Receiving into an unnamed tributary? Yes. No waterways impacted"),
             _row(sewer_overflow_bypass_event_key="o4", permit_identifier="NE0000001", program_report_form_set_id="4",
                  latitude_measure="41.25", longitude_measure="-95.93",
                  sewer_overflow_bypass_description_text="Force main break at a lift station")]
    fx["events"] += other
    fx["types"] += [{"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_type_code": c,
                     "sewer_overflow_bypass_type_desc": "", "sewer_overflow_bypass_type_code_sequence": "1"}
                    for k, c in (("o1", "SSO"), ("o2", "SSO"), ("o3", "SSO"), ("o4", "BYP"))]
    fx["waters"] += [{"sewer_overflow_bypass_event_key": "o1", "name_receiving_water": "Rock Creek"},
                     {"sewer_overflow_bypass_event_key": "o2", "name_receiving_water": "Unnamed Tributary or Unknown"},
                     {"sewer_overflow_bypass_event_key": "o3", "name_receiving_water": "Sample Brook"},
                     {"sewer_overflow_bypass_event_key": "o4", "name_receiving_water": "Unnamed"}]

    def others(states):
        monkeypatch.setattr(E, "STATES", states)
        kept, dropped, _ = _build(fx)
        return sorted(json.dumps({k: v for k, v in r.items() if k != "fetched_at"}, sort_keys=True)
                      for r in kept + dropped if not str(r.get("npdes_permit") or r.get("permit")).startswith("KY"))
    with_ky, without_ky = others(set(E.STATES)), others(set(E.STATES) - {"KY"})
    assert with_ky == without_ky and len(with_ky) == 4
    ne = json.loads(next(r for r in with_ky if "NE0000001" in r))
    assert ne["event_type"] == "bypass" and "type_as_filed" not in ne["raw"]          # Kentucky's retyping is its own
    il = json.loads(next(r for r in with_ky if "IL0000001" in r))
    assert "time_zone" not in il["raw"]


def test_main_reads_a_saved_zip_of_kentucky_rows(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(E, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(E, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    assert E.main(["--file", str(_zip(tmp_path, _fixture()))]) == 0
    doc = json.loads((tmp_path / "events" / "echo-sewer-overflow.json").read_text())
    assert doc["count"] == 8 and "KY" in doc["meta"]["states"]
    dropped = json.loads((tmp_path / "echo-sewer-overflow-dropped.json").read_text())
    assert dropped["count"] == 7 and "Jane Example" not in json.dumps(dropped)
