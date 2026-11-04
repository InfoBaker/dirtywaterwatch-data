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
