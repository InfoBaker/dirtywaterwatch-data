"""Placement of 2026-11-03 (build/status.py Resolver): reports that name no water placed through the
outfall registry (step 1), named matches farther than 2 km kept within the water's own reach (step 2),
and reports that name no receiving water counted apart from the unplaced (step 4).
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

from build import status as S  # noqa: E402
from common import event  # noqa: E402

NOW = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
H = timedelta(hours=1)
LINE = {"type": "LineString", "coordinates": [[-72.0, 42.0], [-71.9, 42.0]]}          # 8.3 km east-west
SHORT = {"type": "LineString", "coordinates": [[-71.5, 42.3], [-71.49, 42.3]]}        # 0.8 km
POND = {"type": "Polygon", "coordinates": [[[-72.0, 42.1], [-71.99, 42.1], [-71.99, 42.11], [-72.0, 42.1]]]}


def w(slug, name, kind, geom, towns=(), state="MA"):
    from shapely.geometry import shape
    b = shape(geom).bounds
    return slug, {"slug": slug, "name": name, "kind": kind, "state": state, "towns": list(towns),
                  "bbox": list(b), "geometry": geom}


WATERS = dict([
    w("test-river-ma", "Test River", "river", LINE, ["Springfield"]),
    w("short-brook-ma", "Short Brook", "stream", SHORT, ["Worcester"]),
    w("other-pond-ma", "Other Pond", "pond", POND, ["Ludlow"]),
    w("mill-river-a-ma", "Mill River", "river", {"type": "LineString", "coordinates": [[-71.0, 42.5], [-70.9, 42.5]]},
      ["Andover"]),
    w("mill-river-b-ma", "Mill River", "river", {"type": "LineString", "coordinates": [[-71.0, 42.53], [-70.9, 42.53]]},
      ["Boxford"]),
    w("side-pond-ma", "Side Pond", "pond", {"type": "Polygon", "coordinates": [[[-71.92, 42.045], [-71.91, 42.045],
                                                                                [-71.91, 42.055], [-71.92, 42.045]]]},
      ["Springfield"]),
])


@pytest.fixture(autouse=True)
def _all_steps():
    saved = dict(S.PLACE_STEPS)
    S.PLACE_STEPS.update(registry=True, relaxed_guard=True, no_receiving_water=True)
    S._GEOM_CACHE.clear()
    S._STATES = {"MA", "CT", "VT"}
    yield
    S.PLACE_STEPS.update(saved)
    S._GEOM_CACHE.clear()
    S._STATES = None


def ev(rid="1", **kw):
    kw.setdefault("event_type", "cso")
    kw.setdefault("status", "ended")
    return event(source_id=kw.pop("source_id", "ma-test"), source_record_id=rid, **kw)


def resolver(outfalls=(), towns=None, dis_waters=None, all_waters=False):
    """all_waters: data/rules.json placement.no_outfall_all_waters (on in the file; tests/test_outfall_placement.py)."""
    return S.Resolver(WATERS, list(outfalls), towns or {}, dis_waters or {}, {"no_outfall_all_waters": all_waters})


# ---------------------------------------------------------------- step 1: the outfall registry

def test_no_text_with_an_outfall_number_takes_the_registry_outfalls_water():
    r = resolver([{"npdes_permit": "MA0100001", "outfall": "017", "state": "MA", "water_slug": "test-river-ma",
                   "match": "geometry+name", "distance_m": 12, "_file": "data/outfalls-ne.json"},
                  {"npdes_permit": "MA0100001", "outfall": "018", "state": "MA", "water_slug": "other-pond-ma",
                   "match": "geometry", "_file": "data/outfalls-ne.json"}])
    pl = r.resolve(ev(npdes_permit="MA0100001", outfall_name="017"))       # the number given as the outfall name
    assert pl["water_slugs"] == ["test-river-ma"] and pl["water_match"] == "outfall_registry"
    assert pl["note"].startswith("placed by outfall 017 of permit MA0100001 (outfall registry): 017 to Test River")
    assert "from its outfall name '017' (data/outfalls-ne.json)" in pl["note"]
    # a street address is not an outfall number, and the permit's outfalls reach two waters: unplaced, with why
    pl = r.resolve(ev("2", npdes_permit="MA0100001", outfall_name="Manhole, 205 Main St"))
    assert pl["water_slugs"] == [] and "registry outfalls discharge to 2 waters" in pl["unplaced_reason"]


def test_registry_outfall_with_no_slug_resolves_its_receiving_water_by_name_at_its_point():
    r = resolver([{"npdes_permit": "MA0100002", "outfall": "033", "state": "MA", "water_slug": None,
                   "receiving_water_echo": "Short Brook", "lat": 42.301, "lon": -71.495, "_file": "x"}])
    pl = r.resolve(ev(npdes_permit="MA0100002", outfall_name="33 HUNT"))
    assert pl["water_slugs"] == ["short-brook-ma"] and "its receiving water 'Short Brook' by name" in pl["note"]


def test_registry_name_only_slug_must_carry_the_receiving_waters_name():
    r = resolver([{"npdes_permit": "MA0100003", "outfall": "087", "state": "MA", "water_slug": "other-pond-ma",
                   "match": "name_only", "receiving_water_echo": "Short Brook", "lat": 42.301, "lon": -71.495}])
    # registry first (2026-11-03): an outfall_id and an outfall name are both read through row_water, whose checks
    # apply to a row the registry pass has not matched (no water_matched_by)
    assert r.resolve(ev(npdes_permit="MA0100003", outfall_id="087"))["water_slugs"] == ["short-brook-ma"]
    pl = r.resolve(ev("2", npdes_permit="MA0100003", outfall_name="087"))
    assert pl["water_slugs"] == ["short-brook-ma"]
    S.PLACE_STEPS["registry_first"] = False             # before: by_outfall took the row's slug as it stood
    try:
        r = resolver([{"npdes_permit": "MA0100003", "outfall": "087", "state": "MA", "water_slug": "other-pond-ma",
                       "match": "name_only", "receiving_water_echo": "Short Brook", "lat": 42.301, "lon": -71.495}])
        assert r.resolve(ev(npdes_permit="MA0100003", outfall_id="087"))["water_slugs"] == ["other-pond-ma"]
    finally:
        S.PLACE_STEPS["registry_first"] = True


def test_permit_with_one_water_for_every_outfall_places_a_report_naming_none():
    rows = [{"npdes_permit": "MA0100004", "outfall": o, "state": "MA", "water_slug": "test-river-ma",
             "match": "geometry+name", "_file": "data/outfalls-ne.json"} for o in ("001", "002")]
    pl = resolver(rows).resolve(ev(npdes_permit="MA0100004", event_type="sso"))
    assert pl["water_slugs"] == ["test-river-ma"] and pl["water_match"] == "inferred"
    assert "every listed outfall of MA0100004 (2)" in pl["note"]


def test_dischargers_single_receiving_water_is_the_weaker_fallback():
    dw = {"ma-one": {"id": "ma-one", "state": "MA", "names": ["Test River"], "slugs": []},
          "ma-two": {"id": "ma-two", "state": "MA", "names": ["Test River", "Other Pond"], "slugs": []}}
    r = resolver(dis_waters=dw)
    pl = r.resolve(ev(discharger_id="ma-one", event_type="plant_bypass"))
    assert pl["water_slugs"] == ["test-river-ma"] and pl["water_match"] == "inferred"
    assert "water from data/dischargers.json: the operator's single listed receiving water" in pl["note"]
    pl = r.resolve(ev("2", discharger_id="ma-two"))
    assert pl["water_slugs"] == [] and "lists 2 receiving waters" in pl["unplaced_reason"]


def test_a_report_that_says_it_reached_no_water_is_never_placed_through_the_registry():
    dw = {"ma-one": {"id": "ma-one", "state": "MA", "names": ["Test River"], "slugs": []}}
    pl = resolver(dis_waters=dw).resolve(ev(discharger_id="ma-one", event_type="sso",
                                            raw={"Reach Waterbody": "No"}))
    assert pl["water_slugs"] == [] and pl["no_receiving_water"].startswith("the report says the discharge did not reach")
    assert "unplaced_reason" not in pl


def test_outfall_group_label_names_its_water():
    r = resolver()
    pl = r.resolve(ev(npdes_permit="MA0100005", outfall_name="Test River CSOs: 021, 024, 025"))
    assert pl["water_slugs"] == ["test-river-ma"] and "outfall group" in pl["note"]
    assert S.outfall_ids_from_name("Mill River CSOs: 009,011,012") == ["009", "011", "012"]
    assert S.outfall_ids_from_name("Manhole, 205 Bostwick Ave") == []


# ---------------------------------------------------------------- step 2: the water's own reach

def test_named_river_kept_within_its_extent_plus_margin_short_stream_not():
    r = resolver()
    pl = r.resolve(ev(waterbody_text="Test River", lat=42.05, lon=-71.95))            # 5.6 km, extent 8.3 km
    assert pl["water_slugs"] == ["test-river-ma"] and pl["water_match"] == "name"
    pl = r.resolve(ev("2", waterbody_text="Short Brook", lat=42.33, lon=-71.495))     # 3.3 km, extent 0.8 km
    assert pl["water_slugs"] == [] and pl["unplaced_reason"].startswith("name match too far (3.")


def test_lakes_allow_their_outline_plus_3_km():
    r = resolver()
    assert r.resolve(ev(waterbody_text="Other Pond", lat=42.13, lon=-71.995))["water_slugs"] == ["other-pond-ma"]
    assert r.resolve(ev("2", waterbody_text="Other Pond", lat=42.15, lon=-71.995))["water_slugs"] == []


def test_a_far_named_match_is_set_aside_when_the_reports_town_is_not_on_the_water():
    r = resolver(towns={"MA0100006": ["Holyoke"]})
    pl = r.resolve(ev(waterbody_text="Test River", npdes_permit="MA0100006", lat=42.05, lon=-71.95))
    assert pl["water_slugs"] == [] and "the report's town (holyoke) is not among the water's towns" in pl["unplaced_reason"]
    r = resolver(towns={"MA0100006": ["Springfield"]})
    assert r.resolve(ev(waterbody_text="Test River", npdes_permit="MA0100006", lat=42.05, lon=-71.95))["water_slugs"] \
        == ["test-river-ma"]
    r = resolver(towns={"MA0100006": ["Hampden County"]})                       # a county is not a town
    assert r.resolve(ev(waterbody_text="Test River", npdes_permit="MA0100006", lat=42.05, lon=-71.95))["water_slugs"] \
        == ["test-river-ma"]


def test_shared_name_beyond_2_km_goes_to_the_water_in_the_reports_town():
    r = resolver(towns={"MA0100007": ["Boxford"]})
    # 2.4 km from the Andover record, 5.8 km from the Boxford one: the report's town decides
    pl = r.resolve(ev(waterbody_text="Mill River", npdes_permit="MA0100007", lat=42.478, lon=-70.95))
    assert pl["water_slugs"] == ["mill-river-b-ma"]


def test_a_relaxed_name_match_gives_way_to_a_point_lying_on_another_water():
    r = resolver()
    pl = r.resolve(ev(waterbody_text="Test River", water_slugs=["test-river-ma"], water_match="name",
                      lat=42.049, lon=-71.912))                                  # on Side Pond, 5.4 km off the river
    assert pl["water_slugs"] == ["side-pond-ma"] and pl["water_match"] == "geometry"
    assert any("not used" in a["reason"] for a in pl["set_aside"])


def test_a_nearer_record_of_the_same_name_wins_over_a_far_one():
    waters = dict(WATERS)
    waters.update(dict([w("test-river-lower-ma", "Test River", "river",
                          {"type": "LineString", "coordinates": [[-71.9, 42.03], [-71.8, 42.03]]}, ["Palmer"])]))
    r = S.Resolver(waters, [], {}, {})
    pl = r.resolve(ev(waterbody_text="Test River", water_slugs=["test-river-ma"], water_match="name",
                      lat=42.04, lon=-71.85))
    assert pl["water_slugs"] == ["test-river-lower-ma"]


# ---------------------------------------------------------------- step 4: no receiving water

@pytest.mark.parametrize("text,expected", [
    ("N/A", True), ("N", True), ("A", True), ("None.", True), ("Select...", True), ("storm drain", True),
    ("Groundwater", True), ("Drainage ditch", True), ("Did not enter Waters of the State", True),
    ("Queen Ditch", False), ("Unnamed tributary", False), ("Atlantic Ocean", False), ("Intervale Wetlands", False),
    ("storm drain leading to L.I.S.", False), ("Near stormdrain that discharges (possibly) into Potapsco", False),
    ("Spill did enter catch basin / Eugene Pond", False), ("", False),
])
def test_texts_that_name_no_water(text, expected):
    assert bool(S.no_water_text(text)) is expected


def test_no_receiving_water_is_counted_apart_and_colours_nothing():
    a = ev("a", event_type="sso", waterbody_text="N/A", started_at=(NOW - H).isoformat(),
           ended_at=NOW.isoformat())
    b = ev("b", event_type="sso", waterbody_text="Nowhere Creek", started_at=(NOW - H).isoformat(),
           ended_at=NOW.isoformat())
    c = ev("c", event_type="beach_advisory", status="advisory_active", waterbody_text="N/A",
           started_at=(NOW - H).isoformat())
    d = ev("d", event_type="sso", waterbody_text="Small Pond Creek", started_at=(NOW - H).isoformat(),
           ended_at=NOW.isoformat())                             # "pond creek": a stem of no record
    e = ev("e", event_type="sso", waterbody_text="storm drain to Test", started_at=(NOW - H).isoformat(),
           raw={"REACH_WATER_BODY": "No"})
    tmp = Path(tempfile.mkdtemp())
    (tmp / "ma-test.json").write_text(json.dumps({"source_id": "ma-test", "ok": True, "last_ok_at": NOW.isoformat(),
                                                  "meta": {}, "records": [a, b, c, d, e]}))
    st, _ = S.build(now=NOW, write=False, events_dir=tmp, waters=dict(WATERS), outfalls=[], registry={},
                    reaches={}, flows=({}, {}), discharger_towns={}, discharger_waters={})
    assert st["counts"]["no_receiving_water"] == 2 and st["counts"]["unplaced"] == 3 and st["counts"]["no_release"] == 0
    assert st["no_receiving_water_events"] == ["ma-test:a", "ma-test:e"]
    assert "ma-test:a" not in st["unplaced_events"] and "ma-test:c" in st["unplaced_events"]
    assert st["placements"]["ma-test:a"]["no_receiving_water"] == "the report gives no receiving water ('N/A')"
    assert st["sources"]["ma-test"]["placement"] == {"placed": 0, "no_receiving_water": 2, "unplaced": 3, "no_release": 0}
    assert not st["waters"]
