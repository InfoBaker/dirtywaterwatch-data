"""The shoreline size rule (data/rules.json reach.shoreline.min_area_km2 and min_area_kinds; owner, 2026-11-16): with
the threshold set, a lake or reservoir at least that large is a shoreline water (build/shoreline.py size_entry); a report
that can start a stretch colours the stretch, and one that can start none keeps the lake's whole-water colour, as
before the rule (build/status.py SHORE_WHOLE, whole_fill). Bays and sounds come under the rule when the kinds list names
them, with their own words and no fallback (they were never filled). Shipped off: data/rules.json carries neither key,
and with min_area_km2 null every output is what it was.

Fixtures: "Big Lake" (64 km2), "Mid Lake" (49 km2), "Big Pond" (80 km2, kind pond), "Casco Test Bay" (120 km2, kind
bay, Maine), a Florida bay of the same size, "Pamlico Sound" (kind lake, as openboatlaunch holds it) and "Wheeler Test
Lake" (no area_km2; a 64 km2 outline). Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from shapely.geometry import shape  # noqa: E402

from build import rain_likely as RL  # noqa: E402
from build import reaches as R  # noqa: E402
from build import shoreline as SH  # noqa: E402
from build import status as S  # noqa: E402
from common import event  # noqa: E402
from export import build as X  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
H = timedelta(hours=1)
PERMIT = "VT0100001"
RULES_FILE = json.loads((ROOT / "data" / "rules.json").read_text())


def rules_on(min_area=50, kinds=None) -> dict:
    """The rules file with the size rule switched on (a scratch copy; the committed file stays off)."""
    r = copy.deepcopy(RULES_FILE)
    r["reach"]["shoreline"]["min_area_km2"] = min_area
    if kinds is not None:
        r["reach"]["shoreline"]["min_area_kinds"] = kinds
    return r


OFF = SH.rule(RULES_FILE)
ON = SH.rule(rules_on())


def square(lon0, lat0, dlon=0.1, dlat=0.072):
    return {"type": "Polygon", "coordinates": [[[lon0, lat0], [lon0 + dlon, lat0], [lon0 + dlon, lat0 + dlat],
                                                 [lon0, lat0 + dlat], [lon0, lat0]]]}


def w(slug, name, kind, geom, state="VT", **extra):
    b = shape(geom).bounds
    return slug, {"slug": slug, "name": name, "kind": kind, "state": state, "towns": ["Testtown"], "bbox": list(b),
                  "geometry": geom, **extra}


BIG = square(-73.40, 44.50)
WATERS = dict([
    w("big-lake-vt", "Big Lake", "lake", BIG, area_km2=64.0),
    w("mid-lake-vt", "Mid Lake", "lake", square(-73.20, 44.50, 0.0875, 0.063), area_km2=49.0),
    w("big-pond-vt", "Big Pond", "pond", square(-73.00, 44.50), area_km2=80.0),
    w("big-res-vt", "Big Reservoir", "reservoir", square(-72.80, 44.50), area_km2=55.0),
    w("wheeler-test-lake-vt", "Wheeler Test Lake", "lake", square(-72.60, 44.50)),         # no area_km2
    w("small-brook-vt", "Small Brook", "stream", {"type": "LineString", "coordinates": [[-72.4, 44.5], [-72.4, 44.6]]}),
])
BAYS = dict([
    w("casco-test-bay-me", "Casco Test Bay", "bay", square(-70.2, 43.6, 0.2, 0.08), state="ME", area_km2=120.0),
    w("florida-test-bay-fl", "Florida Test Bay", "bay", square(-82.6, 27.7, 0.2, 0.08), state="FL", area_km2=120.0),
    w("pamlico-sound-nc", "Pamlico Sound", "lake", square(-76.0, 35.2, 0.5, 0.4), state="NC", area_km2=4083.0),
])


# ---------------------------------------------------------------- which waters (build/shoreline.py)

def test_the_committed_rules_file_ships_the_size_rule_off_and_does_not_name_its_new_keys():
    sh = RULES_FILE["reach"]["shoreline"]
    assert sh["min_area_km2"] is None and "min_area_kinds" not in sh
    assert OFF["min_area_kinds"] == ["lake", "reservoir"]
    assert not SH.size_on(OFF) and SH.size_on(ON)


def test_off_no_lake_bay_or_sound_is_a_shoreline_water_by_size():
    for x in {**WATERS, **BAYS}.values():
        assert SH.size_entry(x, OFF) is None
        assert not SH.is_shoreline(x, OFF)


def test_a_lake_of_50_km2_or_more_is_a_shoreline_water_and_one_of_49_is_not():
    e = SH.shoreline_entry(WATERS["big-lake-vt"], ON)
    assert e == {"name": "Big Lake", "size_rule": True, "area_km2": 64.0, "area_basis": "record"}
    assert SH.is_size_rule(WATERS["big-lake-vt"], ON)
    assert not SH.is_shoreline(WATERS["mid-lake-vt"], ON)
    assert SH.is_shoreline({**WATERS["mid-lake-vt"], "area_km2": 50.0}, ON)          # at the threshold
    assert SH.is_shoreline(WATERS["big-res-vt"], ON)                                   # a reservoir too


def test_ponds_are_untouched_and_a_river_is_never_a_size_rule_water():
    assert not SH.is_shoreline(WATERS["big-pond-vt"], ON)
    assert not SH.is_shoreline(WATERS["small-brook-vt"], SH.rule(rules_on(kinds=["lake", "river", "stream"])))
    assert SH.size_kinds(SH.rule(rules_on(kinds=["lake", "river"]))) == {"lake"}


def test_a_bay_or_sound_only_when_the_kinds_list_names_it_with_its_own_wording_flag():
    bay = BAYS["casco-test-bay-me"]
    assert not SH.is_shoreline(bay, ON)
    both = SH.rule(rules_on(kinds=["lake", "reservoir", "bay", "sound"]))
    e = SH.shoreline_entry(bay, both)
    assert e["size_rule"] and e["bay"] is True and "sound" not in e
    sound = {**bay, "kind": "sound", "name": "Test Sound"}
    assert SH.shoreline_entry(sound, both)["sound"] is True
    assert not SH.is_shoreline({**bay, "area_km2": 49.0}, both)


def test_a_bay_in_a_state_the_ocean_rule_covers_stays_off_the_size_rule():
    """Florida and California: the ocean walk already follows the shore of a bay open to the sea there."""
    both = SH.rule(rules_on(kinds=["lake", "reservoir", "bay", "sound"]))
    assert SH.ocean_states(both) == {"FL", "CA"}
    assert not SH.is_shoreline(BAYS["florida-test-bay-fl"], both)
    assert SH.is_shoreline(BAYS["casco-test-bay-me"], both)


def test_pamlico_sound_a_record_of_kind_lake_comes_under_the_lake_rule():
    e = SH.shoreline_entry(BAYS["pamlico-sound-nc"], ON)
    assert e["size_rule"] and "bay" not in e and "sound" not in e      # worded as a lake: its record's kind


def test_the_listed_waters_keep_their_entries_with_the_rule_on():
    erie = {"kind": "lake", "name": "Lake Erie", "wikidata": "Q5492", "area_km2": 26067.8, "state": "PA"}
    assert SH.shoreline_entry(erie, ON) == SH.shoreline_entry(erie, OFF)
    assert "size_rule" not in SH.shoreline_entry(erie, ON)
    puget = {"kind": "sound", "name": "Puget Sound", "wikidata": "Q604141", "state": "WA", "area_km2": 472}
    assert SH.shoreline_entry(puget, ON) == SH.shoreline_entry(puget, OFF)
    assert not SH.is_size_rule(erie, ON) and not SH.is_size_rule(puget, ON)


def test_a_record_with_no_area_crosses_by_its_outline_area_and_says_so():
    rec = WATERS["wheeler-test-lake-vt"]
    assert not SH.is_shoreline(rec, ON)                       # the record alone has no area
    S._GEOM_CACHE.clear()
    off = S.with_outline_areas(WATERS, OFF)
    assert off is WATERS                                      # off: the records as they are, the same object
    on = S.with_outline_areas(WATERS, ON)
    assert on is not WATERS and "outline_area_km2" not in WATERS["wheeler-test-lake-vt"]
    assert on["wheeler-test-lake-vt"]["outline_area_km2"] == pytest.approx(63.4, abs=1.5)
    e = SH.shoreline_entry(on["wheeler-test-lake-vt"], ON)
    assert e["area_basis"] == "outline" and e["area_km2"] == pytest.approx(63.4, abs=1.5)
    assert on["big-lake-vt"] is WATERS["big-lake-vt"]         # a record with its own area is not measured
    # a record with neither an area nor an outline can never cross
    bare = {"slug": "x", "name": "X", "kind": "lake", "state": "VT"}
    assert S.with_outline_areas({"x": bare}, ON)["x"] is bare and not SH.is_shoreline(bare, ON)


def test_same_named_records_are_one_water_only_where_their_boxes_meet():
    ny = {**WATERS["big-lake-vt"], "slug": "big-lake-ny", "state": "NY"}
    far = {**WATERS["big-lake-vt"], "slug": "big-lake-nh", "state": "NH", "bbox": [-71.5, 43.0, -71.4, 43.1]}
    waters = {**WATERS, "big-lake-ny": ny, "big-lake-nh": far}
    assert SH.lake_waters("big-lake-vt", ["VT", "NY", "NH"], waters, ON) == ["big-lake-vt", "big-lake-ny"]


# ---------------------------------------------------------------- the reach step (build/reaches.py)

def _row(outfall, slug, lat=44.5, lon=-73.35, kind=None):
    return {"npdes_permit": PERMIT, "outfall": outfall, "state": "VT", "water_slug": slug, "lat": lat, "lon": lon,
            "outfall_kind": kind, "_file": "data/outfalls-vt.json"}


def test_an_outfall_on_a_crossing_lake_becomes_a_shoreline_candidate_only_with_the_rule_on():
    rows = [_row("001", "big-lake-vt"), _row("002", "mid-lake-vt", 44.5, -73.15), _row("003", "big-pond-vt", 44.5, -72.95)]
    skipped = {}
    c = R.candidate_outfalls(WATERS, rows, {"VT"}, skipped, set(), plants=False, shore=OFF)
    assert c == [] and {k: v["why"] for k, v in skipped.items()} == {
        f"{PERMIT}-001": "not_river", f"{PERMIT}-002": "not_river", f"{PERMIT}-003": "not_river"}
    skipped = {}
    c = {x["key"]: x for x in R.candidate_outfalls(WATERS, rows, {"VT"}, skipped, set(), plants=False, shore=ON)}
    assert list(c) == [f"{PERMIT}-001"] and c[f"{PERMIT}-001"]["model"] == "shoreline"
    assert skipped[f"{PERMIT}-002"]["why"] == "not_river" and skipped[f"{PERMIT}-003"]["why"] == "not_river"


def shore_rec(outfall="001", slug="big-lake-vt", lat=44.5, lon=-73.35, shore=ON, waters=None):
    c = {"key": f"{PERMIT}-{outfall}", "permit": PERMIT, "outfall": outfall, "water_slug": slug, "lat": lat,
         "lon": lon, "name": None, "sources": ["echo"], "state": "VT", "outfall_kind": "cso", "model": "shoreline"}
    S._GEOM_CACHE.clear()
    return R.shoreline_record(c, waters or WATERS, shore, None)


def test_a_stretch_on_a_lake_whose_shore_is_shorter_than_both_walks_covers_the_whole_shore():
    rec = shore_rec()
    assert rec["cut_reason"] == "shoreline" and rec["waters"] == ["big-lake-vt"]
    ring = R.seg_km(BIG["coordinates"][0])
    assert ring < 40 and rec["length_km"] == pytest.approx(ring, abs=0.2)
    assert "bay" not in rec and "sound" not in rec


def test_a_bay_under_the_size_rule_gets_the_bay_wording_on_its_stretch():
    both = SH.rule(rules_on(kinds=["lake", "reservoir", "bay", "sound"]))
    rec = shore_rec(slug="casco-test-bay-me", lat=43.6, lon=-70.1, shore=both, waters=BAYS)
    assert rec["bay"] is True and rec["segments"]


def test_a_lake_with_no_outline_gets_a_no_trace_record_not_a_stretch(monkeypatch):
    """Production: a crossing lake whose openboatlaunch outline is missing this run, and no Census water."""
    waters = {"big-lake-vt": {k: v for k, v in WATERS["big-lake-vt"].items() if k != "geometry"}}
    monkeypatch.setattr(R, "census_lake_outline", lambda slug, waters, land: None)
    S._GEOM_CACHE.clear()
    rec = R.shoreline_record({"key": f"{PERMIT}-001", "permit": PERMIT, "outfall": "001", "water_slug": "big-lake-vt",
                              "lat": 44.5, "lon": -73.35, "state": "VT", "model": "shoreline"}, waters, ON, {})
    assert rec["cut_reason"] == "no_trace" and rec["segments"] == [] and "no outline" in rec["error"]


# ---------------------------------------------------------------- the status build (build/status.py)

@pytest.fixture(autouse=True)
def _status_state():
    saved = dict(S.PLACE_STEPS)
    S.PLACE_STEPS.update(registry=True, relaxed_guard=True, no_receiving_water=True, outfall_ids=True,
                         multi_outfall=True)
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    S._STATES = {"VT", "ME", "NC", "PA", "NY"}
    yield
    S.PLACE_STEPS.update(saved)
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    S._SHORE_REACHES.clear()
    S._STATES = None


def ev(rid, **kw):
    kw.setdefault("event_type", "cso")
    kw.setdefault("status", "ongoing")
    kw.setdefault("npdes_permit", PERMIT)
    kw.setdefault("started_at", (NOW - 2 * H).isoformat())
    return event(source_id="vt-test", source_record_id=rid, **kw)


REGISTRY = [_row("001", "big-lake-vt"), _row("002", "big-lake-vt", None, None)]


def _build(records, reaches, rules=None, waters=None, registry=None, rain=None):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "vt-test.json").write_text(json.dumps({"source_id": "vt-test", "ok": True, "last_ok_at": NOW.isoformat(),
                                                  "meta": {}, "records": records}))
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    rules = rules or RULES_FILE
    if rain is None:            # no rainfall in these builds unless a test gives its own caution
        rules = {**rules, "rain_likely": {**rules["rain_likely"], "enabled": False}}
    return S.build(now=NOW, write=False, events_dir=tmp, waters=copy.deepcopy(waters or WATERS),
                   outfalls=list(registry or REGISTRY), registry={}, reaches=copy.deepcopy(reaches), flows=({}, {}),
                   discharger_towns={}, discharger_waters={}, rules=rules, rain=rain)


WITH_POINT = ev("1", outfall_id="001", waterbody_text="Big Lake")
NO_POINT = ev("2", outfall_id="002", waterbody_text="Big Lake")
NEW_KEYS = ("shore_size_rule", "fill_status", "fill_status_by_category", "fill_category")


def test_rule_off_the_big_lake_is_filled_whole_as_today_with_no_new_fields():
    st, _ = _build([WITH_POINT, NO_POINT], {})
    lake = st["waters"]["big-lake-vt"]
    assert lake["fill"] is True and lake["status"] == "red" and lake["status_basis"] == "whole water"
    assert "stretch_model" not in lake and not any(k in lake for k in NEW_KEYS)
    assert [r["placement"] for r in lake["reasons"]] == [None, None]
    assert not any(k in x for x in st["waters"].values() for k in NEW_KEYS)
    assert not st["needs_reach"]


def test_rule_off_the_build_is_the_same_with_the_keys_absent_or_null():
    a, ha = _build([WITH_POINT, NO_POINT], {})
    nulls = copy.deepcopy(RULES_FILE)
    nulls["reach"]["shoreline"]["min_area_km2"] = None
    b, hb = _build([WITH_POINT, NO_POINT], {}, rules=nulls)
    drop = ("built",)
    assert json.dumps({k: v for k, v in a.items() if k not in drop}, sort_keys=True, default=str) == \
        json.dumps({k: v for k, v in b.items() if k not in drop}, sort_keys=True, default=str)
    assert json.dumps({k: v for k, v in ha.items() if k not in drop}, sort_keys=True, default=str) == \
        json.dumps({k: v for k, v in hb.items() if k not in drop}, sort_keys=True, default=str)


def test_on_a_report_that_starts_a_stretch_colours_the_stretch_and_the_outline_stays_grey():
    rec = shore_rec()
    st, _ = _build([WITH_POINT], {rec["key"]: rec}, rules=rules_on())
    lake = st["waters"]["big-lake-vt"]
    assert lake["status"] == "red" and lake["stretch_model"] == "shoreline"
    assert [r["placement"] for r in lake["reasons"]] == ["reach"]
    assert lake["fill"] is False and lake["fill_status"] == "grey"
    assert lake["status_basis"] == S.SIZE_STATUS_BASIS and lake["summary"] == S.SHORE_SUMMARY
    assert lake["shore_size_rule"] == {"min_area_km2": 50, "kinds": ["lake", "reservoir"], "area_km2": 64.0,
                                       "area_basis": "record"}
    assert st["reaches"][rec["key"]]["status"] == "red"


def test_on_a_report_that_can_start_no_stretch_keeps_the_whole_lake_colour_and_says_so():
    st, _ = _build([NO_POINT], {}, rules=rules_on())
    lake = st["waters"]["big-lake-vt"]
    off, _ = _build([NO_POINT], {})
    assert lake["status"] == off["waters"]["big-lake-vt"]["status"] == "red"
    assert [r["placement"] for r in lake["reasons"]] == [S.SHORE_WHOLE]
    assert lake["fill"] is True and lake["fill_status"] == "red" and lake["summary"] == S.SHORE_WHOLE_SUMMARY
    assert lake["reasons"][0]["short"].endswith(S.PLACEMENT_TEXT[S.SHORE_WHOLE])
    assert lake["fill_status_by_category"]["sewage"] == "red" and lake["fill_category"] == "sewage"


def test_on_a_report_with_a_point_but_no_stretch_yet_keeps_the_whole_colour_and_asks_for_one():
    own = ev("3", event_type="sso", waterbody_text="Big Lake", lat=44.5, lon=-73.33)
    st, _ = _build([own], {}, rules=rules_on())
    lake = st["waters"]["big-lake-vt"]
    assert lake["fill_status"] == "red" and lake["fill"] is True
    need = [n for n in st["needs_reach"] if n["event_id"] == "vt-test:3"]
    assert need and need[0]["model"] == "shoreline" and need[0]["water_slug"] == "big-lake-vt"


def test_on_a_stretch_that_could_not_be_drawn_falls_back_to_the_whole_lake():
    """No outline this run (no_trace): the report is not on a stretch, so the lake keeps its whole colour."""
    rec = {**shore_rec(), "segments": [], "cut_reason": "no_trace", "error": "no outline for the lake record"}
    st, _ = _build([WITH_POINT], {rec["key"]: rec}, rules=rules_on())
    lake = st["waters"]["big-lake-vt"]
    assert lake["fill"] is True and lake["fill_status"] == "red"
    assert [r["placement"] for r in lake["reasons"]] == [S.SHORE_WHOLE]


def test_on_the_whole_colour_comes_only_from_the_reports_with_no_stretch():
    rec = shore_rec()
    ended = ev("2", outfall_id="002", waterbody_text="Big Lake", status="ended",
               started_at=(NOW - 100 * H).isoformat(), ended_at=(NOW - 90 * H).isoformat())
    st, hist = _build([WITH_POINT, ended], {rec["key"]: rec}, rules=rules_on())
    lake = st["waters"]["big-lake-vt"]
    assert lake["status"] == "red" and lake["fill_status"] == "yellow" and lake["fill"] is True
    assert sorted(r["placement"] for r in lake["reasons"]) == ["reach", S.SHORE_WHOLE]
    # the history strip and the counts are the water's, stretches included, as on the Great Lakes
    assert hist["waters"]["big-lake-vt"][-1] == "r"


def test_on_no_report_shows_less_than_with_the_rule_off():
    """Every report's colour now is still drawn: on its stretch, or in the whole-lake fill."""
    rec = shore_rec()
    records = [WITH_POINT, NO_POINT]
    off, _ = _build(records, {})
    on, _ = _build(records, {rec["key"]: rec}, rules=rules_on())
    was = off["waters"]["big-lake-vt"]
    now = on["waters"]["big-lake-vt"]
    drawn = {r["event_id"]: r["status"] for r in now["reasons"] if r["placement"] == "reach"
             and on["reaches"][r["reach"]]["status"] == r["status"]}
    whole = {r["event_id"]: r["status"] for r in now["reasons"] if r["placement"] == S.SHORE_WHOLE}
    for r in was["reasons"]:
        assert r["event_id"] in drawn or (r["event_id"] in whole and S.RANK[now["fill_status"]] >= S.RANK[r["status"]])


