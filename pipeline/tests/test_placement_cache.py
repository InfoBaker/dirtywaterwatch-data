"""The status build's placement cache (build/status.py PLACEMENT_CACHE): a record that began more than
PLACEMENT_CACHE_DAYS ago keeps the placement the last run made for it while the record and every placement input are
unchanged, so a state's history on file (Michigan from 2001) is not placed again every hour; the output is identical.
Run from pipeline/: python -m pytest tests/test_placement_cache.py -q
"""
from __future__ import annotations

import json
from datetime import timedelta
from pathlib import Path

import pytest

from build import status as S
from tests.test_placement_steps import NOW, WATERS, ev

H = timedelta(hours=1)


@pytest.fixture(autouse=True)
def _states():
    S._GEOM_CACHE.clear()
    yield
    S._GEOM_CACHE.clear()
    S._STATES = None


def world(tmp: Path, records: list[dict], waters=None) -> dict:
    d = tmp / "events"
    d.mkdir(exist_ok=True)
    (d / "ma-test.json").write_text(json.dumps({"source_id": "ma-test", "ok": True, "last_ok_at": NOW.isoformat(),
                                                "meta": {}, "records": records}))
    return dict(now=NOW, write=False, events_dir=d, waters=dict(waters or WATERS), outfalls=[], registry={},
                reaches={}, flows=({}, {}), discharger_towns={}, discharger_waters={},
                rules={**S.load_rules(), "live_states": ["MA"]}, placement_cache=tmp / "cache.json")


def recs():
    old = [ev(f"old{i}", event_type="sso", waterbody_text=t, started_at=(NOW - timedelta(days=400 + i)).isoformat(),
              ended_at=(NOW - timedelta(days=399 + i)).isoformat())
           for i, t in enumerate(["Test River", "Short Brook", "Nowhere Creek"])]
    new = ev("new", event_type="sso", waterbody_text="Test River", started_at=(NOW - 3 * H).isoformat(),
             ended_at=(NOW - H).isoformat())
    return old + [new]


def strip(st):
    o = json.loads(json.dumps(st, default=str))
    o.pop("built", None)
    return o


def test_old_records_reuse_their_placement_and_the_status_is_the_same(tmp_path, monkeypatch):
    rs = recs()
    plain, plain_hist = S.build(**{**world(tmp_path, rs), "placement_cache": None})
    first, first_hist = S.build(**world(tmp_path, rs))
    placed = []
    real = S.Resolver.resolve
    monkeypatch.setattr(S.Resolver, "resolve", lambda self, e: placed.append(e["event_id"]) or real(self, e))
    second, second_hist = S.build(**world(tmp_path, rs))
    assert placed == ["ma-test:new"]                       # the three records of 400 days ago came from the cache
    assert strip(first) == strip(second) == strip(plain) and strip(first_hist) == strip(second_hist)
    assert second["placements"]["ma-test:old0"]["water_slugs"] == ["test-river-ma"]


def test_a_changed_record_or_a_changed_water_places_it_again(tmp_path, monkeypatch):
    rs = recs()
    S.build(**world(tmp_path, rs))
    placed = []
    real = S.Resolver.resolve
    monkeypatch.setattr(S.Resolver, "resolve", lambda self, e: placed.append(e["event_id"]) or real(self, e))
    rs[1] = {**rs[1], "waterbody_text": "Test River"}
    st, _ = S.build(**world(tmp_path, rs))
    assert sorted(placed) == ["ma-test:new", "ma-test:old1"]
    assert st["placements"]["ma-test:old1"]["water_slugs"] == ["test-river-ma"]
    placed.clear()
    waters = {**WATERS, "test-river-ma": {**WATERS["test-river-ma"], "towns": ["Springfield", "Chicopee"]}}
    S.build(**world(tmp_path, rs, waters))
    assert len(placed) == 4                                # a water record changed: every record placed again


def test_the_cache_is_off_for_a_build_that_does_not_write_the_shared_outputs(tmp_path, monkeypatch):
    monkeypatch.setattr(S, "PLACEMENT_CACHE", tmp_path / "default-cache.json")
    kw = world(tmp_path, recs())
    kw["placement_cache"] = True                            # the default: only a writing build of the default events
    S.build(**kw)
    assert not (tmp_path / "default-cache.json").exists() and not (tmp_path / "cache.json").exists()


# ---------------------------------------------------------------- review 2026-11-04: every placement input breaks it

def _spy(monkeypatch):
    placed = []
    real = S.Resolver.resolve
    monkeypatch.setattr(S.Resolver, "resolve", lambda self, e: placed.append(e["event_id"]) or real(self, e))
    return placed


