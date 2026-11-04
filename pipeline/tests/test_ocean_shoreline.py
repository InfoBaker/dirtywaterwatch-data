"""The open ocean as a shoreline water (data/rules.json reach.shoreline.oceans; build/shoreline.py, build/reaches.py
ocean_outline; Florida's go-live gates, 2026-11-04): a report on the Atlantic Ocean or the Gulf of America (Gulf of
Mexico) colours a stretch of the state's ocean shore at its point, never a filled ocean, and the walk follows the open
coast across an inlet rather than into the lagoon behind it. Geometry is synthetic; no network.
Run from pipeline/: python -m pytest tests/test_ocean_shoreline.py -q
"""
from __future__ import annotations

import copy
import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
from shapely.geometry import box, mapping  # noqa: E402

from build import reaches as R  # noqa: E402
from build import shoreline as SH  # noqa: E402
from build import status as S  # noqa: E402
from common import event  # noqa: E402
from export import build as X  # noqa: E402
from ingest import outfall_waters as OW  # noqa: E402
from ingest import waters_from_nhd as N  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
RULES = json.loads((ROOT / "data" / "rules.json").read_text())
SHORE = SH.rule(RULES)
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
H = timedelta(hours=1)

# a coast running north-south at lon -80.10 (land to the west); a barrier island from -80.12 to -80.10 with a lagoon
# behind it (-80.135 to -80.12, lat 25.6 to 26.6) and a 330 m inlet through the island at lat 26.0; the state's
# waters (the TIGER polygon less the land) reach 5.5 km out, to lon -80.045
LAGOON = box(-80.135, 25.6, -80.12, 26.6)
INLET = box(-80.121, 25.9985, -80.099, 26.0015)
FL_LAND = box(-81.0, 25.0, -80.10, 27.0).difference(LAGOON).difference(INLET)
FL_TIGER = box(-81.0, 25.0, -80.045, 27.0)
LAND = {"FL": FL_LAND}


def rec(slug, name, kind, state="FL", **extra):
    return slug, {"slug": slug, "name": name, "kind": kind, "state": state, "towns": [], "bbox": None, **extra}


WATERS = dict([
    rec("atlantic-ocean-fl", "Atlantic Ocean", "bay"),
    rec("gulf-of-america-fl", "Gulf Of America", "bay"),
    rec("north-atlantic-ocean-fl", "North Atlantic Ocean", "sound", area_km2=124023.711),
    rec("atlantic-ocean-va", "Atlantic Ocean", "bay", state="VA"),
    rec("pitts-creek-gulf-of-america-salt-marshes-fl", "Pitts Creek / Gulf of America Salt Marshes", "river"),
    rec("indian-river-lagoon-fl", "Indian River Lagoon", "bay"),
])


@pytest.fixture(autouse=True)
def _census(monkeypatch):
    monkeypatch.setattr(R, "tiger_states", lambda: {"FL": FL_TIGER})
    R._OCEAN.clear()
    S._GEOM_CACHE.clear()
    yield
    R._OCEAN.clear()
    S._GEOM_CACHE.clear()


def test_the_rule_lists_the_oceans_for_florida_with_the_distance_and_its_evidence():
    sh = RULES["reach"]["shoreline"]
    names = {e["name"]: e for e in sh["oceans"]}
    assert set(names) == {"Atlantic Ocean", "Gulf of America"}
    assert "Gulf of Mexico" in names["Gulf of America"]["names"] and names["Atlantic Ocean"]["wikidata"] == "Q97"
    assert all(e["states"] == ["FL"] for e in sh["oceans"])
    assert sh["each_way_km"] == 20 and sh["ocean_open_m"] == 1000
    assert "20 kilometres each way" in sh["ocean_rationale"] and "never as a colour over the ocean" in sh["ocean_rationale"]
    assert "Feddersen" in sh["ocean_source"] and "GeoHealth" in sh["ocean_source"] and "tl_2023_us_state" in sh["ocean_source"]
    for word in ("safe", "owner", "data/", "docs/"):
        assert word not in sh["ocean_rationale"].replace("unsafe", "")


def test_the_oceans_records_are_shoreline_waters_and_their_namesakes_are_not():
    assert SH.is_ocean(WATERS["atlantic-ocean-fl"], SHORE) and SH.is_ocean(WATERS["gulf-of-america-fl"], SHORE)
    assert SH.is_ocean(WATERS["north-atlantic-ocean-fl"], SHORE)
    assert SH.is_shoreline(WATERS["atlantic-ocean-fl"], SHORE)
    assert not SH.is_shoreline(WATERS["atlantic-ocean-va"], SHORE)          # not listed for Virginia (yet)
    assert not SH.is_shoreline(WATERS["pitts-creek-gulf-of-america-salt-marshes-fl"], SHORE)
    assert not SH.is_shoreline(WATERS["indian-river-lagoon-fl"], SHORE)
    assert not SH.is_ocean({"name": "Lake Erie", "kind": "lake", "wikidata": "Q5492", "area_km2": 26000}, SHORE)
    assert SH.is_shoreline({"name": "Lake Erie", "kind": "lake", "wikidata": "Q5492", "area_km2": 26000}, SHORE)
    assert SH.shoreline_slugs(WATERS, SHORE) == {"atlantic-ocean-fl", "gulf-of-america-fl", "north-atlantic-ocean-fl"}


