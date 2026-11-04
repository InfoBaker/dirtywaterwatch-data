"""Water records for the receiving-water names a state's reports give (ingest.waters_from_nhd --names), without the
network: the three shapes of research/<st>/receiving-waters-missing.json, the names that are no water and their
reasons, tributaries, the places the reports give, the name pass per place, the batched name queries, the merge that
keeps the state build's rows, the outfall ties left alone, and the rewrite of the file to what is still missing.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

import pytest
from shapely.geometry import LineString, Polygon, box

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import outfall_waters as OW  # noqa: E402
from ingest import waters_from_nhd as N  # noqa: E402


# ---------------------------------------------------------------- the file's three shapes

def test_the_three_states_files_read_as_rows_most_reports_first(tmp_path):
    nc = tmp_path / "nc.json"
    nc.write_text(json.dumps({"about": "x", "state": "NC", "rows": [
        {"name": "Brier Creek", "reports": 26, "permits": ["WQCS00001"], "points": [[35.23, -80.77]]},
        {"name": "Mountain Creek", "reports": 35, "points": [[35.36, -80.14]]}]}))
    ga = tmp_path / "ga.json"
    ga.write_text(json.dumps({"about": "y", "checked": "2026-11-04", "count": 2, "names": [
        {"name": "Pew Creek", "reports": 3, "kind": "named water"},
        {"name": "MS4 system", "reports": 4, "kind": "storm system or not a named water"}]}))
    fl = tmp_path / "fl.json"
    fl.write_text(json.dumps([["Watson Bayou", 32], ["Intracoastal Waterway", 52]]))
    meta, rows = N.read_names_file(nc)
    assert meta["about"] == "x" and [r["name"] for r in rows] == ["Mountain Creek", "Brier Creek"]
    assert rows[1]["permits"] == ["WQCS00001"]
    meta, rows = N.read_names_file(ga)
    assert meta["checked"] == "2026-11-04" and rows[0]["name"] == "MS4 system" and rows[1]["kind"] == "named water"
    meta, rows = N.read_names_file(fl)
    assert meta == {} and rows == [{"name": "Intracoastal Waterway", "reports": 52}, {"name": "Watson Bayou", "reports": 32}]


# ---------------------------------------------------------------- names that are no water, and tributaries

@pytest.mark.parametrize("text,why", [
    ("MS4 stormwater system", "MS4"),
    ("Springfield Canal (MS4)", "MS4"),
    ("storm drain", "storm-sewer"),
    ("City Stormwater system", "storm-sewer"),
    ("catch basin", "sewer, drainage or treatment works"),
    ("Aeration Basin", "treatment works"),
    ("Private Pond", "private property"),
    ("hardins pond (private)", "private property"),
    ("Creek in resident's yard.", "private property"),
    ("Gulf of Mexico", "open sea"),
    ("Panther Ct.", "street name"),
    ("ground", "not a water name"),
    ("Unamed", "unnamed or unknown"),
    ("unknown tributary", "unnamed or unknown"),
    ("Stream", "kind of water with no name"),
    ("Pond", "kind of water with no name"),
    ("Unnamed Tributary at Belmont Abbey College", "named by a place"),
    ("Unnamed Tributary of Little River Basin", "basin"),
    ("Starkey Road Basin", "basin"),
    ("New River Basin", "basin"),                       # a river's basin is a planning basin of many waters
    ("Upper Upatoi Basin", "basin"),                    # no stream word: not a sewershed named for its creek
    ("Unnamed Creek Basin", "basin"),
    ("Tributary to Private Pond", "private property"),
    ("123 Main Street", "street"),
])
def test_names_that_are_no_water_get_a_reason_and_no_target(text, why):
    parts, reason, _ = N.report_name_parts(text)
    assert parts == [] and why in reason


@pytest.mark.parametrize("text,expected,trib", [
    ("Mountain Creek", ["Mountain Creek"], False),
    ("Tributary to Proctor Creek", ["Proctor Creek"], True),
    ("UT Eno River", ["Eno River"], True),
    ("UT tributary of Ellerbe Creek", ["Ellerbe Creek"], True),
    ("Unknown Tribuatary to Rich Fork Creek", ["Rich Fork Creek"], True),
    ("Unnamed tributary that runs to Lake Hickory", ["Lake Hickory"], True),
    ("Unnamed tributary to Church Branch, a trib to Sandy Run", ["Church Branch"], True),
    ("Ditch feeding Rocky Creek", ["Rocky Creek"], True),
    ("Bull creek tributary", ["Bull creek"], True),
    ("Stormdrain to UT of Island Creek", ["Island Creek"], True),
    ("Walnut Creek (Lake Johnson)", ["Walnut Creek"], False),
    ("County Home Branch (Still House Branch)", ["County Home Branch"], False),
    ("Watson Bayou", ["Watson Bayou"], False),
    ("ICW", ["Intracoastal Waterway"], False),
    ("FRENCH BROAD", ["FRENCH BROAD"], False),
    # a sewershed named for its creek drains to that creek, as a tributary does (2026-11-04 review P3-1)
    ("Lindsey Creek Basin", ["Lindsey Creek"], True),
    ("Dram Branch Basin", ["Dram Branch"], True),
    ("Allens Creek Water Basin", ["Allens Creek"], True),
    ("Tributary to Weracoba Creek Basin", ["Weracoba Creek"], True),
])
def test_report_names_that_name_a_water(text, expected, trib):
    parts, reason, tributary = N.report_name_parts(text)
    assert (parts, reason, tributary) == (expected, None, trib)


# ---------------------------------------------------------------- the places the reports give

def test_places_come_from_the_reports_and_the_operators_they_name(monkeypatch):
    monkeypatch.setattr(N.S, "event_state", lambda ev: ev.get("_st"))
    monkeypatch.setattr(N, "state_discharger_towns", lambda st: {"WQCS00001": ["Charlotte"]})
    rows = [{"name": "Brier Creek", "reports": 2, "permits": ["WQCS00001"]}, {"name": "Watson Bayou", "reports": 3}]
    events = [
        {"_st": "FL", "source_id": "fl-dep-pnp", "waterbody_text": "Watson Bayou", "lat": 30.1501, "lon": -85.6409,
         "raw": {"FACILITY_CITY": "Panama City, FL"}},
        {"_st": "FL", "source_id": "fl-dep-pnp", "waterbody_text": "Storm drain to the bayou", "lat": 30.2, "lon": -85.7,
         "raw": {"_water_names": ["watson bayou"], "FACILITY_CITY": "PANAMA CITY"}},
        {"_st": "GA", "source_id": "ga", "waterbody_text": "Watson Bayou", "lat": 33.0, "lon": -84.0, "raw": {}},
        {"_st": "FL", "source_id": "fl-dep-pnp", "waterbody_text": "Other Creek", "lat": 30.0, "lon": -85.0, "raw": {}},
    ]
    places = N.report_places("FL", rows, events, towns_by_permit={})
    wb = places["Watson Bayou"]
    assert wb["points"] == Counter({(-85.6409, 30.1501): 1, (-85.7, 30.2): 1})      # the GA report is not Florida's
    assert wb["towns"] == Counter({"Panama City": 2}) and wb["sources"] == Counter({"fl-dep-pnp": 2})
    assert places["Brier Creek"]["towns"] == Counter({"Charlotte": 1})               # the operator the row names


# ---------------------------------------------------------------- the name pass, place by place

def fake_nhd(features, towns=None):
    state = box(-85, 34, -75, 37)
    outlines = towns or {}
    return SimpleNamespace(states=SimpleNamespace(shapes={"NC": state}),
                           towns=SimpleNamespace(outlines=lambda st, keys: [outlines[k] for k in keys if k in outlines],
                                                 canonical=lambda st, name: name if name in outlines else None))


def mill_creeks():
    return [{"gnis_id": "1", "gnis_name": "Mill Creek", "comid": 11, "_geom": LineString([(-80.0, 35.0), (-80.0, 35.1)])},
            {"gnis_id": "2", "gnis_name": "Mill Creek", "comid": 22, "_geom": LineString([(-78.0, 35.5), (-78.0, 35.6)])},
            {"gnis_id": "3", "gnis_name": "Mill Creek", "comid": 33, "_geom": LineString([(-77.0, 36.0), (-77.0, 36.1)])}]


def name_target(name, points=(), towns=()):
    t = N.Target(state="NC", name=name, words=N.words(name), points=Counter({p: 1 for p in points}),
                 towns=Counter({x: 1 for x in towns}), point_mode=False)
    t["_l2"], t["_l4"] = mill_creeks(), []
    return t


def test_each_place_of_a_name_takes_the_water_of_that_name_nearest_it():
    t = name_target("Mill Creek", points=[(-80.005, 35.05), (-78.004, 35.55), (-76.0, 34.5)])
    choices, reason, failed = N.report_name_choices(fake_nhd(None), t)
    assert [k for k, _, _ in choices] == [("line", "NC", "1"), ("line", "NC", "2")] and reason is None
    assert "3 waters of that name in NC" in choices[0][2]
    assert len(failed) == 1 and "no NHD water of that name within 2 km" in failed[0]["reason"]


def test_with_no_point_the_town_chooses_and_with_no_place_only_a_single_name_is_taken():
    town = Polygon([(-78.02, 35.54), (-77.98, 35.54), (-77.98, 35.58), (-78.02, 35.58)])
    t = name_target("Mill Creek", towns=["Kenly"])
    choices, _, _ = N.report_name_choices(fake_nhd(None, {"Kenly": town}), t)
    assert [k for k, _, _ in choices] == [("line", "NC", "2")] and "crossing Kenly" in choices[0][2]
    t = name_target("Mill Creek", points=[(-76.0, 34.5)], towns=["Kenly"])      # the point finds none: the town does
    choices, _, failed = N.report_name_choices(fake_nhd(None, {"Kenly": town}), t)
    assert [k for k, _, _ in choices] == [("line", "NC", "2")] and len(failed) == 1
    t = name_target("Mill Creek", points=[(-80.005, 35.05)], towns=["Kenly"])  # the point finds one: the town not asked
    choices, _, _ = N.report_name_choices(fake_nhd(None, {"Kenly": town}), t)
    assert [k for k, _, _ in choices] == [("line", "NC", "1")]
    t = name_target("Mill Creek")
    choices, reason, _ = N.report_name_choices(fake_nhd(None), t)
    assert choices == [] and "3 NHD waters of that name in NC and the reports give no place" in reason
    t["_l2"] = mill_creeks()[:1]
    choices, reason, _ = N.report_name_choices(fake_nhd(None), t)
    assert [k for k, _, _ in choices] == [("line", "NC", "1")] and "the only NHD water of that name" in choices[0][2]


def test_a_name_nhdplus_does_not_carry_says_so():
    t = name_target("Ocean Breeze Waterway", points=[(-80.0, 35.0)])
    choices, reason, _ = N.report_name_choices(fake_nhd(None), t)
    assert choices == [] and reason == "no NHD flowline or waterbody of that name in NC"


def test_a_name_away_from_the_reports_places_goes_to_the_high_resolution_flowlines():
    t = name_target("Mill Creek", points=[(-76.0, 34.5)])
    _, reason, _ = N.report_name_choices(fake_nhd(None), t)
    assert "none within reach" in reason and N.wants_hr(reason)
    assert N.wants_hr("no NHD flowline or waterbody of that name in NC")
    assert not N.wants_hr("3 NHD waters of that name in NC and the reports give no place to choose one")
    assert not N.wants_hr(None)


def test_names_are_asked_thirty_spellings_to_a_query(monkeypatch):
    calls = []

    def fake_arcgis(http, kind, layer, **p):
        calls.append(p["where"])
        return mill_creeks() + [{"gnis_id": "9", "gnis_name": "Town Creek", "_geom": LineString([(-79, 35), (-79, 35.1)])}]
    monkeypatch.setattr(N, "arcgis", fake_arcgis)
    nhd = SimpleNamespace(http=None, state_env=lambda st: "0,0,1,1")
    ts = [N.Target(name=n, words=N.words(n)) for n in ["Mill Creek", "Town Creek", "Deep Creek"]]
    N.prefetch_names(nhd, "NC", ts, 2, "_l2")
    assert len(calls) == 1 and "'MILL CREEK'" in calls[0] and "'TOWN CREEK'" in calls[0]
    assert [len(t["_l2"]) for t in ts] == [3, 1, 0]
    many = [N.Target(name=f"Creek x{i:02d}", words=N.words(f"Creek x{i:02d}")) for i in range(45)]
    calls.clear()
    N.prefetch_names(nhd, "NC", many, 2, "_l2")
    assert len(calls) == 2


# ---------------------------------------------------------------- names a record already holds

def test_a_name_a_record_holds_maps_to_it_and_a_fork_given_to_its_river_is_built(monkeypatch):
    waters = {"deep-river-nc": {"name": "Deep River", "state": "NC", "aliases": []},
              "goodbys-creek-fl": {"name": "Goodbys Creek", "state": "NC", "aliases": []}}

    def by_name(name, st, lat, lon, ev):
        k = N.compact(name)
        return (["deep-river-nc"] if "deepriver" in k else ["goodbys-creek-fl"] if "goodby" in k else []), None, False
    resolver = SimpleNamespace(by_name=by_name, guard=lambda slugs, ev: (slugs, []))
    rows = [{"name": "West Fork Deep River", "reports": 11}, {"name": "Goodby's Creek", "reports": 5},
            {"name": "Deep River", "reports": 2}, {"name": "MS4 system", "reports": 4},
            {"name": "Tributary to Mill Creek", "reports": 3, "points": [[35.05, -80.0]], "towns": ["Kenly"]}]
    targets, done, skipped = N.collect_name_targets("NC", rows, resolver, waters)
    assert [t["name"] for t in targets] == ["West Fork Deep River", "Mill Creek"]
    assert "gives the name to deep-river-nc (another name)" in targets[0]["notes"][0]
    assert targets[1]["tributary"] and targets[1]["points"] == Counter({(-80.0, 35.05): 3})
    assert targets[1]["towns"] == Counter({"Kenly": 3})
    assert [(t["name"], s) for t, s in done] == [("Goodby's Creek", ["goodbys-creek-fl"]), ("Deep River", ["deep-river-nc"])]
    assert skipped == {("NC", "MS4 system"): "a storm-sewer system (MS4), not a named water"}


# ---------------------------------------------------------------- the merge and the outfall ties

def test_report_rows_merge_among_themselves_and_the_state_builds_rows_stay(tmp_path, monkeypatch):
    out = tmp_path / "waters-nhd.json"
    monkeypatch.setattr(N, "OUT", out)
    build_row = {"state": "NC", "name": "Mill Creek", "slugs": ["mill-creek-nc"], "define_by": "name",
                 "permits": ["NC0000001"]}
    old_report = {"state": "NC", "name": "Peters Creek", "slugs": ["peters-creek-nc"], "from": "reports", "reports": 23}
    prev = {"partial": False, "problems": [], "skipped": [], "waters": [],
            "stats": {"state_builds": {"NC": {"records": 5, "existing_duplicates": {"dropped": 2}}}},
            "targets": [build_row, old_report, {"state": "GA", "name": "Mill Creek", "slugs": []}]}
    out.write_text(json.dumps(prev))
    new = [{"state": "NC", "name": "Mill Creek", "slugs": [], "from": "reports", "reports": 3,
            "reason": "3 NHD waters of that name in NC and the reports give no place to choose one"},
           {"state": "NC", "name": "Peters Creek", "slugs": [], "from": "reports",
            "reason": f"{N.NOT_REACHED} (--budget-s used); the next run resumes"}]
    N.write_output([], new, [{"state": "NC", "text": "MS4 system", "reason": "MS4"}], [], partial=True,
                   stats={"NC": {"records": 0}}, final=True, scope_states={"NC"}, rows_from="reports")
    d = json.loads(out.read_text())
    assert d["targets"][0] == build_row and d["targets"][1] == prev["targets"][2]      # the state build's rows exactly
    assert d["targets"][2] == old_report                       # a name the budget did not reach keeps its row
    assert d["targets"][3]["name"] == "Mill Creek" and d["targets"][3]["from"] == "reports"
    nc = d["stats"]["state_builds"]["NC"]
    assert nc["records"] == 5 and nc["existing_duplicates"] == {"dropped": 2} and nc["report_names"]["records"] == 0
    assert d["skipped"] == [{"state": "NC", "text": "MS4 system", "reason": "MS4"}]
    assert N.target_key(new[0]) != N.target_key(build_row)


def test_report_rows_tie_no_outfall():
    rows = [{"state": "NC", "name": "Mill Creek", "slugs": ["mill-creek-kenly-nc"], "from": "reports",
             "texts": ["Tributary to Mill Creek"]},
            {"state": "NC", "name": "Mill Creek", "slugs": ["mill-creek-nc"], "define_by": "name",
             "reach_slugs": {"8791413": "mill-creek-nc"}}]
    targets, reach, _ = OW.index_targets(rows)
    assert targets[("NC", N.compact("Mill Creek"))]["slugs"] == ["mill-creek-nc"]
    assert ("NC", N.compact("Tributary to Mill Creek")) not in targets and reach == {"8791413": "mill-creek-nc"}


# ---------------------------------------------------------------- the file rewritten to what is still missing

def test_the_file_keeps_the_names_still_missing_with_their_reasons(tmp_path):
    path = tmp_path / "missing.json"
    rows = [{"name": "Mountain Creek", "reports": 35, "points": [[35.36, -80.14]], "_parts": ["Mountain Creek"]},
            {"name": "Mill Creek", "reports": 9, "_parts": ["Mill Creek"]},
            {"name": "Tributary to Pew Creek", "reports": 4, "towns": ["Lawrenceville"], "_parts": ["Pew Creek"]},
            {"name": "MS4 system", "reports": 2, "_parts": []}]
    out_rows = [{"name": "Mountain Creek", "from": "reports", "slugs": ["mountain-creek-nc"], "defined_by": "name",
                 "how": ["GNIS name in NC, 78 m from the reports' point"]},
                {"name": "Mill Creek", "from": "reports", "slugs": [], "how": [],
                 "reason": "3 NHD waters of that name in NC and the reports give no place to choose one"},
                {"name": "Pew Creek", "from": "reports", "slugs": [], "how": [],
                 "reason": "no NHD flowline or waterbody of that name in NC",
                 "places_failed": [{"town": "Lawrenceville", "reason": "x"}]}]
    stats = {"built": "2026-11-04T07:00:00Z", "file": "research/nc/receiving-waters-missing.json", "records": 1,
             "network_requests": 12}
    N.rewrite_names(path, {"about": "names", "state": "NC"}, "NC", rows, out_rows,
                    {("NC", "MS4 system"): "a storm-sewer system (MS4), not a named water"}, stats)
    d = json.loads(path.read_text())
    assert d["about"] == "names" and d["waters"] == 3 and d["reports"] == 15
    assert [r["name"] for r in d["rows"]] == ["Mill Creek", "Tributary to Pew Creek", "MS4 system"]
    assert d["rows"][1]["reason"] == "no NHD flowline or waterbody of that name in NC" and d["rows"][1]["parts"] == ["Pew Creek"]
    assert d["rows"][1]["towns"] == ["Lawrenceville"] and d["rows"][1]["places_failed"][0]["town"] == "Lawrenceville"
    assert d["rows"][2]["reason"] == "a storm-sewer system (MS4), not a named water"
    assert d["resolved"] == [{"name": "Mountain Creek", "reports": 35, "slugs": ["mountain-creek-nc"],
                              "how": "record built from the name", "points": [[35.36, -80.14]]}]
    assert d["resolved_names"] == 1 and d["build"]["records_built"] == 1 and "--names" in d["build"]["command"]
    assert all("_parts" not in r for r in d["rows"])


def test_the_files_reasons_are_counted_by_kind():
    assert N.reason_kind("a storm-sewer system (MS4), not a named water") == "a storm-sewer system (MS4), not a named water"
    assert N.reason_kind("1 NHD water of that name in NC, none within reach of the reports' places; no NHD "
                         "high-resolution flowline of that name within 3 km of the points") == \
        "1 NHD water of that name in NC, none within reach of the reports' places"
    assert N.reason_kind("not reached this run (the run's time or request limit was reached on 2026-11-04); the next "
                         "run resumes") == "not reached this run"
    assert N.reason_kind("Pew Creek: no NHD flowline or waterbody of that name in GA", multi=True) == \
        "no NHD flowline or waterbody of that name in GA"


def test_a_reports_spelling_is_asked_in_gniss_forms_and_scored_without_of():
    t = N.Target(name="Lake Apopka", words=N.words("Lake Apopka"), report_name=True)
    assert "APOPKA, LAKE" in N.sql_names(t)
    t = N.Target(name="South Fork of Middle River", words=N.words("South Fork of Middle River"), report_name=True)
    assert "SOUTH FORK MIDDLE RIVER" in N.sql_names(t)
    assert N.report_score(t["words"], "South Fork Middle River") == 1.0
    t = N.Target(name="Intracoastal Waterway", words=N.words("Intracoastal Waterway"), report_name=True)
    assert {"ATLANTIC INTRACOASTAL WATERWAY", "GULF INTRACOASTAL WATERWAY"} <= set(N.sql_names(t))
    assert N.report_score(t["words"], "Atlantic Intracoastal Waterway") == 0.9
    assert N.report_score(N.words("Bull Creek"), "Atlantic Bull Creek") == 0.0
    t = N.Target(name="Joe's Creek", words=N.words("Joe's Creek"), report_name=True)
    assert {"JOES CREEK", "JOE CREEK"} <= set(N.sql_names(t))
    t = N.Target(name="Wills Branch Creek", words=N.words("Wills Branch Creek"), report_name=True)
    assert "WILLS BRANCH" in N.sql_names(t)
    assert N.report_name_parts("Intercoastal Waterway")[0] == ["Intracoastal Waterway"]


def test_a_towns_name_with_no_water_of_that_name_says_so():
    town = Polygon([(-78.02, 35.54), (-77.98, 35.54), (-77.98, 35.58), (-78.02, 35.58)])
    t = name_target("Coral Springs", points=[(-78.0, 35.55)])
    _, reason, _ = N.report_name_choices(fake_nhd(None, {"Coral Springs": town}), t)
    assert reason.startswith("the name of a town (Coral Springs)") and not N.wants_hr(reason)


# ---------------------------------------------------------------- 2026-11-04 review

def test_a_lake_name_either_way_round_is_the_same_existing_record(monkeypatch):
    existing = {"lake-lawne-fl": {"slug": "lake-lawne-fl", "name": "Lake Lawne", "state": "FL", "kind": "lake",
                                  "towns": ["Orlando"], "bbox": [-81.44262, 28.55758, -81.43216, 28.56999]},
                "lawne-creek-fl": {"slug": "lawne-creek-fl", "name": "Lawne Creek", "state": "FL"}}
    assert N.same_named_existing(existing, "FL", "Lawne Lake") == ["lake-lawne-fl"]
    assert N.same_named_existing(existing, "FL", "Lake Lawne") == ["lake-lawne-fl"]
    assert N.same_named_existing(existing, "GA", "Lawne Lake") == []
    assert N.same_named_existing(existing, "FL", "Lawne Pond") == []
    # the report name's record: GNIS's 'Lawne Lake' over openboatlaunch's Lake Lawne (no outline on this machine)
    poly = box(-81.44255, 28.55767, -81.43336, 28.56987)
    monkeypatch.setattr(N, "build_feature", lambda nhd, st, c: {
        "name": "Lawne Lake", "state": "FL", "_geom": poly, "towns": ["Orlando", "Pine Hills"], "length_km": None,
        "area_km2": 0.623, "note": "x", "aliases": []})
    monkeypatch.setattr(N.S, "water_geometry", lambda slug, waters: None)
    run = SimpleNamespace(nhd=None, existing=existing)
    t = N.Target(state="FL", name="Lawne Lake", words=N.words("Lawne Lake"), points=Counter({(-81.442, 28.569): 1}),
                 towns=Counter())
    rec = N.Run.new_record(run, ("wb", "FL", "285401"), {"type": "wb"}, t, {"reason": None})
    assert rec == {"_existing": "lake-lawne-fl"}


def slug_rec(name, towns, slug_towns, weight, gnis):
    return {"name": name, "state": "NC", "towns": towns, "_slug_towns": Counter(slug_towns), "_weight": weight,
            "gnis_id": gnis, "comids": [int(gnis)]}


def test_a_slugs_town_is_one_the_record_reaches_not_the_first_town_of_the_whole_name():
    listed = {"Charlotte": 0, "Raleigh": 0, "Garner": 0, "Wake Forest": 0}      # the reports' towns, the whole name
    charlotte = slug_rec("Brier Creek", ["Charlotte"], {**listed, "Charlotte": 14}, 14, "1")
    raleigh = slug_rec("Brier Creek", ["Cary", "Raleigh"], listed, 12, "2")       # its point lies in no Census place
    nowhere = slug_rec("Brier Creek", [], listed, 1, "3")
    N.assign_slugs([charlotte, raleigh, nowhere], {})
    assert charlotte["slug"] == "brier-creek-nc"
    assert raleigh["slug"] == "brier-creek-raleigh-nc"         # a listed town it reaches, not Charlotte
    assert nowhere["slug"] == "brier-creek-charlotte-nc"       # nothing better known: a listed town still
    assert N.slug_towns(slug_rec("X Creek", ["Cary"], {"Apex": 3, "Durham": 0}, 3, "4")) == ["Apex", "Cary", "Durham"]


def test_two_waters_of_the_name_crossing_a_town_choose_neither():
    town = box(-80.1, 35.0, -77.9, 35.6)                    # crosses Mill Creek 1 and Mill Creek 2
    t = name_target("Mill Creek", towns=["Big Town"])
    choices, reason, failed = N.report_name_choices(fake_nhd(None, {"Big Town": town}), t)
    assert choices == [] and "none within reach" in reason
    assert failed == [{"town": "Big Town", "reason": "two NHD waters of that name lie equally near Big Town"}]


@pytest.mark.parametrize("text,expected", [
    ("Ocean Breeze Waterway", ["Ocean Breeze Waterway"]),
    ("Ocean Pond", ["Ocean Pond"]),
    ("Cedar Hammock Drainage Canal", ["Cedar Hammock Drainage Canal"]),
    ("Johnson Drainage Ditch", ["Johnson Drainage Ditch"]),
    ("Atlantic Ocean", []),
    ("ocean", []),
    ("Ocean water", []),
    ("ocean side beach", []),
    ("Drainage canal", []),
    ("storm drainage ditch", []),
    ("Nearby creek", []),
])
def test_a_water_named_with_ocean_or_drainage_in_it_is_still_a_name(text, expected):
    assert N.report_name_parts(text)[0] == expected


class FakeResolver:
    def __init__(self, answers):
        self.answers = answers

    def by_name(self, text, st, lat, lon, ev):
        return self.answers.get(text, ([], None, False))

    def guard(self, slugs, ev):
        return [s for s in slugs if s != "far-away-nc"], []


def test_the_status_resolver_must_place_a_resolved_spelling_on_its_record():
    r = FakeResolver({"Allen Creek": (["allen-creek-fl"], None, False),
                      "South Fork of Middle River": (["middle-river-fl"], None, False),
                      "Matanzas River": ([], "'matanzas river' names 2 waters in FL (matanzas-river-fl, "
                                             "matanzas-river-saint-augustine-fl); no point", True),
                      "Long Branch": (["far-away-nc"], None, False)})
    row = {"points": [[27.92, -82.75]], "towns": ["Clearwater"]}
    assert N.resolver_places(r, "Allen Creek", "FL", row, ["allen-creek-fl"]) is None
    assert N.resolver_places(r, "Allen's Creek", "FL", row, ["allen-creek-fl"]) == "spelling"      # no alias: unplaced
    assert N.resolver_places(r, "South Fork of Middle River", "FL", row, ["south-fork-middle-river-fl"]) == "spelling"
    assert N.resolver_places(r, "Matanzas River", "FL", row, ["matanzas-river-saint-augustine-fl"]) is None
    assert N.resolver_places(r, "Long Branch", "NC", row, ["far-away-nc"]) == "guard"          # set aside by the guard


def test_a_resolved_name_the_resolver_does_not_place_stays_with_its_record_named(tmp_path):
    path = tmp_path / "missing.json"
    rows = [{"name": "Allen Creek", "reports": 3, "points": [[27.92, -82.75]], "towns": ["Clearwater"],
             "_parts": ["Allen Creek"]},
            {"name": "Allen's Creek", "reports": 2, "points": [[27.93, -82.73]], "_parts": ["Allen's Creek"]}]
    out_rows = [{"name": "Allen Creek", "from": "reports", "slugs": ["allen-creek-fl"], "defined_by": "name",
                 "how": ["GNIS name in FL, 922 m from the reports' point"],
                 "places_failed": [{"town": "Tampa", "reason": "no NHD water of that name within 3 km of Tampa"}]},
                {"name": "Allen's Creek", "from": "reports", "slugs": ["allen-creek-fl"], "defined_by": "name",
                 "how": ["GNIS name in FL, 938 m from the reports' point; the same NHD feature as record allen-creek-fl"]}]
    stats = {"built": "2026-11-04T07:00:00Z", "file": "research/fl/receiving-waters-missing.json", "records": 1,
             "network_requests": 0}
    N.rewrite_names(path, {"state": "FL"}, "FL", rows, out_rows, {}, stats,
                    placed=lambda text, r, slugs: "spelling" if "'" in text else None)
    d = json.loads(path.read_text())
    assert [r["name"] for r in d["resolved"]] == ["Allen Creek"]
    res = d["resolved"][0]
    assert res["points"] == [[27.92, -82.75]] and res["towns"] == ["Clearwater"]          # its places are kept
    assert res["places_failed"][0]["town"] == "Tampa"
    left = d["rows"][0]
    assert left["name"] == "Allen's Creek" and left["records"] == ["allen-creek-fl"]
    assert left["reason"].startswith("a water record holds this water but not this spelling (allen-creek-fl): a report")
    assert d["by_reason"] == {"a water record holds this water but not this spelling: a report of it is not placed "
                              "there until the spelling is an alias": 1}


def test_resolved_names_no_longer_placed_are_asked_again():
    meta = {"resolved": [{"name": "Allen Creek", "reports": 3, "slugs": ["allen-creek-fl"], "how": "x",
                          "points": [[27.92, -82.75]]},
                         {"name": "Lawne Lake", "reports": 1, "slugs": ["lawne-lake-fl"], "how": "x",
                          "points": [[28.569, -81.442]], "towns": ["Apopka"]}]}
    r = FakeResolver({"Allen Creek": (["allen-creek-fl"], None, False)})
    back = N.recheck_resolved(meta, "FL", r)
    assert [x["name"] for x in meta["resolved"]] == ["Allen Creek"]
    assert back == [{"name": "Lawne Lake", "reports": 1, "points": [[28.569, -81.442]], "towns": ["Apopka"]}]


def test_a_name_is_a_record_only_where_every_point_of_its_reports_finds_it():
    waters = {"butler-creek-ga": {"name": "Butler Creek", "state": "GA", "aliases": []}}

    def by_name(name, st, lat, lon, ev):
        return ["butler-creek-ga"], None, False

    def guard(slugs, ev):           # the record lies at Augusta: a report at Kennesaw is set aside
        return ([], [("butler-creek-ga", "name match too far")]) if ev["lon"] < -84 else (slugs, [])
    resolver = SimpleNamespace(by_name=by_name, guard=guard)
    rows = [{"name": "Butler Creek Tributary", "reports": 2, "points": [[33.39487, -81.97529]]},
            {"name": "Tributary to Butler Creek", "reports": 4, "points": [[34.02007, -84.61912]]}]
    targets, done, _ = N.collect_name_targets("GA", rows, resolver, waters)
    assert done == [] and [t["name"] for t in targets] == ["Butler Creek"]
    assert "holds the name at some of the reports' points, not at all of them" in targets[0]["notes"][-1]
    assert not any("another name" in x for x in targets[0]["notes"])
    targets, done, _ = N.collect_name_targets("GA", rows[:1], resolver, waters)
    assert targets == [] and [s for _, s in done] == [["butler-creek-ga"]]


def test_a_creek_basin_text_the_status_resolver_reads_as_a_label_says_so():
    """'Lindsey Creek Basin' gives Lindsey Creek to the names pass, but the status resolver reads the whole text as a
    sewer basin's label (build/status.py, Watershed labels): the row says that, not that an alias is missing."""
    from build import status as S
    waters = {"lindsey-creek-ga": {"slug": "lindsey-creek-ga", "name": "Lindsey Creek", "state": "GA"}}
    r = S.Resolver(waters, [], placement_rules={})
    row = {"towns": ["Columbus"]}
    assert N.resolver_places(r, "Lindsey Creek Basin", "GA", row, ["lindsey-creek-ga"]) == "label"
    assert N.resolver_places(r, "Lindsey Creek", "GA", row, ["lindsey-creek-ga"]) is None
    assert N.resolver_places(r, "Lindsy Creek", "GA", row, ["lindsey-creek-ga"]) == "spelling"
    reason = N.UNPLACED["label"].format(slugs="lindsey-creek-ga")
    assert "basin label" in reason and N.reason_kind(reason).startswith("a water record holds the water this text names,")


