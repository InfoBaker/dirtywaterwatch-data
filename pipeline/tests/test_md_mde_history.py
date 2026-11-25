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


HEADER = ROWS.decode().splitlines()[0]


def build(extra=None, text: bytes = ROWS):
    _, block = runner.load_source(SID)
    rows = socrata.parse(block, text)
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
        assert planted in text
    assert any("notes" in r["raw"]["row"] for r in recs)


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
    assert "same start day, address and type" in both["raw"]["_duplicate_basis"]
    assert stats["duplicates"]["in_2023_table"] == 1
    # without the 2023 table's record nothing is marked across tables
    _, _, alone, stats2 = build()
    assert by_owner(alone, "Baltimore County DPW")[0].get("duplicate_of") is None
    assert stats2["duplicates"]["in_2023_table"] == 0


def small_block_dir(tmp_path, min_rows=5) -> Path:
    """The real source record with min_rows lowered to fit the seven-row fixture."""
    d = tmp_path / "sources"
    d.mkdir(exist_ok=True)
    text = (runner.SOURCES_DIR / f"{SID}.yaml").read_text()
    assert "  min_rows: 27000" in text
    (d / f"{SID}.yaml").write_text(text.replace("  min_rows: 27000", f"  min_rows: {min_rows}"))
    return d


def newer_events(tmp_path) -> None:
    permits, _ = M.load_dischargers()
    newer, _ = M.build(M.read_rows(NEWER_CSV), {"rowsUpdatedAt": 1763600000}, FETCHED, [], [], permits)
    (tmp_path / "events").mkdir(exist_ok=True)
    (tmp_path / "events" / "md-mde-overflows.json").write_text(json.dumps({"ok": True, "records": newer}))


def saved(tmp_path):
    rows_csv, meta = tmp_path / "rows.csv", tmp_path / "meta.json"
    rows_csv.write_bytes(ROWS)
    meta.write_text(json.dumps(META))
    return rows_csv, meta


def test_an_unchanged_table_keeps_its_records_without_reading_the_rows(tmp_path, monkeypatch):
    rows_csv, meta = saved(tmp_path)
    out = tmp_path / "md-hist.json"
    monkeypatch.setattr(runner, "EVENTS_DIR", tmp_path / "events")
    newer_events(tmp_path)
    src = small_block_dir(tmp_path)
    assert runner.run(SID, file=str(rows_csv), meta_file=str(meta), out=str(out), sources_dir=src) == 0
    doc = json.loads(out.read_text())
    assert doc["ok"] and len(doc["records"]) == 7 and doc["meta"]["table_version"] == "1677163934"
    assert doc["meta"]["duplicates"]["in_2023_table"] == 1
    _, block = runner.load_source(SID, src)
    monkeypatch.setattr(socrata, "current_version", lambda b, s: "1677163934")
    msg = runner.keep_unchanged(SID, block, out, "2026-11-21T15:00:00Z")
    assert msg and "unchanged" in msg
    kept = json.loads(out.read_text())
    assert len(kept["records"]) == 7 and kept["meta"]["checked_at"] == "2026-11-21T15:00:00Z"
    monkeypatch.setattr(socrata, "current_version", lambda b, s: "1999999999")
    assert runner.keep_unchanged(SID, block, out, "2026-11-21T16:00:00Z") is None     # a new version is read


def test_a_cut_off_download_is_never_accepted_as_the_frozen_table(tmp_path, monkeypatch):
    """Astra 2026-11-21 P2-4: with no earlier run, min_rows_ratio has nothing to compare; min_rows does."""
    rows_csv, meta = saved(tmp_path)
    out = tmp_path / "md-hist.json"
    monkeypatch.setattr(runner, "EVENTS_DIR", tmp_path / "events")
    newer_events(tmp_path)
    assert runner.run(SID, file=str(rows_csv), meta_file=str(meta), out=str(out),
                      sources_dir=small_block_dir(tmp_path, min_rows=8)) == 1
    doc = json.loads(out.read_text())
    assert doc["ok"] is False and doc["records"] == [] and "expects at least 8" in doc["error"]
    _, real = runner.load_source(SID)
    assert real["min_rows"] == 27000 and runner.validate_block(real, SID) == []
    assert runner.validate_block({**real, "min_rows": 0}, SID) and runner.validate_block({**real, "min_rows": True}, SID)


def test_a_read_without_the_2023_tables_events_file_is_not_kept(tmp_path, monkeypatch):
    """Astra 2026-11-21 P2-5: the table is then asked only for its version, so a read kept without the cross-table
    check would never be checked; the run fails and the next run reads the table again."""
    rows_csv, meta = saved(tmp_path)
    out = tmp_path / "md-hist.json"
    monkeypatch.setattr(runner, "EVENTS_DIR", tmp_path / "events")
    assert runner.run(SID, file=str(rows_csv), meta_file=str(meta), out=str(out),
                      sources_dir=small_block_dir(tmp_path)) == 1
    doc = json.loads(out.read_text())
    assert doc["ok"] is False and "md-mde-overflows.json" in doc["error"]


ROW = ("SSO,{owner},{npdes},01/04/2023,{time},,,,{loc},21216,,{vol},{vol},Blockage,,Unknown,Baltimore City,,,,,")


def csv_of(*rows: str) -> bytes:
    return ("\n".join([HEADER, *rows]) + "\n").encode()


