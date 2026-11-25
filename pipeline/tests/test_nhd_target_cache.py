"""The NHD target scan may reuse placement, but must rebuild targets from today's records."""
import copy
import json

import pytest

from build import status as S
from ingest import waters_from_nhd as N
from tests.test_placement_cache import recs
from tests.test_placement_steps import WATERS, ev, w


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(S, "_STATES", None)
    monkeypatch.setattr(S, "_GEOM_CACHE", {})


def encoded(result, unplaced):
    # Target counters have tuple keys: compare the exact writer-facing rows and unplaced records.
    targets, skipped, reasons, stats, _ = result
    rows = [{**t, "points": list(t["points"].items())} for t in targets]
    return json.dumps([rows, list(skipped.items()), list(reasons.items()), stats, unplaced], default=str).encode()


@pytest.fixture
def guard_world():
    waters = dict([w("example-bay-ma", "Example Bay", "bay", {
        "type": "Polygon", "coordinates": [[[-71.01, 42], [-71, 42], [-71, 42.01],
                                             [-71.01, 42.01], [-71.01, 42]]],
    })])
    records = [ev(rid, waterbody_text="Example Bay", raw={"state": "MA"}, lat=42.005, lon=lon)
               for rid, lon in (("a", -70.95509), ("b", -70.95507))]
    return waters, records


@pytest.mark.parametrize("reverse", [False, True], ids=["inside-first", "outside-first"])
def test_distance_memo_preserves_both_sides_of_bay_guard(guard_world, monkeypatch, reverse):
    waters, records = guard_world
    resolver = S.Resolver(waters, [], {}, {}, {})
    calls = []
    nearest = resolver.nearest
    monkeypatch.setattr(resolver, "nearest", lambda slugs, lat, lon:
                        calls.append((lat, lon)) or nearest(slugs, lat, lon))
    distances = {}
    for record in records[:: -1 if reverse else 1]:
        point = (record["lat"], record["lon"])
        distances[record["source_record_id"]] = resolver.distance_m("example-bay-ma", *point)
        assert resolver.distance_m("example-bay-ma", *point) == distances[record["source_record_id"]]
    assert distances["a"] == pytest.approx(4999.3812, abs=0.001)
    assert distances["b"] == pytest.approx(5001.6076, abs=0.001)
    assert len(calls) == 2  # Each exact point is computed once, then reused.


@pytest.mark.parametrize("reverse", [False, True], ids=["inside-first", "outside-first"])
@pytest.mark.parametrize("change", ["removed", "edit_neighbor", "edit_record", "ordering"])
def test_target_cache_guard_boundary_after_record_changes(tmp_path, monkeypatch, guard_world, change, reverse):
    waters, records = guard_world
    a, b = records
    if reverse:
        records.reverse()
    monkeypatch.setattr(N, "TARGET_PLACEMENTS", tmp_path / "nhd-target-placements.json")
    monkeypatch.setattr(N, "outfall_rows", lambda: [])
    monkeypatch.setattr(S, "make_resolver", lambda w: S.Resolver(w, [], {}, {}, {}))
    initial_unplaced = []
    N.collect_targets(waters, records, verbose=False, unplaced=initial_unplaced)
    initial_ids = [r["event_id"] for r in initial_unplaced]
    stamp = json.loads(N.TARGET_PLACEMENTS.read_text())["stamp"]
    calls = []
    resolve = S.Resolver.resolve
    monkeypatch.setattr(S.Resolver, "resolve", lambda self, record:
                        calls.append(record["event_id"]) or resolve(self, record))
    if change == "removed":
        records.remove(a)
    elif change == "edit_neighbor":
        a["lon"] = -71.005  # Move the influencing record onto the bay; B is unchanged.
    elif change == "edit_record":
        a["lon"], b["lon"] = b["lon"], a["lon"]  # Both records cross the guard.
    else:
        records.reverse()
    warm_unplaced = []
    warm_result = N.collect_targets(waters, records, verbose=False, unplaced=warm_unplaced)
    warm = encoded(warm_result, warm_unplaced)
    assert len(calls) == {"removed": 0, "edit_neighbor": 1, "edit_record": 2, "ordering": 0}[change]
    saved = json.loads(N.TARGET_PLACEMENTS.read_text())
    assert saved["stamp"] == stamp
    assert set(saved["placements"]) == {r["event_id"] for r in records}
    N.TARGET_PLACEMENTS.unlink()
    calls.clear()
    cold_unplaced = []
    cold_result = N.collect_targets(waters, records, verbose=False, unplaced=cold_unplaced)
    assert len(calls) == len(records)
    assert warm == encoded(cold_result, cold_unplaced)
    expected = [a if change == "edit_record" else b]
    assert warm_unplaced == cold_unplaced == expected
    assert len(warm_result[0]) == len(cold_result[0]) == 1
    assert warm_result[0][0]["events"] == 1
    assert warm_result[0][0]["refs"] == [expected[0]["event_id"]]
    assert initial_ids == [b["event_id"]]


