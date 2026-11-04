"""ingest/obl_waters.py: openboatlaunch's out/water records for one state -> data/waters-<st>.json, from a snapshot on
disk (a two-record fixture; nothing is fetched). Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import md_waters, obl_waters  # noqa: E402

FIX = Path(__file__).parent / "fixtures" / "obl-snapshot" / "water"     # openboatlaunch out/ layout (not named out/: git ignores out/)


def test_the_states_records_in_the_extract_shape(tmp_path):
    out_path = tmp_path / "waters-nc.json"
    assert obl_waters.main(["--state", "nc", "--from", str(FIX), "--out", str(out_path)]) == 0
    d = json.loads(out_path.read_text())
    assert d["state"] == "NC" and d["count"] == 2
    assert d["source"] == "openboatlaunch out/water snapshot 2026-10-30"
    assert [w["slug"] for w in d["waters"]] == ["lake-wheeler-nc", "neuse-river-nc"]       # sorted, VA left out
    neuse = d["waters"][1]
    assert set(neuse) == {"slug", "name", "kind", "state", "towns", "bbox", "wikidata", "charted", "area_km2",
                          "launches", "advisories"}
    assert neuse["launches"] == ["example-launch-nc"] and neuse["towns"] == ["Raleigh", "Goldsboro"]
    assert d["waters"][0]["advisories"] == ["example-advisory"] and d["waters"][0]["area_km2"] == 2.6


def test_a_half_written_file_is_skipped_and_counted(tmp_path):
    out = obl_waters.extract("NC", FIX, tmp_path / "w.json", snapshot="2026-11-01")
    assert out["_read"] == {"unreadable": 1, "records": 2}
    assert json.loads((tmp_path / "w.json").read_text())["source"].endswith("2026-11-01")


def test_the_maryland_extract_is_the_same_shape(tmp_path):
    md = tmp_path / "water"
    md.mkdir()
    (md / "back-creek-md.json").write_text(json.dumps({"slug": "back-creek-md", "name": "Back Creek", "kind": "stream",
                                                       "state": "MD", "launches": [{"s": "x-md"}]}))
    out = md_waters.extract(md, tmp_path / "waters-md.json", None, snapshot="2026-11-02")
    assert out["count"] == 1 and out["waters"][0]["launches"] == ["x-md"] and "_read" not in out
    md_waters._records.cache_clear()
    md_waters._index.cache_clear()


def test_no_directory_no_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        obl_waters.extract("NC", tmp_path / "missing", tmp_path / "w.json")
    assert not (tmp_path / "w.json").exists()
