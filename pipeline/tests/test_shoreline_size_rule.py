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
SIZE_KEYS = ("min_area_km2", "min_area_kinds", "min_mean_width_km", "narrow_min_length_km", "min_ring_km")


def rules_off() -> dict:
    """The rules file with the size rule off: every size-rule key absent, whatever the committed file says (the lake
    switch set three of them on 2026-11-16). Tests of the rule-off behaviour read this, never the committed state."""
    r = copy.deepcopy(RULES_FILE)
    for k in SIZE_KEYS:
        r["reach"]["shoreline"].pop(k, None)
    return r


RULES_OFF = rules_off()


def rules_on(min_area=50, kinds=None) -> dict:
    """The size rule on at min_area with no other size key (a scratch copy built from rules_off)."""
    r = copy.deepcopy(RULES_OFF)
    r["reach"]["shoreline"]["min_area_km2"] = min_area
    if kinds is not None:
        r["reach"]["shoreline"]["min_area_kinds"] = kinds
    return r


OFF = SH.rule(RULES_OFF)
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

def test_the_committed_rules_file_has_the_lake_switch_on_with_the_narrow_floor_and_the_islet_floor():
    """The lake switch (owner, 2026-11-16, decisions 26 and 28): lakes and reservoirs of 50 km2 or more, the long,
    narrow ones (under 1.5 km wide on average and 40 km or more long) kept whole; and the islet floor (decision 29): a
    ring under 5 km is not walked alone. Bays and sounds are a later switch, so their key is absent."""
    sh = RULES_FILE["reach"]["shoreline"]
    assert sh["min_area_km2"] == 50 and sh["min_mean_width_km"] == 1.5 and sh["narrow_min_length_km"] == 40
    assert sh["min_ring_km"] == 5 and R.shore_sig(SH.rule(RULES_FILE)).endswith("|ring5")
    assert "min_area_kinds" not in sh
    committed = SH.rule(RULES_FILE)
    assert SH.size_on(committed) and SH.size_kinds(committed) == {"lake", "reservoir"}
    assert OFF["min_area_kinds"] == ["lake", "reservoir"] and OFF["min_area_km2"] is None
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
    # never the Census water (shaped for the Great Lakes and the coasts; a sliver or the sea beside an inland lake)
    monkeypatch.setattr(R, "census_lake_outline", lambda *a, **k: pytest.fail("a size-rule lake took a Census outline"))
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
    rules = rules or RULES_OFF
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
    nulls = copy.deepcopy(RULES_OFF)            # every key present and null, against every key absent
    nulls["reach"]["shoreline"].update(min_area_km2=None, min_mean_width_km=None, narrow_min_length_km=None,
                                       min_ring_km=None)
    b, hb = _build([WITH_POINT, NO_POINT], {}, rules=nulls)
    drop = ("built",)

    def bare(o):
        """The build without its stamps and without the echo of the rule's own null keys (the rule as written)."""
        if isinstance(o, dict):
            return {k: bare(v) for k, v in o.items() if k not in drop and not (k in SIZE_KEYS and v is None)}
        if isinstance(o, list):
            return [bare(v) for v in o]
        return o
    assert json.dumps(bare(a), sort_keys=True, default=str) == json.dumps(bare(b), sort_keys=True, default=str)
    assert json.dumps(bare(ha), sort_keys=True, default=str) == json.dumps(bare(hb), sort_keys=True, default=str)


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
                             rules=RULES_OFF)[0]
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
    assert whole == {"big-lake-vt", "big-res-vt"} and RL.size_rule_whole(WATERS, RULES_OFF) == set()
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
    # a yellow sewage fallback beside a red bloom on the named water: the headline is the sewage yellow, and the
    # bloom stays in the categories (the map shows it when sewage is hidden); never red sewage (Astra finding 3)
    mixed = {"fill": True, "fill_status": "red", "fill_category": "sewage",
             "fill_status_by_category": {"sewage": "yellow", "beach": "grey", "bloom": "red"}}
    p = X.part_fill_props(mixed)
    assert p["status"] == p["headline_status"] == "yellow" and p["status_by_category"]["bloom"] == "red"


def test_out_rules_is_unchanged_with_the_rule_off_and_says_the_size_rule_with_it_on():
    assert X.shoreline_rules(RULES_OFF) is RULES_OFF
    on = X.shoreline_rules(rules_on())
    sh, sh0 = on["reach"]["shoreline"], RULES_OFF["reach"]["shoreline"]
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
    assert "On a bay or sound, such a report is listed on the water's page, and its outlets are marked on the map." in bays["rationale"]
    assert SH.size_texts(OFF) == {}


