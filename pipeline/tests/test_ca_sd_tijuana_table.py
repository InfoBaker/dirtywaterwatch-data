"""San Diego Water Board table of USIBWC spill and transboundary flow events (pipeline/ingest/ca_sd_tijuana_table.py).
The fixture is the page's table section as read on 2026-11-15 (16 rows, page last updated 5/27/26); the tests change
copies of its rows.
Run from pipeline/: python -m pytest tests/test_ca_sd_tijuana_table.py -q
"""
from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path

from build import status as S
from ingest import ca_sd_tijuana_table as M

FIX = Path(__file__).resolve().parent / "fixtures" / "ca_sd_tijuana_table.html"
AT = "2026-11-15T22:00:00Z"
NONE_PLACED: dict = {}


def rows():
    return M.read_rows(FIX.read_text())


def by_id(recs):
    return {r["source_record_id"]: r for r in recs}


def build(rs=None, prev=(), placed=None):
    return M.build(rows() if rs is None else rs, AT, list(prev), NONE_PLACED if placed is None else placed)


def test_the_table_is_read_with_its_seven_columns_and_the_page_date():
    rs = rows()
    assert len(rs) == 16
    assert rs[0] == {"start": "10/11/2023", "end": "Ongoing intermittent flows",
                     "event_type": "Tijuana River Transboundary Flow Events", "location": "Tijuana River",
                     "volume": "66.1 billion gallons", "recovered": "None", "notes": rs[0]["notes"]}
    assert rs[0]["notes"].startswith("Discharge volume consists of cumulative wet and dry weather flows from Mexico.")
    assert rs[-1]["start"] == "3/14/2026" and rs[-1]["location"] == "Stewart's Drain"
    assert M.page_updated(FIX.read_text()) == "2026-05-27"


def test_a_page_without_the_table_is_an_error_not_an_empty_feed():
    import pytest
    with pytest.raises(ValueError):
        M.read_rows("<html><table><tr><th>Beach</th><th>Status</th></tr><tr><td>A</td><td>open</td></tr></table>")


def test_every_row_is_a_record_with_the_sources_own_dates_volume_and_no_point():
    recs, stats = build()
    assert stats["rows_in_table"] == 16 and stats["records"] == 16
    assert stats["by_year"] == {"2023": 1, "2024": 4, "2025": 8, "2026": 3}
    assert stats["by_status"] == {"ended": 15, "ongoing": 1}
    r = by_id(recs)["2024-06-17-goat-canyon"]
    assert r["event_type"] == "sso" and r["status"] == "ended"
    assert (r["started_at"], r["ended_at"], r["time_precision"]) == ("2024-06-17", "2024-09-16", "day")
    assert r["raw"]["time_zone"] == "America/Los_Angeles" and r["raw"]["ended_at_precision"] == "day"
    assert r["volume_gal"] == 40_400_000 and r["estimate_flag"] == "estimated"
    assert r["volume_text"] == "40.4 million gallons (approximate discharge volume); none recovered"
    assert r["raw"]["volume_recovered_gal"] == 0
    assert r["lat"] is None and r["lon"] is None and r["coord_source"] is None
    assert r["discharger_id"] == "ca-usibwc-south-bay" and r["npdes_permit"] == "CA0108928"
    assert r["source_url"] == M.PAGE_URL and r["authority"] == M.AUTHORITY
    assert r["raw"]["event_kinds"] == ["facility_spill", "canyon_collector_flow"]
    h = by_id(recs)["2024-06-17-hollister-street-pump-station"]
    assert h["volume_gal"] == 302_000 and h["raw"]["volume_recovered_gal"] == 48_000
    assert h["volume_text"] == "302,000 gallons (approximate discharge volume); 48,000 gallons recovered"
    assert h["waterbody_text"] is None and h["raw"]["named_water"] is None
    # the two rows that start the same day are two records, keyed by start and location
    assert len({r["event_id"] for r in recs}) == 16


def test_times_are_kept_apart_and_no_report_or_publication_date_is_made_up():
    recs, _ = build()
    for r in recs:
        assert r["reported_at"] is None and r["published_at"] is None
        assert r["fetched_at"] == AT and r["raw"]["_first_seen_at"] == AT
    t = by_id(recs)["2023-10-11-tijuana-river"]
    assert t["source_updated_at"] == "2026-04-30"                  # "Volume reported by USIBWC on 04/30/2026"
    assert "04/30/2026" in t["raw"]["_source_updated_basis"]
    assert by_id(recs)["2024-06-17-goat-canyon"]["source_updated_at"] is None
    # the first time a row was seen is kept across runs
    later, _ = M.build(rows(), "2026-11-16T22:00:00Z", recs, NONE_PLACED)
    assert by_id(later)["2024-06-17-goat-canyon"]["raw"]["_first_seen_at"] == AT


