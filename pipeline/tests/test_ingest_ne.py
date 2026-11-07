"""Nebraska: the Nebraska rules of EPA's overflow tables (the zone by the event's point against the Mountain-time
counties, the free-text scrub, --file), on real Nebraska rows (tests/fixtures/ne_sobe_rows.json: thirteen events of the
2026-11-04 extract; one house address replaced by a placeholder), the proof that adding the state changes no other
state's record, and the Beach Watch fetch block (tests/fixtures/ne_dwee_beachwatch.json: real rows of the layer)."""
import copy
import csv
import io
import json
import re
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
    assert E.POINT_ZONE_FILES == {"SD": "sd-mountain-time-counties.json", "NE": "ne-mountain-time-counties.json"}
    assert "NE" in E.FREE_TEXT_STATES and "NE" not in E.REPEATED_POINT_STATES and "NE" not in E.STATE_NO_WATER


def test_the_mountain_counties_file_cites_the_boundary_and_holds_eighteen_counties_and_cherrys_west():
    doc = json.loads((ROOT / "data" / "reference" / "ne-mountain-time-counties.json").read_text())
    assert doc["law"]["cite"] == "49 CFR 71.7(c)" and doc["zone"] == "America/Denver"
    assert sorted(c["county"] for c in doc["counties"]) == sorted(
        [f"{n} County" for n in ("Arthur", "Banner", "Box Butte", "Chase", "Cheyenne", "Dawes", "Deuel", "Dundy",
                                 "Garden", "Grant", "Hooker", "Keith", "Kimball", "Morrill", "Perkins",
                                 "Scotts Bluff", "Sheridan", "Sioux")])
    assert [c["county"] for c in doc["split_counties"]] == ["Cherry County"]          # South Dakota's shape
    cherry = doc["split_counties"][0]
    assert cherry["mountain_part"] and cherry["central_part"] and 0.6 < cherry["mountain_share"] < 0.7
    assert "tigerweb.geo.census.gov" in doc["source"]["url"] and "NTAD_Time_Zones" in doc["checked_against"]["url"]


def test_the_zone_is_the_zone_of_the_events_own_point():
    assert E.point_zone("NE", 41.866, -103.667)[0] == "America/Denver"        # Scottsbluff, Scotts Bluff County
    assert E.point_zone("NE", 41.128, -101.719)[0] == "America/Denver"        # Ogallala, Keith County
    assert E.point_zone("NE", 41.123, -100.765)[0] == "America/Chicago"       # North Platte, Lincoln County
    assert E.point_zone("NE", 41.257, -95.935)[0] == "America/Chicago"        # Omaha
    tz, basis = E.point_zone("NE", 42.917, -101.700)                         # Merriman, western Cherry County
    assert tz == "America/Denver" and "part of Cherry County west of the boundary" in basis
    tz, basis = E.point_zone("NE", 42.873, -100.551)                         # Valentine, eastern Cherry County
    assert tz == "America/Chicago" and "Central part of Cherry County" in basis and "split" in basis and "split" in basis
    tz, basis = E.point_zone("NE", 40.81, -96.70)                            # Lincoln
    assert tz == "America/Chicago" and "outside the eighteen Mountain-time counties and Cherry County" in basis
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
        "CSO at a CSO outfall or regulator"                                   # Omaha's CSO permit, at outfall 110
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
    unk = by["NE0112810:11:1"]                                                # into a storm inlet; water 'Unknown'
    assert unk["waterbody_text"] is None and unk["raw"]["receiving_waters"] == ["Unknown"]
    assert "'Unknown'" in unk["raw"]["receiving_water_note"]                  # kept, never printed as a water name
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


def test_beachwatch_block_reads_the_whole_layer_with_its_hooks():
    from ingest.generic import runner
    _, block = runner.load_source("ne-dwee-beachwatch")
    assert block["live"] is True and block["platform"] == "arcgis" and not runner.validate_block(block)
    assert "where" not in block                                              # every row: the next sample is needed
    assert block["post"] == "ingest.ne_transforms.ne_beachwatch_sequence"
    assert block["time_zone"] == "America/Chicago"


