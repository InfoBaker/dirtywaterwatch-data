"""Utah: DEQ's Environmental Incidents layer (the spill hotline log) and DWQ's recreational advisories through the generic
ArcGIS block (ingest/ut_transforms.py), and Utah's rows of EPA's eRule tables (ingest/echo_sewer_overflow_events.py,
module docstring, Utah). Fixtures: real rows of the 2026-11-07 fetches (titles with no names) and three invented rows
(Example names, a placeholder house number and telephone number). No network."""
import copy
import json
import re
from collections import Counter
from pathlib import Path

import pytest

from ingest import echo_sewer_overflow_events as E
from ingest import ut_transforms as U
from ingest.generic import runner as R

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures"
FETCHED = "2026-11-07T23:00:00Z"
PERSONAL = ["Example and Sample", "1234 Example", "801-555-0142", "555-0142", "Responsible_Party", "Address_Location",
            "Incident_summary", "Salesforce_Id", "Advisory_Picture"]


def echo_ut():
    t = {k: v for k, v in json.loads((FIX / "ut" / "sobe_rows.json").read_text()).items() if isinstance(v, list)}
    return t, E.build(t, {"extract_date": "2026-11-04"})


def incidents(echo=None):
    _, block = R.load_source("ut-deq-environmental-incidents")
    rows = R.platform("arcgis").parse(block, (FIX / "ut" / "incidents.json").read_bytes())
    extra = {"ut_echo_records": echo if echo is not None else []}
    recs, stats = R.build("ut-deq-environmental-incidents", block, rows, FETCHED, (), None, extra)
    return {r["outfall_name"]: r for r in recs}, stats


def advisories():
    _, block = R.load_source("ut-dwq-recreational-advisories")
    rows = R.platform("arcgis").parse(block, (FIX / "ut" / "recreational.json").read_bytes())
    recs, stats = R.build("ut-dwq-recreational-advisories", block, rows, FETCHED, (), None)
    return recs, stats


def test_blocks_validate_and_request_only_safe_fields():
    for sid in ("ut-deq-environmental-incidents", "ut-dwq-recreational-advisories"):
        _, block = R.load_source(sid)
        assert R.validate_block(block, sid) == []
    _, block = R.load_source("ut-deq-environmental-incidents")
    never = {"Responsible_Party", "Address_Location", "Incident_summary", "Salesforce_Id", "Map_Label"}
    assert not never & set(block["safe_fields"])
    _, rec = R.load_source("ut-dwq-recreational-advisories")
    assert "Advisory_Picture" not in rec["safe_fields"] and "Hold_Date" not in rec["safe_fields"]


def test_the_blocks_filter_is_the_modules_keyword_lists():
    _, block = R.load_source("ut-deq-environmental-incidents")
    f = block["filter"]
    assert f[0] == {"field": "Title_EventName", "regex": U.SEWAGE_WORDS}
    assert [x["regex"] for x in f[1:]] == list(U.NOT_SEWAGE.values()) and all(x["exclude"] for x in f[1:])


@pytest.mark.parametrize("title,want", [
    ("Moab - Sanitary Sewer Overflow", "sso"),
    ("Sewage Bypass Failure - Syracuse", "bypass"),
    ("Orem - Partially Treated Wastewater Release to Wetlands", "sso"),
    ("Hyrum - WWTP - Sewage Spill", "plant_bypass"),
    ("Orem - Effluent release into Powell Slough", "plant_bypass"),
    ("Personal RV Sewage Dump Ogden", "sso"),
    ("Ogden - Acidic Wastewater Release", None),
    ("Eagle Mountain - Sewer Overflow into Homes", None),
    ("SLC - Discharge from Water Treatment Plant", None),
    ("Springville - Sheen at Waste Water Treatment Plant", None),
    ("Millard County - Fuel Release Associated With AST", None),        # 'Associated' is not 'SSO'
    ("Corrine (UPRR Causeway) Train Car Fire", None),                   # 'Causeway' is not 'sewer'
    ("Swift Transportation", None),                                     # 'Transportation' is not 'porta'
])
def test_sewage_titles_by_rule(title, want):
    assert U.classify(title)[0] == want


def test_kept_and_dropped_rows_and_the_day_in_mountain_time():
    recs, stats = incidents()
    assert stats["rows"] == 19 and stats["rows_kept_by_filter"] == 14 and stats["records_written"] == 14
    for gone in ("Ogden - Acidic Wastewater Release", "Eagle Mountain - Sewer Overflow into Homes",
                 "SLC - Discharge from Water Treatment Plant", "Salt Lake City -- Firefighting foam in sewer",
                 "Millard County - Fuel Release Associated With AST"):
        assert gone not in recs
    r = recs["UPDATE American Fork - Sewage Release"]
    assert r["event_type"] == "sso" and r["status"] == "unknown" and r["ended_at"] is None
    assert r["started_at"] == "2026-08-17T00:00:00-06:00" and r["time_precision"] == "day"
    assert r["raw"]["time_zone"] == "America/Denver" and r["raw"]["county"] == "Utah County"
    assert r["reported_at"] is None and r["published_at"] is None and r["volume_gal"] is None
    assert r["raw"]["_filter_time_as_given"] == "2026-08-17T17:00:00Z"            # kept as given, not used
    assert r["source_record_id"] == "00021105" and r["source_url"].startswith("https://deqspillsps.deq.utah.gov/")
    assert r["lat"] == pytest.approx(40.3475, abs=1e-3) and r["lon"] == pytest.approx(-111.798, abs=1e-3)
    assert recs["Sewage Bypass Failure - Syracuse"]["event_type"] == "bypass"
    winter = recs["Moab - Sanitary Sewer Overflow"]["started_at"]
    assert winter.endswith("-06:00") or winter.endswith("-07:00")
    undated = recs["Example Town - Sewage Release"]
    assert undated["started_at"] is None and undated["raw"]["_undated"]


