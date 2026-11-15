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
    assert set(by) == {"002", "003", "004", "005Z", "006"} and out["no_point"][0]["outfall"] == "006"
    assert by["006"]["lat"] is None and by["006"]["outfall_status"].startswith("CLS")   # its status still counts
    assert by["002"]["supersedes"]["coords_from"] == "facility" and by["002"]["permittee"] == "EXAMPLE WWTP"
    assert (by["002"]["lat"], by["002"]["lon"]) == (39.9, -86.1) and by["002"]["coords_from"] == "state outfall layer"
    assert by["003"]["lat"] == 40.0 and isinstance(by["003"]["lat"], float)
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
    assert all(abs(r["lat"] - 39.8) < 2.2 and -88.2 < r["lon"] < -84.7 for r in doc["outfalls"] if r["lat"] is not None)
    assert all(r["lat"] == round(r["lat"], 3) and r["lon"] == round(r["lon"], 3) for r in doc["outfalls"] if r["lat"])
    assert not [r for r in doc["outfalls"] if r.get("coords_from") == "facility"]


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


def test_the_dmr_cache_is_compact_and_a_run_keeps_to_its_request_budget(tmp_path, monkeypatch):
    from ingest import in_echo_cso_monthly as M
    res = _results()[("IN0000004", "84165")]
    res["PermFeatures"][0]["Parameters"].append({"ParameterCode": "00530", "ParameterDesc": "Solids",
                                                 "MonitoringLocationDesc": "Effluent Gross",
                                                 "DischargeMonitoringReports": [_dmr("31-AUG-25", "9")]})
    c = M.compact(res)
    assert [p["ParameterCode"] for f in c["PermFeatures"] for p in f["Parameters"]] == ["84165", "84165", "84165"]
    assert set(c["PermFeatures"][0]["Parameters"][0]["DischargeMonitoringReports"][0]) <= \
        {"MonitoringPeriodEndDate", *M.RAW_FIELDS}
    today = M.date(2026, 11, 14)
    cache = {"IN0000004-84165": {"fetched": "2026-11-10", "since": "2025-01-01", "results": c},
             "IN0000004-50037": {"fetched": "2026-10-01", "since": "2025-01-01", "results": c}}
    assert M.cached(cache, "IN0000004", "84165", M.date(2025, 1, 1), today)[1].startswith("cache")
    assert M.cached(cache, "IN0000004", "50037", M.date(2025, 1, 1), today) == (None, None)
    assert M.cached(cache, "IN0000004", "50037", M.date(2025, 1, 1), today, stale_ok=True)[1].startswith("stale")
    # a run with a budget of one request asks one and reads the rest from older answers or the previous run
    monkeypatch.setattr(M, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(M, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    common.write_json(M.CACHE_FILE, {"answers": cache})
    monkeypatch.setattr(M, "registry_outfalls", lambda rows=None: _registry())
    monkeypatch.setattr(M, "MAX_LIVE_REQUESTS", 1)
    monkeypatch.setattr(M, "SLEEP_S", 0)
    asked = []
    monkeypatch.setattr(M, "fetch", lambda p, code, since: (asked.append(code) or _results()[(p, code)], "live"))
    assert M.main(["--since", "2025-01-01"]) == 0
    doc = json.loads((tmp_path / "events" / "in-echo-dmr-cso.json").read_text())
    assert asked == ["74063"]                              # never fetched: asked first; the budget then ends
    assert doc["meta"]["fetch"]["IN0000004-50037"].startswith("stale cache")
    assert doc["meta"]["not_asked_this_run"] == ["IN0000004-50037"]
    assert json.loads(M.CACHE_FILE.read_text())["answers"]["IN0000004-74063"]["fetched"]


# ------------------------------------------------------------------------------------------------ registry and text

def _rows(state="IN"):
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == state]


def test_every_indiana_permit_is_in_one_operator_row_and_no_person_is_named():
    from ingest import dischargers_schema as DS
    rows = _rows()
    permits = [p for r in rows for p in r["npdes_permits"]]
    assert len(permits) == len(set(permits)) >= 750
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "IN"}
    idem = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-in.json").read_text())["outfalls"]}
    assert plants | idem <= set(permits)
    assert DS.check_legal_forms(rows) == []
    by = {r["id"]: r for r in rows}
    assert by["in-city-of-la-porte"]["legal_form"] == "city" and by["in-town-of-waterloo"]["legal_form"] == "town"
    assert by["in-citizens-energy-group-cwa-authority"]["kind"] == "cso"
    assert set(by["in-city-of-south-bend"]["npdes_permits"]) == {"IN0024520", "INM024520"}
    assert "Gifford" not in json.dumps(rows) and "Blucher" not in json.dumps(rows)   # plants named after people
    holders = [r for r in rows if r["legal_form"] == "facility (permittee not named)"]
    assert all(r["name"].startswith("Holder of permit") or "(permit IN" in r["name"] for r in holders)


