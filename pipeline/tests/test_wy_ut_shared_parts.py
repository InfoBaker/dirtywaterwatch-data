"""Flaming Gorge Reservoir at the Wyoming-Utah line (registry fix, 2026-11-16): openboatlaunch gives each state the whole
reservoir, so Wyoming DEQ's bloom advisory, placed on Wyoming's record, coloured Utah's side too. Each record is now its
own state's part (scripts/cut_lakes_to_state_waters.py --shared -> data/water-state-parts.json, applied by
build/status.py apply_state_parts), each naming the other."""
from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import box, mapping, shape

ROOT = Path(__file__).resolve().parents[2]
WY_SLUG, UT_SLUG = "flaming-gorge-reservoir-wy", "flaming-gorge-reservoir-ut"
LINE = 41.0                     # the Wyoming-Utah line here runs along about 41 N


def _script():
    spec = importlib.util.spec_from_file_location("cut_lakes_shared", ROOT / "scripts" / "cut_lakes_to_state_waters.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _parts():
    return json.loads((ROOT / "data" / "water-state-parts.json").read_text())


def _loaded(with_parts: bool = True) -> dict:
    from build import status as S
    real = S.WATER_STATE_PARTS_FILE
    try:
        if not with_parts:
            S.WATER_STATE_PARTS_FILE = "no-such-water-state-parts.json"
        return S.load_waters()
    finally:
        S.WATER_STATE_PARTS_FILE = real


# ---------------------------------------------------------------- the cut (synthetic)

def test_a_shared_record_is_cut_to_its_states_part_and_names_the_other():
    C = _script()
    north, south = box(0, 1, 1, 2), box(0, 0, 1, 1)             # two states, about 111 km a side, the line at y = 1
    lake = box(0.4, 0.6, 0.6, 1.4)                             # 40 per cent of it south of the line
    shared = {"x-lake-nn": {"state": "NN", "other_parts": ["x-lake-ss"], "why": "test"},
              "x-lake-ss": {"state": "SS", "other_parts": ["x-lake-nn"], "why": "test"}}
    recs = {s: {"slug": s, "kind": "reservoir", "geometry_hash": "h1"} for s in shared}
    rep = C.run_shared(dry_run=True, shared=shared, shapes={"NN": north, "SS": south},
                       records=lambda slug, st: recs[slug], outlines=lambda slug: lake, when="2026-11-16")
    doc = rep["doc"]
    n, s = doc["x-lake-nn"], doc["x-lake-ss"]
    assert n["bbox"][1] >= 1 - 1e-4 and n["bbox"][3] == 1.4 and s["bbox"][3] <= 1 + 1e-4 and s["bbox"][1] == 0.6
    assert abs(n["area_km2"] / n["whole_area_km2"] - 0.5) < 0.02 and abs(s["area_km2"] / s["whole_area_km2"] - 0.5) < 0.02
    assert n["other_parts"] == ["x-lake-ss"] and s["other_parts"] == ["x-lake-nn"]
    assert n["cut_from_geometry_hash"] == "h1" and "TIGER" in n["note"]
    assert shape(n["geometry"]).intersection(shape(s["geometry"])).area < 1e-6


def test_a_record_inside_its_state_or_without_an_outline_is_not_cut(tmp_path):
    C = _script()
    spec = {"y-lake-nn": {"state": "NN", "other_parts": [], "why": "test"}}
    rec = {"slug": "y-lake-nn", "kind": "lake"}
    inside = C.run_shared(dry_run=True, shared=spec, shapes={"NN": box(0, 0, 1, 1)}, records=lambda *a: rec,
                          outlines=lambda slug: box(0.2, 0.2, 0.3, 0.3), path=tmp_path / "p.json")
    gone = C.run_shared(dry_run=True, shared=spec, shapes={"NN": box(0, 0, 1, 1)}, records=lambda *a: rec,
                        outlines=lambda slug: None, path=tmp_path / "p.json")
    assert inside["changed"] == [] and "nothing to cut" in inside["kept"][0][1]
    assert gone["changed"] == [] and "not on this machine" in gone["kept"][0][1]
    assert not (tmp_path / "p.json").exists()


def test_a_part_is_applied_by_load_and_a_changed_outline_or_a_missing_record_is_a_problem(tmp_path):
    from build import status as S
    g = json.loads(json.dumps(mapping(box(0, 1, 1, 2))))
    p = tmp_path / "water-state-parts.json"
    p.write_text(json.dumps({"a-lake-nn": {"geometry": g, "bbox": [0, 1, 1, 2], "area_km2": 5.0, "whole_area_km2": 9.0,
                                           "other_parts": ["a-lake-ss"], "cut_from_geometry_hash": "old"},
                             "gone-lake-nn": {"geometry": g, "bbox": [0, 1, 1, 2]}}))
    waters = {"a-lake-nn": {"slug": "a-lake-nn", "state": "NN", "area_km2": 9.0, "bbox": [0, 0, 1, 2],
                            "geometry_hash": "new"},
              "b-lake-nn": {"slug": "b-lake-nn", "state": "NN", "area_km2": 1.0}}
    b_before = dict(waters["b-lake-nn"])
    probs = S.apply_state_parts(waters, p)
    a = waters["a-lake-nn"]
    assert a["geometry"] == g and a["bbox"] == [0, 1, 1, 2] and a["area_km2"] == 5.0 and a["other_parts"] == ["a-lake-ss"]
    assert waters["b-lake-nn"] == b_before
    assert any("a-lake-nn" in x and "changed since the cut" in x for x in probs)
    assert any("gone-lake-nn is not a water record" in x for x in probs)


# ---------------------------------------------------------------- the real records

def test_flaming_gorge_wyoming_is_wyomings_part_and_utah_is_utahs_each_naming_the_other():
    from build import status as S
    waters = _loaded()
    wy, ut = waters[WY_SLUG], waters[UT_SLUG]
    gw, gu = S.water_geometry(WY_SLUG, waters), S.water_geometry(UT_SLUG, waters)
    assert gw.bounds[1] > LINE - 0.005 and gu.bounds[3] < LINE + 0.005            # each ends at the line
    assert gw.bounds[3] > 41.4 and gu.bounds[1] < 40.9                             # and keeps its own side whole
    assert wy["bbox"] == [round(x, 5) for x in gw.bounds] and ut["bbox"] == [round(x, 5) for x in gu.bounds]
    whole = _parts()[WY_SLUG]["whole_area_km2"]
    assert 100 < wy["area_km2"] < 120 and 45 < ut["area_km2"] < 60                 # about two thirds and one third
    assert abs(wy["area_km2"] + ut["area_km2"] - whole) < 1.0
    assert gw.intersection(gu).area / gw.area < 0.001                             # no water in both
    assert wy["other_parts"] == [UT_SLUG] and ut["other_parts"] == [WY_SLUG]
    assert wy["state"] == "WY" and ut["state"] == "UT" and wy["name"] == ut["name"] == "Flaming Gorge Reservoir"


def test_the_parts_were_cut_from_the_outline_the_extracts_name():
    """openboatlaunch's outline is the one the extracts' geometry_hash names; when it changes, the build lists a
    problem and this fails until the cut is run again."""
    parts = _parts()
    for slug, st in ((WY_SLUG, "wy"), (UT_SLUG, "ut")):
        ext = json.loads((ROOT / "data" / f"waters-{st}.json").read_text())
        rec = next(w for w in ext["waters"] if w["slug"] == slug)
        assert "geometry" not in rec                                          # the extract itself is openboatlaunch's
        assert parts[slug]["cut_from_geometry_hash"] == rec["geometry_hash"], slug
    assert set(parts) == {WY_SLUG, UT_SLUG}


def test_no_other_wyoming_or_utah_water_changes():
    before, after = _loaded(False), _loaded(True)
    assert set(before) == set(after)
    changed = sorted(k for k in after if before[k] != after[k])
    assert changed == sorted([WY_SLUG, UT_SLUG])
    for k in changed:
        assert {x for x in set(before[k]) | set(after[k]) if before[k].get(x) != after[k].get(x)} == \
            {"geometry", "bbox", "area_km2", "other_parts", "state_part"}


def _status(recs, waters):
    import tempfile
    from build import status as S
    from ingest import wy_deq_hcb_bulletins as W
    d = Path(tempfile.mkdtemp()) / "events"
    d.mkdir()
    (d / f"{W.SOURCE_ID}.json").write_text(json.dumps({"source_id": W.SOURCE_ID, "ok": True,
                                                       "fetched_at": "2026-11-16T03:00:00Z",
                                                       "last_ok_at": "2026-11-16T03:00:00Z", "meta": {},
                                                       "count": len(recs), "records": recs}))
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    rules["live_states"] = sorted(set(rules["live_states"]) | {"WY", "UT"})
    rules["rain_likely"] = {**rules["rain_likely"], "enabled": False}
    st, _ = S.build(now=datetime(2026, 11, 16, 3, 0, tzinfo=timezone.utc), write=False, events_dir=d, waters=waters,
                    outfalls=[], registry={}, reaches={}, flows=({}, {}), rules=rules, placement_cache=False)
    return st


def test_wyomings_advisory_colours_wyomings_part_and_never_utahs():
    sys.path.insert(0, str(ROOT / "pipeline" / "tests"))
    import test_ingest_wy as T
    from build import status as S
    recs = T._audit_build([("Flaming Gorge Reservoir", "Firehole Ramp", "Bloom", "9/4/2026")])
    assert recs[0]["raw"]["advisory_extent"] == "named_water"
    waters = {k: w for k, w in _loaded().items() if w.get("state") in ("WY", "UT")}
    st = _status(recs, waters)
    assert st["placements"][recs[0]["event_id"]]["water_slugs"] == [WY_SLUG]
    assert st["waters"][WY_SLUG]["status"] == "red"
    assert st["waters"].get(UT_SLUG, {}).get("status", "grey") == "grey"
    # the colour is drawn on the record's outline: Wyoming's part, which ends at the line
    assert S.water_geometry(WY_SLUG, waters).bounds[1] > LINE - 0.005