def test_citizen_reports_keep_their_sewage_class_and_are_marked():
    recs, _ = incidents()
    for t in ("Personal RV Sewage Dump Ogden", "Cedar City - Sewage Dumping"):
        r = recs[t]
        assert r["event_type"] == "sso" and r["raw"]["report_provenance"] == "citizen"
    assert "report_provenance" not in recs["Moab - Sanitary Sewer Overflow"]["raw"]


def test_a_water_named_in_the_title_is_the_records_water_text():
    recs, _ = incidents()
    assert recs["Bear Lake - Sewage Release"]["waterbody_text"] == "Bear Lake"
    assert recs["Mt. Carmel - Sewage release to Virgin RIver"]["waterbody_text"] == "Virgin River"
    assert recs["Moab - Sanitary Sewer Overflow"]["waterbody_text"] is None
    assert U.water_in_title("Salt Lake City - Sewage Release") is None
    assert U.water_in_title("S. Salt Lake - Sewer line break") is None
    assert U.water_in_title("Wolf Creek Sewer District") is None
    assert recs["Salt Lake City - Wastewater"]["material"] == "wastewater (type not stated)"


def test_no_personal_field_or_string_reaches_the_records():
    recs, _ = incidents()
    text = json.dumps(list(recs.values()))
    for s in PERSONAL:
        assert s not in text, s
    p = [r for r in recs.values() if r["source_record_id"] == "99000001"][0]
    assert p["outfall_name"] == "Vacuum Truck (Septic Service)" and p["raw"]["report_provenance"] == "citizen"
    h = [r for r in recs.values() if r["source_record_id"] == "99000002"][0]
    assert "[house number removed]" in h["outfall_name"] and "[phone removed]" in h["outfall_name"]
    recs_a, _ = advisories()
    assert not [s for s in PERSONAL if s in json.dumps(recs_a)]


def test_the_epa_report_of_the_same_overflow_absorbs_the_hotline_row():
    _, (kept, _, _) = echo_ut()
    recs, stats = incidents(kept)
    r = recs["UPDATE American Fork - Sewage Release"]
    assert r["duplicate_of"] == "echo-sewer-overflow:UT0023639:1:1" and stats["duplicates"]["linked_to_epa"] == 1
    assert recs["Bear Lake - Sewage Release"]["duplicate_of"] is None


def test_utahs_epa_report_is_read_in_mountain_time_with_its_sign_repaired():
    assert "UT" in E.STATES and E.STATE_TZ["UT"] == "America/Denver" and "UT" in E.SIGN_REPAIR_PREFIXES
    assert "UT" not in E.FREE_TEXT_STATES and "UT" not in E.REPEATED_POINT_STATES
    _, (kept, dropped, why) = echo_ut()
    assert len(kept) == 1 and not dropped and why[("UT", "kept", "receiving water named")] == 1
    k = kept[0]
    assert k["started_at"] == "2026-08-17T14:39:00-06:00" and k["ended_at"] == "2026-08-17T14:49:00-06:00"
    assert k["lon"] == -111.798013 and k["raw"]["reported_longitude"] == "111.798013"
    assert k["volume_gal"] == 1000 and k["reported_at"] == "2026-08-25" and k["npdes_permit"] == "UT0023639"


def test_adding_utah_leaves_the_other_states_records_as_they_were(monkeypatch):
    ut, _ = echo_ut()
    nm = {k: v for k, v in json.loads((FIX / "nm_sobe_rows.json").read_text()).items() if isinstance(v, list)}
    both = {k: nm.get(k, []) + ut.get(k, []) for k in set(nm) | set(ut)}
    with_ut, _, _ = E.build(copy.deepcopy(both), {"extract_date": "2026-11-04"})
    monkeypatch.setattr(E, "STATES", E.STATES - {"UT"})
    monkeypatch.setattr(E, "STATE_TZ", {k: v for k, v in E.STATE_TZ.items() if k != "UT"})
    monkeypatch.setattr(E, "SIGN_REPAIR_PREFIXES", E.SIGN_REPAIR_PREFIXES - {"UT"})
    without, _, _ = E.build(copy.deepcopy(both), {"extract_date": "2026-11-04"})

    def strip(rs):
        return [{k: v for k, v in r.items() if k != "fetched_at"} for r in rs if not r["npdes_permit"].startswith("UT")]
    assert strip(with_ut) == strip(without) and len(with_ut) == len(without) + 1


def test_advisories_looks_good_is_no_record_and_codes_are_read():
    recs, stats = advisories()
    by = {r["raw"]["_advisory_label"]: r for r in recs}
    assert stats["rows"] == 9 and len(recs) == 7 and "Looks Good" not in by and None not in by
    assert by["Warning HAB"]["event_type"] == "hab_advisory" and by["Warning HAB"]["status"] == "advisory_active"
    assert by["Danger HAB"]["event_type"] == by["HAB HW"]["event_type"] == by["Warning Mats"]["event_type"] == "hab_advisory"
    assert by["Warning E coli"]["event_type"] == by["E coli HW"]["event_type"] == "beach_advisory"
    assert by["Mats CF"]["raw"]["code_undecoded"] and "code_undecoded" not in by["Warning HAB"]["raw"]
    for r in recs:
        assert r["time_precision"] == "day" and re.fullmatch(r"\d{4}-\d{2}-\d{2}T00:00:00-0[67]:00", r["started_at"])
        assert r["raw"]["time_zone"] == "America/Denver" and r["raw"]["_last_monitored"]
        assert r["reported_at"] is None and not re.search(r"\b(safe|clean)\b", r["advice_text"] or "", re.I)