def test_on_a_rain_caution_with_no_stretch_keeps_the_whole_lake_colour(monkeypatch):
    base = S.event_intervals(ev("9", outfall_id="002"), "VT", NOW, water={**WATERS["big-lake-vt"], "slug": "big-lake-vt"},
                             rules=RULES_FILE)[0]
    iv = {**base, "event_id": f"rain_likely:{PERMIT}:x", "rule": "rain_likely", "color": "yellow", "placement": None,
          "reach": None, "source_id": RL.SOURCE_ID}
    block = {"enabled": True, "rule": "rain_likely", "label": "x", "waters": {}, "problems": []}
    monkeypatch.setattr(RL, "compute", lambda *a, **k: ({"big-lake-vt": [dict(iv)]}, {}, dict(block)))
    on, _ = _build([], {}, rules=rules_on(), rain={"rainfall": {}})
    lake = on["waters"]["big-lake-vt"]
    assert [r["placement"] for r in lake["reasons"]] == [S.SHORE_WHOLE]
    assert lake["fill"] is True and lake["fill_status"] == "yellow"
    off, _ = _build([], {}, rain={"rainfall": {}})
    assert [r["placement"] for r in off["waters"]["big-lake-vt"]["reasons"]] == [None]
    assert off["waters"]["big-lake-vt"]["fill"] is True and off["waters"]["big-lake-vt"]["status"] == "yellow"


