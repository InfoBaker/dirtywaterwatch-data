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
    ("Orem - Partially Treated Wastewater Release to Wetlands", "plant_bypass"),      # review P3-10
    # review 2026-11-08 P2-2: sewage titles the first rules missed
    ("Midvale Human Waste Dumping", "sso"),
    ("Park Valley Box Elder - Human waste dumping", "sso"),
    ("South Salt Lake- Improper human waste storage", "sso"),
    ("ST GEORGE -- human waste", "sso"),
    ("Complaint - Brighton Canal - fill & human waste", "sso"),
    ("Cedar City Septage", "sso"),
    ("Girls Camp Septage Dumping", "sso"),
    ("SLC - Dumping Fluids from RVs", "sso"),
    ("Spainish Fork Porto jJohn company", "sso"),
    ("Orem - Rainfall event at Orem City Reclamation", "plant_bypass"),
    ("Hyrum - Activated Sludge", "plant_bypass"),
    ("SLC Chevron Refinery- Waste Water", None),                                        # review P3-2
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
    # review P2-1: Date_Discovered is the UTC date; an evening discovery (21:00 Mountain on 09-03) is dated 09-03
    bear = recs["Bear Lake - Sewage Release"]
    assert bear["raw"]["row"]["Date_Discovered"] == "09/04/2026" and bear["raw"]["_filter_time_as_given"] == "2026-09-04T03:00:00Z"
    assert bear["started_at"] == "2026-09-03T00:00:00-06:00" and "Mountain date" in bear["raw"]["_day_basis"]
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


# ---------------------------------------------------------------- registry, register, rules, text, waters

def ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "UT"]


def test_every_utah_permit_is_in_exactly_one_row():
    from ingest import dischargers_schema as DS
    every = Counter(p for r in json.loads((ROOT / "data" / "dischargers.json").read_text())
                    for p in dict.fromkeys([r.get("npdes_permit"), *(r.get("npdes_permits") or [])]) if p)
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "UT"}
    research = {r["npdes_permit"] for r in json.loads((ROOT / "research" / "ut" / "dischargers.json").read_text())}
    assert len(plants) == 90 and all(every[p] == 1 for p in plants | research)        # 93 less the 3 dewatering coverages
    rows = ops()
    held = [p for r in rows for p in r["npdes_permits"]]
    assert len(held) == len(set(held)) == 221 and sum(1 for p in held if p.startswith("UTG580")) == 126
    tim = next(r for r in rows if r["id"] == "ut-timpanogos-ssd")
    assert "ut-ut0023639" in tim["aliases"] and set(tim["npdes_permits"]) == {"UT0023639", "UTL023639"}
    assert not DS.check_legal_forms(rows)
    from build import redact
    assert not [r["name"] for r in rows if redact.person_shaped(r["name"])]


def test_register_rows_per_operator_and_the_state_channels():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "ut.json").read_text())["channels"]}
    for r in ops():
        tribal = r["legal_form"] == "tribal" or any(p.startswith(("NN", "COG", "UTG5894")) for p in r["npdes_permits"])
        row = reg[f"{r['id']}-epa-report" if tribal else f"{r['id']}-dwq-report"]
        assert row["operator_id"] == r["id"]
        if r["id"] in ("ut-alder-construction", "ut-fx-construction", "ut-whitaker-construction"):
            assert "R317-801-4" not in row["legal_basis"] and "dewatering" in row["legal_basis"]   # review P3-4
        elif not tribal:
            assert "R317-801-4" in row["legal_basis"] and row["barrier"] == "no_web_page" and row["urls"] == []
    assert reg["ut-timpanogos-ssd-epa-report"]["feed_source_id"] == "echo-sewer-overflow"
    assert reg["ut-deq-environmental-incidents"]["feed_source_id"] == "ut-deq-environmental-incidents"
    assert reg["ut-dwq-recreational-advisories"]["feed_source_id"] == "ut-dwq-recreational-advisories"
    assert "ut-habs-utah-gov" not in reg and reg["ut-dwq-recreational-page"]["urls"] == ["https://deq.utah.gov/dwq/recreational-water-quality"]
    assert reg["ut-dwq-class-1-sso-reports"]["barrier"] == "no_web_page"


def test_rules_row_cites_the_law_and_sets_no_window():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    ut = rules["red"]["by_state"]["UT"]
    assert ut["hours"] is None and "R317-801-4" in ut["source"] and "R317-801-1(13)" in ut["source"]
    assert "UT" not in rules["live_states"] and not re.search(r"\b(safe|clean)\b", ut["basis"], re.I)


