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


def test_case_variants_of_a_name_keep_their_own_rows():
    """'Dry Creek' (resolved) and 'Dry creek' (not) are two report targets: each keeps its own last row (review of
    2026-11-06, ca-merge P2-2); a spelling with no exact row falls back to the compact form only when it is unique."""
    rows = [{"name": "Dry Creek", "slugs": ["dry-creek-antelope-ca"], "reason": None},
            {"name": "Dry creek", "slugs": [], "reason": "57 NHD waters of that name in CA"},
            {"name": "Foo Creek", "slugs": ["foo-creek-ca"], "reason": None}]
    last = N.LastRows(rows)
    assert last.get("Dry Creek")["slugs"] == ["dry-creek-antelope-ca"]
    assert last.get("Dry creek")["slugs"] == []
    assert last.get("DRY CREEK") is None                    # two rows share the compact form: neither is guessed
    assert last.get("FOO CREEK")["slugs"] == ["foo-creek-ca"]


def test_a_hand_only_run_keeps_each_case_variants_row(tmp_path, monkeypatch):
    rows = [{"name": "Dry Creek", "from": N.REPORT_ROWS, "state": "CA", "slugs": ["dry-creek-antelope-ca"],
             "how": ["GNIS name in CA"], "reason": None},
            {"name": "Dry creek", "from": N.REPORT_ROWS, "state": "CA", "slugs": [], "how": [],
             "reason": "57 NHD waters of that name in CA"}]
    out = tmp_path / "waters-nhd.json"
    out.write_text(json.dumps({"waters": [], "targets": rows}))
    monkeypatch.setattr(N, "OUT", out)
    monkeypatch.setattr(N, "HAND", [])
    monkeypatch.setattr(N.Towns, "load", lambda self, state: ([], None))
    seen = {}
    monkeypatch.setattr(N, "names_finish", lambda *a, **k: seen.setdefault("rows", a[11].rows) and 0)
    args = SimpleNamespace(refresh=False, offline=True, max_requests=0, budget_s=None)
    N.names_hand_only(args, tmp_path / "names.json", {}, "CA", [], [_target("Dry Creek"), _target("Dry creek")], [],
                      {}, {})
    by = {r["name"]: r for r in seen["rows"]}
    assert by["Dry Creek"]["slugs"] == ["dry-creek-antelope-ca"] and by["Dry Creek"]["reason"] is None
    assert by["Dry creek"]["slugs"] == [] and by["Dry creek"]["reason"].startswith("57 NHD")


def test_the_names_file_follows_a_tidys_drops_and_renames(tmp_path):
    """A slug the tidy dropped or renamed is replaced in the names file's resolved names and rows (review of the CA
    merge, P3-1); a slug the tidy did not touch stays."""
    path = tmp_path / "names.json"
    path.write_text(json.dumps({"state": "CA", "rows": [{"name": "X", "reports": 1, "records": ["mission-creek-ca"]}],
                                "resolved": [{"name": "Mission Creek", "reports": 2, "slugs": ["mission-creek-ca"]},
                                             {"name": "Mare Island Strait", "reports": 1,
                                              "slugs": ["mare-island-strait-vallejo-ca", "napa-river-ca"]}]}))
    actions = [{"slug": "mission-creek-ca", "action": "renamed", "to": "mission-creek-mission-canyon-ca"},
               {"slug": "mare-island-strait-vallejo-ca", "action": "dropped", "to": "mare-island-strait-ca"},
               {"slug": None, "action": "mapped", "to": "san-francisco-bay-ca", "row": "SF Bay"}]
    assert N.names_follow_tidy(path, actions) == 3
    doc = json.loads(path.read_text())
    assert doc["rows"][0]["records"] == ["mission-creek-mission-canyon-ca"]
    assert doc["resolved"][0]["slugs"] == ["mission-creek-mission-canyon-ca"]
    assert doc["resolved"][1]["slugs"] == ["mare-island-strait-ca", "napa-river-ca"]
    assert N.names_follow_tidy(path, []) == 0
