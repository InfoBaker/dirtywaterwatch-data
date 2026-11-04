"""California Beach Watch advisories (pipeline/ingest/ca_beachwatch.py). The fixture is invented; its personal fields
are placeholders that must never reach a record.
Run from pipeline/: python -m pytest tests/test_ca_beachwatch.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

from ingest import ca_beachwatch as M

FIX = Path(__file__).resolve().parent / "fixtures" / "ca_beachwatch_advisories.json"
FETCHED = "2026-11-04T10:00:00Z"


def rows():
    return [{k: x.get(k) for k in M.FIELDS} for x in json.loads(FIX.read_text())["result"]["records"]]


def recs(prev=()):
    rs = rows()
    out, stats = M.build(rs, FETCHED, M.as_of(rs), list(prev))
    return {r["source_record_id"]: r for r in out}, stats


def test_a_sewage_closure_keeps_the_countys_times_and_cause():
    r, _ = recs()
    a = r["80001"]
    assert a["event_type"] == "beach_closure" and a["status"] == "advisory_lifted"
    assert a["started_at"] == "2026-01-10T09:30:00-08:00" and a["ended_at"] == "2026-01-13T15:00:00-08:00"
    assert a["time_precision"] == "minute" and a["raw"]["cause"] == "Sewage Spill" and a["raw"]["sewage_cause"] is True
    assert a["volume_gal"] == 12000 and a["outfall_name"] == "Sample Beach - Sample Pier"
    assert a["lat"] == 32.7 and a["lon"] == -117.2


def test_an_open_posting_ages_from_the_date_the_table_is_current_to_and_a_signless_longitude_is_repaired():
    r, stats = recs()
    a = r["80002"]
    assert a["status"] == "advisory_active" and a["ended_at"] is None
    assert a["source_updated_at"] == "2026-03-05" == stats["current_to"]
    assert a["lon"] == -118.07


def test_a_date_only_rain_advisory_is_day_precision_and_an_end_before_the_start_is_not_used():
    r, _ = recs()
    assert r["80003"]["event_type"] == "rain_advisory" and r["80003"]["time_precision"] == "day"
    b = r["80004"]
    assert b["ended_at"] is None and b["status"] == "advisory_active" and "before" in b["raw"]["_end_not_used"]


def test_records_outside_the_read_window_are_kept():
    r, _ = recs()
    old = dict(r["80001"], event_id="ca-beachwatch-advisories:70000", source_record_id="70000")
    r2, stats = recs(prev=[old])
    assert "70000" in r2 and stats["kept_from_earlier_runs"] == 1


def test_personal_fields_never_reach_a_record():
    r, _ = recs()
    text = json.dumps(list(r.values()))
    for p in ("Pat Example", "Robin Placeholder", "619-555-0123", "448 Example"):
        assert p not in text