def test_the_register_names_every_operator_and_validates():
    from ingest import notification_pages as NP
    doc = json.loads((ROOT / "data" / "notice-channels" / "in.json").read_text())
    chans = doc["channels"]
    ops = {r["operator_id"] for r in chans if r.get("operator_id")}
    rows = _rows()
    assert {r["id"] for r in rows} <= ops
    assert {r["id"] for r in rows if r["kind"] == "cso"} <= {r["operator_id"] for r in chans
                                                              if r["id"].endswith("-cso-notice")}
    by = {r["id"]: r for r in chans}
    assert by["in-fort-wayne-cso-notifications"]["barrier"] == "bot_wall"
    assert by["in-idem-beachalert"]["barrier"] == "not_verified"            # review 2026-11-14 P2-10: templates only
    assert by["in-mishawaka-cso-alerts-x"]["barrier"] == "login_required"
    assert by["in-epa-echo-cso-dmr"]["feed_source_id"] == "in-echo-dmr-cso"
    assert not [r for r in chans if r.get("barrier_review")]
    full = NP.load_register(ROOT / "data" / "notice-channels")
    assert NP.validate_register(full, json.loads((ROOT / "data" / "dischargers.json").read_text()), ROOT) == []


def test_the_rules_row_and_the_missing_waters_list():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    row = rules["red"]["by_state"]["IN"]
    assert row["hours"] is None and "327 IAC 5-2.1" in row["source"] and "49 CFR 71.5(b)" in row["source"]
    assert "safe" not in row["basis"].lower() and "clean" not in row["basis"].lower()
    miss = json.loads((ROOT / "research" / "in" / "receiving-waters-missing.json").read_text())
    names = {r["name"] for r in miss["rows"]} | {r.get("name") for r in miss.get("resolved") or []}
    assert miss["state"] == "IN" and {"Pouges Run", "Little Calumet River"} <= names
    assert not [r for r in miss["rows"] if r["name"].lower().startswith("unnamed")]
    assert all(len(p) == 2 and p == [round(p[0], 3), round(p[1], 3)] for r in miss["rows"] for p in r["points"])


def test_a_monthly_grade_from_epas_reports_credits_epa_and_other_states_read_as_before():
    from datetime import UTC, datetime

    from export import coverage as C
    f = {"records_12m": 4485, "dated_share": 0.0002, "monthly_share": 0.9998, "annual_share": 0.0,
         "latest_dated": "2026-08-12T21:30:00-04:00", "lag_days": 1}
    now = datetime(2026, 11, 14, tzinfo=UTC)
    g, s = C.grade_of("IN", f, now, federal=True)
    assert g == "Monthly totals only"
    assert s.startswith("Overflow reports from sewer operators in Indiana are published by the U.S. "
                        "Environmental Protection Agency almost all as monthly totals, with few dated reports")
    assert "Indiana publishes" not in s and "no dated" not in s
    g0, s0 = C.grade_of("IN", dict(f, dated_share=0.0), now, federal=True)
    assert s0.startswith("Monthly overflow totals from sewer operators in Indiana are published by the U.S.")
    g2, s2 = C.grade_of("NJ", f, now, federal=False)
    assert s2 == ("New Jersey publishes monthly totals, not dated reports; the map shows no dated discharges there "
                  "because none are reported by date, not because none happen.")


# ------------------------------------------------------------------------------------------------ review 2026-11-14

def test_indiana_name_placement_is_county_aware(monkeypatch):
    """Astra review 2026-11-14 P2-6: two same-named creeks in different counties; the report's point decides."""
    from build import status as S
    assert S.COUNTY_STATES["IN"] == "in-counties.json"
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"IN"})
    assert S.point_county("IN", 39.77, -86.16)[1] == "Marion County"
    assert S.point_county("IN", 41.68, -86.25)[1] == "St. Joseph County"
    waters = {"mill-creek-marion-in": {"state": "IN", "bbox": [-86.20, 39.70, -86.10, 39.80]},
              "mill-creek-st-joseph-in": {"state": "IN", "bbox": [-86.30, 41.60, -86.20, 41.70]}}
    ev = {"source_id": "in-idem-cyanobacteria", "event_id": "in-idem-cyanobacteria:x", "lat": 41.65, "lon": -86.26,
          "raw": {"state": "IN"}}
    kept, why = S.county_slugs(list(waters), ev, waters, lambda slug, lat, lon: 50_000)
    assert kept == ["mill-creek-st-joseph-in"] and "St. Joseph" in why
    assert S.COUNTY_STATES["OH"] == "oh-counties.json" and "IN" in S.COUNTY_FIELD_STATES


