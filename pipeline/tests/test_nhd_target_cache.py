"""The NHD target scan may reuse placement, but must rebuild targets from today's records."""
import copy
import json

import pytest

from build import status as S
from ingest import waters_from_nhd as N
from tests.test_placement_cache import recs
from tests.test_placement_steps import WATERS


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(S, "_STATES", None)
    monkeypatch.setattr(S, "_GEOM_CACHE", {})


def encoded(result, unplaced):
    # Target counters have tuple keys: compare the exact writer-facing rows and unplaced records.
    targets, skipped, reasons, stats, _ = result
    rows = [{**t, "points": list(t["points"].items())} for t in targets]
    return json.dumps([rows, list(skipped.items()), list(reasons.items()), stats, unplaced], default=str).encode()


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
    assert len(calls) == {"fetch": 0, "record": 1, "water": 4, "removed": 0, "corrupt": 4}[change]
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
