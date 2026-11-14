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


# ------------------------------------------------------------------------------------------------ IDEM's outfall layer

def _script(name):
    import importlib.util
    import sys
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(ROOT / "scripts"))
    spec.loader.exec_module(mod)
    return mod


def _idem(oid, permit, cso, status, lat=40.0, lon=-86.0, wtype="Untreated CSO", stream="Sample Creek"):
    return {"attributes": {"OBJECTID": oid, "Agency_Interest_ID": 1, "City": "City of Example", "NPDES_Number": permit,
                           "CSO_Number": cso, "Receiving_Stream": stream, "waterbody_desc_2": "Example River",
                           "waterbody_desc_3": "Wabash River", "waterbody_desc_4": None, "Status": status,
                           "County": "Marion", "Basin": "Patoka-White", "Sub_Basin": "Upper White",
                           "Watershed": "Sample Creek", "Wastewater_Type": wtype, "X_Coordinate": lon,
                           "Y_Coordinate": lat, "Photo_Credit": "Jane Example"},
            "geometry": None if lat is None else {"x": lon, "y": lat}}


def test_idem_outfall_numbers_and_names():
    B = _script("build_in_outfalls")
    assert B.outfall_number("002C -- CSO - Town Lake - Inactive") == "002"
    assert B.outfall_number("011CP -- CSO - Authorized when WWTP exceeds cap") == "011"
    assert B.outfall_number("11AC -- CSO - Example and Sample") == "11A"
    assert B.outfall_number("004Z -- SSO") == "004Z"
    assert B.outfall_number("A38 -- CSO - Example St and Sample St") == "A38"
    assert B.outfall_number("CSO at the bridge") is None
    assert B.scrub_name("CSO - 1234 S Example St") == "CSO - [house number removed] S Example St"
    assert B.scrub_name("CSO - 800' North of 4321 Sample Ave.") == "CSO - 800' North of [house number removed] Sample Ave."
    for keep in ("CSO - Highway 67 East of Highway 1", "CSO - 001 Pond", "CSO - CS 002 Pump Station",
                 "CSO - Alley 31-32 North Side Blvd", "CSO - Example Rd 120\" S of Bridge"):
        assert B.scrub_name(keep) == keep


def test_idem_rows_supersede_epas_and_inactive_is_closed():
    B = _script("build_in_outfalls")
    doc = {"features": [_idem(1, "IN0000003", "002C -- CSO - Example Ave", "Active", 39.9, -86.1),
                        _idem(2, "IN0000003", "003C -- CSO - 1234 Sample St - Inactive", "Inactive"),
                        _idem(3, "IN0000003", "004C -- CSO - Example", "Active, Discharge Prohibited"),
                        _idem(4, "IN0000003", "005Z -- SSO", "Inactive", wtype="Domestic (Sanitary) Wastewater"),
                        _idem(5, "IN0000003", "006C -- CSO", "Inactive", lat=None)]}
    epa = [{"npdes_permit": "IN0000003", "state": "IN", "outfall": "002", "outfall_status": "CSO", "permittee": "EXAMPLE WWTP",
            "city": "EXAMPLE", "coords_from": "facility", "echo_url": "https://echo.epa.gov/x"},
           {"npdes_permit": "IN0000003", "state": "IN", "outfall": "009", "outfall_status": "CSO", "permittee": "EXAMPLE WWTP"}]
    out = B.build(doc, epa, "2026-11-14T00:00:00Z")
    by = {r["outfall"]: r for r in out["outfalls"]}
    assert set(by) == {"002", "003", "004", "005Z"} and out["no_point"][0]["outfall"] == "006"
    assert by["002"]["supersedes"]["coords_from"] == "facility" and by["002"]["permittee"] == "EXAMPLE WWTP"
    assert (by["002"]["lat"], by["002"]["lon"]) == (39.9, -86.1) and by["002"]["coords_from"] == "state outfall layer"
    assert by["002"]["downstream_waters"] == ["Example River", "Wabash River"]
    assert by["003"]["outfall_status"].startswith("CLS") and "house number removed" in by["003"]["outfall_name"]
    assert not by["004"]["outfall_status"].startswith("CLS")
    assert by["005Z"]["outfall_kind"] == "other" and by["002"]["outfall_kind"] == "cso"
    assert out["epa_not_in_state_layer"][0]["outfall"] == "009"
    assert "Jane Example" not in json.dumps(out) and "Photo_Credit" not in json.dumps(out)


def test_the_committed_outfall_file_is_the_registrys_indiana_layer():
    import common as C
    doc = json.loads((ROOT / "data" / "outfalls-in.json").read_text())
    assert doc["count"] == len(doc["outfalls"]) >= 800 and "Photo_Credit" not in json.dumps(doc)
    reg = {C.outfall_key(r["npdes_permit"], r["outfall"]): r for r in C.load_outfall_registry(provisional=False)
           if r.get("state") == "IN"}
    row = next(r for r in doc["outfalls"] if r.get("supersedes"))
    assert reg[C.outfall_key(row["npdes_permit"], row["outfall"])]["_file"] == "data/outfalls-in.json"
    assert all(abs(r["lat"] - 39.8) < 2.2 and -88.2 < r["lon"] < -84.7 for r in doc["outfalls"])


