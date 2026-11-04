"""Failure handling of ingest/me_dep_cso.py (review finding #14).

Run from pipeline/:  python -m pytest ingest/me_dep_cso_test.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import requests  # noqa: E402

import common  # noqa: E402
from ingest import me_dep_cso as m  # noqa: E402


def test_layer_failure_is_not_ok_and_keeps_last_good_outfalls(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(m, "BUILD_DIR", tmp_path)
    prev_outfalls = {"ok": True, "count": 1, "outfalls": [{"permit": "ME0100005", "outfall": "001"}]}
    (tmp_path / "me-cso-outfalls.json").write_text(json.dumps(prev_outfalls))

    def boom(*a, **k):
        raise requests.ConnectionError("simulated outage")
    monkeypatch.setattr(m.requests, "get", boom)
    assert m.main([]) == 1
    out = json.loads((tmp_path / "events" / f"{m.SOURCE_ID}.json").read_text())
    assert out["ok"] is False and "MEPDES CSO layer" in out["error"]
    kept = json.loads((tmp_path / "me-cso-outfalls.json").read_text())
    assert kept["outfalls"] == prev_outfalls["outfalls"] and kept["ok"] is False


def test_report_tables_parse(tmp_path):
    t = m.load_report(m.REPORTS[0])
    assert t["rows"]["ME0101435"]["gal"][2025] == 115_308_100
    assert t["rows"]["ME0100781"]["days"][2024] == 16
