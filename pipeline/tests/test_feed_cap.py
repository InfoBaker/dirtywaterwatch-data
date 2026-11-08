"""A feed never holds the hourly refresh (run 42440292355, 2026-11-08: EPA's DMR service did not answer and
ingest.echo_cso_dmr_monthly spent 3,219 s, past the workflow's 100 minutes): scripts/timed.sh --cap stops a feed at
its wall-clock cap (the Makefile's FEED_CAP_S, 600 s), and echo_cso_dmr_monthly stops asking after five failed or
timed-out requests in a row. Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

import pytest
import requests

import common
from ingest import echo_cso_dmr_monthly as dmr

ROOT = Path(__file__).resolve().parents[2]
TIMED = str(ROOT / "scripts" / "timed.sh")
needs_sh = pytest.mark.skipif(not shutil.which("sh"), reason="needs sh")


def run(args, tmp_path, **env):
    tf = tmp_path / "t.tsv"
    e = {**os.environ, "TIMINGS_FILE": str(tf), **env}
    t0 = time.monotonic()
    r = subprocess.run(["sh", TIMED, *args], capture_output=True, text=True, env=e, timeout=60)
    return r, time.monotonic() - t0, tf.read_text() if tf.exists() else ""


@needs_sh
def test_a_feed_past_its_cap_is_stopped_logged_and_failed(tmp_path):
    r, took, tsv = run(["--cap", "1", "ingest.slow", "sh", "-c", "echo started; sleep 30; echo never"], tmp_path)
    assert r.returncode == 124 and took < 15
    assert r.stdout.splitlines() == ["started", "timing: ingest.slow 1 s (exit 124, stopped at the cap)"]
    assert tsv == "ingest.slow\t1\n"


@needs_sh
def test_a_feed_within_its_cap_keeps_its_line_and_exit_code(tmp_path):
    r, took, _ = run(["--cap", "20", "ingest.quick", "sh", "-c", "echo out; exit 3"], tmp_path)
    assert r.returncode == 3 and took < 10            # the watchdog does not hold the wrapper to the cap
    assert r.stdout.splitlines()[0] == "out" and r.stdout.splitlines()[1].endswith("s (exit 3)")
    r, _, _ = run(["--cap", "20", "ingest.ok", "true"], tmp_path)
    assert r.returncode == 0 and r.stdout.startswith("timing: ingest.ok ")


@needs_sh
def test_a_feeds_own_cap_and_no_cap_for_a_backfill(tmp_path):
    slow = ["sh", "-c", "sleep 3"]
    # its own cap overrides the default one
    r, _, _ = run(["--cap", "1", "ingest.fl_doh_beaches", *slow], tmp_path, FEED_CAP_ingest_fl_doh_beaches="20")
    assert r.returncode == 0
    r, _, _ = run(["--cap", "20", "ingest.fl_doh_beaches", *slow], tmp_path, FEED_CAP_ingest_fl_doh_beaches="1")
    assert r.returncode == 124
    # 0: no cap; a --backfill run: no cap
    r, _, _ = run(["--cap", "1", "ingest.x", *slow], tmp_path, FEED_CAP_ingest_x="0")
    assert r.returncode == 0
    r, _, _ = run(["--cap", "1", "ingest.y", "sh", "-c", "sleep 3", "--backfill"], tmp_path)
    assert r.returncode == 0


@needs_sh
def test_a_stopped_feed_keeps_its_previous_events_file_whole(tmp_path):
    """The ingesters write their events file once, at the end, through common.write_json (a temporary file, then an
    atomic rename): a feed stopped before that leaves the previous file as it was."""
    events = tmp_path / "x.json"
    events.write_text(json.dumps({"records": [{"event_id": "prev:1"}]}))
    script = (f"import json, time, sys; sys.path.insert(0, {str(ROOT / 'pipeline')!r}); import common; "
              f"time.sleep(30); common.write_json(__import__('pathlib').Path({str(events)!r}), {{'records': []}})")
    r, _, _ = run(["--cap", "1", "ingest.x", str(ROOT / "pipeline" / ".venv" / "bin" / "python")
                   if (ROOT / "pipeline" / ".venv" / "bin" / "python").exists() else "python3", "-c", script], tmp_path)
    assert r.returncode == 124
    assert json.loads(events.read_text()) == {"records": [{"event_id": "prev:1"}]}


def test_the_makefile_caps_every_feed_of_the_ingest_loops():
    mk = (ROOT / "Makefile").read_text()
    assert "FEED_CAP_S ?= 600" in mk and "TIMED_FEED = $(TIMED) --cap $(FEED_CAP_S)" in mk
    recipe = mk.split("\ningest:", 1)[1].split("\n\n", 1)[0]
    runs = [ln for ln in recipe.splitlines() if "-m ingest." in ln and "TIMED" in ln]
    assert runs and all("$(TIMED_FEED)" in ln for ln in runs)


# ---------------------------------------------------------------- echo_cso_dmr_monthly's request budget

PREV = {"source_id": dmr.SOURCE_ID, "fetched_at": "2026-11-07T00:00:00Z", "ok": True, "error": None,
        "last_ok_at": "2026-11-07T00:00:00Z", "meta": {"m": 1}, "count": 1, "records": [{"event_id": "prev:1"}]}


def test_the_dmr_feed_stops_after_five_failed_requests_and_keeps_its_records(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(dmr.time, "sleep", lambda s: None)
    p = tmp_path / f"{dmr.SOURCE_ID}.json"
    p.write_text(json.dumps(PREV))
    calls = []

    def timeout(url, params=None, headers=None, timeout=None):
        calls.append(timeout)
        raise requests.Timeout("read timed out")
    monkeypatch.setattr(dmr.requests, "get", timeout)
    assert dmr.main([]) == 1
    assert len(calls) == dmr.MAX_CONSECUTIVE_FAILURES == 5        # nine requests of three tries were 27 before
    assert all(t == dmr.REQUEST_TIMEOUT and max(t) <= 30 for t in calls)
    out = json.loads(p.read_text())
    assert out["ok"] is False and out["error"].startswith("stopped after 5 failures")
    assert out["records"] == PREV["records"] and out["last_ok_at"] == PREV["last_ok_at"]


def test_a_good_answer_resets_the_count():
    b = dmr.Budget(3)
    b.consecutive = 2
    assert not b.stopped
    b.consecutive += 1
    assert b.stopped