def test_rain_caution_keeps_the_whole_lake_for_an_outfall_of_the_permit_with_no_stretch():
    rec = shore_rec()
    outs = [_row("001", "big-lake-vt", kind="cso"), _row("002", "big-lake-vt", None, None, kind="cso")]
    whole = RL.size_rule_whole(WATERS, rules_on())
    assert whole == {"big-lake-vt", "big-res-vt"} and RL.size_rule_whole(WATERS, RULES_FILE) == set()
    keys, tags, reach_of, _ = RL.targets(PERMIT, WATERS, outs, [], {rec["key"]: rec}, S.reach_waters, whole)
    assert keys == [rec["key"]] and tags == {"big-lake-vt": None} and reach_of == {"big-lake-vt": [rec["key"]]}
    # every outfall here has its stretch: the stretch alone
    _, tags, _, _ = RL.targets(PERMIT, WATERS, outs[:1], [], {rec["key"]: rec}, S.reach_waters, whole)
    assert tags == {"big-lake-vt": "reach"}
    # the rule off (no such lakes): as before
    _, tags, _, _ = RL.targets(PERMIT, WATERS, outs, [], {rec["key"]: rec}, S.reach_waters)
    assert tags == {"big-lake-vt": "reach"}


def test_on_the_listed_great_lakes_are_unchanged():
    erie = dict([w("lake-erie-pa", "Lake Erie", "lake", square(-80.5, 42.0, 1.0, 0.5), state="PA",
                   area_km2=26067.8, wikidata="Q5492")])
    rec = ev("5", npdes_permit="PA0026301", waterbody_text="Lake Erie")
    off, offh = _build([rec], {}, waters=erie, registry=[])
    on, onh = _build([rec], {}, rules=rules_on(), waters=erie, registry=[])
    a, b = off["waters"]["lake-erie-pa"], on["waters"]["lake-erie-pa"]
    assert a == b and a["fill"] is False and [r["placement"] for r in a["reasons"]] == ["shoreline_unmodeled"]
    assert offh["waters"] == onh["waters"]