def test_a_name_only_tie_beyond_25_km_is_refused_in_indiana():
    from ingest import outfall_waters as OW
    assert OW.NAME_ONLY_CAP_M == {"TX": 25_000, "IN": 25_000}

    class MT:
        waters = {"sample-creek-in": {"name": "Sample Creek", "kind": "river"}}
        d = 0.0

        def dist(self, s, lat, lon):
            return self.d

        def source_of(self, s):
            return "nhd"

        def no_outline(self, s):
            return False

        def evidence_of(self):
            return {}
    mt = MT()
    for d, tied in ((24_000.0, True), (26_000.0, False), (100_000.0, False)):
        mt.d = d
        o = {"state": "IN", "npdes_permit": "IN0000006", "lat": 40.0, "lon": -86.0, "receiving_water_echo": "SAMPLE CREEK"}
        OW.apply(o, {"slug": "sample-creek-in", "step": "name", "how": "the only record of that name"}, mt)
        assert (o["water_slug"] == "sample-creek-in") is tied, d
    o2 = {"state": "KY", "npdes_permit": "KY0000006", "lat": 37.0, "lon": -86.0, "receiving_water_echo": "SAMPLE CREEK"}
    OW.apply(o2, {"slug": "sample-creek-in", "step": "name", "how": "the only record of that name"}, mt)
    assert o2["water_slug"] == "sample-creek-in"                           # other states unchanged


def _one_sample(level, date="2026-09-08", oid=9001):
    return {"objectid": oid, "advisory_level": level, "beach_name": "Example Beach", "waterbody": "Example Lake",
            "date_": date, "year_": 2026, "location_id": "EXA-01-0001", "sample_id": f"S{oid}",
            "project": "2026 Example Project", "microcystin": -1, "_x": -86.0, "_y": 40.0}


def test_a_blank_level_neither_lifts_nor_reopens_and_a_restored_advisory_reopens():
    """Astra review 2026-11-14 P1-1: Advisory, blank, Advisory stays one open interval; Advisory, Low Risk, Advisory
    closes at the Low Risk read and reopens at the next read, the first interval kept."""
    a, _ = _cyano([_one_sample("Advisory")], "2026-09-09T12:00:00Z")
    assert a[0]["status"] == "advisory_active" and a[0]["time_precision"] == "poll"
    b, _ = _cyano([_one_sample("")], "2026-09-09T13:00:00Z", a)
    assert b[0]["status"] == "advisory_active" and b[0]["ended_at"] is None and b[0]["raw"]["_level_unknown_this_read"]
    c, _ = _cyano([_one_sample("Advisory")], "2026-09-09T14:00:00Z", b)
    assert c[0]["status"] == "advisory_active" and c[0]["started_at"] == "2026-09-09T12:00:00Z"
    d, _ = _cyano([_one_sample("Low Risk")], "2026-09-09T15:00:00Z", c)
    assert d[0]["status"] == "advisory_lifted" and d[0]["ended_at"] == "2026-09-09T15:00:00Z"
    e, _ = _cyano([_one_sample("Advisory")], "2026-09-09T16:00:00Z", d)
    assert e[0]["status"] == "advisory_active" and e[0]["started_at"] == "2026-09-09T16:00:00Z"
    assert e[0]["raw"]["_advisory_observed"]["earlier_periods"][0]["end"] == "2026-09-09T15:00:00Z"


def test_a_newer_sample_with_an_unknown_level_does_not_end_an_advisory():
    a, _ = _cyano([_one_sample("Advisory")], "2026-09-09T12:00:00Z")
    b, _ = _cyano([_one_sample("Advisory"), _one_sample("", "2026-09-14", 9002)], "2026-09-15T12:00:00Z", a)
    r = next(x for x in b if x["sampled_at"] == "2026-09-08")
    assert r["status"] == "advisory_active" and r["ended_at"] is None
    c, _ = _cyano([_one_sample("Advisory"), _one_sample("Low Risk", "2026-09-14", 9002)], "2026-09-15T13:00:00Z", b)
    r = next(x for x in c if x["sampled_at"] == "2026-09-08")
    assert r["status"] == "advisory_lifted" and r["raw"]["ended_at_precision"] == "poll"


