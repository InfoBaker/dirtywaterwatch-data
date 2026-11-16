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


def ID(start, location):
    return M.record_ids([{"start": start, "location": location}])[0]


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
    r = by_id(recs)[ID("06/17/2024", "Goat Canyon")]
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
    h = by_id(recs)[ID("06/17/2024", "Hollister Street Pump Station")]
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
    t = by_id(recs)[ID("10/11/2023", "Tijuana River")]
    assert t["source_updated_at"] == "2026-04-30"                  # "Volume reported by USIBWC on 04/30/2026"
    assert "04/30/2026" in t["raw"]["_source_updated_basis"]
    assert by_id(recs)[ID("06/17/2024", "Goat Canyon")]["source_updated_at"] is None
    # the first time a row was seen is kept across runs
    later, _ = M.build(rows(), "2026-11-16T22:00:00Z", recs, NONE_PLACED)
    assert by_id(later)[ID("06/17/2024", "Goat Canyon")]["raw"]["_first_seen_at"] == AT


def test_ongoing_is_ongoing_with_no_end_and_a_blank_end_is_never_made_up():
    recs, _ = build()
    t = by_id(recs)[ID("10/11/2023", "Tijuana River")]
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
    r = by_id(recs)[ID("06/17/2024", "Hollister Street Pump Station")]
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
    r = by_id(recs)[ID("06/17/2024", "Hollister Street Pump Station")]
    assert r["event_type"] == "unknown" and r["parse_error"] == "event type not read: 'Odor complaint'"
    # a flow that is not a Spill Event of the facility joins no operator
    f = by_id(build()[0])[ID("3/14/2026", "Stewart's Drain")]
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
    t = by_id(recs)[ID("10/11/2023", "Tijuana River")]
    assert t["water_slugs"] == ["tijuana-river-ca"] and t["water_match"] == "name"
    g = by_id(recs)[ID("06/17/2024", "Goat Canyon")]
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
    gone = by_id(later)[ID("10/11/2023", "Tijuana River")]
    assert gone["raw"]["_missing_from_table_since"] == "2026-11-20T22:00:00Z" and stats["kept_missing_from_table"] == 1
    h = by_id(later)[ID("06/17/2024", "Hollister Street Pump Station")]
    assert h["volume_gal"] == 310_000 and h["raw"]["_revisions"][0]["volume"] == "302,000 gallons"


def test_no_name_or_address_and_no_internal_note_reaches_a_record():
    recs, _ = build()
    blob = json.dumps(recs)
    for word in ("owner", "decision", "@", "research/", "docs/"):
        assert word not in blob


def test_the_feed_writes_only_its_own_file_and_its_records_count_under_california(tmp_path, monkeypatch):
    # the known states are read from data/rules.json and cached; another test may leave a scratch set behind
    monkeypatch.setattr(S, "states", lambda: {"CA", "AZ", "OR"})
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
    t = by_id(recs)[ID("10/11/2023", "Tijuana River")]
    now = datetime(2026, 11, 15, 22, tzinfo=UTC)
    assert [iv for iv in S.event_intervals(t, "CA", now, None, rules) if iv["end"] is None or iv["end"] > now] == []
    s = by_id(recs)[ID("3/14/2026", "Stewart's Drain")]
    ivs = S.event_intervals(s, "CA", datetime(2026, 3, 16, tzinfo=UTC), None, rules)
    assert ivs[0]["rule"] == "discharge" and ivs[0]["color"] == "red"
    assert any(iv["color"] == "yellow" for iv in ivs)


# ---------------------------------------------------------------- review 2026-11-15 (Astra) findings


def test_an_end_after_the_read_is_kept_in_raw_only_and_draws_no_window():
    """P1-1: the shared rule allows ends up to 31 days ahead, so a future end in ended_at would draw a window."""
    rs = rows()
    rs[1].update(start="11/14/2026", end="11/17/2026")
    recs, _ = build(rs)
    r = by_id(recs)[M.record_ids(rs)[1]]
    assert r["status"] == "unknown" and r["ended_at"] is None
    assert r["raw"]["_end_as_published"] == "2026-11-17" and "after the page was read" in r["raw"]["_end_not_used"]
    rules = S.load_rules()
    now = datetime(2026, 11, 15, 22, tzinfo=UTC)
    ivs = S.event_intervals(r, "CA", now, None, rules)
    assert not [iv for iv in ivs if iv["rule"] == "discharge"]
    assert all(iv["end"] is None or iv["end"] < datetime(2026, 11, 17, tzinfo=UTC) or iv["rule"] != "discharge"
               for iv in ivs)