def test_state_text_is_in_the_page_shape():
    t = (ROOT / "research" / "ut" / "state-text.md").read_text()
    assert t.startswith("---\nstate: UT\nname: Utah\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I) and ".json" not in t and ".py" not in t
    assert "387" in t and "8,980" in t and "R317-801-4" in t


def test_missing_waters_list_leaves_out_the_national_lists_names():
    d = json.loads((ROOT / "research" / "ut" / "receiving-waters-missing.json").read_text())
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())

    def k(n):
        return re.sub(r"[^a-z0-9]", "", (n or "").lower())
    held = {k(n) for w in nat["states"]["UT"]["waters"]
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    assert d["state"] == "UT" and d["waters"] == len(d["rows"]) > 0
    assert not [r["name"] for r in d["rows"] if k(r["name"]) in held]
    keys = [(r["name"], r["county"]) for r in d["rows"]]
    assert len(keys) == len(set(keys)) and not [r for r in d["rows"] if re.search(r"(?i)storm|outfall", r["name"])]


# ---------------------------------------------------------------- review 2026-11-08

def test_the_discovery_day_is_the_earlier_of_the_utc_date_and_the_mountain_date():
    from datetime import date, datetime, timezone

    def ms(iso):
        return int(datetime.fromisoformat(iso).replace(tzinfo=timezone.utc).timestamp() * 1000)
    assert U.discovery_day("09/04/2026", ms("2026-09-04T03:00:00"))[0] == date(2026, 9, 3)      # 21:00 MDT
    assert U.discovery_day("08/17/2026", ms("2026-08-17T17:00:00"))[0] == date(2026, 8, 17)     # 11:00 MDT
    assert U.discovery_day("12/24/2011", ms("2011-12-24T05:00:00"))[0] == date(2011, 12, 24)    # midnight Eastern
    assert U.discovery_day("07/04/2014", ms("2014-07-04T04:00:00"))[0] == date(2014, 7, 4)
    assert U.discovery_day(None, None)[0] is None


class _Ctx:
    def __init__(self, echo):
        self.extra = {"ut_echo_records": echo}


def _row(**kw):
    r = {"event_id": "ut-deq-environmental-incidents:x", "event_type": "sso", "lat": 40.3475, "lon": -111.798,
         "started_at": "2026-08-17T00:00:00-06:00", "waterbody_text": None, "duplicate_of": None, "raw": {}}
    r.update(kw)
    return r


def test_the_epa_link_keeps_the_public_and_other_waters_and_far_points_apart():
    _, (kept, _, _) = echo_ut()
    e = kept[0]
    same = _row(event_id="a")
    citizen = _row(event_id="b", raw={"report_provenance": "citizen"})
    other_water = _row(event_id="c", waterbody_text="Jordan River")
    e_named = dict(e, waterbody_text="Dry Creek")
    far = _row(event_id="d", lat=40.3475 + 0.027)                     # about 3 km north
    U.ut_incidents_post([same, citizen, far], _Ctx([e]))
    assert same["duplicate_of"] == e["event_id"]
    assert citizen["duplicate_of"] is None and far["duplicate_of"] is None
    U.ut_incidents_post([other_water], _Ctx([e_named]))
    assert other_water["duplicate_of"] is None and U.ECHO_LINK_M == 2_000


def _advisory_rows(*labels):
    return [{"FID": i, "MLID": 4000000 + i, "Waterbody": "Example Reservoir", "Site_Name": "Example Beach",
             "Public_Name": "Example Beach", "Monitored_Date": "2026-10-20", "Lat": 40.5, "Long": -111.5,
             "Advisory": lab, "Advisory_Date": (1791007200000 if i else None),
             "Additional_Advisory_Notes": "Kayaking is OK"} for i, lab in enumerate(labels)]


def test_a_respelled_or_new_advisory_label_is_never_grey():
    _, block = R.load_source("ut-dwq-recreational-advisories")
    rows = _advisory_rows("Mats CF", "Warning Ecoli", "E. coli HW", "Danger Toxin", "Looks Good", "Looks  good")
    recs, _ = R.build("ut-dwq-recreational-advisories", block, rows, FETCHED, (), None)
    by = {r["raw"]["_advisory_label"]: r for r in recs}
    assert set(by) == {"Mats CF", "Warning Ecoli", "E. coli HW", "Danger Toxin"}
    assert by["Warning Ecoli"]["event_type"] == "beach_advisory" and by["Warning Ecoli"]["status"] == "advisory_active"
    assert "code_undecoded" not in by["Warning Ecoli"]["raw"] and by["E. coli HW"]["event_type"] == "beach_advisory"
    t = by["Danger Toxin"]
    assert t["event_type"] == "hab_advisory" and t["status"] == "advisory_active" and "Danger Toxin" in t["raw"]["code_undecoded"]
    m = by["Mats CF"]                                                   # review P2-4 and P3-6, P3-7
    assert "observed by its monitoring team" in m["raw"]["code_undecoded"] and "do not say" not in json.dumps(m)
    assert m["started_at"] == "2026-10-20T00:00:00-06:00" and "Monitored_Date" in m["raw"]["_date_basis"]
    assert "DWQ's note: Kayaking is OK" in by["Warning Ecoli"]["advice_text"]


def test_the_texts_state_only_what_has_a_basis():
    assert "two weeks" not in U.REC_WINDOW_BASIS and "no authority has confirmed" not in U.CITIZEN_NOTE
    _, block = R.load_source("ut-dwq-recreational-advisories")
    assert "two weeks" not in block["meta"]["caveat"]
    _, inc = R.load_source("ut-deq-environmental-incidents")
    assert "UTC" in inc["meta"]["time_basis"]
    t = (ROOT / "research" / "ut" / "state-text.md").read_text()
    assert "UTC" in t and "does not explain" not in t and "do not say" not in t and "two weeks" not in t
    assert "64 sites under an algal bloom or algae mat advisory" in t


def test_the_sign_repair_set_is_pinned():
    assert E.SIGN_REPAIR_PREFIXES == {"NM", "NN", "UT"}