def newer_of(*rows: str) -> list[dict]:
    permits, _ = M.load_dischargers()
    head = NEWER_CSV.splitlines()[0]
    recs, _ = M.build(M.read_rows("\n".join([head, *rows]) + "\n"), {"rowsUpdatedAt": 1763600000}, FETCHED, [], [],
                      permits)
    return recs


def newer_row(time: str, loc: str = "3637 Example Road", kind: str = "SSO") -> str:
    return (f"{kind},Example Collection System,MDCPRIVAT,01/04/2023,{time},0,1,0,{loc},21216,Baltimore County DPW,5,"
            f"Blockage,None,Baltimore City,,,,1")


def test_reports_with_different_known_times_types_or_several_candidates_are_not_joined_across_tables():
    """Astra 2026-11-21 P1-1: a match needs one 2023 record with the same day, address and type, and times that agree
    (equal, or one known only to the day)."""
    old_at_8 = csv_of(ROW.format(owner="Baltimore County DPW", npdes="N/A", time="08:00:00 AM", loc="3637 Example Rd.", vol=5))
    _, _, recs, stats = build({"md_mde_records": newer_of(newer_row("20:00:00"))}, old_at_8)
    assert recs[0].get("duplicate_of") is None and stats["duplicates"]["in_2023_table"] == 0
    _, _, recs, _ = build({"md_mde_records": newer_of(newer_row("08:00:00"))}, old_at_8)
    assert recs[0]["duplicate_of"]                                                    # the same minute: one report
    _, _, recs, _ = build({"md_mde_records": newer_of(newer_row("08:00:00", kind="CSO"))}, old_at_8)
    assert recs[0].get("duplicate_of") is None                                        # another type
    day_only = csv_of(ROW.format(owner="Baltimore County DPW", npdes="N/A", time="", loc="3637 Example Rd.", vol=5))
    two = newer_of(newer_row("09:00:00"), newer_row("15:00:00"))
    _, _, recs, stats = build({"md_mde_records": two}, day_only)
    assert recs[0].get("duplicate_of") is None and stats["duplicates"]["in_2023_table_ambiguous"] == 1


def test_a_2023_record_that_is_itself_a_copy_passes_the_link_to_its_original():
    """Astra 2026-11-21 P2-6: a 2023 record already duplicate_of the City's own SSO record still matches."""
    newer = newer_of(newer_row("12:00:00"))
    newer[0]["duplicate_of"] = "md-baltimore-sso:123"
    _, _, recs, _ = build({"md_mde_records": newer})
    both = by_owner(recs, "Baltimore County DPW")[0]
    assert both["duplicate_of"] == "md-baltimore-sso:123"
    assert "itself a copy of md-baltimore-sso:123" in both["raw"]["_duplicate_basis"]


def test_rows_sharing_a_key_but_naming_another_owner_or_volume_are_both_kept():
    """Astra 2026-11-21 P1-2: with no time and no address the key is permit and day; two owners' reports are two."""
    text = csv_of(ROW.format(owner="City of Baltimore", npdes="N/A", time="", loc="", vol=100),
                  ROW.format(owner="City of Cumberland", npdes="N/A", time="", loc="", vol=100),
                  ROW.format(owner="City of Cumberland", npdes="N/A", time="", loc="", vol=100),
                  ROW.format(owner="City of Cumberland", npdes="N/A", time="", loc="", vol=250))
    _, _, recs, stats = build({}, text)
    assert len(recs) == 4 and len({r["event_id"] for r in recs}) == 4
    copies = [r for r in recs if r.get("duplicate_of")]
    assert len(copies) == 1 and copies[0]["volume_gal"] == 100
    assert copies[0]["raw"]["row"]["municipality_facility"] == "City of Cumberland"
    assert stats["duplicates"]["same_key_kept_apart"] == 2
    assert all("_same_key_kept" in r["raw"] for r in recs if not r.get("duplicate_of") and "~" in r["event_id"])


def test_an_older_spelling_keeps_the_owner_over_another_operators_permit():
    """Astra 2026-11-21 P1-3: the 2023 rule (the owner filed the report) applies to the older spellings too."""
    text = csv_of(ROW.format(owner="City of Baltimore", npdes="MDC121555", time="", loc="1 Example St.", vol=10))
    _, _, recs, _ = build({}, text)
    assert recs[0]["discharger_id"] == "md-baltimore-city-dpw"
    basis = recs[0]["raw"]["_discharger_basis"]
    assert "md-baltimore-county-dpw" in basis and "2005-2023 table's spelling" in basis
    # every older spelling maps to an operator the 2023 table also spells
    assert all(T._canonical_spelling(did) for did in T.MD_HISTORY_OWNERS.values())


def test_a_removed_name_is_no_owner_and_invents_no_operator():
    """Astra 2026-11-21 P2-7: "[name removed]" never becomes the operator id md-name-removed."""
    text = csv_of(ROW.format(owner="[name removed]", npdes="N/A", time="", loc="2 Example St.", vol=10),
                  ROW.format(owner="[name removed]", npdes="MD0021598", time="", loc="3 Example St.", vol=10))
    _, _, recs, _ = build({}, text)
    by_loc = {r["outfall_name"]: r for r in recs}
    assert by_loc["2 Example St."]["discharger_id"] is None
    assert by_loc["3 Example St."]["discharger_id"] == "md-cumberland"                # the permit still names it