def test_no_name_mailbox_phone_or_house_number_reaches_any_field_or_identifier():
    """P1-2: typed text in the location is scrubbed before it is used anywhere, and identifiers carry no free text."""
    from build import redact
    rs = rows()
    rs[1]["location"] = "Goat Canyon; contact Jane Doe at jane.doe@example.com, phone 619-555-0123"
    rs[2]["location"] = "Goat Canyon near the home at 123 Main Street"
    rs[3]["notes"] = "Call Jane Doe at 619-555-0123 or jane.doe@example.com."
    recs, _ = build(rs)
    blob = json.dumps(redact.redact_events(recs))
    for bad in ("Jane", "Doe", "jane", "555-0123", "example.com", "123 Main"):
        assert bad not in blob, bad
    r = by_id(recs)[M.record_ids(rs)[2]]
    assert r["outfall_name"] == "Goat Canyon near the home at [house number removed] Main Street"
    assert all(set(x["source_record_id"]) <= set("0123456789abcdefghijklmnopqrstuvwxyz-") for x in recs)


def test_identifiers_are_unique_and_never_meet_another_rows():
    """P1-3: same start and location, and a location ending in a number, give distinct keys."""
    rs = [{"start": "06/17/2024", "location": "Goat Canyon"}, {"start": "06/17/2024", "location": "Goat Canyon"},
          {"start": "06/17/2024", "location": "Goat Canyon 2"}]
    ids = M.record_ids(rs)
    assert len(set(ids)) == 3 and ids[1] == ids[0] + "-n2"
    assert M.record_ids(rows()) == M.record_ids(rows())          # stable across reads


def test_a_same_named_water_outside_the_valley_withholds_the_name_even_when_the_name_is_ambiguous():
    """P1-4: two Goat Canyons outside the valley (one in San Diego, USIBWC's town): the name match the status build
    settles by the operator's towns must not take it."""
    waters = {"goat-canyon-ca": {**_water("goat-canyon-ca", "Goat Canyon", [-117.15, 32.80, -117.10, 32.85], "stream"),
                                 "towns": ["San Diego"]},
              "goat-canyon-ca-2": _water("goat-canyon-ca-2", "Goat Canyon", [-120.5, 38.0, -120.4, 38.1], "stream")}
    placed = M.valley_waters(waters)
    assert placed["Goat Canyon"] == {"slugs": [], "elsewhere": ["goat-canyon-ca", "goat-canyon-ca-2"]}
    recs, _ = build(placed=placed)
    res = S.Resolver(waters, [], discharger_towns={"ca-usibwc-south-bay": ["San Diego"], "CA0108928": ["San Diego"]},
                     placement_rules={})
    for r in recs:
        if (r.get("raw") or {}).get("named_water") == "Goat Canyon":
            assert r["waterbody_text"] is None and res.resolve(r)["water_slugs"] == []


def test_a_volume_that_is_not_one_plain_amount_has_no_number():
    """P1-5: ranges, bounds, signs and rates are kept as text, never a total."""
    assert M.gallons(".5 million gallons") == 500_000
    assert M.gallons("1.61 million gallons") == 1_610_000 and M.gallons("41,105 gallons") == 41_105
    for v in ("-100 gallons", "1-2 million gallons", "<1,000 gallons", "1 million gallons/day",
              "1 million gallons per day", "1,00 gallons", "up to 5,000 gallons"):
        assert M.gallons(v) is None, v
    rs = rows()
    rs[1]["volume"] = "<1,000 gallons"
    r = by_id(build(rs)[0])[M.record_ids(rs)[1]]
    assert r["volume_gal"] is None and "<1,000 gallons" in r["volume_text"] and "volume not read" in r["parse_error"]