# ---------------------------------------------------------------- the geometry pilot's points and the review's fixes

def _ring(lon0, lat0, dlon, dlat):
    return [[lon0, lat0], [lon0 + dlon, lat0], [lon0 + dlon, lat0 + dlat], [lon0, lat0 + dlat], [lon0, lat0]]


def test_min_ring_km_null_walks_the_islet_as_today_and_set_starts_on_the_shore_and_marks_the_islet():
    """Lake Washington WA0031682-018: an 80 m islet 38 m nearer than the mainland took the whole stretch."""
    from shapely.geometry import Polygon
    lake = Polygon(_ring(-73.40, 44.50, 0.1, 0.072)[:-1], [_ring(-73.3505, 44.5004, 0.0008, 0.0006)[:-1]])
    lon, lat = -73.3501, 44.50028          # 31 m from the south shore (lat 44.50), 13 m from the islet (lat 44.5004)
    today = SH.stretch(lon, lat, lake, None, 20, snap_km=5)
    assert today["length_km"] < 1 and "islets" not in today            # the islet ring, as before
    assert SH.stretch(lon, lat, lake, None, 20, snap_km=5, min_ring_km=None) == today
    fixed = SH.stretch(lon, lat, lake, None, 20, snap_km=5, min_ring_km=5)
    assert fixed["length_km"] == pytest.approx(SH.stretch(lon, 44.4999, lake, None, 20)["length_km"], abs=0.5)
    assert fixed["length_km"] > 15 and len(fixed["islets"]) == 1 and fixed["islets"][0]["km"] < 0.5
    # no long ring within reach: the nearest ring as before
    alone = Polygon(_ring(-73.3505, 44.5004, 0.0008, 0.0006)[:-1])
    assert SH.stretch(lon, lat, alone, None, 20, snap_km=5, min_ring_km=5)["length_km"] < 1


def test_the_ring_floor_enters_the_stretch_signature_only_when_set():
    assert R.shore_sig(OFF) == "|".join(str(OFF[k]) for k in ("each_way_km", "shore_m", "gap_km", "snap_km", "ocean_open_m"))
    assert "ring" not in R.shore_sig(OFF) and R.shore_sig({**OFF, "min_ring_km": 5}).endswith("|ring5")


def test_an_islet_marked_whole_takes_the_stretchs_status_with_no_distance_and_no_stop():
    """An islet past the walk (min_ring_km 5): the record, the status build and the export. The islet is a segment of
    the stretch, so it takes the stretch's status hour by hour; it adds no distance and no stop; and the export marks
    it (islet true) so the lists never print its km 0 to 0 as a distance along the shore."""
    ring5 = rules_on()
    ring5["reach"]["shoreline"]["min_ring_km"] = 5
    islet_lake = {"type": "Polygon", "coordinates": [_ring(-73.40, 44.50, 0.1, 0.072),
                                                     _ring(-73.3505, 44.5004, 0.0008, 0.0006)]}
    waters = {**WATERS, "big-lake-vt": {**WATERS["big-lake-vt"], "geometry": islet_lake}}
    rec = shore_rec(lat=44.50028, lon=-73.3501, shore=SH.rule(ring5), waters=waters)
    islets = [sg for sg in rec["segments"] if sg.get("islet")]
    walked = [sg for sg in rec["segments"] if not sg.get("islet")]
    assert len(islets) == 1 and islets[0]["km_start"] == islets[0]["km_end"] == 0.0 and islets[0]["ring_km"] < 0.5
    assert islets[0]["coords"][0] == islets[0]["coords"][-1] and len(islets[0]["coords"]) == 5     # the whole ring
    assert rec["length_km"] > 15 and rec["length_km"] == pytest.approx(sum(sg["km_end"] for sg in walked), abs=0.01)
    assert len(rec["stops"]) == len(walked) and rec["states"] == ["VT"] and rec["waters"] == ["big-lake-vt"]
    st, _ = _build([WITH_POINT], {rec["key"]: rec}, rules=ring5, waters=waters)
    lake = st["waters"]["big-lake-vt"]
    assert st["reaches"][rec["key"]]["status"] == "red" and lake["fill"] is False and lake["fill_status"] == "grey"
    by_event = {"vt-test:1": {"started_at": (NOW - 2 * H).isoformat()}}
    feats, paths = X.reach_features(st, by_event, {rec["key"]: rec})
    segs = [f["properties"] for f in feats if f["properties"]["feature"] == "segment"]
    stops = [f for f in feats if f["properties"]["feature"] == "stop"]
    assert len(segs) == len(rec["segments"]) and {p["status"] for p in segs} == {"red"}
    assert [p.get("islet") for p in segs] == [None] * len(walked) + [True]
    assert len(stops) == len(walked) and all(f["geometry"]["coordinates"] not in islets[0]["coords"] for f in stops)
    path = paths[0]["properties"]
    assert path["length_km"] == rec["length_km"] and path["status"] == "red" and len(path["stops"]) == len(walked)
    assert path["segments_km"][-1] == [0.0, 0.0] and len(paths[0]["geometry"]["coordinates"]) == len(rec["segments"])
    by_state, homeless = X.reaches_by_state(feats, paths, st, {rec["key"]: rec}, {"VT"})
    assert homeless == [] and len(by_state["VT"]) == len(feats) + 1