def _dmr_main(tmp_path, monkeypatch, results, registry=None, prev=None):
    from ingest import in_echo_cso_monthly as M
    monkeypatch.setattr(M, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(M, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    monkeypatch.setattr(M, "registry_outfalls", lambda rows=None: registry or _registry())
    monkeypatch.setattr(M, "SLEEP_S", 0)
    monkeypatch.setattr(M, "fetch", lambda p, code, since: (results.get((p, code)) or
                                                            {"Message": "Success", "PermFeatures": []}, "live"))
    assert M.main(["--since", "2025-01-01", "--refresh"]) == 0
    return json.loads((tmp_path / "events" / "in-echo-dmr-cso.json").read_text())


def test_a_month_the_source_drops_is_kept_and_one_it_corrects_to_no_discharge_is_withdrawn(tmp_path, monkeypatch):
    """Astra review 2026-11-14 P1-2."""
    first = _dmr_main(tmp_path, monkeypatch, _results())
    assert [r["source_record_id"] for r in first["records"]] == ["IN0000004:002:2025-08"]
    gone = _dmr_main(tmp_path, monkeypatch, {})                        # an empty successful answer
    assert len(gone["records"]) == 1 and gone["records"][0]["raw"]["_missing_from_source_since"]
    assert gone["meta"]["latest_month_by_outfall"]["IN0000004|002"]["month"] == "2025-09"   # the earlier zero kept
    res = _results()
    for code in ("84165", "50037", "74063"):
        row = res[("IN0000004", code)]["PermFeatures"][0]["Parameters"][0]["DischargeMonitoringReports"][0]
        row.update(DMRValueNmbr=None, NODICode="C", NODIDesc="No Discharge")
    fixed = _dmr_main(tmp_path, monkeypatch, res)
    assert fixed["records"] == [] and fixed["meta"]["months_withdrawn_by_the_source"]


def test_a_revised_dmr_row_wins_over_a_larger_earlier_value():
    """Astra review 2026-11-14 P2-9."""
    from ingest import in_echo_cso_monthly as M
    old = dict(_dmr("31-AUG-25", "3"), VersionNmbr="0")
    new = dict(_dmr("31-AUG-25", None, nodi="C", received="15-OCT-25"), VersionNmbr="1")
    assert M.revision_key(new) > M.revision_key(old)
    res = _results()
    rows = res[("IN0000004", "84165")]["PermFeatures"][0]["Parameters"][0]["DischargeMonitoringReports"]
    rows[:] = [dict(_dmr("31-AUG-25", "0", received="20-OCT-25"), VersionNmbr="1"),
               dict(_dmr("31-AUG-25", "4"), VersionNmbr="0")]
    from collections import Counter, defaultdict
    cells, _ = M.collect(res, _registry(), defaultdict(Counter))
    assert cells[("IN0000004", "002", "2025-08")]["events"]["DMRValueNmbr"] == "0"


def test_a_plant_point_is_withheld_points_are_rounded_and_charts_get_events_and_hours():
    """Astra review 2026-11-14 P1-4, P1-5 and P2-8."""
    from collections import Counter, defaultdict

    from build import charts
    from ingest import in_echo_cso_monthly as M
    reg = _registry()
    reg[("IN0000004", "2")] = dict(reg[("IN0000004", "2")], lat=41.612345, lon=-86.712345)
    cells, names = M.collect(_results(), reg, defaultdict(Counter))
    r = M.build_records(cells, names, reg, {}, defaultdict(Counter))[0]
    assert (r["lat"], r["lon"]) == (41.612, -86.712)
    assert charts.total_measures(r) == {"gallons": 1_100_000.0, "events": 1.0, "hours": 4.0}
    reg[("IN0000004", "2")] = dict(reg[("IN0000004", "2")], coords_from="facility")
    r = M.build_records(cells, names, reg, {}, defaultdict(Counter))[0]
    assert r["lat"] is None and r["coord_source"] is None and "plant's point" in r["raw"]["point_note"]


def test_epas_tie_is_carried_only_onto_the_same_named_water_and_epas_plant_points_never_reach_the_registry():
    """Astra review 2026-11-14 P1-3 and P1-4 (synthetic permits, names and points)."""
    B = _script("build_in_outfalls")
    doc = {"features": [_idem(1, "IN0000007", "002C -- CSO", "Active", 40.0, -86.0, stream="Little Example River"),
                        _idem(2, "IN0000007", "003C -- CSO", "Active", 40.001, -86.0, stream="Example River"),
                        _idem(3, "IN0000007", "004C -- CSO", "Inactive", lat=None),
                        _idem(4, "IN0000007", "006C -- CSO", "Active", lat=None)]}
    tie = {"state": "IN", "npdes_permit": "IN0000007", "outfall_status": "CSO", "lat": 40.0005, "lon": -86.0,
           "coords_from": "permitted_feature", "water_slug": "example-river-in", "water_name": "Example River",
           "match": "name"}
    epa = [dict(tie, outfall="002"), dict(tie, outfall="003"), dict(tie, outfall="004"),
           dict(tie, outfall="006", coords_from="facility"), dict(tie, outfall="005", coords_from="facility")]
    by = {r["outfall"]: r for r in B.build(doc, epa, "2026-11-14T00:00:00Z")["outfalls"]}
    assert "water_slug" not in by["002"]                       # Little Example River is not the Example River
    assert by["003"]["water_slug"] == "example-river-in"
    assert by["004"]["outfall_status"].startswith("CLS") and by["004"]["lat"] == 40.001  # EPA's own feature point
    assert by["006"]["lat"] is None and "own point" in by["006"]["point_note"]           # EPA's plant point withheld
    assert by["005"]["lat"] is None and by["005"]["source"] == "fed-echo-national-cso-inventory"


def test_the_saved_layer_answer_is_sanitized_before_it_is_written():
    B = _script("build_in_outfalls")
    doc = {"features": [_idem(1, "IN0000008", "002C -- CSO - 1234 S Example St", "Active", 40.123456, -86.654321)]}
    out = B.sanitize(doc)
    a, g = out["features"][0]["attributes"], out["features"][0]["geometry"]
    assert "1234" not in json.dumps(out) and "Jane Example" not in json.dumps(out) and "Photo_Credit" not in a
    assert g == {"x": -86.654, "y": 40.123} and a["X_Coordinate"] == -86.654
    assert B.outfall_number(a["CSO_Number"]) == "002"


def test_operators_are_never_named_after_a_plant_and_count_only_sewage_outlets():
    """Astra review 2026-11-14 P2-7."""
    import re
    rows = _rows()
    assert not [r["name"] for r in rows if re.search(r"\bWWTP\b|\bWWTF\b|Treatment Plant|\bSTP\b", r["name"])]
    B = _script("add_in_operators")
    assert B.owner_of_plant("EXAMPLE ESTATES WWTP", "Mixed Ownership (e.g., Public/Private)")[0] is None
    assert B.owner_of_plant("EXAMPLE LAKE CD WWTP", "Municipal or Water District")[1] == "Example Lake CD"
    assert not B.outfall_counts({"outfall": None})
    assert not B.outfall_counts({"outfall": "002", "limit_set_names": ["GROUNDWATER FROM DEWATERING PIPE"]})
    assert B.outfall_counts({"outfall": "001", "limit_set_names": ["MAIN OUTFALL"]})
    holder = next(r for r in rows if "INJ043168" in r["npdes_permits"])
    assert holder["name"] == "Holder of permit INJ043168" and holder["outfall_count"] is None


def test_a_partial_dmr_answer_never_withdraws_an_earlier_discharge(tmp_path, monkeypatch):
    """Astra re-review 2026-11-14 P1-1: zero hours with the events and volume rows missing keeps the discharge."""
    first = _dmr_main(tmp_path, monkeypatch, _results())
    assert first["records"][0]["volume_gal"] == 1_100_000
    res = _results()
    for code in ("84165", "74063"):                                  # events and volume rows missing for August
        rows = res[("IN0000004", code)]["PermFeatures"][0]["Parameters"][0]["DischargeMonitoringReports"]
        rows[:] = [x for x in rows if x["MonitoringPeriodEndDate"] != "31-AUG-25"]
    hours = res[("IN0000004", "50037")]["PermFeatures"][0]["Parameters"][0]["DischargeMonitoringReports"][0]
    hours.update(DMRValueNmbr="0")
    part = _dmr_main(tmp_path, monkeypatch, res)
    assert [r["source_record_id"] for r in part["records"]] == ["IN0000004:002:2025-08"]
    r = part["records"][0]
    assert r["volume_gal"] == 1_100_000 and r["raw"]["events"] == 1.0 and r["raw"]["hours"] == 0.0
    assert r["raw"]["dmr"]["events"]["from_previous_run"] and "from_previous_run" not in r["raw"]["dmr"]["hours"]
    assert not part["meta"].get("months_withdrawn_by_the_source")
    # a wholly missing month is still carried; a full correction to no discharge still withdraws
    gone = _dmr_main(tmp_path, monkeypatch, {})
    assert gone["records"][0]["raw"]["_missing_from_source_since"]
    res = _results()
    for code in ("84165", "50037", "74063"):
        row = res[("IN0000004", code)]["PermFeatures"][0]["Parameters"][0]["DischargeMonitoringReports"][0]
        row.update(DMRValueNmbr=None, NODICode="C", NODIDesc="No Discharge", VersionNmbr="1")
    fixed = _dmr_main(tmp_path, monkeypatch, res)
    assert fixed["records"] == [] and fixed["meta"]["months_withdrawn_by_the_source"]
    assert fixed["meta"]["latest_month_by_outfall"]["IN0000004|002"]["month"] == "2025-09"


def test_equally_ranked_conflicting_dmr_rows_resolve_the_same_whatever_their_order(tmp_path, monkeypatch):
    """Astra re-review 2026-11-14 P2-7."""
    from collections import Counter, defaultdict

    from ingest import in_echo_cso_monthly as M

    def run(rows):
        res = _results()
        res[("IN0000004", "84165")]["PermFeatures"][0]["Parameters"][0]["DischargeMonitoringReports"][:] = rows
        stats = defaultdict(Counter)
        cells, names = M.collect(res, _registry(), stats)
        return cells, M.build_records(cells, names, _registry(), {}, stats), stats

    three, zero = _dmr("31-AUG-25", "3"), _dmr("31-AUG-25", "0")
    nodi = _dmr("31-AUG-25", None, nodi="C")
    for a, b in ((three, zero), (three, nodi)):
        c1, r1, s1 = run([a, b])
        c2, r2, _ = run([b, a])
        assert c1 == c2 and r1 == r2 and s1["conflicting_equal_revisions"]
        assert r1[0]["raw"]["events"] is None and r1[0]["raw"]["conflicting_rows"] == ["events"]
    # missing revision metadata on both rows is equal ranking too
    bare = [{k: v for k, v in x.items() if k not in ("VersionNmbr", "ValueReceivedDate")} for x in (three, zero)]
    assert run(bare)[0] == run(bare[::-1])[0]
    # identical duplicates are no conflict
    c, r, s = run([three, dict(three)])
    assert not s["conflicting_equal_revisions"] and r[0]["raw"]["events"] == 3.0
    # with a previous run, the conflicting parameter keeps the earlier authoritative row
    first = _dmr_main(tmp_path, monkeypatch, _results())
    assert first["records"][0]["raw"]["events"] == 1.0
    res = _results()
    res[("IN0000004", "84165")]["PermFeatures"][0]["Parameters"][0]["DischargeMonitoringReports"][:] = [three, zero]
    again = _dmr_main(tmp_path, monkeypatch, res)
    assert again["records"][0]["raw"]["events"] == 1.0


def test_no_answer_text_reaches_any_saved_file_on_any_path(tmp_path, monkeypatch):
    """Astra re-review 2026-11-14 P1-2: successful, refused, malformed and non-success answers; raw, cache, events,
    meta and error text are all inspected."""
    import requests as rq

    from ingest import in_echo_cso_monthly as M
    secret = ("Jane Example", "1234 S Example St", "555-0100")
    saved = []
    monkeypatch.setattr(M, "save_raw", lambda sid, body, name: saved.append(body.decode()))
    monkeypatch.setattr(M.time, "sleep", lambda s: None)
    good = _results()[("IN0000004", "84165")]
    good = dict(good, FacStreet="1234 S Example St", ContactName="Jane Example")

    class R:
        def __init__(self, js=None, bad=False, status=200):
            self.js, self.bad, self.status_code = js, bad, status

        def raise_for_status(self):
            if self.status_code >= 400:
                raise rq.HTTPError("500 for Jane Example at 1234 S Example St", response=self)

        def json(self):
            if self.bad:
                raise rq.JSONDecodeError("Expecting value: <html>Jane Example 555-0100</html>", "x", 0)
            return self.js
    answers = {"84165": R({"Results": dict(good, Message="Success")}),
               "50037": R({"Results": {"Message": "Failed", "Detail": "Jane Example, 1234 S Example St, 555-0100"}}),
               "74063": R(bad=True)}
    monkeypatch.setattr(M.requests, "get", lambda url, params, **k: answers[params["parameter_code"]])
    monkeypatch.setattr(M, "CACHE_FILE", tmp_path / "cache.json")
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(M, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / "events" / f"{sid}.json", **kw))
    monkeypatch.setattr(M, "registry_outfalls", lambda rows=None: _registry())
    assert M.main(["--since", "2025-01-01", "--refresh"]) == 1
    first = json.loads((tmp_path / "events" / "in-echo-dmr-cso.json").read_text())
    assert "answer not Success" in first["error"] and "request error" in first["error"]
    answers["84165"] = R({"Results": {"Error": {"ErrorMessage": "NPDES ID IN0000004 is invalid! Call Jane Example"}}})
    answers["50037"] = R(status=500)
    M.main(["--since", "2025-01-01", "--refresh"])
    files = "".join(p.read_text() for p in tmp_path.rglob("*.json")) + "".join(saved)
    assert saved and "Success" in saved[0]
    for s in secret:
        assert s not in files
    doc = json.loads((tmp_path / "events" / "in-echo-dmr-cso.json").read_text())
    assert doc["ok"] is False
    assert json.loads((tmp_path / "cache.json").read_text())["answers"]["IN0000004-84165"]["invalid"] == \
        "NPDES ID IN0000004 is invalid!"


def test_a_cso_number_without_the_delimiter_is_scrubbed_and_an_error_answer_is_a_category():
    """Astra re-review 2026-11-14 P1-2."""
    B = _script("build_in_outfalls")
    doc = {"features": [_idem(1, "IN0000008", "CSO at 1234 S Example St", "Active", 40.1, -86.6),
                        _idem(2, "IN0000008", "003C", "Active", 40.1, -86.6)]}
    out = json.dumps(B.sanitize(doc))
    assert "1234" not in out and "[house number removed] S Example St" in out and '"003C"' in out


def test_a_reopened_algae_advisory_renders_both_intervals_and_other_sources_are_unchanged():
    """Astra re-review 2026-11-14 P2-3: Advisory 12:00, Low Risk 13:00, Advisory 14:00 renders 12:00-13:00 and an open
    interval from 14:00, the gap kept; a record of another source with the same fields replays nothing."""
    from datetime import datetime as dt

    from build import status as S
    a, _ = _cyano([_one_sample("Advisory")], "2026-09-09T12:00:00Z")
    b, _ = _cyano([_one_sample("Low Risk")], "2026-09-09T13:00:00Z", a)
    c, _ = _cyano([_one_sample("Advisory")], "2026-09-09T14:00:00Z", b)
    d, _ = _cyano([_one_sample("Low Risk")], "2026-09-09T15:00:00Z", c)
    e, _ = _cyano([_one_sample("Advisory")], "2026-09-09T16:00:00Z", d)
    now = dt.fromisoformat("2026-09-09T17:00:00+00:00")
    ivs = S.event_intervals(e[0], "IN", now)
    starts = sorted((S.parse_time(iv["start"]).isoformat(), iv.get("end") and S.parse_time(iv["end"]).isoformat())
                    for iv in ivs)
    assert starts[0][0] == "2026-09-09T12:00:00+00:00" and starts[0][1] is not None
    assert S.parse_time(starts[0][1]) <= dt.fromisoformat("2026-09-09T13:00:00+00:00")
    assert any(s == "2026-09-09T14:00:00+00:00" for s, _ in starts)
    assert any(s == "2026-09-09T16:00:00+00:00" for s, _ in starts)
    assert not any(s < "2026-09-09T16:00:00" and (en is None or en > "2026-09-09T16:00:00") for s, en in starts)
    other = dict(e[0], source_id="xx-example-source")
    assert len(S.event_intervals(other, "IN", now)) < len(ivs)
    assert S.EARLIER_PERIOD_SOURCES == {"ne-dwee-beachwatch", "in-idem-cyanobacteria"}


def _in_water(slug, bbox):
    return {"slug": slug, "name": "Sample Creek", "kind": "river", "state": "IN", "towns": [], "bbox": bbox,
            "aliases": None}


def _in_report(rid, county, text="Sample Creek"):
    return {"event_id": f"in-echo-dmr-cso:{rid}", "source_id": "in-echo-dmr-cso", "source_record_id": rid,
            "event_type": "cso", "status": "ended", "waterbody_text": text, "water_slugs": [], "water_match": "none",
            "lat": None, "lon": None, "npdes_permit": None, "outfall_id": None,
            "raw": {"state": "IN", "county": county}, "time_precision": "month", "started_at": "2025-08-01"}


def test_a_county_without_a_point_constrains_indiana_placement(monkeypatch):
    """Astra re-review 2026-11-14 P2-4: a Marion County record with no point is not put on St. Joseph County's Sample
    Creek; with both namesakes it goes to Marion's; a qualified name is still refused; other states unchanged."""
    import copy

    from build import status as S
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"IN"})
    stj = _in_water("sample-creek-st-joseph-in", [-86.30, 41.60, -86.20, 41.70])
    mar = _in_water("sample-creek-marion-in", [-86.20, 39.70, -86.10, 39.80])
    one = S.Resolver({stj["slug"]: copy.deepcopy(stj)}, [], placement_rules={})
    assert one.resolve(_in_report("a", "Marion"))["water_slugs"] == []
    assert one.resolve(_in_report("b", "St. Joseph"))["water_slugs"] == [stj["slug"]]
    both = S.Resolver({stj["slug"]: copy.deepcopy(stj), mar["slug"]: copy.deepcopy(mar)}, [], placement_rules={})
    assert both.resolve(_in_report("c", "Marion"))["water_slugs"] == [mar["slug"]]
    assert both.resolve(_in_report("d", "Marion", "Little Sample Creek"))["water_slugs"] == []
    # the registry row's county reaches the resolver's stand-in record for an outfall with no point (Indiana only)
    row = {"npdes_permit": "IN0000007", "outfall": "002", "state": "IN", "county": "Marion", "lat": None, "lon": None,
           "receiving_water_echo": "Sample Creek"}
    assert S.REGISTRY_COUNTY_STATES == {"IN"}
    from ingest import outfall_waters as OW
    assert OW.Matcher.fake(None, row, "Sample Creek")["raw"]["county"] == "Marion"
    assert "county" not in OW.Matcher.fake(None, dict(row, state="TX", county="Harris"), "x")["raw"]