def test_only_an_end_that_says_ongoing_is_ongoing():
    """P1-6: "No longer ongoing" is not ongoing."""
    rs = rows()
    rs[1]["end"] = "No longer ongoing"
    rs[2]["end"] = "Ongoing, stopped 11/2"
    recs, _ = build(rs)
    for i in (1, 2):
        r = by_id(recs)[M.record_ids(rs)[i]]
        assert r["status"] == "unknown" and r["ended_at"] is None and "end not read" in r["parse_error"]


def test_a_change_of_the_notes_alone_is_kept_as_a_revision():
    """P2-7."""
    recs, _ = build()
    rs = rows()
    rs[0]["notes"] = rs[0]["notes"].replace("04/30/2026", "05/31/2026")
    later, _ = M.build(rs, "2026-11-20T22:00:00Z", recs, NONE_PLACED)
    t = by_id(later)[ID("10/11/2023", "Tijuana River")]
    assert t["source_updated_at"] == "2026-05-31" and "04/30/2026" in t["raw"]["_revisions"][0]["notes"]


def test_a_failed_request_is_not_repeated_within_six_hours(tmp_path, monkeypatch):
    """P2-8: one request at most every six hours, a failed one included; the failed health stays."""
    out, state = tmp_path / "e.json", tmp_path / "s.json"
    assert M.main(["--file", str(FIX), "--out", str(out), "--state", str(state)]) == 0
    calls = []

    class Fail:
        status_code = 503

        def raise_for_status(self):
            raise RuntimeError("503")

    monkeypatch.setattr(M.requests, "get", lambda *a, **k: calls.append(1) or Fail())
    times = iter(["2026-11-15T12:00:00Z", "2026-11-15T13:00:00Z", "2026-11-15T19:00:00Z"])
    monkeypatch.setattr(M, "now_iso", lambda: next(times))
    json.dump({"fetched_at": "2026-11-15T05:00:00Z", "last_rows": 16}, state.open("w"))
    assert M.main(["--out", str(out), "--state", str(state)]) == 1 and len(calls) == 1
    assert M.main(["--out", str(out), "--state", str(state)]) == 0 and len(calls) == 1      # within six hours
    doc = json.loads(out.read_text())
    assert doc["ok"] is False and len(doc["records"]) == 16
    assert M.main(["--out", str(out), "--state", str(state)]) == 1 and len(calls) == 2      # seven hours later


# ---------------------------------------------------------------- second review (fixes) 2026-11-15


def test_the_key_hashes_the_scrubbed_location_so_a_removed_house_number_cannot_be_recovered():
    a = M.record_ids([{"start": "06/17/2024", "location": "Goat Canyon near the home at 123 Main Street"}])[0]
    b = M.record_ids([{"start": "06/17/2024", "location": "Goat Canyon near the home at 4567 Main Street"}])[0]
    assert a == b and len(a.rsplit("-", 1)[1]) == 10


def test_ongoing_that_says_it_has_not_stopped_is_ongoing():
    rs = rows()
    rs[1].update(start="11/14/2026", end="Ongoing (has not stopped)")
    r = by_id(build(rs)[0])[M.record_ids(rs)[1]]
    assert r["status"] == "ongoing" and r["ended_at"] is None and r["parse_error"] is None


def test_an_unread_volume_recovered_gets_a_parse_note():
    rs = rows()
    rs[1]["recovered"] = "<1,000 gallons"
    r = by_id(build(rs)[0])[M.record_ids(rs)[1]]
    assert r["raw"]["volume_recovered_gal"] is None and "<1,000 gallons recovered" in r["volume_text"]
    assert r["parse_error"] == "volume recovered not read: '<1,000 gallons'"


def test_a_value_the_final_redaction_changed_is_no_revision_when_the_source_is_unchanged():
    from build import redact
    rs = rows()
    rs[1]["notes"] = "A resident, Jane Doe, reported the spill."
    recs = redact.redact_events(build(rs)[0])
    rid = M.record_ids(rs)[1]
    assert "Jane" not in json.dumps(by_id(recs)[rid])
    for day in ("2026-11-16T22:00:00Z", "2026-11-17T22:00:00Z"):
        recs = redact.redact_events(M.build(rs, day, recs, NONE_PLACED)[0])
    assert "_revisions" not in by_id(recs)[rid]["raw"]
    assert M.same_text("Flows [name removed] here", "Flows Jane Doe here")
    assert not M.same_text("Flows [name removed] here", "Flows Jane Doe there")