def test_ongoing_is_ongoing_with_no_end_and_a_blank_end_is_never_made_up():
    recs, _ = build()
    t = by_id(recs)["2023-10-11-tijuana-river"]
    assert t["status"] == "ongoing" and t["ended_at"] is None and t["volume_gal"] == 66_100_000_000
    assert t["raw"]["event_kinds"] == ["river_transboundary_flow"] and t["raw"]["transboundary"] is True
    assert t["discharger_id"] is None and t["npdes_permit"] is None and "USIBWC" in t["raw"]["reported_by"]
    rs = rows()
    rs[5]["end"] = ""
    rs[6]["end"] = "Pending"
    recs, _ = build(rs)
    for i in (5, 6):
        rid = M.record_ids(rs)[i]
        r = by_id(recs)[rid]
        assert r["status"] == "unknown" and r["ended_at"] is None, rid
        assert r["started_at"] is not None
    assert by_id(recs)[M.record_ids(rs)[6]]["parse_error"] == "end not read: 'Pending'"


def test_an_end_before_the_start_is_kept_as_published_and_not_used():
    rs = rows()
    rs[1]["end"] = "06/10/2024"                    # Hollister Street, start 06/17/2024
    recs, _ = build(rs)
    r = by_id(recs)["2024-06-17-hollister-street-pump-station"]
    assert r["status"] == "unknown" and r["ended_at"] == "2024-06-10"
    assert "is before the start" in r["raw"]["_end_not_used"] and "ended_at_precision" not in r["raw"]
    now = datetime(2024, 6, 20, tzinfo=UTC)
    assert S.end_not_credible(r, now) is not None   # the status build's shared rule draws no window from it


def test_a_row_with_no_volume_has_none():
    rs = rows()
    rs[2]["volume"] = ""
    rs[3]["volume"] = "None"
    rs[4]["volume"] = "not estimated"
    recs, _ = build(rs)
    ids = M.record_ids(rs)
    for i in (2, 3):
        r = by_id(recs)[ids[i]]
        assert r["volume_gal"] is None and r["estimate_flag"] == "unknown" and r["parse_error"] is None
        assert r["volume_text"] == "none recovered"
    r = by_id(recs)[ids[4]]
    assert r["volume_gal"] is None and r["parse_error"] == "volume not read: 'not estimated'"


def test_the_event_type_follows_the_tables_wording_and_unread_wording_is_unknown():
    assert M.kinds_of("Spill Event") == ["facility_spill"]
    assert M.kinds_of("Spill Event and Dry weather Canyon CollectorTransboundary Flow Event") == \
        ["facility_spill", "canyon_collector_flow"]                    # the page's own run-together spelling
    assert M.kinds_of("Dry Weather Canyon Collector Transboundary Flow Event") == ["canyon_collector_flow"]
    assert M.kinds_of("Tijuana River Transboundary Flow Events") == ["river_transboundary_flow"]
    _, stats = build()
    assert stats["by_kind"] == {"river_transboundary_flow": 1, "facility_spill": 4,
                                "facility_spill+canyon_collector_flow": 8, "canyon_collector_flow": 3}
    rs = rows()
    rs[1]["event_type"] = "Odor complaint"
    recs, _ = build(rs)
    r = by_id(recs)["2024-06-17-hollister-street-pump-station"]
    assert r["event_type"] == "unknown" and r["parse_error"] == "event type not read: 'Odor complaint'"
    # a flow that is not a Spill Event of the facility joins no operator
    f = by_id(build()[0])["2026-03-14-stewarts-drain"]
    assert f["discharger_id"] is None and f["raw"]["transboundary"] is True


def test_the_discharge_location_names_its_water_and_a_facility_its_canyon():
    assert M.water_name("Smuggler's Gulch") == "Smuggler's Gulch"
    assert M.water_name("Smuggler’s Gulch") == "Smuggler's Gulch"
    assert M.water_name("Goat Canyon Pump Station") == "Goat Canyon"
    assert M.water_name("Del Sol Canyon Collector") == "Canyon del Sol"
    assert M.water_name("Hollister Street Pump Station") is None
    _, stats = build()
    assert stats["placed"] == 0 and stats["unplaced"] == 16
    assert stats["unplaced_by_water"] == {"Tijuana River": 1, "Smuggler's Gulch": 5, "Goat Canyon": 4,
                                          "Stewart's Drain": 2, "Silva Drain": 1, "Canyon del Sol": 1,
                                          "(names no water)": 2}


def _water(slug, name, bbox, kind="river"):
    return {"slug": slug, "name": name, "kind": kind, "state": "CA", "towns": [], "bbox": bbox}