# ------------------------------------------------------------------------------------------------ EPA's monthly DMRs

def _dmr(pend, value=None, nodi=None, unit="#/mo", received="28-SEP-25"):
    return {"MonitoringPeriodEndDate": pend, "DMRValueNmbr": value, "DMRUnitDesc": unit if value else None,
            "StatisticalBaseDesc": "MO TOTAL", "NODICode": nodi, "NODIDesc": "No Discharge" if nodi == "C" else None,
            "ValueReceivedDate": received, "DMRValueId": f"v{pend}"}


def _results():
    def res(code, desc, unit, rows_by_feat):
        return {"Message": "Success", "CWPName": "EXAMPLE WWTP", "StartDate": "01/01/2025",
                "PermFeatures": [{"PermFeatureNmbr": f, "PermFeatureTypeDesc": "External Outfall",
                                  "Parameters": [{"ParameterCode": code, "ParameterDesc": desc,
                                                  "MonitoringLocationDesc": "Effluent Gross",
                                                  "DischargeMonitoringReports": rows}]}
                                 for f, rows in rows_by_feat.items()]}
    return {
        ("IN0000004", "84165"): res("84165", "Discharge event observation", "#/mo", {
            "002": [_dmr("31-AUG-25", "1"), _dmr("30-SEP-25", nodi="C", received="28-OCT-25")],
            "003": [_dmr("31-AUG-25", nodi="C")], "001": [_dmr("31-AUG-25", "4")]}),
        ("IN0000004", "50037"): res("50037", "Duration", "hr/mo", {
            "002": [_dmr("31-AUG-25", "4", unit="hr/mo"), _dmr("30-SEP-25", nodi="C", received="28-OCT-25")]}),
        ("IN0000004", "74063"): res("74063", "Overflow volume", "Mgal", {
            "002": [_dmr("31-AUG-25", "1.1", unit="Mgal"), _dmr("30-SEP-25", nodi="C", received="28-OCT-25")]}),
    }


def _registry():
    return {("IN0000004", "2"): {"npdes_permit": "IN0000004", "outfall": "002", "state": "IN", "outfall_kind": "cso",
                                 "outfall_status": "active (IDEM layer)", "lat": 41.6, "lon": -86.7,
                                 "county": "LaPorte", "receiving_water_echo": "Sample Ditch", "water_slug": "sample-ditch-in",
                                 "_file": "data/outfalls-in.json"},
            ("IN0000004", "3"): {"npdes_permit": "IN0000004", "outfall": "003", "state": "IN", "outfall_kind": "cso",
                                 "outfall_status": "active (IDEM layer)", "lat": 41.61, "lon": -86.71, "county": "LaPorte"}}


def test_monthly_dmr_totals_are_one_month_precision_record_per_outfall_month():
    from collections import Counter, defaultdict

    from ingest import in_echo_cso_monthly as M
    stats = defaultdict(Counter)
    cells, names = M.collect(_results(), _registry(), stats)
    recs = M.build_records(cells, names, _registry(), {}, stats)
    assert len(recs) == 1
    r = recs[0]
    assert r["source_record_id"] == "IN0000004:002:2025-08" and r["event_type"] == "cso" and r["status"] == "ended"
    assert (r["started_at"], r["ended_at"], r["time_precision"]) == ("2025-08-01", "2025-08-31", "month")
    assert r["reported_at"] == "2025-09-28" and r["volume_gal"] == 1_100_000
    assert r["volume_text"] == "1 discharge event, 4 hours, 1.1 million gallons in 2025-08 (monthly DMR totals)"
    assert r["water_slugs"] == ["sample-ditch-in"] and r["lat"] == 41.6
    assert r["raw"]["time_zone"] == "America/Chicago"                     # LaPorte County keeps Central time
    assert stats["skipped_not_cso_outfall"]["IN0000004:001"] == 1          # the plant's own outfall
    assert stats["no_discharge_months"]["IN0000004"] == 2                  # 002 in September, 003 in August
    latest = M.latest_months(cells)
    assert latest["IN0000004|002"] == {"month": "2025-09", "discharged": False, "events": 0.0, "received_at": "2025-10-28"}
    assert latest["IN0000004|003"]["discharged"] is False


def test_monthly_records_never_colour_and_are_an_epa_monthly_source():
    from build import status
    assert "in-echo-dmr-cso" in status.EPA_MONTHLY_SOURCES
    from ingest import in_echo_cso_monthly as M
    assert M.SOURCE_ID == "in-echo-dmr-cso" and set(M.PARAMS) == {"84165", "50037", "74063"}


def test_permits_read_are_those_with_an_open_combined_sewer_outfall():
    from ingest import in_echo_cso_monthly as M
    reg = _registry()
    reg[("IN0000005", "1")] = {"npdes_permit": "IN0000005", "outfall": "001", "state": "IN", "outfall_kind": "cso",
                               "outfall_status": "CLS (inactive in IDEM's layer)"}
    assert M.permits_to_read(reg) == ["IN0000004"]


