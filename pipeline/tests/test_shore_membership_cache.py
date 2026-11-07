"""Shoreline stretches belong to every water they run through, under every shoreline model, and a cached stretch is
rebuilt when what it was built from changes (SOL wave1 review of 2026-11-07, P1-6 and P2-10). Synthetic Puget Sound
geometry (the record's own outline is openboatlaunch's); no network.
Run from pipeline/: python -m pytest tests/test_shore_membership_cache.py -q
"""
from __future__ import annotations

import copy
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from shapely.geometry import box, mapping

from build import reaches as R
from build import shoreline as SH
from build import status as S

ROOT = Path(__file__).resolve().parents[2]
RULES = json.loads((ROOT / "data" / "rules.json").read_text())
SHORE = SH.rule(RULES)
NOW = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
SOUND = box(-122.60, 47.52, -122.40, 47.70)        # a box whose east edge is the shore
LAND = {"WA": box(-122.40, 47.40, -122.20, 47.80)}
BAY = box(-122.42, 47.58, -122.395, 47.64)         # a bay record along that shore, about 7 km of it
OUTFALL = (47.5238863, -122.3963928)


def _waters():
    rec = S.load_waters()["puget-sound-wa"]
    return {"puget-sound-wa": {**copy.deepcopy(rec), "geometry": mapping(SOUND), "bbox": list(SOUND.bounds)},
            "example-bay-wa": {"slug": "example-bay-wa", "name": "Example Bay", "kind": "bay", "state": "WA",
                               "towns": [], "bbox": list(BAY.bounds), "geometry": mapping(BAY)}}


def _cand():
    return {"key": R.reach_key("WA0029181", "057"), "permit": "WA0029181", "outfall": "057", "state": "WA",
            "water_slug": "puget-sound-wa", "lat": OUTFALL[0], "lon": OUTFALL[1], "sources": ["echo"],
            "model": SH.MODEL}


def test_a_sound_stretch_along_a_bay_is_on_both_records_and_their_reach_lists():
    waters = _waters()
    rec = R.shoreline_record(_cand(), waters, SHORE, LAND)
    assert rec["error"] is None and rec.get("sound") is True and rec["segments"]
    assert rec["waters"][0] == "puget-sound-wa" and "example-bay-wa" in rec["waters"]
    # the status build: the report is on both waters, and both list the stretch (the export copies the list)
    from common import event
    tmp = Path(tempfile.mkdtemp())
    e = event(source_id="wa-test", source_record_id="WA0029181-057", event_type="cso", status="ongoing",
              npdes_permit="WA0029181", outfall_id="057", waterbody_text="Puget Sound",
              started_at=(NOW - timedelta(hours=2)).isoformat())
    (tmp / "wa-test.json").write_text(json.dumps({"source_id": "wa-test", "ok": True, "last_ok_at": NOW.isoformat(),
                                                  "meta": {}, "records": [e]}))
    row = {"npdes_permit": "WA0029181", "outfall": "057", "state": "WA", "water_slug": "puget-sound-wa",
           "lat": OUTFALL[0], "lon": OUTFALL[1], "outfall_kind": "cso", "_file": "data/outfalls-us.json"}
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    saved = S._STATES
    S._STATES = {"WA"}
    try:
        st, _ = S.build(now=NOW, write=False, events_dir=tmp, waters=waters, outfalls=[row], registry={},
                        reaches={rec["key"]: rec}, flows=({}, {}), discharger_towns={}, discharger_waters={},
                        rules={**RULES, "live_states": ["WA"]})
    finally:
        S._STATES = saved
        S._SHORE_REACHES.clear()
        S._GEOM_CACHE.clear()
    sound, bay = st["waters"]["puget-sound-wa"], st["waters"]["example-bay-wa"]
    assert sound["reaches"] == [rec["key"]] and bay["reaches"] == [rec["key"]]
    assert e["event_id"] in sound["events"] and e["event_id"] in bay["events"]
    assert bay["status"] in ("red", "yellow")


# ---------------------------------------------------------------- the cache (P2-10)

@pytest.fixture
def built(tmp_path, monkeypatch):
    """One fresh, successful cached sound stretch; the Census outlines never fetched."""
    monkeypatch.setattr(R, "REACH_DIR", tmp_path)
    monkeypatch.setattr(R, "land_outlines", lambda: LAND)
    waters = _waters()
    out = R.run_shorelines([_cand()], waters, SHORE, log=lambda m: None, land=LAND)
    assert out["built"] == 1
    again = R.run_shorelines([_cand()], waters, SHORE, log=lambda m: None, land=LAND)
    assert again["due"] == 0                                    # fresh and unchanged: not rebuilt
    return waters


def _due(waters, shore=SHORE):
    return R.run_shorelines([_cand()], waters, shore, log=lambda m: None, land=LAND)["due"]


def test_a_changed_outline_rebuilds_a_fresh_stretch(built):
    waters = copy.deepcopy(built)
    moved = box(-122.60, 47.52, -122.41, 47.70)
    waters["puget-sound-wa"].update(geometry=mapping(moved), bbox=list(moved.bounds))
    assert _due(waters) == 1


def test_a_changed_entry_open_m_rebuilds_a_fresh_stretch(built):
    rules = copy.deepcopy(RULES)
    for e in rules["reach"]["shoreline"]["lakes"]:
        if e["name"] == "Puget Sound":
            e["open_m"] = 1500
    shore = SH.rule(rules)
    assert R.shore_sig(shore) == R.shore_sig(SHORE)           # the shared rule values alone would not tell
    assert _due(built, shore) == 1


def test_an_added_or_changed_overlapping_water_record_rebuilds_a_fresh_stretch(built):
    waters = copy.deepcopy(built)
    other = box(-122.42, 47.53, -122.395, 47.56)
    waters["another-bay-wa"] = {"slug": "another-bay-wa", "name": "Another Bay", "kind": "bay", "state": "WA",
                                "towns": [], "bbox": list(other.bounds), "geometry": mapping(other)}
    assert _due(waters) == 1
    rebuilt = R.load_reaches()[_cand()["key"]]
    assert "another-bay-wa" in rebuilt["waters"]
    assert _due(waters) == 0
    changed = copy.deepcopy(waters)
    changed["example-bay-wa"]["kind"] = "lake"                  # an overlapping record changes
    assert _due(changed) == 1


def test_a_far_record_and_an_unchanged_run_rebuild_nothing(built):
    waters = copy.deepcopy(built)
    far = box(-120.0, 46.0, -119.9, 46.1)
    waters["far-lake-wa"] = {"slug": "far-lake-wa", "name": "Far Lake", "kind": "lake", "state": "WA", "towns": [],
                             "bbox": list(far.bounds), "geometry": mapping(far)}
    assert _due(waters) == 0


def test_a_cached_stretch_from_before_the_signature_is_rebuilt_once(built):
    path = R.REACH_DIR / f"{_cand()['key']}.json"
    d = json.loads(path.read_text())
    d.pop("input_sig")
    path.write_text(json.dumps(d))
    assert _due(built) == 1 and _due(built) == 0
