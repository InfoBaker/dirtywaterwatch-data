"""Failure handling of the ECHO ingesters (review finding #14): a failed part never yields ok=True.

Run from pipeline/:  python -m pytest ingest/echo_ingest_failures_test.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402
import requests  # noqa: E402

import common  # noqa: E402
from ingest import echo_cso_dmr_monthly as dmr  # noqa: E402
from ingest import echo_sewer_overflow_events as sobe  # noqa: E402

PREV = {"source_id": "x", "fetched_at": "2026-11-01T00:00:00Z", "ok": True, "error": None,
        "last_ok_at": "2026-11-01T00:00:00Z", "meta": {}, "count": 1, "records": [{"event_id": "prev:1"}]}


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(common, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(sobe, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(dmr.time, "sleep", lambda s: None)
    (tmp_path / "events").mkdir()
    return tmp_path


def boom(*a, **k):
    raise requests.ConnectionError("simulated outage")


def test_sobe_download_failure_keeps_previous_records_not_ok(dirs, monkeypatch):
    p = dirs / "events" / f"{sobe.SOURCE_ID}.json"
    p.write_text(json.dumps(PREV))
    monkeypatch.setattr(sobe.requests, "get", boom)
    assert sobe.main([]) == 1
    out = json.loads(p.read_text())
    assert out["ok"] is False and "ECHO download" in out["error"]
    assert out["records"] == PREV["records"] and out["last_ok_at"] == PREV["last_ok_at"]
    assert not (dirs / "echo-sewer-overflow-dropped.json").exists()


def test_sobe_first_run_failure_uses_research_copy_marked_not_ok(dirs, monkeypatch):
    monkeypatch.setattr(sobe.requests, "get", boom)
    assert sobe.main([]) == 1
    out = json.loads((dirs / "events" / f"{sobe.SOURCE_ID}.json").read_text())
    assert out["ok"] is False and out["last_ok_at"] is None and out["count"] > 0
    assert out["meta"]["via"] == "research copy"


def test_dmr_one_failed_request_is_not_ok(dirs, monkeypatch):
    p = dirs / "events" / f"{dmr.SOURCE_ID}.json"
    p.write_text(json.dumps(PREV))
    real = dmr.fetch

    def fetch(permit, code, since):
        if (permit, code) == ("MA0101508", "82220"):
            return None, "failed (ConnectionError: simulated)"
        return {"Message": "Success", "CWPName": permit, "PermFeatures": []}, "live"
    monkeypatch.setattr(dmr, "fetch", fetch)
    assert dmr.main([]) == 1
    out = json.loads(p.read_text())
    assert out["ok"] is False and "MA0101508:82220" in out["error"] and out["records"] == PREV["records"]
    assert real is not fetch