# ------------------------------------------------------------------------------------------------ IDEM's bloom samples

def _cyano(rows=None, at="2026-11-14T18:00:00Z", prev=()):
    from ingest.generic import arcgis, runner
    _, block = runner.load_source("in-idem-cyanobacteria")
    rows = arcgis.parse(block, (FIX / "in_idem_cyanobacteria.json").read_bytes()) if rows is None else rows
    return runner.build("in-idem-cyanobacteria", block, rows, at, prev)


def _cyano_rows():
    from ingest.generic import arcgis, runner
    _, block = runner.load_source("in-idem-cyanobacteria")
    return arcgis.parse(block, (FIX / "in_idem_cyanobacteria.json").read_bytes())


def test_cyano_block_reads_the_layer_with_its_hooks():
    from ingest.generic import runner
    _, block = runner.load_source("in-idem-cyanobacteria")
    assert block["platform"] == "arcgis" and not runner.validate_block(block) and block["round_coords"] == 3
    assert block["transform"] == "ingest.in_transforms.in_cyano_record"
    assert block["after_history"] == "ingest.in_transforms.in_cyano_sequence"


def test_advisory_level_samples_are_idems_bloom_records_and_low_risk_is_none():
    recs, stats = _cyano()
    assert len(recs) == 7                                  # 4 Advisory at Mississinewa, 3 Dog Park Closed
    assert {r["event_type"] for r in recs} == {"hab_advisory"}
    assert not [r for r in recs if "Low Risk" in str(r["raw"].get("_level"))]
    r = next(x for x in recs if x["sampled_at"] == "2026-09-08" and "WMI" in x["source_record_id"])
    assert r["started_at"] is None and r["ended_at"] is None and r["status"] == "unknown"   # the season is 67 days old
    assert "Advisory" in r["advice_text"] and r["raw"]["time_zone"] == "America/New_York"
    assert r["lat"] == round(r["lat"], 3) and r["raw"]["_placement"] == "named_water_only"


def test_a_recent_advisory_sample_opens_an_interval_at_the_poll_and_a_newer_sample_closes_it():
    rows = [r for r in _cyano_rows() if r.get("location_id") == "WWU-09-0027"]
    rows.sort(key=lambda r: r["date_"])
    before_last = [r for r in rows if r["date_"] < "2026-09-14"]
    first, _ = _cyano(before_last, "2026-09-10T15:00:00Z")
    open_ = next(r for r in first if r["sampled_at"] == "2026-09-08")
    assert open_["status"] == "advisory_active" and open_["started_at"] == "2026-09-10T15:00:00Z"
    assert open_["time_precision"] == "poll" and open_["ended_at"] is None
    older = next(r for r in first if r["sampled_at"] == "2026-08-31")
    assert older["started_at"] is None                     # not the latest sample: history only
    second, _ = _cyano(rows, "2026-09-16T15:00:00Z", first)
    was = next(r for r in second if r["sampled_at"] == "2026-09-08")
    assert was["ended_at"] == "2026-09-16T15:00:00Z" and was["raw"]["ended_at_precision"] == "poll"
    assert was["status"] == "ended"                        # the newer sample is also at an advisory level
    now = next(r for r in second if r["sampled_at"] == "2026-09-14")
    assert now["status"] == "advisory_active" and now["started_at"] == "2026-09-16T15:00:00Z"


def test_an_old_season_first_read_late_opens_nothing():
    recs, _ = _cyano(at="2026-11-14T18:00:00Z")
    assert all(r["started_at"] is None and r["status"] == "unknown" for r in recs)


def test_an_implausible_monthly_volume_is_kept_as_text_only():
    from collections import Counter, defaultdict

    from ingest import in_echo_cso_monthly as M
    res = _results()
    res[("IN0000004", "74063")]["PermFeatures"][0]["Parameters"][0]["DischargeMonitoringReports"][0]["DMRValueNmbr"] = "28482"
    stats = defaultdict(Counter)
    cells, names = M.collect(res, _registry(), stats)
    r = M.build_records(cells, names, _registry(), {}, stats)[0]
    assert r["volume_gal"] is None and "28482 million gallons" in r["volume_text"]
    assert "not counted as a volume" in r["raw"]["volume_note"]


def test_an_invalid_permit_is_an_answer_not_a_failure(monkeypatch):
    from ingest import in_echo_cso_monthly as M

    class R:
        content = b"{}"

        def raise_for_status(self):
            pass

        def json(self):
            return {"Results": {"Error": {"ErrorMessage": "NPDES ID  IN0000009 is invalid!"}}}
    monkeypatch.setattr(M.requests, "get", lambda *a, **k: R())
    res, how = M.fetch("IN0000009", "84165", M.date(2025, 1, 1))
    assert res is None and how.startswith("not in ECHO") and not how.startswith("failed")
