"""A --names ... --hand-only run (ingest/waters_from_nhd.py names_hand_only) keeps what the last full build wrote: every
other name's row whole (reason_detail and notes included), the names file's note of the last full build (under
last_build, the run's own note naming --hand-only), and the full build's statistics (the run's go under
stats.state_builds.<ST>.report_names_hand_only). Review of 2026-11-06 (docs/reviews/2026-11-06-ca-bays-review.md in
the site repository), P2-1 and P3-1. No network.
Run from pipeline/: python -m pytest tests/test_hand_only_provenance.py -q
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import waters_from_nhd as N  # noqa: E402

FULL = {"date": "2026-11-04", "command": "python -m ingest.waters_from_nhd --names research/ca/receiving-waters-missing.json "
        "--state CA", "records_built": 13, "names_resolved": 14, "network_requests": 182, "stopped": "--budget-s used"}


def _target(name):
    return {"key": ("name", "CA", name), "state": "CA", "name": name, "names": [], "texts": Counter({name: 1}),
            "outfalls": 0, "events": 2, "points": [], "towns": Counter()}


def test_a_hand_only_run_writes_the_last_builds_row_back_whole(tmp_path, monkeypatch):
    prev = {"name": "Foo Creek", "from": N.REPORT_ROWS, "state": "CA", "slugs": [], "how": ["asked NHD"],
            "reason": "no NHD flowline or waterbody of that name in CA", "reason_detail": ["(--budget-s used)"],
            "notes": ["the status resolver gives the name to foo-ca (another name)"], "defined_by": None}
    out = tmp_path / "waters-nhd.json"
    out.write_text(json.dumps({"waters": [], "targets": [prev]}))
    monkeypatch.setattr(N, "OUT", out)
    monkeypatch.setattr(N, "HAND", [])
    monkeypatch.setattr(N.Towns, "load", lambda self, state: ([], None))
    seen = {}

    def finish(*a, **k):
        seen["rows"], seen["hand_only"] = a[11].rows, k.get("hand_only")
        return 0
    monkeypatch.setattr(N, "names_finish", finish)
    args = SimpleNamespace(refresh=False, offline=True, max_requests=0, budget_s=None)
    assert N.names_hand_only(args, tmp_path / "names.json", {}, "CA", [], [_target("Foo Creek")], [], {}, {}) == 0
    row = [r for r in seen["rows"] if r["name"] == "Foo Creek"][0]
    for k in ("how", "reason", "reason_detail", "notes"):
        assert row[k] == prev[k]
    assert seen["hand_only"] is True


def test_the_hand_only_note_keeps_the_last_full_build():
    recheck = {"date": "2026-11-06", "command": FULL["command"] + " --recheck", "records_built": 0, "last_build": FULL}
    assert N.kept_build_note({"build": recheck}) == FULL
    assert N.kept_build_note({"build": FULL}) == FULL
    hand = {"date": "2026-11-06", "command": FULL["command"] + " --hand-only", "records_built": 3}
    assert N.kept_build_note({"build": hand}) is None          # a hand-only note is never taken for a full build
    assert N.kept_build_note({}) is None


def test_the_names_file_note_names_the_hand_only_run(tmp_path):
    path = tmp_path / "names.json"
    stats = {"built": "2026-11-06T06:00:00Z", "file": "research/ca/receiving-waters-missing.json", "records": 3,
             "network_requests": 0}
    N.rewrite_names(path, {"state": "CA"}, "CA", [], [], {}, stats,
                    command=f"python -m ingest.waters_from_nhd --names {stats['file']} --state CA --hand-only",
                    last_build=N.kept_build_note({"build": {"command": "x --recheck", "last_build": FULL}}))
    note = json.loads(path.read_text())["build"]
    assert note["command"].endswith("--hand-only") and note["records_built"] == 3 and note["last_build"] == FULL


def test_hand_only_statistics_do_not_replace_the_full_builds(tmp_path, monkeypatch):
    out = tmp_path / "waters-nhd.json"
    full = {"records": 13, "targets_mapped": 15, "stopped": "--budget-s used"}
    out.write_text(json.dumps({"waters": [], "targets": [], "skipped": [], "problems": [],
                               "stats": {"state_builds": {"CA": {"report_names": full, "targets": 9}}}}))
    monkeypatch.setattr(N, "OUT", out)
    N.write_output([], [], [], [], partial=True, stats={"CA": {"records": 3}}, final=True, scope_states={"CA"},
                   rows_from=N.REPORT_ROWS, stats_key="report_names_hand_only")
    ca = json.loads(out.read_text())["stats"]["state_builds"]["CA"]
    assert ca["report_names"] == full and ca["targets"] == 9
    assert ca["report_names_hand_only"]["records"] == 3
