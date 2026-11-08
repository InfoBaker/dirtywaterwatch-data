"""The standing name review in the hourly refresh (build/name_review.py --standing; 2026-11-04 Florida name-review
review, point (e)): its details under data/build only, counts and never a name in the public log, a ::warning:: for new
candidates to review against the previous run's saved review, and never a block on the publish.
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import name_review as NR  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]


def rep(*cands):
    """A review with these (candidate, auto_redact, verdict) rows (placeholder names)."""
    rows = [{"candidate": c, "count": 1, "sources": {"x": 1}, "fields": {}, "example_event_ids": ["x:1"],
             "example": f"... {c} ...", "contexts": {}, "first_name": None, "auto_redact": a, "verdict": v}
            for c, a, v in cands]
    return {"built": "2026-11-04T00:00:00Z", "by_source": {}, "candidates": rows,
            "totals": {"records": 10, "candidates": len(rows), "occurrences": len(rows),
                       "auto_redacted_candidates": sum(1 for r in rows if r["auto_redact"]), "redactions": 0,
                       "records_changed": 0, "with_first_name": 0, "allowlist": 0, "blocklist": 0}}


def test_only_candidates_still_to_review_count_and_new_ones_raise_a_warning():
    before = rep(("Zeb Quill", False, None), ("Sample Sampleton", True, None))
    after = rep(("Zeb Quill", False, None), ("Sample Sampleton", True, None), ("Example Placeholder", False, None),
                ("Lee Ann", False, "allow"), ("Quill Zeb", True, None))
    lines = NR.standing_lines(before, after)
    assert lines[0] == "name review: 5 candidates in 10 records; 2 removed by the export; 2 to review, 1 new since the last run"
    assert lines[1].startswith("::warning::name review: 1 new candidate names to review since the last run (2 in all)")
    assert NR.standing_lines(after, after) == [
        "name review: 5 candidates in 10 records; 2 removed by the export; 2 to review, 0 new since the last run"]
    first = NR.standing_lines(None, after)
    assert "no earlier review in the saved state" in first[0] and first[1].startswith("::warning::name review: 2 ")


def test_the_standing_review_writes_under_data_build_and_prints_no_name(tmp_path, monkeypatch, capsys):
    out_json, out_md = tmp_path / "build" / "name-review.json", tmp_path / "build" / "name-review.md"
    out_json.parent.mkdir()
    out_json.write_text(json.dumps(rep(("Zeb Quill", False, None))))
    monkeypatch.setattr(NR, "load", lambda d: [])
    monkeypatch.setattr(NR, "review", lambda rows: rep(("Zeb Quill", False, None), ("Sample Sampleton", False, None)))
    assert NR.standing(tmp_path, out_json, out_md) == 0
    out = capsys.readouterr()
    assert "Zeb" not in out.out + out.err and "Sample" not in out.out + out.err
    assert "1 new since the last run" in out.out and "::warning::" in out.out
    assert "Sample Sampleton" in out_json.read_text() and "Sample Sampleton" in out_md.read_text()


def test_a_failing_standing_review_prints_the_exceptions_type_only(tmp_path, monkeypatch, capsys):
    def boom(d):
        raise ValueError("Zeb Quill at 12 Sample Street")
    monkeypatch.setattr(NR, "load", boom)
    assert NR.standing(tmp_path, tmp_path / "r.json", tmp_path / "r.md") == 1
    out = capsys.readouterr()
    assert "Zeb" not in out.out + out.err and "ValueError" in out.out and "::warning::name review failed" in out.out


@pytest.mark.skipif(not shutil.which("sh"), reason="needs sh")
@pytest.mark.parametrize("review_rc,blocked,want_rc", [(0, False, 0), (1, False, 0), (1, True, 1)])
def test_the_refresh_runs_the_review_after_the_export_and_never_blocks_on_it(tmp_path, review_rc, blocked, want_rc):
    """scripts/refresh-data.sh with stand-ins for make, the upload and the Python: the review runs right after
    `make refresh`, and its failure leaves the exit status to the refresh and the export's blocklist check."""
    (tmp_path / "scripts").mkdir()
    for n in ("refresh-data.sh", "timed.sh"):
        shutil.copy(ROOT / "scripts" / n, tmp_path / "scripts" / n)
    (tmp_path / "scripts" / "upload-current.sh").write_text("echo upload >> \"$LOG\"\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "make").write_text("#!/bin/sh\necho \"make $*\" >> \"$LOG\"\n"
                               + ("[ \"$1\" = refresh ] && mkdir -p data/build && echo '{}' > data/build/export-blocked.json\n"
                                  if blocked else "") + "exit 0\n")
    py = tmp_path / "pipeline" / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text(f"#!/bin/sh\necho \"python $* in $(basename \"$PWD\")\" >> \"$LOG\"\nexit {review_rc}\n")
    for f in (bin_ / "make", py):
        f.chmod(0o755)
    log = tmp_path / "log.txt"
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "LOG": str(log)}
    r = subprocess.run(["sh", str(tmp_path / "scripts" / "refresh-data.sh")], capture_output=True, text=True, env=env,
                       timeout=60)
    assert r.returncode == want_rc, r.stdout + r.stderr
    calls = log.read_text().splitlines()
    # the daily-pass check comes first (any answer but 3 runs the review: 0 due, 1 a failed check), and a good review
    # is recorded (pipeline/cadence.py; 2026-11-07 refresh-time brief)
    assert calls[:3] == ["make refresh", "python -m cadence daily name-review in pipeline",
                         "python -m build.name_review --standing in pipeline"]
    assert ("python -m cadence ran name-review in pipeline" in calls) is (review_rc == 0)
    assert ("upload" in calls) is (not blocked)
    assert ("name review failed: not blocking" in r.stdout) is (review_rc != 0)


@pytest.mark.skipif(not shutil.which("sh"), reason="needs sh")
def test_the_refresh_skips_the_review_when_it_ran_in_the_last_day(tmp_path):
    """pipeline/cadence.py daily answers 3 (the review ran well less than a day ago): no review this run, the rest as
    before."""
    (tmp_path / "scripts").mkdir()
    for n in ("refresh-data.sh", "timed.sh"):
        shutil.copy(ROOT / "scripts" / n, tmp_path / "scripts" / n)
    (tmp_path / "scripts" / "upload-current.sh").write_text("echo upload >> \"$LOG\"\n")
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    (bin_ / "make").write_text("#!/bin/sh\necho \"make $*\" >> \"$LOG\"\nexit 0\n")
    py = tmp_path / "pipeline" / ".venv" / "bin" / "python"
    py.parent.mkdir(parents=True)
    py.write_text('#!/bin/sh\necho "python $*" >> "$LOG"\ncase "$*" in "-m cadence daily"*) exit 3 ;; esac\nexit 0\n')
    for f in (bin_ / "make", py):
        f.chmod(0o755)
    log = tmp_path / "log.txt"
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "LOG": str(log)}
    r = subprocess.run(["sh", str(tmp_path / "scripts" / "refresh-data.sh")], capture_output=True, text=True, env=env,
                       timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr
    calls = log.read_text().splitlines()
    assert not any("build.name_review" in c for c in calls) and "upload" in calls
    assert "name review: on its daily pass, not due this run" in r.stdout
