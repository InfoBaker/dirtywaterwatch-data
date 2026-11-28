"""Export performance regressions: one normalization per index row and no redundant mkdir per JSON write.

The export's blocklist self-check keeps the digests of the out/ texts it found clean (export.build.blocklist_hits
cache=; docs/refresh-time-brief-2026-11-07.md): an unchanged text is not searched again, and the files it names are the
same as a search of every file. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json

from build import redact as R
from export import build as X

NAME = "Zebulon Quillfeather"      # a made-up name


def make_out(tmp_path):
    out = tmp_path / "out"
    (out / "waters").mkdir(parents=True)
    (out / "events").mkdir()
    X.write_compact(out / "events.json", {"events": [{"event_id": "a", "waterbody_text": "Test River"}]})
    X.write_compact(out / "waters" / "test-river-ma.json", {"events": []})
    for i in range(20):
        X.write_compact(out / "events" / f"e{i}.json", {"placement_note": f"placed by name {chr(97 + i)}"})
    return out






def test_index_row_preserves_column_values_with_one_normalization(monkeypatch):
    """Every column retains index_obj's bounds, state and coordinate handling, computed once."""
    records = [
        {"event_id": "synthetic:a", "event_type": "sso", "npdes_permit": "MA0000001",
         "lat": "42.1234567", "lon": "-71.7654321", "started_at": "2026-01-01",
         "ended_at": "2026-01-02", "time_precision": "day", "raw": {"ended_at_precision": "poll"}},
        {"event_id": "synthetic:b", "state": "NY", "started_at_bound": "on_or_before",
         "started_at_kind": "response", "ended_at": None, "time_precision": "minute"},
        {"event_id": "synthetic:c", "raw": {}, "water_slugs": []},
    ]
    original = X.index_obj
    expected = [[original(rec)[k] for k in X.INDEX_FIELDS] for rec in records]
    calls = []

    def counted(rec):
        calls.append(rec["event_id"])
        return original(rec)

    monkeypatch.setattr(X, "index_obj", counted)
    assert [X.index_row(rec) for rec in records] == expected
    assert calls == [rec["event_id"] for rec in records]


def test_compact_write_reuses_existing_directory_and_replaces_atomically(tmp_path, monkeypatch):
    """An existing output directory needs no mkdir syscall for every event written into it."""
    from pathlib import Path

    target = tmp_path / "event.json"
    target.write_text("previous complete record")
    real_mkdir = Path.mkdir

    def mkdir(path, *args, **kwargs):
        assert path != tmp_path, "existing output directory was created again"
        return real_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(Path, "mkdir", mkdir)
    X.write_compact(target, {"water": "Rivière", "missing": None, "path": Path("example")})
    assert target.read_bytes() == '{"water":"Rivière","missing":null,"path":"example"}'.encode()
    assert not target.with_suffix(".json.tmp").exists()
    X.write_compact(tmp_path / "new" / "nested" / "record.json", {"ok": True})
    assert (tmp_path / "new" / "nested" / "record.json").read_bytes() == b'{"ok":true}'


def test_empty_requested_removals_do_not_traverse_or_read_outputs(tmp_path, monkeypatch):
    from export.removals import RemovalList
    policy = RemovalList([])
    monkeypatch.setattr(policy, '_files', lambda *a: (_ for _ in ()).throw(AssertionError('unneeded scan')))
    policy.publish(tmp_path)
    assert policy.enforce(tmp_path) == 0