def test_a_new_alias_on_a_water_record_places_the_cached_records_again(tmp_path, monkeypatch):
    """A hand alias (data/water-aliases.json, merged into the records' aliases by load_waters) is a placement input:
    a record of 400 days ago whose text only the new alias names is placed by it on the next build."""
    rs = [ev("alias", event_type="sso", waterbody_text="Old Mill Stream",
             started_at=(NOW - timedelta(days=400)).isoformat(), ended_at=(NOW - timedelta(days=399)).isoformat())]
    st, _ = S.build(**world(tmp_path, rs))
    assert st["placements"]["ma-test:alias"]["water_slugs"] == []
    placed = _spy(monkeypatch)
    waters = {**WATERS, "short-brook-ma": {**WATERS["short-brook-ma"], "aliases": ["Old Mill Stream"]}}
    st, _ = S.build(**world(tmp_path, rs, waters))
    assert placed == ["ma-test:alias"] and st["placements"]["ma-test:alias"]["water_slugs"] == ["short-brook-ma"]


def test_a_change_of_the_placement_code_places_every_cached_record_again(tmp_path, monkeypatch):
    rs = recs()
    S.build(**world(tmp_path, rs))
    placed = _spy(monkeypatch)
    S.build(**world(tmp_path, rs))
    assert placed == ["ma-test:new"]
    code = tmp_path / "status_copy.py"
    code.write_text(Path(S.__file__).read_text() + "\n# a change to the resolver\n")
    monkeypatch.setattr(S, "__file__", str(code))
    placed.clear()
    S.build(**world(tmp_path, rs))
    assert len(placed) == 4
    placed.clear()
    saved = dict(S.PLACE_STEPS)
    try:
        S.PLACE_STEPS["registry_first"] = not S.PLACE_STEPS["registry_first"]     # a step switched in the process
        S.build(**world(tmp_path, rs))
    finally:
        S.PLACE_STEPS.update(saved)
    assert len(placed) == 4


def test_a_water_outline_read_from_openboatlaunch_is_a_placement_input(tmp_path, monkeypatch):
    """An openboatlaunch record carries no inline geometry: its outline is read from OBL_WATER_DIR/<slug>.json. An
    outline that moves (or a machine with no such folder, as the hosted runner) places the cached records again."""
    obl = tmp_path / "obl"
    obl.mkdir()
    monkeypatch.setattr(S, "OBL_WATER_DIR", obl)
    line = {"type": "LineString", "coordinates": [[-71.0, 41.0], [-70.9, 41.0]]}
    (obl / "far-river-ma.json").write_text(json.dumps({"geometry": line}))
    waters = {**WATERS, "far-river-ma": {"slug": "far-river-ma", "name": "Far River", "kind": "river", "state": "MA",
                                         "towns": [], "bbox": [-71.0, 41.0, -70.9, 41.0]}}
    rs = [ev("pt", event_type="sso", lat=41.0001, lon=-70.95, started_at=(NOW - timedelta(days=400)).isoformat(),
             ended_at=(NOW - timedelta(days=399)).isoformat())]
    st, _ = S.build(**world(tmp_path, rs, waters))
    assert st["placements"]["ma-test:pt"]["water_slugs"] == ["far-river-ma"]
    S._GEOM_CACHE.clear()
    (obl / "far-river-ma.json").unlink()                     # the folder is not there (another machine)
    placed = _spy(monkeypatch)
    st, _ = S.build(**world(tmp_path, rs, waters))
    plain, _ = S.build(**{**world(tmp_path, rs, waters), "placement_cache": None})
    assert placed and st["placements"]["ma-test:pt"] == plain["placements"]["ma-test:pt"]
    assert st["placements"]["ma-test:pt"]["water_slugs"] == []


def test_an_old_record_with_no_end_reuses_its_place_but_its_colour_is_worked_out_again_each_build(tmp_path):
    """The cache holds the placement only: an ongoing record that began 200 days ago, or a completed one with no end,
    is coloured from its intervals at each build's own time, as an uncached build colours it."""
    rs = [ev("open", event_type="sso", status="ongoing", waterbody_text="Test River",
             started_at=(NOW - timedelta(days=200)).isoformat()),
          ev("noend", event_type="sso", status="ended", waterbody_text="Short Brook",
             started_at=(NOW - timedelta(days=130)).isoformat())]
    S.build(**world(tmp_path, rs))
    for later in (timedelta(days=1), timedelta(days=40)):
        kw = {**world(tmp_path, rs), "now": NOW + later}
        cached, cached_hist = S.build(**kw)
        plain, plain_hist = S.build(**{**kw, "placement_cache": None})
        assert strip(cached) == strip(plain) and strip(cached_hist) == strip(plain_hist)


def test_the_cache_holds_only_the_old_records_of_this_build(tmp_path):
    """It does not grow past the records on file: a record gone from the events leaves it, a recent one never enters."""
    rs = recs()
    S.build(**world(tmp_path, rs))
    held = json.loads((tmp_path / "cache.json").read_text())["placements"]
    assert sorted(held) == ["ma-test:old0", "ma-test:old1", "ma-test:old2"]
    S.build(**world(tmp_path, rs[1:]))
    assert sorted(json.loads((tmp_path / "cache.json").read_text())["placements"]) == ["ma-test:old1", "ma-test:old2"]
