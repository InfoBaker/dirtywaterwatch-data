"""Nebraska's go-live gates (2026-11-07): every one of Omaha's open combined sewer outfalls (permit NE0133680, EPA's
CSO inventory in data/outfalls-us.json) has a water record, the four on an 'Outfall channel to Missouri River' tied
to the Missouri River by scripts/ne_gate_ties.py. Data tests on the files as committed; no network.
Run from pipeline/: python -m pytest tests/test_ne_gates.py -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def _omaha_cso():
    rows = json.loads((DATA / "outfalls-us.json").read_text())["outfalls"]
    return {str(o["outfall"]): o for o in rows if o.get("npdes_permit") == "NE0133680"}


def _script():
    spec = importlib.util.spec_from_file_location("ne_gate_ties", ROOT / "scripts" / "ne_gate_ties.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_open_omaha_cso_outfall_has_a_water_record():
    from build import status as S
    waters = S.load_waters()
    rows = {k: o for k, o in _omaha_cso().items() if not str(o.get("outfall_status") or "").upper().startswith("CLS")}
    assert len(rows) == 25
    untied = sorted(k for k, o in rows.items() if not o.get("water_slug"))
    assert untied == []
    assert all(o["water_slug"] in waters for o in rows.values())


def test_the_outfall_channel_rows_go_to_the_missouri_by_the_text_not_to_a_channel():
    """'Outfall channel to Missouri River' names the water the channel carries the overflow to: the cloud ties of
    2026-11-07 read 'Outfall channel' as the water and left 105 to 108 without one, while 111 to 117 (the same text,
    nearer the river line) kept the Missouri River."""
    rows = _omaha_cso()
    channel = sorted(k for k, o in rows.items() if o.get("receiving_water_echo", "").rstrip(".") ==
                     "Outfall channel to Missouri River")
    assert channel == ["105", "106", "107", "108", "111", "112", "114", "115", "117"]
    assert {rows[k]["water_slug"] for k in channel} == {"missouri-river-ne"}
    for k in ("105", "106", "107", "108"):
        o = rows[k]
        assert o["receiving_water_override"]["water"] == "Missouri River"
        assert "Outfall channel to Missouri River" in o["receiving_water_override"]["basis"]
        assert o["water_matched_by"].startswith("scripts/ne_gate_ties.py")
        assert "no_water_reason" not in o and "replaced_match" not in o
        assert o["match"] == "name_only" and 500 <= o["distance_m"] <= 1100      # a centre line: the bank is nearer


def test_the_table_is_what_the_file_says():
    mod = _script()
    doc = json.loads((DATA / "outfalls-us.json").read_text())
    before = json.dumps(doc, sort_keys=True)
    from build import status as S
    assert mod.apply(doc, S.load_waters()) == []
    assert json.dumps(doc, sort_keys=True) == before


def test_a_row_whose_text_changed_is_not_tied_by_the_table():
    mod = _script()
    doc = {"outfalls": [{"npdes_permit": "NE0133680", "outfall": "105", "receiving_water_echo": "Cole Creek"}]}
    missing = mod.apply(doc, {"missouri-river-ne": {"name": "Missouri River", "kind": "river"}})
    assert "NE0133680/105" in missing
    assert "water_slug" not in doc["outfalls"][0]


def test_outfall_205r_keeps_epas_facility_point_aside_and_its_creek_by_the_text():
    """205R has no point in EPA's inventory: the facility's point it carried is outfall 107's, on the Missouri
    riverfront, 10.9 km from Little Papillion Creek. Kept as published, not used; tied by EPA's text."""
    o = _omaha_cso()["205R"]
    assert o["lat"] is None and o["lon"] is None
    assert (o["echo_lat"], o["echo_lon"]) == (41.27685, -95.92526) == (_omaha_cso()["107"]["lat"], _omaha_cso()["107"]["lon"])
    assert o["coords_from"] == "facility" and "not this outfall's place" in o["coords_problem"]
    assert o["water_slug"] == "little-papillion-creek-ne" and o["receiving_water_echo"] == "Little Papillion Creek"
    assert o["distance_m"] is None and o["match"] == "name_only"
    # the rain check and the reaches read no point for it (the other 24 outfalls are read)
    from ingest import rainfall as RF
    pts = RF.cso_outfalls(live={"NE"})
    assert len(pts) == 24 and "205R" not in {p["outfall"] for p in pts}


