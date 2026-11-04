"""The hourly log names where the time goes (2026-11-04: the first run with NC, GA and FL took 56 minutes and only the
timestamps told which step): every feed, extra and refresh stage prints "timing: NAME SECONDS s" (scripts/timed.sh),
collected in TIMINGS_FILE, and scripts/refresh-data.sh lists the longest at the end.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
pytestmark = pytest.mark.skipif(not shutil.which("sh") or not shutil.which("make"), reason="needs sh and make")


def test_timed_prints_one_line_keeps_the_exit_code_and_collects_the_seconds(tmp_path):
    tf = tmp_path / "t.tsv"
    env = {**os.environ, "TIMINGS_FILE": str(tf)}
    ok = subprocess.run(["sh", str(ROOT / "scripts" / "timed.sh"), "ingest.demo", "sh", "-c", "echo hello"],
                        capture_output=True, text=True, env=env)
    # whole seconds from date +%s: the count depends on the machine's load, so only its form is checked (a test that
    # expected 0 or 1, and 1 or 2 around a sleep, failed on a busy runner)
    assert ok.returncode == 0 and ok.stdout.splitlines()[0] == "hello"
    assert re.fullmatch(r"timing: ingest\.demo \d+ s", ok.stdout.splitlines()[1])
    bad = subprocess.run(["sh", str(ROOT / "scripts" / "timed.sh"), "stage.x", "sh", "-c", "echo out; echo err >&2; exit 3"],
                         capture_output=True, text=True, env=env)
    assert bad.returncode == 3 and bad.stderr == "err\n"
    assert bad.stdout.splitlines()[0] == "out" and re.fullmatch(r"timing: stage\.x \d+ s \(exit 3\)", bad.stdout.splitlines()[1])
    assert re.fullmatch(r"ingest\.demo\t\d+\nstage\.x\t\d+\n", tf.read_text())


def test_make_refresh_times_every_feed_extra_step_and_stage(tmp_path):
    """make refresh with a stand-in Python (prints nothing, exits 0): the order of the stages is the old refresh
    target's, and each feed module, extra and stage has its timing line."""
    stub = tmp_path / "python"
    stub.write_text("#!/bin/sh\nexit 0\n")
    stub.chmod(0o755)
    tf = tmp_path / "t.tsv"
    env = {k: v for k, v in os.environ.items() if not k.startswith("MAKE")}
    env.update(TIMINGS_FILE=str(tf), FIXTURES="0")
    r = subprocess.run(["make", "--no-print-directory", "-C", str(ROOT), "refresh", f"PYTHON={stub}"],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode == 0, r.stdout + r.stderr
    names = [line.split("\t")[0] for line in tf.read_text().splitlines()]
    stages = [n for n in names if n.startswith("stage.")]
    assert stages == ["stage.ingest", "stage.provisional-outfalls", "stage.reaches", "stage.build", "stage.charts",
                      "stage.export"]
    for n in ("ingest.fl_doh_beaches", "ingest.nj_outfalls", "ingest.nj_cso_likely", "waters-nhd", "conditions",
              "rainfall", "rain-thresholds", "status"):
        assert n in names, n
    assert all(re.fullmatch(r"timing: \S+ \d+ s", line) for line in r.stdout.splitlines() if line.startswith("timing:"))


def test_make_refresh_stops_at_the_first_stage_that_fails(tmp_path):
    stub = tmp_path / "python"
    stub.write_text('#!/bin/sh\ncase "$*" in *build.status*) exit 2 ;; esac\nexit 0\n')
    stub.chmod(0o755)
    tf = tmp_path / "t.tsv"
    env = {k: v for k, v in os.environ.items() if not k.startswith("MAKE")}
    env.update(TIMINGS_FILE=str(tf), FIXTURES="0")
    r = subprocess.run(["make", "--no-print-directory", "-C", str(ROOT), "refresh", f"PYTHON={stub}"],
                       capture_output=True, text=True, env=env, timeout=120)
    assert r.returncode != 0
    stages = [n for n in (line.split("\t")[0] for line in tf.read_text().splitlines()) if n.startswith("stage.")]
    assert stages[-1] == "stage.build" and "stage.charts" not in stages and "stage.export" not in stages


def test_the_refresh_script_lists_the_longest_steps_at_the_end():
    s = (ROOT / "scripts" / "refresh-data.sh").read_text()
    assert "export TIMINGS_FILE" in s and "summary" in s.split("trap", 1)[1].split("\n", 1)[0]
    assert s.index(": > \"$TIMINGS_FILE\"") < s.index("make refresh")