def test_a_report_is_placed_only_on_a_water_record_in_the_tijuana_river_valley():
    waters = {"tijuana-river-ca": _water("tijuana-river-ca", "Tijuana River", [-117.13, 32.53, -117.03, 32.56]),
              # a same-named canyon far away (Sierra foothills) is not this one
              "goat-canyon-ca": _water("goat-canyon-ca", "Goat Canyon", [-120.5, 38.0, -120.4, 38.1], "stream"),
              "pacific-ocean-ca": _water("pacific-ocean-ca", "Pacific Ocean", None, "bay")}
    placed = M.valley_waters(waters)
    assert placed["Tijuana River"] == {"slugs": ["tijuana-river-ca"], "elsewhere": []}
    assert placed["Goat Canyon"] == {"slugs": [], "elsewhere": ["goat-canyon-ca"]}
    recs, stats = build(placed=placed)
    t = by_id(recs)["2023-10-11-tijuana-river"]
    assert t["water_slugs"] == ["tijuana-river-ca"] and t["water_match"] == "name"
    g = by_id(recs)["2024-06-17-goat-canyon"]
    assert g["water_slugs"] == [] and g["waterbody_text"] is None and g["raw"]["named_water"] == "Goat Canyon"
    assert stats["placed"] == 1 and stats["unplaced"] == 15
    # the status build places them the same way: the river on its record, the far canyon nowhere, never the ocean
    res = S.Resolver(waters, [], placement_rules={})
    for r in recs:
        got = res.resolve(r)
        assert got["water_slugs"] == (["tijuana-river-ca"] if r is t else []), r["event_id"]


def test_with_the_water_files_on_disk_every_report_resolves_only_to_a_valley_water():
    """The real water files: the status build's placement gives each record its own valley slugs or none, never a
    same-named water elsewhere and never the Pacific Ocean record by the permit's ocean outfall."""
    waters = S.load_waters()
    placed = M.valley_waters(waters)
    recs, _ = build(placed=placed)
    valley = {s for v in placed.values() for s in v["slugs"]}
    res = S.make_resolver(waters)
    for r in recs:
        got = res.resolve(r)
        assert set(got["water_slugs"]) <= valley, (r["event_id"], got)


def test_a_row_that_leaves_the_table_keeps_its_record_and_revisions_are_kept():
    recs, _ = build()
    rs = rows()[1:]
    rs[0]["volume"] = "310,000 gallons"
    later, stats = M.build(rs, "2026-11-20T22:00:00Z", recs, NONE_PLACED)
    gone = by_id(later)["2023-10-11-tijuana-river"]
    assert gone["raw"]["_missing_from_table_since"] == "2026-11-20T22:00:00Z" and stats["kept_missing_from_table"] == 1
    h = by_id(later)["2024-06-17-hollister-street-pump-station"]
    assert h["volume_gal"] == 310_000 and h["raw"]["_revisions"][0]["volume"] == "302,000 gallons"


def test_no_name_or_address_and_no_internal_note_reaches_a_record():
    recs, _ = build()
    blob = json.dumps(recs)
    for word in ("owner", "decision", "@", "research/", "docs/"):
        assert word not in blob


def test_the_feed_writes_only_its_own_file_and_its_records_count_under_california(tmp_path):
    out, state = tmp_path / "e.json", tmp_path / "s.json"
    assert M.main(["--file", str(FIX), "--out", str(out), "--state", str(state)]) == 0
    assert sorted(p.name for p in tmp_path.iterdir()) == ["e.json", "s.json"]
    doc = json.loads(out.read_text())
    assert doc["ok"] is True and len(doc["records"]) == 16
    assert {S.event_state(r) for r in doc["records"]} == {"CA"}
    assert doc["meta"]["page_last_updated"] == "2026-05-27" and doc["meta"]["registry_ids"] == [M.SOURCE_ID]
    # an empty answer is an outage that keeps the records
    bad = tmp_path / "bad.html"
    bad.write_text("<html><body>Service unavailable</body></html>")
    assert M.main(["--file", str(bad), "--out", str(out), "--state", str(state)]) == 1
    doc = json.loads(out.read_text())
    assert doc["ok"] is False and len(doc["records"]) == 16


def test_the_ongoing_river_flow_since_2023_sets_no_colour_now_and_an_ended_spill_its_caution():
    """What the status build makes of these records (the rules of data/rules.json): the ongoing Tijuana River row,
    which started on 2023-10-11, is past the ongoing rule's 30 days, so it sets no colour today; an ended spill is red
    from its start to the end of its end day, then the site's caution."""
    recs, _ = build()
    rules = S.load_rules()
    t = by_id(recs)["2023-10-11-tijuana-river"]
    now = datetime(2026, 11, 15, 22, tzinfo=UTC)
    assert [iv for iv in S.event_intervals(t, "CA", now, None, rules) if iv["end"] is None or iv["end"] > now] == []
    s = by_id(recs)["2026-03-14-stewarts-drain"]
    ivs = S.event_intervals(s, "CA", datetime(2026, 3, 16, tzinfo=UTC), None, rules)
    assert ivs[0]["rule"] == "discharge" and ivs[0]["color"] == "red"
    assert any(iv["color"] == "yellow" for iv in ivs)