@pytest.mark.parametrize("slug,state,name,spelling", [
    ("allen-creek-fl", "FL", "Allen Creek", "Allen's Creek"),
    ("allen-creek-fl", "FL", "Allen Creek", "Allens Creek"),
    ("sherman-creek-fl", "FL", "Sherman Creek", "Sherman's Creek"),
    ("mccoys-creek-fl", "FL", "McCoys Creek", "Mc Coys Creek"),
    ("lake-lawne-fl", "FL", "Lake Lawne", "Lawne Lake"),
    ("north-fork-middle-river-fl", "FL", "North Fork Middle River", "North Fork of Middle River"),
    ("north-fork-middle-river-fl", "FL", "North Fork Middle River", "N Fork of Middle River"),
    ("south-fork-middle-river-fl", "FL", "South Fork Middle River", "South Fork of Middle River"),
    ("south-fork-middle-river-fl", "FL", "South Fork Middle River", "S Fork of Middle River"),
    ("seventeen-mile-river-ga", "GA", "Seventeen Mile River", "17 Mile River"),
])
def test_the_reports_spellings_of_these_waters_are_hand_aliases(slug, state, name, spelling):
    """The 2026-11-04 report-name review's alias candidates (P3-6) are in data/water-aliases.json, and the status
    resolver reads each spelling as its water."""
    from build import status as S
    waters = {slug: {"slug": slug, "name": name, "state": state},
              "middle-river-fl": {"slug": "middle-river-fl", "name": "Middle River", "state": "FL"}}
    problems = S.apply_water_aliases(waters, S.DATA_DIR / S.WATER_ALIASES_FILE)     # the file's other slugs are absent
    assert not [p for p in problems if slug in p]
    r = S.Resolver(waters, [], placement_rules={})
    assert r.by_name(spelling, state, None, None)[0] == [slug]