def _stretch(lat=26.1, lon=-80.08, open_m=None, slug="atlantic-ocean-fl"):
    shore = SHORE if open_m is None else {**SHORE, "ocean_open_m": open_m}
    c = {"key": "pt-1", "permit": None, "outfall": None, "water_slug": slug, "lat": lat, "lon": lon,
         "sources": ["event-point"], "state": "FL", "model": "shoreline"}
    return R.shoreline_record(c, WATERS, shore, LAND)


def test_an_ocean_report_gets_a_stretch_of_the_open_coast_each_way():
    r = _stretch()
    assert r["error"] is None and r["cut_reason"] == "shoreline" and r["ocean"] is True and r["outline"] == "census_ocean"
    assert [s["km_end"] for s in r["segments"]] == [pytest.approx(20, abs=0.05)] * 2
    assert [s["cut_reason"] for s in r["stops"]] == ["shoreline_limit", "shoreline_limit"]
    assert r["waters"][0] == "atlantic-ocean-fl" and r["states"] == ["FL"] and r["river"] == "Atlantic Ocean"
    lons = [x for s in r["segments"] for x, _ in s["coords"]]
    assert min(lons) > -80.106 and max(lons) < -80.09            # along the open coast, never into the lagoon
    lats = sorted(s["coords"][-1][1] for s in r["segments"])
    assert lats[0] < 26.0 < lats[1]                              # across the inlet's mouth


def test_without_the_opening_the_walk_would_turn_into_the_lagoon_behind_the_inlet():
    lons = [x for s in _stretch(open_m=0)["segments"] for x, _ in s["coords"]]
    assert min(lons) < -80.11


def test_the_ocean_records_own_outline_is_never_walked_and_needs_a_point():
    waters = copy.deepcopy(WATERS)
    waters["atlantic-ocean-fl"]["geometry"] = mapping(box(-80.0, 25.0, -70.0, 30.0))     # the ocean, not the shore
    g, src = R.lake_outline("atlantic-ocean-fl", waters, LAND, (-80.08, 26.1), SHORE)
    assert src == "census_ocean" and g.bounds[0] < -80.09
    assert R.lake_outline("atlantic-ocean-fl", waters, LAND, None, SHORE) == (None, None)
    nopt = R.shoreline_record({"key": "k", "water_slug": "atlantic-ocean-fl", "lat": None, "lon": None}, waters, SHORE, LAND)
    assert nopt["cut_reason"] == "no_trace" and nopt["error"] == "no point to start from"


def test_a_point_inland_gets_no_ocean_stretch_and_without_the_census_files_none_this_run(monkeypatch):
    far = _stretch(lat=26.1, lon=-80.2)                # 10 km inland: no shore within snap_km
    assert far["cut_reason"] == "no_trace" and "no shore of the water" in far["error"]
    R._OCEAN.clear()
    away = _stretch(lat=26.1, lon=-80.6)               # no state waters at all near the point
    assert away["error"] == "no coastal waters of the state near the point"
    R._OCEAN.clear()
    monkeypatch.setattr(R, "tiger_states", lambda: (_ for _ in ()).throw(OSError("offline")))
    off = _stretch()
    assert off["cut_reason"] == "no_trace" and off["error"] == "no coastal waters of the state near the point"


def test_the_rule_signature_includes_the_opening():
    assert R.shore_sig(SHORE) != R.shore_sig({**SHORE, "ocean_open_m": 500})


# ---------------------------------------------------------------- status and export

def _build(records, reaches):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "fl-test.json").write_text(json.dumps({"source_id": "fl-test", "ok": True, "last_ok_at": NOW.isoformat(),
                                                  "meta": {}, "records": records}))
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    saved = S._STATES
    S._STATES = {"FL"}
    try:
        return S.build(now=NOW, write=False, events_dir=tmp, waters=copy.deepcopy(WATERS), outfalls=[], registry={},
                       reaches=copy.deepcopy(reaches), flows=({}, {}), discharger_towns={}, discharger_waters={},
                       rules={**RULES, "live_states": ["FL"]})
    finally:
        S._STATES = saved
        S._SHORE_REACHES.clear()


def _ev(rid, **kw):
    kw.setdefault("event_type", "sso")
    kw.setdefault("status", "ongoing")
    kw.setdefault("started_at", (NOW - 2 * H).isoformat())
    return event(source_id="fl-test", source_record_id=rid, **kw)