def test_a_narrow_reservoir_keeps_the_whole_fill_under_the_width_floor():
    long_narrow = {"type": "Polygon", "coordinates": [_ring(-72.0, 44.0, 0.9, 0.009)]}     # about 71 km by 1 km
    waters = dict([w("narrow-res-vt", "Narrow Reservoir", "reservoir", long_narrow, area_km2=71.0), *WATERS.items()])
    on = SH.rule(rules_on())
    floor = SH.rule({**rules_on(), "reach": {**rules_on()["reach"], "shoreline": {
        **rules_on()["reach"]["shoreline"], "min_mean_width_km": 1.5}}})
    S._GEOM_CACHE.clear()
    plain = S.with_outline_areas(waters, on)
    assert SH.is_shoreline(plain["narrow-res-vt"], on) and "outline_mean_width_km" not in plain["narrow-res-vt"]
    S._GEOM_CACHE.clear()
    measured = S.with_outline_areas(waters, floor)
    assert measured["narrow-res-vt"]["outline_mean_width_km"] == pytest.approx(1.0, abs=0.05)
    assert not SH.is_shoreline(measured["narrow-res-vt"], floor)          # kept filled whole
    assert SH.is_shoreline(measured["big-lake-vt"], floor)                  # 8 km wide: moves
    assert "narrower than 0.9 mile (1.5 kilometres) on average, such as" in SH.size_texts(floor)["rationale"]
    assert measured["narrow-res-vt"]["outline_length_km"] == pytest.approx(71.5, abs=1.5)
    # with the pilot's length condition too: kept at 40 km, moved at 100 km
    for ln, moves in ((40, False), (100, True)):
        r2 = {**floor, "narrow_min_length_km": ln}
        assert SH.is_shoreline(measured["narrow-res-vt"], r2) is moves
    assert "on average and longer than 25 miles (40 kilometres), such as" in \
        SH.size_texts({**floor, "narrow_min_length_km": 40})["rationale"]
    assert "narrower" not in SH.size_texts(on)["rationale"]


def test_ocean_and_sea_records_and_bays_with_no_outline_stay_off_the_bay_rule():
    both = SH.rule(rules_on(kinds=["lake", "reservoir", "bay", "sound"]))
    sea = {"kind": "sound", "name": "North Atlantic Ocean", "state": "ME", "area_km2": 9000.0}
    bering = {"kind": "bay", "name": "Bering Sea", "state": "AK", "area_km2": 9000.0}
    assert not SH.is_shoreline(sea, both) and not SH.is_shoreline(bering, both)
    bare = {"slug": "back-bay-x", "name": "Back Test Bay", "kind": "bay", "state": "ME", "area_km2": 120.0}
    S._GEOM_CACHE.clear()
    out = S.with_outline_areas({"back-bay-x": bare, **BAYS}, both)
    assert out["back-bay-x"]["no_outline_here"] is True and not SH.is_shoreline(out["back-bay-x"], both)
    assert SH.is_shoreline(out["casco-test-bay-me"], both)


def test_the_measured_area_is_not_rounded_across_the_threshold():
    rec = {"kind": "lake", "name": "Edge Lake", "state": "VT", SH.OUTLINE_AREA: 49.96}
    assert not SH.is_shoreline(rec, ON)


def test_an_empty_or_rejected_kinds_list_is_the_rule_off_not_an_error():
    for kinds in ([], ["river"]):
        r = SH.rule(rules_on(kinds=kinds))
        assert not SH.size_on(r) and SH.size_texts(r) == {} and not SH.is_shoreline(WATERS["big-lake-vt"], r)
        assert X.shoreline_rules(rules_on(kinds=kinds))["reach"]["shoreline"] == rules_on(kinds=kinds)["reach"]["shoreline"]


