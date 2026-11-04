"""California FHAB bloom reports (pipeline/ingest/ca_swrcb_fhab.py). The fixture is invented; its personal fields
are placeholders that must never reach a record.
Run from pipeline/: python -m pytest tests/test_ca_swrcb_fhab.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

from ingest import ca_swrcb_fhab as M

FIX = Path(__file__).resolve().parent / "fixtures" / "ca_fhab_bloom_reports.json"
FETCHED = "2026-11-04T10:00:00Z"


def recs():
    rows = [{k: x.get(k) for k in M.FIELDS} for x in json.loads(FIX.read_text())["result"]["records"]]
    out, stats = M.build(rows, FETCHED)
    return {r["source_record_id"]: r for r in out}, stats


def test_an_open_advisory_is_active_and_ages_from_its_last_sample():
    r, _ = recs()
    a = r["9001-7001"]
    assert a["event_type"] == "hab_advisory" and a["status"] == "advisory_active"
    assert a["started_at"] == "2026-10-21" and a["ended_at"] is None and a["time_precision"] == "day"
    assert a["source_updated_at"] == "2026-10-28" and a["raw"]["advisory_level"] == "Warning"
    assert a["waterbody_text"] == "Sample Reservoir" and a["lat"] == 38.6


def test_an_advisory_end_lifts_it_and_a_closed_case_lends_its_end_only_when_the_advisory_has_none():
    r, _ = recs()
    assert r["9002-7002"]["status"] == "advisory_lifted" and r["9002-7002"]["ended_at"] == "2026-07-15"
    c = r["9003-7003"]
    assert c["status"] == "advisory_lifted" and c["ended_at"] == "2025-10-01" and "case" in c["raw"]["_end_basis"]


def test_a_new_unassessed_report_is_unknown_and_reports_with_no_advisory_are_left_out_and_counted():
    r, stats = recs()
    assert r["9004"]["status"] == "unknown" and r["9004"]["started_at"] == "2026-10-31"
    assert "9005-7005" not in r and "9006" not in r
    assert stats["left_out"] == {"no advisory recommended": 2}


def test_personal_fields_never_reach_a_record():
    r, _ = recs()
    text = json.dumps(list(r.values()))
    for p in ("Pat Example", "Robin Placeholder", "916-555-0123", "448 Example"):
        assert p not in text
    assert r["9002-7002"]["outfall_name"] == "[house number removed] Example St"