def _totals_chart(evs, sid):
    import types
    from datetime import UTC, datetime

    from build import charts as C
    b = C.Bucket("discharger", "example-in")
    b.state = "IN"
    b.totals = [dict(e, source_id=sid) for e in evs]
    data = types.SimpleNamespace(history={}, status={}, waters={}, by_id={}, dropped={}, effective={}, placements={},
                                 now=datetime(2026, 11, 14, tzinfo=UTC), rules={}, events=[], dischargers={})
    doc = C.build_entity(b, data, {}, {}, "Example")
    return {s["key"]: s["values"] for s in doc["charts"]["reported_totals"][0]["series"]}


def _month_rec(ym, events=None, hours=None, gal=None, outfall="002"):
    last = {"08": "31", "09": "30", "10": "31"}[ym[5:]]
    params = {k: {"DMRValueNmbr": v} for k, v in (("events", events), ("duration", hours)) if v is not None}
    return {"event_id": f"x:{outfall}:{ym}", "started_at": f"{ym}-01", "ended_at": f"{ym}-{last}",
            "time_precision": "month", "event_type": "cso", "volume_gal": gal, "discharger_name": "Example",
            "raw": {"parameters": params}}


def test_monthly_totals_leave_missing_months_and_measures_blank_and_other_feeds_are_unchanged():
    """Astra re-review 2026-11-14 P2-5: August and October with September absent are [1, None, 1], never 0; a month
    whose record lacks a measure is None for that measure; an explicit zero stays zero; another source's series
    keep the zero they always had."""
    evs = [_month_rec("2025-08", 1, 4, 1_100_000), _month_rec("2025-10", 1, 4, 1_100_000)]
    s = _totals_chart(evs, "in-echo-dmr-cso")
    assert s["events"] == [1.0, None, 1.0] and s["hours"] == [4.0, None, 4.0]
    assert s["gallons"] == [1_100_000.0, None, 1_100_000.0]
    part = [_month_rec("2025-08", 2, 0, None), _month_rec("2025-09", 1, None, 500_000),
            _month_rec("2025-09", 1, 3, 200_000, outfall="003")]
    s = _totals_chart(part, "in-echo-dmr-cso")
    assert s["events"] == [2.0, 2.0] and s["hours"] == [0.0, None] and s["gallons"] == [None, 700_000.0]
    other = _totals_chart(evs, "xx-example-monthly")
    assert other["events"] == [1.0, 0.0, 1.0] and other["gallons"] == [1_100_000.0, 0.0, 1_100_000.0]


