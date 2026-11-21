"""Maryland's frozen 2005 to January 2023 overflow table (MDE, Socrata 3rgd-zjxx) as a generic fetch block
(data/sources/md-mde-sewer-overflows-2005-2023.yaml; docs/generic-ingesters.md): its rows read under the 2023
table's column names (ingest/generic/transforms.md_history_row) so ingest/md_mde_overflows.py's coordinate repairs,
operator match and duplicate rules apply; the older table's own operator spellings; a report in both tables kept
once (in the 2023 table); the columns not read (Notes, Penalty Comments); one read, then only the table's version.

Fixture (tests/fixtures/generic/md_mde_2005_2023_rows.csv): seven invented rows in the table's own columns, with
invented names planted in the two columns that are never read. No network.
Run from pipeline/: python -m pytest tests/test_md_mde_history.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

from ingest import md_mde_overflows as M
from ingest.generic import runner, socrata
from ingest.generic import transforms as T

FIX = Path(__file__).parent / "fixtures" / "generic"
SID = "md-mde-sewer-overflows-2005-2023"
FETCHED = "2026-11-21T14:00:00Z"
ROWS = (FIX / "md_mde_2005_2023_rows.csv").read_bytes()
META = json.loads((FIX / "md_mde_2005_2023_meta.json").read_text())
# one 2023-table row: the report the older table also holds (same day and address, timed to the minute here)
NEWER_CSV = (
    "OVERFLOW_TYPE,FACILITY/COLLECTION_SYSTEM,NPDES_NO,START_DATE,START_TIME,DURATION_DAY,DURATION_HOUR,"
    "DURATION_MINUTE,OVERFLOW_ADDRESS,ZIP,OWNER_NAME,DISCHARGE_VOLUME,OVERFLOW_CAUSE,RECEIVING_WATER,COUNTY,"
    "PENALTY_ID,OVERFLOW_LATITUDE,OVERFLOW_LONGITUDE,ID\n"
    "SSO,Example Collection System,MDCPRIVAT,01/04/2023,12:00:00,0,1,0,3637 Example Road,21216,"
    "Baltimore County DPW,5,Blockage,None,Baltimore City,,,,1\n")


def build(extra=None):
    _, block = runner.load_source(SID)
    rows = socrata.parse(block, ROWS)
    recs, stats = runner.build(SID, block, rows, FETCHED, [], META, {"md_baltimore_records": [], "md_mde_records": [],
                                                                    **(extra or {})})
    return block, rows, recs, stats


def by_owner(recs, owner):
    return [r for r in recs if (r["raw"]["row"].get("municipality_facility") or "") == owner]


def test_the_block_is_live_valid_and_reads_the_whole_table_once_then_only_its_version():
    row, block = runner.load_source(SID)
    assert runner.validate_block(block, SID) == []
    assert block["live"] is True and block["dataset"] == "3rgd-zjxx" and block["format"] == "csv"
    assert block["metadata"] is True and block["if_changed"] is True
    assert row["role"] == "events" and row["states"] == ["MD"]


def test_every_row_is_a_record_with_the_mapped_type_times_and_volume():
    _, rows, recs, _ = build()
    assert len(rows) == len(recs) == 7
    assert {r["event_type"] for r in recs} == {"cso", "sso", "bypass"}
    cso = by_owner(recs, "Cumberland, City of")[0]
    assert cso["started_at"] == "2011-03-14T08:15:00-04:00" and cso["time_precision"] == "minute"
    assert cso["ended_at"] == "2011-03-14T14:45:00-04:00" and cso["status"] == "ended"
    assert cso["volume_gal"] == 250000 and cso["npdes_permit"] == "MD0021598"
    # no time of day: read at day precision; no duration: no end is invented
    sso = by_owner(recs, "City of Baltimore")[0]
    assert sso["time_precision"] == "day" and sso["ended_at"] is None and sso["status"] == "unknown"
    assert sso["npdes_permit"] is None                                       # "N/A" is not a permit
    assert all(r["source_updated_at"] == recs[0]["source_updated_at"] is not None for r in recs)
    assert all(r["reported_at"] is None and r["published_at"] is None for r in recs)


def test_notes_and_penalty_comments_are_never_read():
    _, rows, recs, _ = build()
    assert any("Placeholder" in (r.get("notes") or "") for r in rows)          # the fixture plants them
    text = json.dumps(recs)
    for planted in ("Placeholder", "Invented Name", "Second Placeholder", "waived", "odor"):
        assert planted not in text
    assert all(set(r["raw"]["row"]) <= set(runner.load_source(SID)[1]["safe_fields"]) for r in recs)


def test_the_older_tables_operator_spellings_reach_the_research_operators():
    _, _, recs, _ = build()
    assert {r["discharger_id"] for r in by_owner(recs, "Cumberland, City of")} == {"md-cumberland"}
    assert by_owner(recs, "Frostburg, City of")[0]["discharger_id"] == "md-frostburg"      # "City of Frostburg"
    assert {r["discharger_id"] for r in by_owner(recs, "City of Baltimore")} == {"md-baltimore-city-dpw"}
    assert by_owner(recs, "MES")[0]["discharger_id"] == "md-mes"
    # an owner with no research row keeps the id built from its name, as in the 2023 module
    assert by_owner(recs, "Example Private Utility")[0]["discharger_id"] == "md-example-private-utility"
    assert T.md_history_owner("Salisbury, City of") == "md-salisbury"
    assert T.md_history_owner("") is None


def test_the_2023_modules_coordinate_repairs_apply():
    _, _, recs, _ = build()
    cso = by_owner(recs, "Cumberland, City of")[0]
    assert cso["lat"] == 39.6489 and cso["lon"] == -78.7625                       # the longitude's sign added
    assert "minus sign" in cso["raw"]["_coords"]
    assert by_owner(recs, "MES")[0]["lat"] is None


def test_repeated_rows_are_kept_once_and_a_report_in_both_tables_points_at_the_2023_table():
    permits, _ = M.load_dischargers()
    newer, _ = M.build(M.read_rows(NEWER_CSV), {"rowsUpdatedAt": 1763600000}, FETCHED, [], [], permits)
    _, _, recs, stats = build({"md_mde_records": newer})
    twins = by_owner(recs, "City of Baltimore")
    assert len(twins) == 2 and sum(1 for r in twins if r.get("duplicate_of")) == 1
    both = by_owner(recs, "Baltimore County DPW")[0]
    assert both["duplicate_of"] == newer[0]["event_id"]
    assert "same start day and address" in both["raw"]["_duplicate_basis"]
    assert stats["duplicates"]["in_2023_table"] == 1
    # without the 2023 table's record nothing is marked across tables
    _, _, alone, stats2 = build()
    assert by_owner(alone, "Baltimore County DPW")[0].get("duplicate_of") is None
    assert stats2["duplicates"]["in_2023_table"] == 0


def test_an_unchanged_table_keeps_its_records_without_reading_the_rows(tmp_path, monkeypatch):
    rows_csv, meta = tmp_path / "rows.csv", tmp_path / "meta.json"
    rows_csv.write_bytes(ROWS)
    meta.write_text(json.dumps(META))
    out = tmp_path / "md-hist.json"
    monkeypatch.setattr(runner, "EVENTS_DIR", tmp_path / "events")
    assert runner.run(SID, file=str(rows_csv), meta_file=str(meta), out=str(out)) == 0
    doc = json.loads(out.read_text())
    assert doc["ok"] and len(doc["records"]) == 7 and doc["meta"]["table_version"] == "1677163934"
    _, block = runner.load_source(SID)
    monkeypatch.setattr(socrata, "current_version", lambda b, s: "1677163934")
    msg = runner.keep_unchanged(SID, block, out, "2026-11-21T15:00:00Z")
    assert msg and "unchanged" in msg
    kept = json.loads(out.read_text())
    assert len(kept["records"]) == 7 and kept["meta"]["checked_at"] == "2026-11-21T15:00:00Z"
    monkeypatch.setattr(socrata, "current_version", lambda b, s: "1999999999")
    assert runner.keep_unchanged(SID, block, out, "2026-11-21T16:00:00Z") is None     # a new version is read