def test_beachwatch_health_alert_is_the_authoritys_bloom_advisory_and_e_coli_a_caution():
    recs, stats = _beachwatch()
    by = {r["source_record_id"]: r for r in recs}
    rock = by["LBB1ROCKFD04-2026-w23"]
    assert rock["event_type"] == "hab_advisory" and rock["started_at"] == "2026-06-08" and rock["time_precision"] == "day"
    assert rock["waterbody_text"] == "Rockford Lake" and rock["outfall_name"] == "Rockford Lake at Beach"
    assert rock["advice_text"].startswith("This beach is under health alert") and "13.78" in rock["advice_text"]
    assert rock["lat"] == 40.223196 and rock["published_at"] is None
    both = by["LNE2IRONHT04-2026-w23"]                                       # alert and E. coli: the alert
    assert both["event_type"] == "hab_advisory" and both["raw"]["_ecoli_risk"].startswith("Elevated")
    oak = by["LLP2BRNOAK09-2026-w21"]
    assert oak["event_type"] == "beach_advisory" and oak["status"] == "unknown"
    assert oak["raw"]["_agency_label_only"] is True and oak["raw"]["_agency_label"] == "Elevated health risk for E. coli"
    assert "\u201cElevated health risk for E. coli\u201d" in oak["advice_text"] and "no advisory" in oak["advice_text"]
    assert oak["waterbody_text"] == "Branched Oak Lake" and oak["started_at"] == "2026-05-26"
    # a sample with neither statement is read (for the sequence) but is not a record
    assert "GPTLKBACT1-2026-w21" not in by and "LBB1ROCKFD04-2026-w24" not in by
    assert stats["by_type"] == {"hab_advisory": 3, "beach_advisory": 2} and stats["duplicates"]["samples_dropped"] == 2


def test_a_bloom_alert_ends_at_the_stations_next_sample():
    """Rockford Lake: on alert in weeks 22 and 23, off in week 24 (the real sequence)."""
    by = {r["source_record_id"]: r for r in _beachwatch()[0]}
    w22, w23 = by["LBB1ROCKFD04-2026-w22"], by["LBB1ROCKFD04-2026-w23"]
    assert w22["status"] == "ended" and w22["ended_at"] == "2026-06-08" and w22["raw"]["_continued_by"] == w23["source_record_id"]
    assert w23["status"] == "advisory_lifted" and w23["ended_at"] == "2026-06-15"
    assert w23["raw"]["_lifted_by"] == "LBB1ROCKFD04-2026-w24"
    iron = by["LNE2IRONHT04-2026-w23"]                                       # no later sample in the fixture: open
    assert iron["status"] == "advisory_active" and iron["ended_at"] is None


def test_beachwatch_colours_red_to_the_lift_and_e_coli_with_the_sites_caution_only():
    from datetime import UTC, datetime, timedelta
    from build import status as S
    by = {r["source_record_id"]: r for r in _beachwatch()[0]}
    now = datetime(2026, 9, 1, tzinfo=UTC)
    rules = S.load_rules()
    ivs = S.event_intervals(by["LBB1ROCKFD04-2026-w23"], "NE", now, None, rules)
    assert [i["color"] for i in ivs] == ["red"] and ivs[0]["rule"] == "advisory_active"
    chicago = S.ZoneInfo("America/Chicago")      # a Nebraska day ends at Central midnight (SOL 2026-11-07 wave 2 P1-1)
    assert ivs[0]["end"] == S.end_of_local_day(S.parse_time("2026-06-15", chicago), chicago)   # the next sample's day
    assert ivs[0]["end"].isoformat() == "2026-06-16T05:00:00+00:00"
    ivs = S.event_intervals(by["LLP2BRNOAK09-2026-w21"], "NE", now, None, rules)
    assert len(ivs) == 1 and ivs[0]["color"] == "yellow" and ivs[0]["rule"] == "sample_caution"
    assert ivs[0]["end"] - ivs[0]["start"] == timedelta(hours=72) and ivs[0]["category"] == "beach"
    assert ivs[0]["rule_applied"]["rule"] == "unresolved.sample_caution" and ivs[0]["red_rule"] is None
    assert ivs[0]["rule_applied"]["label"] == "Elevated health risk for E. coli"
    assert "advisory" not in ivs[0]["label"].split(";")[0].lower() or "no advisory" in ivs[0]["label"].lower()