# ---------------------------------------------------------------- Beach Watch: no record on a river

YANKTON = {"OBJECTID": 9001, "StationID": "YAKLKBACT1", "StationName": "Lake Yankton (Cottonwood Lake) at Beach",
           "Latitude": 42.853031, "Longitude": -97.468522, "SampleYear": "2026", "WeekNumber": "32",
           "ActivityStartDate": 1786338000000, "EColi": "461", "Microcystin": "", "HealthAlert": "NO",
           "EColiRisk": "Elevated health risk for E. coli", "HealthDescription": ""}


def _beachwatch_with_yankton():
    from ingest.generic import arcgis, runner
    _, block = runner.load_source("ne-dwee-beachwatch")
    doc = json.loads((Path(__file__).parent / "fixtures" / "ne_dwee_beachwatch.json").read_text())
    doc["features"].append({"attributes": dict(YANKTON)})
    rows = arcgis.parse(block, json.dumps(doc).encode())
    return runner.build("ne-dwee-beachwatch", block, rows, "2026-11-07T01:14:00Z", [])[0]


def _resolver(live, missouri_near_yankton=True):
    """The status resolver over the committed water records, with the given states shown; the Missouri River gets a
    line 319 m south of the Lake Yankton station (as openboatlaunch's outline lies), so a fall-through to the nearest
    water would find it."""
    from shapely.geometry import LineString, mapping
    from build import status as S
    waters = {k: dict(v) for k, v in S.load_waters().items()}
    if missouri_near_yankton:
        waters["missouri-river-ne"]["geometry"] = mapping(LineString([(-97.50, 42.8502), (-97.44, 42.8502)]))
    S._STATES = set(live)
    return S, S.Resolver(waters, S.load_registry_outfalls(), {}, {}, None)


def test_the_lake_yankton_station_names_its_south_dakota_lake():
    by = {r["source_record_id"]: r for r in _beachwatch_with_yankton()}
    y = by["YAKLKBACT1-2026-w32"]
    assert y["waterbody_text"] == "Lake Yankton" and y["raw"]["waterbody_as_named"] == "Lake Yankton (Cottonwood Lake)"
    assert y["raw"]["state"] == "SD" and y["raw"]["county"] == "Yankton County" and "lake-yankton-sd" in y["raw"]["state_basis"]
    assert y["event_type"] == "beach_advisory" and y["raw"]["_agency_label_only"] is True
    assert all("state" not in r["raw"] for k, r in by.items() if k != "YAKLKBACT1-2026-w32")


def test_no_beach_watch_record_places_on_a_river():
    from build import status as S0
    keep = S0._STATES
    try:
        S, R = _resolver({"NE"})
        recs = _beachwatch_with_yankton()
        for r in recs:
            pl = R.resolve(r)
            kinds = {R.waters[s].get("kind") for s in pl["water_slugs"]}
            assert not kinds & S.RIVER_KINDS, (r["source_record_id"], pl)
        y = R.resolve(next(r for r in recs if r["source_record_id"].startswith("YAKLK")))
        assert y["water_slugs"] == [] and "Yankton County, SD" in y["unplaced_reason"]
        # without the guard's state check the point would fall to the Missouri, 319 m away
        assert R.by_point(42.853031, -97.468522, "NE")[1] == "missouri-river-ne"
        # once South Dakota is shown, the record lands on its lake
        S, R = _resolver({"NE", "SD"})
        assert R.resolve(next(r for r in recs if r["source_record_id"].startswith("YAKLK")))["water_slugs"] == ["lake-yankton-sd"]
    finally:
        S0._STATES = keep


def test_the_report_names_file_leaves_the_south_dakota_lake_out():
    d = json.loads((ROOT / "research" / "ne" / "receiving-waters-missing.json").read_text())
    assert not [r for r in d["rows"] if "yankton" in r["name"].lower()]
    assert d["waters"] == len(d["rows"]) == 40 and d["named_waters"] == 37 and d["reports"] == sum(r["reports"] for r in d["rows"])