def test_a_facility_name_never_becomes_the_operator_and_permit_only_rows_are_not_counted():
    """Astra re-review 2026-11-14 P2-6: state, federal, institutional, school, park and business plants whose names do
    not give their permittee are permit-only rows (the plant kept in the notes, out of the named-operator count);
    a legal entity's own name (LLC, district) still names the row; the register follows the rows."""
    B = _script("add_in_operators")
    for pn, t in (("EXAMPLE CREEK I-69 SB REST AREA", "State Government"),
                  ("EXAMPLEVILLE CORRECTIONAL FACILITY", "State Government"),
                  ("EXAMPLE DIVISION, NAVAL SURFACE WARFARE CENTER", "Federal Facility (U.S. Government)"),
                  ("EXAMPLE CHRISTIAN VILLAGE", "Privately Owned Facility"),
                  ("EXAMPLE ELEMENTARY SCHOOL", "Non-Government"),
                  ("EXAMPLE ACRES MOBILE HOME PARK", "Privately Owned Facility"),
                  ("CAMP EXAMPLE", "Privately Owned Facility"),
                  ("EXAMPLE TRAVEL CENTER", "Privately Owned Facility")):
        rid, name, lf, note = B.owner_of_plant(pn, t)
        assert (rid, name, lf) == (None, None, B.PERMIT_ONLY) and "does not establish" in note, pn
    assert B.owner_of_plant("EXAMPLE ACRES MOBILE HOME PARK LLC", "Privately Owned Facility")[2] == "mobile-home park"
    assert B.owner_of_plant("EXAMPLE LAKE CD WWTP", "Municipal or Water District")[1] == "Example Lake CD"
    assert B.owner_of_plant("EXAMPLE SCHOOL CORPORATION WWTP", "Non-Government")[2] == "special district"
    rows = _rows()
    for permit, plant in (("IN0052043", "Pigeon Creek I-69 Sb Rest Area"),
                          ("IN0042960", "Putnamville Correctional Facility")):
        r = next(x for x in rows if permit in x["npdes_permits"])
        assert r["name"] == f"Holder of permit {permit}" and r["legal_form"] == B.PERMIT_ONLY and plant in r["notes"]
    assert not [r["id"] for r in rows if r["name"].startswith("Holder of permit") and r["legal_form"] != B.PERMIT_ONLY]
    chans = json.loads((ROOT / "data" / "notice-channels" / "in.json").read_text())["channels"]
    names = {c.get("operator_id"): json.dumps(c) for c in chans if c.get("operator_id") == "in-in0042960"}
    assert names and "Putnamville" not in "".join(names.values())


def test_the_public_claims_match_the_build():
    """Astra re-review 2026-11-14 P2-9: the permit count is the registry's, the lag is EPA's receipt (not publication),
    and the rain caution is qualified by location and placement wherever it is described."""
    import re

    from ingest import in_echo_cso_monthly as M
    n = len(M.permits_to_read(M.registry_outfalls()))
    text = (ROOT / "research" / "in" / "state-text.md").read_text()
    m = re.search(r"from (\d+) of the (\d+) permits with an open combined sewer outfall", text)
    assert m and int(m.group(2)) == n == 91
    assert "appearing a median" not in text and "received a median of 24 days" in text
    for p in ("research/in/sources.json", "scripts/add_in_register_rows.py", "data/sources/in-echo-dmr-cso.yaml"):
        assert "92 permits" not in (ROOT / p).read_text() and "(92:" not in (ROOT / p).read_text(), p
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    assert "rain caution at every open" not in json.dumps(rules)
    assert "with a location once the outfall is placed on its water" in json.dumps(rules)
