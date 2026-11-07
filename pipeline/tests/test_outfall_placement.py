"""Placement by the outfalls a report names (build/status.py, 2026-11-03): the CT DEEP dashboard's Greater New
Haven rows name their outfalls only in a per-outfall volume string; each named outfall is joined to the outfall
registry by permit + outfall id (step 1, with the outfall's own point as the last resort), and a report whose
outfalls reach several waters is one record placed on each of them, each outfall's cached reach carrying its own
water (step 2).
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
PERMIT = "CT0100999"


def w(slug, name, kind, coords, towns=("New Haven",)):
    geom = {"type": "LineString", "coordinates": coords}
    xs, ys = [c[0] for c in coords], [c[1] for c in coords]
    return slug, {"slug": slug, "name": name, "kind": kind, "state": "CT", "towns": list(towns),
                  "bbox": [min(xs), min(ys), max(xs), max(ys)], "geometry": geom}


WATERS = dict([
    w("test-river-ct", "Test River", "river", [[-72.0, 41.3], [-71.9, 41.3]]),
    w("mill-river-ct", "Mill River", "river", [[-71.8, 41.3], [-71.7, 41.3]]),
    w("bruce-brook-ct", "Bruce Brook", "stream", [[-71.6, 41.3], [-71.59, 41.3]]),
])


def row(outfall, slug=None, receiving="", lat=None, lon=None, match="geometry"):
    return {"npdes_permit": PERMIT, "outfall": outfall, "state": "CT", "city": "NEW HAVEN", "water_slug": slug,
            "match": match if slug else "none", "distance_m": 10 if slug else None,
            "receiving_water_echo": receiving, "lat": lat, "lon": lon, "_file": "data/outfalls-new-england.json"}


ROWS = [row("003", receiving="Test River", lat=41.3005, lon=-71.95),       # no slug: its receiving water by name
        row("004", receiving="Test River", lat=41.3005, lon=-71.96),
        row("009", "mill-river-ct", "Mill River", 41.3001, -71.75),
        row("020", lat=41.3009, lon=-71.95),                                 # no water listed: 100 m from Test River
        row("021", receiving="Johnsons Creek", lat=41.3009, lon=-71.595),   # 100 m from Bruce Brook, another name
        row("022", lat=41.3020, lon=-71.95),                                 # 222 m: too far for the point
        row("153", "mill-river-ct", "Mill River", 41.3001, -71.76)]


@pytest.fixture(autouse=True)
def _all_steps():
    saved = dict(S.PLACE_STEPS)
    S.PLACE_STEPS.update(registry=True, relaxed_guard=True, no_receiving_water=True, outfall_ids=True,
                         multi_outfall=True)
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    S._STATES = {"CT", "MA"}
    yield
    S.PLACE_STEPS.update(saved)
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    S._STATES = None


def ev(rid="1", **kw):
    kw.setdefault("event_type", "cso")
    kw.setdefault("status", "ended")
    kw.setdefault("npdes_permit", PERMIT)
    return event(source_id=kw.pop("source_id", "ct-deep"), source_record_id=rid, **kw)


def gnh(rid, volume, **kw):
    """A 2026 dashboard row: no outfall, no water, the outfalls only in the final volume (which the ingester
    also writes as volume_text)."""
    return ev(rid, volume_text=volume, raw={"Report Type": "CSO - Greater New Haven 5 Day Report",
                                           "Final Volume": volume, "CSO Group Name": None, "Receiving Waterbody": None},
              **kw)


def resolver(rows=ROWS, all_waters=False, dis_waters=None):
    """all_waters: data/rules.json placement.no_outfall_all_waters."""
    return S.Resolver(WATERS, list(rows), {}, dis_waters or {}, {"no_outfall_all_waters": all_waters})


# ---------------------------------------------------------------- what a report names

@pytest.mark.parametrize("text,ids", [
    ("003-0.197 MG 2005 to 2145004-0.023 MG 2015 to 2040005-0.128 MG 1950 to", ["003", "004", "005"]),
    ("015-No release016-No release", ["015", "016"]),
    ("021-0.991 MG 1405 to 1650024-No data available 025-No release", ["021", "024", "025"]),
    ("0.7 in Rain021-No release024-No release025-No release", ["021", "024", "025"]),
    ("015- no release016- no release", ["015", "016"]),
    ("500 - 1,000 gallons", []), ("20,001 - 50,000 gallons", []), ("0.004 MGD", []), ("45273", []), (None, []),
])
def test_outfall_numbers_of_a_per_outfall_volume_string(text, ids):
    assert S.outfall_ids_from_volume(text) == ids


def test_outfall_ids_a_report_names():
    assert S.outfall_ids_of(gnh("a", "015-0.279 MG 1950 to 2050016-0.384 MG 1535 to 2125")) == \
        (["015", "016"], "its per-outfall volume text")
    assert S.outfall_ids_of(ev("b", outfall_name="WANN 153"))[0] == ["153"]          # Bridgeport East's label
    assert S.outfall_ids_of(ev("c", outfall_id="SPR010"))[0] == ["SPR010"]
    plant = ev("d", event_type="plant_bypass", raw={"Report Type": "002-1 - Norwalk 5 Day Report"})
    assert S.outfall_ids_of(plant) == (["002-1"], "its report type")
    # an SSO's volume is not read for outfalls, and neither is a binned range
    assert S.outfall_ids_of(ev("e", event_type="sso", raw={"Final Volume": "015-No release"})) == ([], "")
    assert S.outfall_ids_of(ev("f", raw={"Final Volume": "501 - 1,000 gallons"})) == ([], "")


# ---------------------------------------------------------------- step 1: by outfall id

def test_a_report_naming_its_outfalls_only_in_its_volume_is_placed_by_them():
    pl = resolver().resolve(gnh("1", "003-0.197 MG 2005 to 2145004-0.023 MG 2015 to 2040"))
    assert pl["water_slugs"] == ["test-river-ct"] and pl["water_match"] == "outfall_registry"
    assert pl["note"].startswith("placed by outfalls 003, 004 of permit CT0100999 (outfall registry): "
                                 "003, 004 to Test River (its receiving water 'Test River' by name)")
    assert "from its per-outfall volume text (data/outfalls-new-england.json)" in pl["note"]
    assert pl["outfalls"] == [{"outfall": "003", "water_slug": "test-river-ct"},
                              {"outfall": "004", "water_slug": "test-river-ct"}]
    # without the step the same report stays unplaced (the permit's outfalls reach several waters)
    S.PLACE_STEPS["outfall_ids"] = False
    S._GEOM_CACHE.clear()
    pl = resolver().resolve(gnh("1", "003-0.197 MG 2005 to 2145004-0.023 MG 2015 to 2040"))
    assert pl["water_slugs"] == [] and "registry outfalls discharge to" in pl["unplaced_reason"]


def test_a_report_with_no_outfall_and_no_water_stays_unplaced():
    pl = resolver().resolve(gnh("2", "0.0 MGD"))
    assert pl["water_slugs"] == [] and "registry outfalls discharge to" in pl["unplaced_reason"]


def test_a_registry_outfall_with_no_water_takes_the_water_at_its_point_only_when_close_and_not_contradicted():
    r = resolver()
    by = {x["outfall"]: x for x in ROWS}
    assert r.row_water({**by["020"]}) == ("test-river-ct", "the water at its point (100 m)")
    slug, how = r.row_water(by["021"])                          # Bruce Brook is not Johnson's Creek
    assert slug is None and "the water at its point (Bruce Brook, 100 m) is not its receiving water" in how
    assert r.row_water(by["022"]) == (None, "no receiving water listed")          # 222 m: beyond OUTFALL_POINT_M
    pl = r.resolve(ev("3", outfall_name="020"))
    assert pl["water_slugs"] == ["test-river-ct"] and "the water at its point (100 m)" in pl["note"]
    pl = r.resolve(ev("4", outfall_name="021"))
    assert pl["water_slugs"] == [] and "has no mapped water" in pl["unplaced_reason"]


def test_names_disagree():
    assert S.names_disagree("Johnson's Creek", "Bruce Brook") == "no name word in common"
    assert S.names_disagree("South Branch Park River Conduit", "North Branch Park River") == "opposite compass words"
    assert S.names_disagree("North Branch Park River Conduit", "North Branch Park River") is None
    assert S.names_disagree("", "Test River") is None


def test_a_water_text_no_record_matches_still_lets_the_outfall_place_the_report():
    r = resolver()
    pl = r.resolve(ev("5", outfall_name="WANN 153", waterbody_text="Nowhere Creek"))
    assert pl["water_slugs"] == ["mill-river-ct"] and pl["note"].startswith("placed by outfall 153 of permit")
    # a text that names no water is not overruled by the outfall
    pl = r.resolve(ev("6", outfall_name="WANN 153", waterbody_text="storm drain"))
    assert pl["water_slugs"] == [] and pl["no_receiving_water"]


def test_a_plant_outfall_002_1_is_not_cso_outfall_021():
    rows = ROWS + [row("021", "mill-river-ct", "Mill River", 41.3001, -71.75)]
    plant = ev("7", event_type="plant_bypass", raw={"Report Type": "002-1 - Test 5 Day Report"})
    assert resolver(rows).outfall_rows(PERMIT, "002-1") == []
    assert resolver(rows).resolve(plant)["water_slugs"] == []


# ---------------------------------------------------------------- step 2: several waters

def test_outfalls_on_several_waters_place_one_record_on_each():
    e = gnh("8", "003-0.2 MG 1405 to 1650009-No data")
    pl = resolver().resolve(e)
    assert pl["water_slugs"] == ["test-river-ct", "mill-river-ct"] and pl["water_match"] == "outfall_registry"
    assert "one record on each of the 2 waters its outfalls reach" in pl["note"]
    assert "003 to Test River" in pl["note"] and "009 to Mill River" in pl["note"]
    S.PLACE_STEPS["multi_outfall"] = False
    pl = resolver().resolve(e)
    assert pl["water_slugs"] == [] and "discharge to 2 waters" in pl["unplaced_reason"]


def _build(records, reaches=None):
    tmp = Path(tempfile.mkdtemp())
    (tmp / "ct-deep.json").write_text(json.dumps({"source_id": "ct-deep", "ok": True, "last_ok_at": NOW.isoformat(),
                                                  "meta": {}, "records": records}))
    st, _ = S.build(now=NOW, write=False, events_dir=tmp, waters=dict(WATERS), outfalls=list(ROWS), registry={},
                    reaches=reaches or {}, flows=({}, {}), discharger_towns={}, discharger_waters={})
    return st


def _reach(outfall, slug, x0, segments=True):
    return {"key": f"{PERMIT}-{outfall}", "permit": PERMIT, "outfall": outfall, "water_slug": slug, "lat": 41.3,
            "lon": x0, "river": WATERS[slug]["name"], "cut_reason": "cap_km" if segments else "tidal_at_outfall",
            "length_km": 4.0 if segments else 0.0,
            "segments": [{"comid": 1, "km_start": 0.0, "km_end": 4.0, "totdasqkm": 500, "qe_ma": 300, "slope": 1e-3,
                          "gnis_name": WATERS[slug]["name"], "coords": [[x0, 41.3], [x0 + 0.05, 41.3]]}]
            if segments else []}


def test_build_counts_the_record_once_and_lists_it_on_each_water():
    e = gnh("9", "003-0.2 MG 1405 to 1650009-No data", started_at=(NOW - 3 * H).isoformat(),
            ended_at=(NOW - 2 * H).isoformat())
    st = _build([e])
    assert st["counts"]["placed"] == 1 and st["counts"]["unplaced"] == 0
    for slug in ("test-river-ct", "mill-river-ct"):
        assert st["waters"][slug]["events"] == ["ct-deep:9"]
        assert [r["event_id"] for r in st["waters"][slug]["reasons"]] == ["ct-deep:9"]
        assert st["waters"][slug]["reasons"][0]["placement"] == "unmodeled"       # no cached reach


def test_each_outfalls_reach_carries_its_own_water():
    e = gnh("10", "003-0.2 MG 1405 to 1650009-No data", status="ongoing", started_at=(NOW - 2 * H).isoformat())
    reaches = {f"{PERMIT}-003": _reach("003", "test-river-ct", -71.97),
               f"{PERMIT}-009": _reach("009", "mill-river-ct", -71.77, segments=False)}
    st = _build([e], reaches)
    p = st["placements"]["ct-deep:10"]
    assert p["reach"] == f"{PERMIT}-003" and p["reaches"] == [f"{PERMIT}-003", f"{PERMIT}-009"]
    river = st["waters"]["test-river-ct"]
    assert river["reaches"] == [f"{PERMIT}-003"] and [r["placement"] for r in river["reasons"]] == ["reach"]
    assert st["reaches"][f"{PERMIT}-003"]["status"] == "red"
    mill = st["waters"]["mill-river-ct"]                 # its outfall's reach is cut at the outfall: tidal
    assert [r["placement"] for r in mill["reasons"]] == ["tidal"]


# ---------------------------------------------------------------- follow-up 1: reports of no release

def test_a_report_of_no_release_at_every_outfall_is_kept_but_placed_on_no_water():
    pl = resolver().resolve(gnh("20", "015-No release016-No release"))
    assert pl["water_slugs"] == [] and pl["no_release"] is True and "unplaced_reason" not in pl
    assert pl["no_receiving_water"] == "the operator reported no release (at every outfall it lists: 015, 016)"
    # after a rainfall note, and a whole-text statement, even with a water named
    assert resolver().resolve(gnh("21", "0.7 in Rain021-No release024-No release"))["no_release"]
    pl = resolver().resolve(ev("22", event_type="sso", volume_text="0 Did not overflow", waterbody_text="Test River"))
    assert pl["water_slugs"] == [] and pl["no_receiving_water"] == "the operator reported no release ('0 Did not overflow')"
    assert not resolver().resolve(gnh("23", "0.0 MGD")).get("no_release")      # a zero rate is not a statement


def test_a_mixed_report_is_placed_on_its_released_outfalls_only():
    pl = resolver().resolve(gnh("24", "003-No release009-0.2 MG 1405 to 1650"))
    assert pl["water_slugs"] == ["mill-river-ct"] and "no release at 003" in pl["note"]
    pl = resolver().resolve(gnh("25", "003-No release009-No data"))              # no data is not a no release
    assert pl["water_slugs"] == ["mill-river-ct"]


def test_a_no_release_report_colours_nothing_and_gets_no_reach():
    e = ev("26", status="ended", outfall_id="003", waterbody_text="Test River", volume_text="No release",
           started_at=(NOW - 3 * H).isoformat(), ended_at=(NOW - 2 * H).isoformat())
    st = _build([e], {f"{PERMIT}-003": _reach("003", "test-river-ct", -71.97)})
    assert st["counts"]["no_release"] == 1 and st["counts"]["no_receiving_water"] == 1 and st["counts"]["placed"] == 0
    p = st["placements"]["ct-deep:26"]
    assert "reach" not in p and p["no_release"] and st["reaches"] == {}
    assert all("ct-deep:26" not in w["events"] for w in st["waters"].values())
    assert st["sources"]["ct-deep"]["placement"]["no_release"] == 1


# ---------------------------------------------------------------- follow-up 2: a person's name as the water
# (a synthetic name: no real name is written in a committed file)

SYNTHETIC = "Quentin Marbleworth"


def test_a_persons_name_in_the_receiving_water_field_is_redacted_for_the_export():
    from build import redact as R
    rec = ev("27", event_type="plant_bypass", waterbody_text=SYNTHETIC,
             raw={"RECEIVING_WATER_BODY": SYNTHETIC.upper(), "COMMENTS": "Plant flooded",
                  "_dww_note": [f"receiving water '{SYNTHETIC}' has no matching water record"]})
    water = ev("28", event_type="sso", waterbody_text="Mill Brook", raw={"Receiving Waterbody": "Mill Brook"})
    site = ev("29", event_type="hab_advisory", status="advisory_active", waterbody_text=SYNTHETIC)
    out = {e["event_id"]: e for e in R.redact_events([rec, water])}
    red = out["ct-deep:27"]
    assert red["waterbody_text"] == R.REDACTED and red["raw"]["RECEIVING_WATER_BODY"] == R.REDACTED
    assert "Marbleworth" not in json.dumps(red)
    assert out["ct-deep:28"]["waterbody_text"] == "Mill Brook"
    assert R.redact_events([site, water])[0]["waterbody_text"] == SYNTHETIC   # an advisory names its site
    # a name whose given name is not on the common list: no word of it is known to the lexicon
    odd = ev("30", event_type="sso", waterbody_text="Zorvath Quellbrin")
    assert R.redact_events([odd, water])[0]["waterbody_text"] == R.REDACTED
    assert R.person_shaped(SYNTHETIC) and not R.person_shaped("Mill Brook") and not R.person_shaped("Herbert Run")


def test_placement_reads_a_person_shaped_or_redacted_water_text_as_no_water_name():
    from build import redact as R
    for text in (SYNTHETIC, R.REDACTED):
        pl = resolver().resolve(ev("31", outfall_name="WANN 153", waterbody_text=text))
        assert pl["water_slugs"] == ["mill-river-ct"] and "holds no water name" in pl["note"]
        assert "Marbleworth" not in json.dumps(pl) and "no_receiving_water" not in pl


# ---------------------------------------------------------------- follow-up 3: no outfall stated

def test_a_cso_report_naming_no_outfall_is_shown_on_every_water_its_permit_reaches():
    pl = resolver(all_waters=True).resolve(gnh("32", "0.0 MGD"))
    assert pl["water_slugs"] == ["test-river-ct", "mill-river-ct"] and pl["water_match"] == "inferred"
    assert pl["note"].startswith(S.NO_OUTFALL_NOTE + " (2 waters from the 7 registry outfalls of CT0100999; "
                                 "2 of them have no water record")
    assert {o["water_slug"] for o in pl["outfalls"]} == {"test-river-ct", "mill-river-ct"}
    assert resolver(all_waters=False).resolve(gnh("32", "0.0 MGD"))["water_slugs"] == []
    # an SSO is not a discharge at the permit's CSO outfalls, and a named but unlisted outfall is not "not stated"
    assert resolver(all_waters=True).resolve(ev("33", event_type="sso"))["water_slugs"] == []
    assert resolver(all_waters=True).resolve(ev("34", outfall_name="099"))["water_slugs"] == []


def test_a_permit_the_registry_lacks_uses_every_receiving_water_the_operator_lists_for_a_cso_only():
    dw = {"ct-x": {"id": "ct-x", "state": "CT", "names": ["Test River", "Mill River"], "slugs": []}}
    cso = ev("36", npdes_permit="CT0109999", discharger_id="ct-x")
    pl = resolver(all_waters=True, dis_waters=dw).resolve(cso)
    assert pl["water_slugs"] == ["test-river-ct", "mill-river-ct"]
    assert pl["note"].startswith("outfall not stated in the report; shown on every water")
    assert resolver(all_waters=False, dis_waters=dw).resolve(cso)["water_slugs"] == []
    # a plant bypass leaves by the plant's own outfall, not by every water the operator lists (review 2026-11-03 P3-1)
    plant = ev("35", event_type="plant_bypass", npdes_permit="CT0109999", discharger_id="ct-x",
               raw={"Report Type": "002-1 - Test 5 Day Report"})
    pl = resolver(all_waters=True, dis_waters=dw).resolve(plant)
    assert pl["water_slugs"] == [] and "the operator lists 2 receiving waters" in pl["unplaced_reason"]


def test_the_switch_is_on_in_data_rules_json_with_a_public_basis():
    rules = json.loads((S.DATA_DIR / "rules.json").read_text())
    p = rules["placement"]
    assert p["no_outfall_all_waters"] is True and p["no_outfall_all_waters_basis"].count(". ") == 0
    assert S.Resolver(WATERS, ROWS, {}, {}, p).no_outfall_all_waters