def test_a_point_beyond_snap_km_falls_back_to_the_whole_lake():
    """Lake Maurepas: both outfalls 8.6 to 9.1 km from the outline get no stretch, so their reports fill the lake."""
    far = shore_rec(lat=44.536, lon=-73.35)                 # mid-lake, about 4 km from every edge... within 5 km
    assert far["segments"]
    S._GEOM_CACHE.clear()
    rec = R.shoreline_record({"key": f"{PERMIT}-001", "permit": PERMIT, "outfall": "001", "water_slug": "big-lake-vt",
                              "lat": 44.536, "lon": -73.35, "state": "VT", "model": "shoreline"}, WATERS,
                             {**ON, "snap_km": 1.0}, None)
    assert rec["cut_reason"] == "no_trace" and "no shore" in rec["error"]
    st, _ = _build([WITH_POINT], {rec["key"]: rec}, rules=rules_on())
    lake = st["waters"]["big-lake-vt"]
    assert lake["fill"] is True and lake["fill_status"] == "red" and [r["placement"] for r in lake["reasons"]] == [S.SHORE_WHOLE]


def test_a_stretch_that_cannot_be_drawn_or_whose_water_left_the_rule_never_hides_the_report():
    rec = shore_rec()
    flat = {**rec, "segments": [{**sg, "coords": [sg["coords"][0]] * 3} for sg in rec["segments"]]}
    assert SH.drawable(rec) and not SH.drawable(flat)
    st, _ = _build([WITH_POINT], {flat["key"]: flat}, rules=rules_on())
    assert st["waters"]["big-lake-vt"]["fill_status"] == "red"
    stale = {**rec, "water_slug": "mid-lake-vt"}            # a water that is not (or no longer) under the rule
    st, _ = _build([WITH_POINT], {stale["key"]: stale}, rules=rules_on())
    assert st["waters"]["big-lake-vt"]["fill_status"] == "red" and stale["key"] not in st["reaches"]


def test_the_input_signature_index_gives_the_same_hash_as_the_record_by_record_walk():
    rec = shore_rec()
    alone = R.shore_input_sig("big-lake-vt", rec["segments"], WATERS, ON)
    R._SIG_INDEX.clear()
    R._SIG_INDEX["active"] = True
    try:
        assert R.shore_input_sig("big-lake-vt", rec["segments"], WATERS, ON) == alone
        assert R.shore_input_sig("big-lake-vt", rec["segments"], WATERS, ON) == alone      # from the memo
    finally:
        R._SIG_INDEX.clear()
    assert rec["input_sig"] == alone


def test_the_committed_file_publishes_the_lake_sentences_with_the_narrow_floor_and_no_bay_or_sound_words():
    out = X.shoreline_rules(X.public_rules(RULES_FILE))["reach"]["shoreline"]
    sh0 = RULES_FILE["reach"]["shoreline"]
    added_doc = out["doc"][len(sh0["doc"]):].strip()
    added = out["rationale"][len(sh0["rationale"]):].strip()
    assert out["doc"].startswith(sh0["doc"]) and out["rationale"].startswith(sh0["rationale"])
    assert added_doc == ("Other lakes and reservoirs of 19 square miles (50 square kilometres) or more are drawn the "
                         "same way. A report on such a lake or reservoir that cannot be placed on the shore colours "
                         "the whole water, as on a smaller one.")
    assert added == ("We draw other lakes and reservoirs of 19 square miles (50 square kilometres) or more the same "
                     "way. The 12-mile (20-kilometre) distance comes from studies on the Great Lakes and on ocean "
                     "shores; on these smaller waters we apply it as a cautious distance, not a measurement. Where a "
                     "water's whole shoreline is shorter than 25 miles (40 kilometres), the stretch covers all of it. "
                     "A report on such a lake or reservoir that we cannot place on the shore colours the whole water, "
                     "as on a smaller lake. Lakes and reservoirs narrower than 0.9 mile (1.5 kilometres) on average "
                     "and longer than 25 miles (40 kilometres), such as reservoirs that fill a river valley, are still "
                     "coloured as a whole: a stretch along one bank would leave the nearby opposite bank grey.")
    assert not any(w in added + added_doc for w in (" bay", " sound", "Bay", "Sound"))
    assert out["min_area_kinds"] == ["lake", "reservoir"] and not X.internal_wording(out)
