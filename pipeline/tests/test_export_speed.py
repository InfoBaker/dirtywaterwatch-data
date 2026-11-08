"""The export's blocklist self-check keeps the digests of the out/ texts it found clean (export.build.blocklist_hits
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
        X.write_compact(out / "events" / f"e{i}.json", {"placement_note": f"placed by name {i}"})
    return out


def test_the_cache_gives_the_same_files_as_a_full_search_and_skips_unchanged_clean_texts(tmp_path, monkeypatch):
    out = make_out(tmp_path)
    cache = tmp_path / "scan-cache.json"
    X.write_compact(out / "events" / "b.json", {"no_receiving_water": f"only 'yard of {NAME.upper()}'"})
    first = X.blocklist_hits(out, [NAME], cache=cache)
    assert first == X.blocklist_hits(out, [NAME]) == ["events/b.json"]
    c = json.loads(cache.read_text())
    assert len(c["clean"]) == 22 and NAME.split()[0].lower() not in cache.read_text().lower()

    # the second run searches only the texts not known clean: the hit (b.json) and a changed file
    searched = []
    real = R.BlockScan.found
    monkeypatch.setattr(R.BlockScan, "found", lambda self, t: searched.append(t) or real(self, t))
    X.write_compact(out / "waters" / "test-river-ma.json", {"reasons": [{"short": f"SSO · {NAME}"}]})
    second = X.blocklist_hits(out, [NAME], cache=cache)
    assert second == ["waters/test-river-ma.json", "events/b.json"] == X.blocklist_hits(out, [NAME])
    assert len(searched) == 2 + 23          # 2 with the cache, then 23 for the full search without it

    # another blocklist (or other scanning code) is another stamp: every text is searched again
    searched.clear()
    assert X.blocklist_hits(out, [NAME, "Someone Else"], cache=cache) == second
    assert len(searched) == 23


def test_only_the_real_out_folder_uses_the_cache(tmp_path, monkeypatch):
    out = make_out(tmp_path)
    monkeypatch.setattr(X, "BLOCKED_MARK", tmp_path / "export-blocked.json")
    monkeypatch.setattr(X, "HITS_MARK", tmp_path / "blocklist-hits.json")
    monkeypatch.setattr(X, "SCAN_CACHE", tmp_path / "scan-cache.json")
    X.enforce_blocklist(out, [NAME])
    assert not (tmp_path / "scan-cache.json").exists()
    monkeypatch.setattr(X, "OUT_DIR", out)
    X.enforce_blocklist(out, [NAME])
    assert (tmp_path / "scan-cache.json").exists()