def test_beachwatch_records_keep_only_the_safe_fields():
    recs, _ = _beachwatch()
    for r in recs:
        assert set(r["raw"]["row"]) <= {"OBJECTID", "StationID", "StationName", "Latitude", "Longitude", "SampleYear",
                                        "WeekNumber", "ActivityStartDate", "EColi", "Microcystin", "HealthAlert",
                                        "EColiRisk", "HealthDescription"}


# ---------------------------------------------------------------- review 2026-11-07: CSO by structure, 'Unknown'

def test_a_cso_typed_overflow_at_a_manhole_is_a_sewer_overflow_with_the_type_as_filed():
    by = {r["source_record_id"]: r for r in _build()[0]}
    for rid in ("NE0112810:63:1", "NE0112810:11:1", "NE0036358:7:1"):       # manhole, manhole, lift station
        r = by[rid]
        assert r["event_type"] == "sso" and r["raw"]["type_as_filed"] == "CSO", rid
        assert "not at a combined sewer outfall" in r["raw"]["type_note"] and r["outfall_id"] is None
        assert r["material"] == E.MATERIAL["sso"]
    assert by["NE0133680:1:1"]["event_type"] == "cso" and by["NE0133680:1:1"]["outfall_id"] == "110"
    w204 = by["NE0133680:8:1"]                                                # permitted feature 204 given
    assert w204["event_type"] == "cso" and w204["outfall_id"] == "204" and "type_as_filed" not in w204["raw"]
    # every NE CSO left names its outfall or its water: none can fall to "every water of the operator"
    assert all(r["outfall_id"] or r["waterbody_text"] for r in by.values() if r["event_type"] == "cso")


def test_an_outfall_named_only_in_the_description_is_read_into_outfall_id():
    fx = _fixture()
    ev = next(e for e in fx["events"] if e["permit_identifier"] == "NE0133680" and e["program_report_form_set_id"] == "8")
    ev["permitted_feature_identifier"] = ""
    ev["sewer_overflow_structure_type_code"], ev["sewer_overflow_structure_type_desc"] = "BRO", "Broken Pipe"
    ev["sewer_overflow_bypass_description_text"] = "Water Main break caused a dry weather overflow at CSO 119"
    r = next(x for x in _build(fx)[0] if x["source_record_id"] == "NE0133680:8:1")
    assert r["event_type"] == "cso" and r["outfall_id"] == "119" and "CSO 119" in r["raw"]["outfall_basis"]


def test_the_structure_rule_and_unknown_water_are_nebraskas_only():
    assert E.CSO_BY_STRUCTURE_STATES == {"NE"} and E.UNKNOWN_WATER_STATES == {"NE"}
    from tests.test_ingest_dc import _row
    t = {"events": [_row(sewer_overflow_bypass_event_key="x", permit_identifier="IL0000009",
                         sewer_overflow_structure_type_code="MAN", sewer_overflow_structure_type_desc="Manhole")],
         "types": [{"sewer_overflow_bypass_event_key": "x", "sewer_overflow_bypass_type_code": "CSO",
                    "sewer_overflow_bypass_type_desc": "", "sewer_overflow_bypass_type_code_sequence": "1"}],
         "waters": [{"sewer_overflow_bypass_event_key": "x", "name_receiving_water": "Unknown"}]}
    r = E.build(t, {})[0][0]
    assert r["event_type"] == "cso" and r["waterbody_text"] == "Unknown"     # Illinois as before