def test_a_recheck_resolves_what_a_record_now_holds_and_builds_nothing(tmp_path, monkeypatch):
    """--names --recheck: no build, no network, data/waters-nhd.json not written; a name a record now holds moves to
    resolved, a name that needs a build keeps the last build's outcome or waits for the next --names run."""
    out = tmp_path / "waters-nhd.json"
    monkeypatch.setattr(N, "OUT", out)
    path = tmp_path / "missing.json"
    meta = {"state": "GA", "build": {"date": "2026-11-04", "command": "python -m ingest.waters_from_nhd --names x "
                                     "--state GA", "records_built": 3, "names_resolved": 1, "network_requests": 9}}
    rows = [{"name": "17 Mile River", "reports": 1, "points": [[31.5, -82.85]], "_parts": ["17 Mile River"],
             "reason": "a water record holds this water but not this spelling (seventeen-mile-river-ga): ..."},
            {"name": "Weracoba Creek Basin", "reports": 1, "towns": ["Columbus"], "_parts": ["Weracoba Creek"],
             "reason": "a basin (a river basin, or a stormwater, treatment or marina basin), not a water's name"},
            {"name": "Dram Branch Basin", "reports": 1, "towns": ["Columbus"], "_parts": ["Dram Branch"]},
            {"name": "catch basin", "reports": 2, "_parts": []}]
    done = [(N.Target(name="17 Mile River"), ["seventeen-mile-river-ga"])]
    targets = [N.Target(name="Weracoba Creek"), N.Target(name="Dram Branch")]
    previous = [{"state": "GA", "name": "Weracoba Creek", "from": "reports", "slugs": [], "how": [],
                 "reason": "no NHD flowline or waterbody of that name in GA"}]
    skipped = {("GA", "catch basin"): "part of a sewer, drainage or treatment works, not a public water"}
    r = FakeResolver({"17 Mile River": (["seventeen-mile-river-ga"], None, False)})
    assert N.names_recheck(path, meta, "GA", rows, targets, done, skipped, r, previous=previous) == 0
    assert not out.exists()
    d = json.loads(path.read_text())
    assert [x["name"] for x in d["resolved"]] == ["17 Mile River"]
    assert d["resolved"][0]["how"] == "a water record already holds the name"
    left = {x["name"]: x["reason"] for x in d["rows"]}
    assert left["Weracoba Creek Basin"] == "no NHD flowline or waterbody of that name in GA"
    assert left["Dram Branch Basin"].startswith("not reached this run (a recheck builds nothing)")
    assert left["catch basin"].startswith("part of a sewer")
    assert d["build"]["command"].endswith("--state GA --recheck") and d["build"]["network_requests"] == 0
    assert d["build"]["last_build"]["records_built"] == 3                  # the last real build is still named