def test_on_a_bay_under_the_size_rule_keeps_its_markers_and_gets_no_fallback():
    both = rules_on(kinds=["lake", "reservoir", "bay", "sound"])
    rec = ev("6", npdes_permit="ME0100001", waterbody_text="Casco Test Bay")
    off, _ = _build([rec], {}, waters=BAYS, registry=[])
    on, _ = _build([rec], {}, rules=both, waters=BAYS, registry=[])
    a, b = off["waters"]["casco-test-bay-me"], on["waters"]["casco-test-bay-me"]
    assert a["fill"] is False and [r["placement"] for r in a["reasons"]] == ["tidal"]
    assert b["fill"] is False and [r["placement"] for r in b["reasons"]] == ["bay_shore_unmodeled"]
    assert b["status_basis"] == S.BAY_STATUS_BASIS and b["stretch_model"] == "shoreline" and "fill_status" not in b
    assert b["status"] == a["status"] == "red"
    # with the kinds list at its default, the bay is what it was
    lakes_only, _ = _build([rec], {}, rules=rules_on(), waters=BAYS, registry=[])
    assert lakes_only["waters"]["casco-test-bay-me"] == a


def test_on_pamlico_sound_held_as_a_lake_falls_back_to_its_whole_colour():
    rec = ev("7", npdes_permit="NC0100001", waterbody_text="Pamlico Sound")
    on, _ = _build([rec], {}, rules=rules_on(), waters=BAYS, registry=[])
    p = on["waters"]["pamlico-sound-nc"]
    assert p["fill"] is True and p["fill_status"] == "red" and p["status_basis"] == S.SIZE_STATUS_BASIS


