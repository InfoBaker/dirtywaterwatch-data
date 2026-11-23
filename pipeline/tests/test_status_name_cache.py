"""Pure name matches reuse the placement cache; complete status outputs remain byte-identical."""
from __future__ import annotations

import copy
import json
from datetime import timedelta
from pathlib import Path

import pytest

from build import fixtures as F, status as S
from tests.test_placement_cache import world
from tests.test_placement_steps import NOW, WATERS, ev


def legacy_matches(self, text, state, stems=False):
    keys = list(self.names) + (list(self.stems) if stems else [])
    return [n for st, n in keys if st == state and f" {n} " in text]


@pytest.fixture(autouse=True)
def clean_state(monkeypatch):
    monkeypatch.setattr(S, "_STATES", None)
    monkeypatch.setattr(S, "_GEOM_CACHE", {})
    monkeypatch.setattr(S, "_REACH_WATERS", {})
    monkeypatch.setattr(S, "now_iso", lambda: NOW.isoformat())


def output_bytes(root):
    return {p.name: p.read_bytes() for p in root.glob("*.json")}


def test_repository_fixtures_every_status_output_byte_matches(tmp_path, monkeypatch):
    """Compare the original national scan, no cache, cold cache and warm cache, including metadata.
    Freeze both clocks; do not remove timestamps or any other output fields before comparing."""
    monkeypatch.setattr(F, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(F, "now_iso", lambda: NOW.isoformat())
    F.main()
    output = tmp_path / "outputs"
    monkeypatch.setattr(S, "BUILD_DIR", output)
    kw = dict(include_fixtures=True, now=NOW, events_dir=F.EVENTS_DIR, waters=S.load_waters(),
              outfalls=[], registry={}, reaches={}, flows=({}, {}), discharger_towns={}, discharger_waters={},
              discharger_aliases_map={}, rules=copy.deepcopy(S.load_rules()), rain={}, write=True)
    with monkeypatch.context() as m:
        m.setattr(S.Resolver, "matching_names", legacy_matches)
        S.build(**kw, placement_cache=None)
    before = output_bytes(output)
    assert set(before) == {"status.json", "history.json"}
    for cache in (None, tmp_path / "cache.json", tmp_path / "cache.json"):
        S._GEOM_CACHE.clear()
        S._REACH_WATERS.clear()
        S.build(**kw, placement_cache=cache)
        assert output_bytes(output) == before
    assert json.loads((tmp_path / "cache.json").read_text())["name_matches"]


def test_indexed_matches_preserve_scan_order_and_word_boundaries():
    waters = {**WATERS,
              "ct": {"state": "CT", "name": "Test River", "aliases": ["The Test River"]},
              "ma": {"state": "MA", "name": "Little Test River", "aliases": ["The Test River"]}}
    r = S.Resolver(waters, [], {}, {}, {})
    for state in ("MA", "CT", "PR", None):
        for text in ("", "test river", "little test river", "the test river and short brook",
                     "test rivers", "short", "test river short brook test river"):
            padded = f" {S.norm_name(text)} "
            for stems in (False, True):
                expected = legacy_matches(r, padded, state, stems)
                assert r.matching_names(padded, state, stems) == expected
                assert r.matching_names(padded, state, stems) == expected
    # A hit performs no name-index scan, even for a cached empty answer.
    r.names_by_state.clear()
    r.stems_by_state.clear()
    assert r.matching_names(" test river ", "MA") == ["test river"]
    assert r.matching_names(" test rivers ", "MA") == []


@pytest.mark.parametrize("change", ["rules", "record", "new", "removed", "code"])
def test_cache_invalidation_and_every_output_byte(tmp_path, monkeypatch, change):
    rs = [ev(str(i), waterbody_text=name, started_at=(NOW - timedelta(hours=3)).isoformat(),
             ended_at=(NOW - timedelta(hours=1)).isoformat())
          for i, name in enumerate(("Test River", "Short Brook"))]
    kw = world(tmp_path, rs)
    output = tmp_path / "outputs"
    monkeypatch.setattr(S, "BUILD_DIR", output)
    kw.update(write=True, discharger_aliases_map={})
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(kw["rules"]))
    kw["rules"] = S.load_rules(rules_path)
    first, _ = S.build(**kw)
    held = json.loads(kw["placement_cache"].read_text())
    assert held["name_matches"]
    # Unchanged inputs really hit the persisted cache in a fresh Resolver.
    hits = []
    real = S.Resolver.matching_names

    def spy(self, text, state, stems=False):
        key = json.dumps([state, text, stems], ensure_ascii=False)
        hits.append(key in self.name_matches_old)
        return real(self, text, state, stems)

    monkeypatch.setattr(S.Resolver, "matching_names", spy)
    S.build(**kw)
    assert hits and all(hits)
    hits.clear()
    if change == "rules":
        rules = json.loads(rules_path.read_text())
        rules.setdefault("placement", {})["no_outfall_all_waters"] = not bool(
            rules.get("placement", {}).get("no_outfall_all_waters"))  # without changing rules.version
        rules_path.write_text(json.dumps(rules))
        kw["rules"] = S.load_rules(rules_path)
    elif change == "record":
        rs[0].update(lat=0, lon=0)                   # same text hit, different point: guard must still run
    elif change == "new":
        rs.append(ev("new", waterbody_text="Other Pond", started_at=rs[0]["started_at"],
                     ended_at=rs[0]["ended_at"]))
    elif change == "removed":
        rs.pop()
    else:
        code = tmp_path / "status-v2.py"
        code.write_bytes(Path(S.__file__).read_bytes() + b"\n# code version bump\n")
        monkeypatch.setattr(S, "__file__", str(code))
    event_path = kw["events_dir"] / "ma-test.json"
    doc = json.loads(event_path.read_text())
    doc["records"] = rs
    event_path.write_text(json.dumps(doc))
    # Time also advances; cached names must not freeze colours or intervals.
    kw["now"] = NOW + timedelta(days=10)
    changed, _ = S.build(**kw)
    cached = output_bytes(output)
    updated = json.loads(kw["placement_cache"].read_text())
    if change in ("rules", "code"):
        assert held["stamp"] != updated["stamp"]
        assert hits and not any(hits)
    elif change == "record":
        assert hits and all(hits)
        assert first["placements"]["ma-test:0"] != changed["placements"]["ma-test:0"]
    elif change == "new":
        assert "ma-test:new" in changed["placements"]
        assert hits and not all(hits)
    else:
        assert "ma-test:1" not in changed["placements"]
        assert not any("short brook" in key for key in updated["name_matches"])
    S.build(**{**kw, "placement_cache": None})
    assert output_bytes(output) == cached