def test_a_retyped_report_naming_no_water_is_never_spread_over_the_operators_waters():
    from build import status as S
    from tests.test_outfall_placement import WATERS
    rec = {r["source_record_id"]: r for r in _build()[0]}["NE0112810:11:1"]
    dw = {rec["discharger_id"]: {"id": rec["discharger_id"], "state": "CT", "names": ["Test River", "Mill River"],
                                 "slugs": []}}
    saved = dict(S.PLACE_STEPS)
    S.PLACE_STEPS.update(registry=True, relaxed_guard=True, no_receiving_water=True, outfall_ids=True,
                         multi_outfall=True)
    S._GEOM_CACHE.clear()
    try:
        res = S.Resolver(WATERS, [], {}, dw, {"no_outfall_all_waters": True})
        # without the point, so the distance guard cannot stand in for the rule (a long river such as the Missouri
        # passes it near Omaha)
        rec = dict(rec, npdes_permit="CT0109999", lat=None, lon=None, coord_source=None)
        assert res.resolve(rec)["water_slugs"] == []
        as_filed = dict(rec, event_type="cso", waterbody_text="Unknown")
        assert res.resolve(as_filed)["water_slugs"] == ["test-river-ct", "mill-river-ct"]   # what the fix prevents
    finally:
        S.PLACE_STEPS.update(saved)
        S._GEOM_CACHE.clear()


# ---------------------------------------------------------------- review 2026-11-07 P2-4: EPA-issued permits

def test_indian_country_permits_report_to_epa_not_dwee():
    dis = {d["id"]: d for d in json.loads((ROOT / "data" / "dischargers.json").read_text()) if d.get("state") == "NE"}
    reg = {r["id"]: r for r in json.loads((ROOT / "data" / "notice-channels" / "ne.json").read_text())["channels"]}
    epa_ops = ("ne-omaha-tribe-macy", "ne-santee-sioux-nation", "ne-winnebago", "ne-walthill", "ne-thurston",
               "ne-pender", "ne-rosalie", "ne-emerson")
    for oid in epa_ops:
        assert dis[oid]["notification_channel"].startswith("NPDES permit issued by EPA Region 7"), oid
        assert "DWEE" not in dis[oid]["notification_channel"], oid
        row = reg[f"{oid}-epa-report"]
        assert "issued by EPA Region 7" in row["legal_basis"] and "DWEE" not in row["legal_basis"]
        assert f"{oid}-dwee-epa-report" not in reg
    assert "DWEE" in dis["ne-beatrice"]["notification_channel"] and "ne-beatrice-dwee-epa-report" in reg


def test_legal_forms_from_the_census_class_and_a_reason_where_none():
    dis = {d["id"]: d for d in json.loads((ROOT / "data" / "dischargers.json").read_text()) if d.get("state") == "NE"}
    assert dis["ne-beatrice"]["legal_form"] == "city" and dis["ne-adams"]["legal_form"] == "town"   # city, village
    assert "Census Bureau" in dis["ne-adams"]["notes"]
    empty = [d for d in dis.values() if not d.get("legal_form")]
    assert len(empty) <= 10
    assert all(re.search(r"not read|not stated", d["notes"]) for d in empty)


def test_public_wording_says_what_was_read():
    text = (ROOT / "research" / "ne" / "state-text.md").read_text()
    assert "kept but not placed" not in text and "are not shown on this site" in text
    assert "must notify the public" not in text and "could not be read" in text
    assert "were not searched one by one" in text and "issued by the federal agency" in text
    basis = json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"]["NE"]["basis"]
    assert "notifies the public under its permit" not in basis and "could not be read" in basis
    reg = {r["id"]: r for r in json.loads((ROOT / "data" / "notice-channels" / "ne.json").read_text())["channels"]}
    assert "exists in Nebraska" not in reg["ne-dwee-overflow-alerts"]["note"]
    for rid in ("ne-omaha-public-works-pages", "ne-dwee-beachwatch-page", "ne-douglas-county-health"):
        assert reg[rid]["urls"], rid                                          # the page's health is recorded