def test_an_ocean_report_with_no_stretch_yet_is_listed_never_fills_and_asks_for_one():
    st, _ = _build([_ev("1", waterbody_text="Atlantic Ocean", lat=26.1, lon=-80.08)], {})
    w = st["waters"]["atlantic-ocean-fl"]
    assert w["events"] == ["fl-test:1"] and w["fill"] is False and w["stretch_model"] == "shoreline"
    assert w["status_basis"] == S.OCEAN_STATUS_BASIS
    assert [r["placement"] for r in w["reasons"]] == ["ocean_shore_unmodeled"]
    assert "ocean shore: stretch not modeled" in w["reasons"][0]["short"]
    need = [n for n in st["needs_reach"] if n["event_id"] == "fl-test:1"]
    assert need and need[0]["model"] == "shoreline" and need[0]["water_slug"] == "atlantic-ocean-fl"


def test_a_gulf_of_mexico_report_is_the_gulf_records_and_colours_its_stretch():
    r = _stretch(slug="gulf-of-america-fl")
    import hashlib
    key = "pt-" + hashlib.sha1(b"fl-test:2").hexdigest()[:12]
    r = {**r, "key": key, "event_ids": ["fl-test:2"]}
    waters = copy.deepcopy(WATERS)
    S.apply_water_aliases(waters, S.DATA_DIR / S.WATER_ALIASES_FILE)
    assert S.Resolver(waters, [], placement_rules={}).by_name("Gulf of Mexico", "FL", None, None)[0] == ["gulf-of-america-fl"]
    st, _ = _build([_ev("2", waterbody_text="Gulf Of America", lat=26.1, lon=-80.08)], {key: r})
    w = st["waters"]["gulf-of-america-fl"]
    assert w["fill"] is False and w["status"] in ("red", "yellow") and w["reaches"] == [key]
    assert "on a modeled shoreline stretch" in w["reasons"][0]["short"]


def test_the_export_words_an_ocean_stretch_as_the_ocean_shore():
    r = {**_stretch(), "outfall": None}
    a = {"event_id": "e1", "reach": "pt-1", "status": "red", "rule": "ongoing", "short": "s", "hours_since_start": 2}
    feats = X.shore_event_features(a, r, {}, {})
    seg = [f for f in feats if f["properties"]["feature"] == "segment"]
    stops = [f for f in feats if f["properties"]["feature"] == "stop"]
    assert seg and "Atlantic Ocean shore at the reported location" in seg[0]["properties"]["label"]
    assert "ocean beaches" in seg[0]["properties"]["label"] and "Great Lakes" not in seg[0]["properties"]["label"]
    assert all("ocean beaches" in f["properties"]["label"] for f in stops)
    props = X.shore_path_props(r)
    assert props["ocean"] is True and all("Great Lakes" not in s["label"] for s in props["stops"])
    lake = X.shore_path_props({**r, "ocean": False})
    assert "Great Lakes" in lake["stops"][0]["label"] and "ocean" not in lake


# ---------------------------------------------------------------- the registry's ties and the names file

def _matcher():
    from shapely.geometry import Polygon  # noqa: F401
    m = SimpleNamespace(waters=WATERS, states=SimpleNamespace(shapes={"FL": FL_LAND}))
    return m


@pytest.mark.parametrize("lat,lon,kept,word", [
    (26.1, -80.06, True, "offshore"),        # EPA's point in the ocean, 3.9 km off the shore
    (26.1, -80.11, True, "inland"),          # a plant's own point 1 km inland
    (26.1, -80.30, False, "inland"),         # 20 km inland: not this ocean's outfall point
])
def test_an_outfall_on_the_ocean_is_tied_by_its_point_near_the_coast(lat, lon, kept, word):
    ok, why = OW.Matcher.ocean_evidence(_matcher(), "atlantic-ocean-fl", {"lat": lat, "lon": lon, "state": "FL"})
    assert ok is kept and word in why and "reach.shoreline.oceans" in why
    assert ("held until" in why) is (not kept)
    assert OW.Matcher.ocean_evidence(_matcher(), "indian-river-lagoon-fl", {"lat": lat, "lon": lon}) is None
    no_pt = OW.Matcher.ocean_evidence(_matcher(), "atlantic-ocean-fl", {"lat": None, "lon": None})
    assert no_pt[0] is False


def test_the_names_pass_reads_an_ocean_with_a_record_as_that_water():
    waters = copy.deepcopy(WATERS)
    S.apply_water_aliases(waters, S.DATA_DIR / S.WATER_ALIASES_FILE)
    r = S.Resolver(waters, [], placement_rules={})
    assert N.ocean_record_named(r, "Gulf of Mexico", "FL") and N.ocean_record_named(r, "Atlantic Ocean", "FL")
    assert not N.ocean_record_named(r, "Atlantic Ocean", "VA")             # Virginia's is not an ocean shore water
    targets, done, skipped = N.collect_name_targets("FL", [{"name": "Gulf of Mexico", "reports": 9, "points": []}], r, waters)
    assert not skipped and [s for _, s in done] == [["gulf-of-america-fl"]]
    _, _, skipped = N.collect_name_targets("VA", [{"name": "Atlantic Ocean", "reports": 1, "points": []}], r, waters)
    assert list(skipped.values()) == [N.OPEN_SEA]