@pytest.mark.parametrize("change", ["fetch", "record", "water", "removed", "corrupt"])
def test_target_cache_reuses_and_invalidates(tmp_path, monkeypatch, change):
    waters = copy.deepcopy(WATERS)
    records = recs()
    monkeypatch.setattr(N, "TARGET_PLACEMENTS", tmp_path / "nhd-target-placements.json", raising=False)
    monkeypatch.setattr(N, "outfall_rows", lambda: [])
    monkeypatch.setattr(S, "make_resolver", lambda w: S.Resolver(w, [], {}, {}, {}))
    N.collect_targets(waters, records, verbose=False)
    calls = []
    real = S.Resolver.resolve
    monkeypatch.setattr(S.Resolver, "resolve", lambda self, ev: calls.append(ev["event_id"]) or real(self, ev))
    if change == "fetch":
        for r in records:
            r["fetched_at"] = "2026-11-22T19:26:00Z"
    elif change == "record":
        records[0]["waterbody_text"] = "New Creek"
    elif change == "water":
        waters["test-river-ma"]["name"] = "New Creek"
    elif change == "removed":
        records.pop()
    else:
        N.TARGET_PLACEMENTS.write_text("{")
    unplaced = []
    warm = encoded(N.collect_targets(waters, records, verbose=False, unplaced=unplaced), unplaced)
    assert len(calls) == {"fetch": 0, "record": 1, "water": 2, "removed": 0, "corrupt": 4}[change]
    saved = json.loads(N.TARGET_PLACEMENTS.read_text())
    assert set(saved["placements"]) == {r["event_id"] for r in records}
    N.TARGET_PLACEMENTS.unlink()
    unplaced = []
    cold = encoded(N.collect_targets(waters, records, verbose=False, unplaced=unplaced), unplaced)
    assert warm == cold


def test_fixed_clock_nhd_file_bytes_match_uncached_cold_and_warm(tmp_path, monkeypatch):
    """An offline, stopped-budget run writes the same complete waters-nhd file for the same targets."""
    monkeypatch.setattr(N, "TARGET_PLACEMENTS", tmp_path / "nhd-target-placements.json")
    monkeypatch.setattr(N, "OUT", tmp_path / "waters-nhd.json")
    monkeypatch.setattr(N, "now_iso", lambda: "2026-11-22T18:26:00Z")
    monkeypatch.setattr(N, "outfall_rows", lambda: [])
    monkeypatch.setattr(S, "make_resolver", lambda w: S.Resolver(w, [], {}, {}, {}))
    records = recs()

    class Uncached:
        def __init__(self, resolver):
            self.resolve = resolver.resolve

        def save(self):
            pass

    def write():
        targets, _, reasons, stats, _ = N.collect_targets(copy.deepcopy(WATERS), records, verbose=False)
        rows = [N.Run.new_row(t) for t in targets]
        for r in rows:
            r["reason"] = f"{N.NOT_REACHED} (--wall-s used); the next run resumes"
        N.OUT.unlink(missing_ok=True)
        N.write_output([], N.finish_rows(rows), N.skipped_list(reasons), [], partial=True, stats=dict(stats))
        return N.OUT.read_bytes()

    with monkeypatch.context() as m:
        m.setattr(N, "TargetPlacements", Uncached)
        before = write()
    assert write() == before
    for r in records:
        r["fetched_at"] = "2026-11-22T19:26:00Z"
    assert write() == before