def test_advisories_are_unchanged_by_the_size_rule():
    """A beach or bloom advisory already colours a lake whole only under 50 km2 (SMALL_WATER_KM2): on Big Lake it is a
    marker before and after; on the 49 km2 lake it colours the lake whole before and after."""
    bloom_big = ev("8", event_type="hab_advisory", status="advisory_active", npdes_permit=None,
                   waterbody_text="Big Lake", lat=44.50, lon=-73.35)
    bloom_mid = ev("9", event_type="hab_advisory", status="advisory_active", npdes_permit=None,
                   waterbody_text="Mid Lake", lat=44.53, lon=-73.15)
    off, _ = _build([bloom_big, bloom_mid], {})
    on, _ = _build([bloom_big, bloom_mid], {}, rules=rules_on())
    assert S.colours_whole_water(WATERS["mid-lake-vt"]) and not S.colours_whole_water(WATERS["big-lake-vt"])
    assert json.dumps(off["advisory_points"], sort_keys=True, default=str) == json.dumps(on["advisory_points"], sort_keys=True, default=str)
    assert off["waters"]["mid-lake-vt"] == on["waters"]["mid-lake-vt"]
    a, b = off["waters"]["big-lake-vt"], on["waters"]["big-lake-vt"]
    # the big lake's map colour: the whole fill before, the part fill after; the same either way
    assert a["fill"] is True and (b["fill_status"] if b["fill"] else "grey") == (a["status"] if a["fill"] else "grey")
    assert {p["event_id"] for p in on["advisory_points"]} >= {"vt-test:8"}


