"""No tracked file under data/ grows past the batch's size ceiling (scripts/state_batch.py MAX_FILE_BYTES, 90 MiB):
GitHub refuses a pushed file over 100 MB, and Louisiana's batch (2026-11-15) was refused at 101.39 MB for
data/waters-nhd.json. The suite sees the growth before a push does. Also the row layout that file is written in
(common.dumps_rows)."""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

from common import ROW_LIST_KEYS, dumps_rows, write_rows_json

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("state_batch_sizes", ROOT / "scripts" / "state_batch.py")
B = importlib.util.module_from_spec(_spec)
sys.modules["state_batch_sizes"] = B      # dataclasses look their module up there
_spec.loader.exec_module(B)


def tracked_sizes(root: Path, files: list[str]) -> dict[str, int]:
    """{file: bytes} of every file; a tracked path that cannot be stat'ed fails (review P2: it must not pass unseen)."""
    out = {}
    for f in files:
        try:
            out[f] = (root / f).stat().st_size
        except OSError as ex:
            raise AssertionError(f"tracked file {f} cannot be read for its size ({type(ex).__name__})") from None
    return out


def test_no_tracked_data_file_is_over_the_ceiling():
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "-z", "--", "data"], check=True,
                           stdout=subprocess.PIPE).stdout.decode().split("\0")
    files = [f for f in files if f]
    sizes = tracked_sizes(ROOT, files)
    assert len(sizes) == len(files) > 0, "git ls-files found nothing under data/"
    assert sizes.get("data/waters-nhd.json", 0) > 0
    big = {f: n for f, n in sizes.items() if n > B.MAX_FILE_BYTES}
    assert not big, f"over {B.MAX_FILE_BYTES / 2**20:.0f} MiB (GitHub refuses 100 MB): {big}"


def test_a_tracked_path_that_cannot_be_stated_fails(tmp_path):
    (tmp_path / "a.json").write_text("{}")
    assert tracked_sizes(tmp_path, ["a.json"]) == {"a.json": 2}
    try:
        tracked_sizes(tmp_path, ["a.json", "gone.json"])
    except AssertionError as ex:
        assert "gone.json" in str(ex)
    else:
        raise AssertionError("a missing tracked file passed")


def test_rows_layout_encodes_keys_as_json_does():
    """Review P1: a non-string top-level key is encoded (or refused) exactly as json.dumps does."""
    for doc in ({True: "x", "waters": []}, {None: 1}, {1: [1], 2.5: "y", False: None}, {"waters": [{"a": 1}], 7: {"b": 2}}):
        assert json.loads(dumps_rows(doc)) == json.loads(json.dumps(doc, indent=1)), doc
    for bad in ({(1, 2): "x"}, {b"k": 1}):
        for f in (dumps_rows, lambda d: json.dumps(d, indent=1)):
            try:
                f(bad)
            except TypeError:
                pass
            else:
                raise AssertionError(f"accepted {bad!r}")


def test_the_ceiling_is_under_githubs_limit():
    assert B.MAX_FILE_BYTES == 90 * 1024 * 1024 < 100 * 1000 * 1000


DOC = {"source": "NHDPlus; data (c) OpenStreetMap contributors", "built": "2026-11-15T00:00:00Z", "partial": False,
       "count": 2, "note": "ünïcode kept", "stats": {"state_builds": {"WV": {"targets": 3, "by": {"a": [1, 2]}}}},
       "problems": ["x-wv: dropped (lies on its river)"], "skipped": [],
       "targets": [{"state": "WV", "name": "Elk River", "reason": "line\nbreak \"quoted\"", "slugs": []},
                   {"state": "WV", "name": "Ünnamed", "slugs": ["a-wv"], "n": 1.0, "x": 1e-07}],
       "waters": [{"slug": "a-wv", "geometry": {"type": "LineString", "coordinates": [[-80.123456, 38.1], [-80.2, 38.25]]}},
                  {"slug": "b-wv", "geometry": None, "bbox": [1, 2, 3, 4]}]}


def test_rows_layout_round_trips_one_row_per_line_and_is_deterministic(tmp_path):
    text = dumps_rows(DOC)
    assert json.loads(text) == DOC == json.loads(json.dumps(DOC, indent=1, ensure_ascii=False))
    assert text == dumps_rows(json.loads(text))                       # the same data gives the same bytes
    assert text.endswith("}\n") and not text.endswith("\n\n")
    lines = text.split("\n")
    for k in ROW_LIST_KEYS:
        rows = DOC[k]
        if not rows:
            assert f' "{k}": [],' in lines or f' "{k}": []' in lines
            continue
        i = lines.index(f' "{k}": [')
        got = lines[i + 1:i + 1 + len(rows)]
        assert [json.loads(x.strip().rstrip(",")) for x in got] == rows
        assert all(x.startswith("  {") or x.startswith('  "') for x in got)
        assert lines[i + 1 + len(rows)].startswith(" ]")
    assert ' "stats": {' in lines and '   "WV": {' in lines            # stats stays readable at indent=1
    assert "ünïcode" in text and "Ünnamed" in text                       # ensure_ascii=False
    assert '"coordinates":[[-80.123456,38.1],[-80.2,38.25]]' in text    # compact, precision as it was
    p = tmp_path / "waters-nhd.json"
    write_rows_json(p, DOC)
    assert p.read_text() == text and not (tmp_path / "waters-nhd.json.tmp").exists()


def test_the_file_on_main_is_in_the_rows_layout():
    """data/waters-nhd.json is written by common.write_rows_json only; a writer that wrote it another way would show here."""
    text = (ROOT / "data" / "waters-nhd.json").read_text()
    assert text == dumps_rows(json.loads(text))


def test_the_readers_read_the_rows_layout(tmp_path, monkeypatch):
    """The waters builder's own readers (previous_slugs, previous_rows) and build/status's water files read the file."""
    from ingest import waters_from_nhd as N
    p = tmp_path / "waters-nhd.json"
    write_rows_json(p, {"targets": [], "waters": [
        {"slug": "elk-river-wv", "state": "WV", "name": "Elk River", "kind": "river", "source": "nhd", "gnis_id": "1",
         "geometry": {"type": "LineString", "coordinates": [[-80.0, 38.0], [-80.1, 38.1]]}}]})
    assert "elk-river-wv" in N.previous_slugs(p).values()
    assert [r[0] for r in N.previous_rows(p)] == ["elk-river-wv"]