# ---------------------------------------------------------------- the export (export/build.py)

def test_the_overlay_of_a_part_filled_lake_carries_the_fill_colour_only():
    w_ = {"status": "red", "fill": True, "fill_status": "yellow", "fill_category": "sewage",
          "fill_status_by_category": {"sewage": "yellow", "beach": "grey", "bloom": "grey"}}
    p = X.part_fill_props(w_)
    assert p == {"status": "yellow", "part_fill": True, "category": "sewage",
                 "status_by_category": {"sewage": "yellow", "beach": "grey", "bloom": "grey"}, "headline_status": "yellow"}
    assert X.part_fill_props({**w_, "fill": False, "fill_status": "grey"})["status"] == "grey"
    assert X.part_fill_props({**w_, "fill": False, "fill_status": "monthly"})["status"] == "monthly"


def test_out_rules_is_unchanged_with_the_rule_off_and_says_the_size_rule_with_it_on():
    assert X.shoreline_rules(RULES_FILE) is RULES_FILE
    on = X.shoreline_rules(rules_on())
    sh, sh0 = on["reach"]["shoreline"], RULES_FILE["reach"]["shoreline"]
    assert sh["min_area_kinds"] == ["lake", "reservoir"] and sh["min_area_km2"] == 50
    assert sh["doc"].startswith(sh0["doc"]) and sh["rationale"].startswith(sh0["rationale"])
    words = SH.size_texts(SH.rule(rules_on()))
    assert sh["doc"] == f"{sh0['doc']} {words['doc']}" and sh["rationale"] == f"{sh0['rationale']} {words['rationale']}"
    assert words["doc"] == ("Other lakes and reservoirs of 19 square miles (50 square kilometres) or more are drawn the "
                            "same way. A report on such a lake or reservoir that cannot be placed on the shore colours "
                            "the whole water, as on a smaller one.")
    assert "The 12-mile (20-kilometre) distance comes from studies on the Great Lakes and on ocean shores" in words["rationale"]
    assert "shorter than 25 miles (40 kilometres), the stretch covers all of it" in words["rationale"]
    for t in words.values():
        assert not any(x in t.lower() for x in ("safe", "clean", "green"))
    bays = SH.size_texts(SH.rule(rules_on(kinds=["lake", "reservoir", "bay", "sound"])))
    assert bays["doc"].startswith("Other lakes, reservoirs, bays and sounds of 19 square miles")
    assert bays["rationale"].endswith("On a bay or sound, such a report is listed on the water's page, and its outlets are marked on the map.")
    assert SH.size_texts(OFF) == {}
