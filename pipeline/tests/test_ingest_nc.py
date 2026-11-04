"""North Carolina ingesters: DWR sewer overflows (this year's layer and the 2022-2025 history), the coastal swimming
advisory snapshot and the algal bloom reports. Fixtures in tests/fixtures/nc_*.json are small, name-free samples
shaped like the live layers (the personal details in them are invented placeholders that must never reach a record).
Run from pipeline/: python -m pytest tests/test_ingest_nc.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import common
from ingest import nc_algal_blooms as B
from ingest import nc_dwr_sso as S
from ingest import nc_rwq_advisories as R

FIX = Path(__file__).resolve().parent / "fixtures"
FETCHED = "2026-11-04T03:00:00Z"
PERMITS = {"WQCS00002": "nc-raleigh", "WQCS00001": "nc-charlotte-water", "WQCS00006": "nc-greensboro"}
PLACEHOLDERS = ["Pat Example", "919-555-0123", "pat.example@example.com", "Inspector Sample", "Quill, Pat Q.", "Pat Q.",
                "Behind my house", "252-555-0199", "12 Example Lane", "448 Example St", "example_account", "back yard"]


def strings(o):
    if isinstance(o, dict):
        for k, v in o.items():
            yield str(k)
            yield from strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from strings(v)
    elif isinstance(o, str):
        yield o


def no_placeholder(records):
    text = "\n".join(strings(records))
    return [p for p in PLACEHOLDERS if p in text]


def sso_records():
    rows = S._load_file(str(FIX / "nc_dwr_sso_2026.json"))
    recs, stats = S.build(rows, FETCHED, [], PERMITS)
    return {r["source_record_id"]: r for r in recs}, stats


# ---------------------------------------------------------------- this year's SSO layer

def test_times_are_utc_epochs_written_in_eastern_time_and_the_published_start_matches():
    recs, _ = sso_records()
    r = recs["aaaaaaaa-0000-4000-8000-000000000001"]          # globalid braces dropped, lower case
    assert r["event_id"] == "nc-dwr-sso-2026:aaaaaaaa-0000-4000-8000-000000000001"
    assert r["started_at"] == "2026-05-12T08:21:00-04:00"    # Raleigh Water published 8:21 a.m.
    assert r["ended_at"] == "2026-05-12T21:58:00-04:00" and r["status"] == "ended" and r["time_precision"] == "minute"
    assert r["reported_at"] == "2026-05-13T08:00:00-04:00" and r["published_at"] is None
    assert r["discharger_id"] == "nc-raleigh" and r["npdes_permit"] == "WQCS00002"
    assert r["discharger_name"] == "Raleigh Collection System" and r["event_type"] == "sso"
    assert r["waterbody_text"] == "Brier Creek" and r["raw"]["_stream_index"] == "27-33-10"
    assert r["volume_gal"] == 1143800 and r["raw"]["_gallons_to_water"] == 223125 and r["raw"]["reached_water"] is True
    assert r["volume_text"] == "1,143,800 gallons estimated; 223,125 gallons reached surface water"
    assert r["lat"] == 35.870169 and r["coord_source"] == "source" and r["water_slugs"] == []


def test_ongoing_and_the_cautious_reading_of_the_two_reports():
    recs, stats = sso_records()
    r = recs["aaaaaaaa-0000-4000-8000-000000000002"]
    assert r["status"] == "ongoing" and r["ended_at"] is None
    r = recs["aaaaaaaa-0000-4000-8000-000000000003"]           # ongoing per 24 h, the 5-day report gives an end
    assert r["status"] == "ended" and r["ended_at"] == "2026-08-06T10:45:00-04:00"
    assert r["started_at"] == "2026-07-31T09:00:00-04:00"      # the 5-day start is earlier
    assert "start from the 5-day report" in r["raw"]["_times_basis"] and r["raw"]["_ongoing_flag_with_end"]
    assert r["volume_gal"] == 9000 and "larger of the 24-hour and 5-day" in r["volume_text"]
    assert r["raw"]["reached_water"] is True and r["waterbody_text"] == "North Buffalo Creek"
    r = recs["aaaaaaaa-0000-4000-8000-000000000006"]           # not ongoing, but no end time anywhere
    assert r["status"] == "ended" and r["ended_at"] is None and r["raw"]["_end_basis"]
    assert r["event_type"] == "bypass" and r["discharger_id"] is None
    assert r["waterbody_text"] == "CATAWBA RIVER (Lake Hickory below elevation 935)" and r["raw"]["_stream_index"] == "11-(51)"
    assert stats["by_status"] == {"ended": 5, "ongoing": 1}


def test_an_end_before_the_start_is_not_used_and_a_point_outside_the_state_is_dropped():
    recs, _ = sso_records()
    r = recs["aaaaaaaa-0000-4000-8000-000000000005"]
    assert r["ended_at"] == "2026-02-13T20:16:00-05:00"        # the 24-hour end; the 5-day end is before the start
    assert "an end before the start was not used" in r["parse_error"]
    assert r["lat"] is None and r["raw"]["_coords_rejected"]["why"] == "not in North Carolina"
    assert r["npdes_permit"] is None and r["discharger_id"] is None


def test_no_surface_water_is_kept_with_its_flag_and_an_unnamed_tributary_is_spelled_out():
    recs, _ = sso_records()
    r = recs["aaaaaaaa-0000-4000-8000-000000000004"]
    assert r["raw"]["reached_water"] is False
    assert r["waterbody_text"] == "Unnamed tributary to Example Creek" and r["raw"]["_water"]["source_text"] == "UT to Example Creek"
    from build import status
    assert status.no_water_flag(r)                              # kept, but placed on no water


def test_personal_details_in_comments_never_reach_the_record():
    recs, _ = sso_records()
    r = recs["aaaaaaaa-0000-4000-8000-000000000004"]
    assert "[phone removed]" in r["raw"]["deq_comments"] and "[email removed]" in r["raw"]["deq_comments"]
    assert no_placeholder(list(recs.values())) == []


def test_records_that_leave_the_layer_are_kept():
    rows = S._load_file(str(FIX / "nc_dwr_sso_2026.json"))
    first, _ = S.build(rows, FETCHED, [], PERMITS)
    again, stats = S.build(rows[1:], "2026-11-05T03:00:00Z", first, PERMITS)
    gone = next(r for r in again if r["event_id"].endswith("000000000001"))
    assert gone["raw"]["_missing_from_layer_since"] == "2026-11-05T03:00:00Z" and stats["kept_from_earlier_runs"] == 1
    kept = next(r for r in again if r["event_id"].endswith("000000000002"))
    assert kept["raw"]["_first_seen_at"] == FETCHED


def test_owner_kind_names_public_bodies_only():
    assert S.owner_kind("City of Hickory") == ("public", "City of Hickory")
    assert S.owner_kind("Harnett County") == ("public", "Harnett County")
    assert S.owner_kind("Cape Fear Public Utility Authority")[0] == "public"
    for private in ("Aqua North Carolina Inc", "Example Homeowners Association Inc", "Quill, Pat Q.", "Pat Example",
                    "Naples Terrace NC LLC"):
        assert S.owner_kind(private) == ("private or not stated", None), private
    assert S.owner_kind(None) == ("not stated", None)


def test_permit_index_maps_north_carolina_rows_and_drops_contested_permits():
    rows = [{"id": "nc-a", "state": "NC", "npdes_permit": "NC0000001", "npdes_permits": ["WQCS00009", "NC0000001"]},
            {"id": "nc-b", "state": "NC", "npdes_permits": ["WQCS00010"]},
            {"id": "nc-c", "state": "NC", "npdes_permits": ["WQCS00010"]},
            {"id": "va-x", "state": "VA", "npdes_permits": ["WQCS00011"]}]
    assert S.permit_index(rows) == {"NC0000001": "nc-a", "WQCS00009": "nc-a"}


# ---------------------------------------------------------------- history layer

def test_history_has_no_end_times_marks_this_years_copies_and_withholds_private_owners():
    cur, _ = sso_records()
    hist = [a for _, a in S._load_file(str(FIX / "nc_dwr_sso_history.json"))]
    recs, stats = S.build_history(hist, FETCHED, list(cur.values()), {"WQCS00001": "nc-charlotte-water"})
    by = {r["source_record_id"]: r for r in recs}
    r = by["202300101"]
    assert r["event_id"] == "nc-dwr-sso-2022-2025:202300101" and r["status"] == "ended" and r["ended_at"] is None
    assert r["started_at"] == "2023-03-01T05:00:00-05:00" and "not an end time" in r["raw"]["_end_basis"]
    assert r["outfall_name"] == "Intersection of Example Dr and US 321"   # the leading coordinates are dropped
    assert r["raw"]["_owner_public"] == "Town of Example" and "facility_owner" not in r["raw"]
    p = by["202400777"]
    assert p["raw"]["_owner_kind"] == "private or not stated" and "_owner_public" not in p["raw"]
    assert p["started_at"] is None and p["reported_at"] and p["raw"]["reached_water"] is False
    d = by["202601742"]
    assert d["duplicate_of"] == "nc-dwr-sso-2026:aaaaaaaa-0000-4000-8000-000000000002"
    assert d["discharger_id"] == "nc-charlotte-water"
    assert {"202502056-14", "202502056-15"} <= set(by)          # a repeated incident number takes the object id
    assert stats["duplicate_of_this_year"] == 1 and stats["without_start"] == 3
    assert no_placeholder(recs) == []


def test_main_writes_both_files_and_redacts(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(S, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(S, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(S, "permit_index", lambda rows=None: dict(PERMITS))
    assert S.main(["--file", str(FIX / "nc_dwr_sso_2026.json"), "--backfill-file", str(FIX / "nc_dwr_sso_history.json")]) == 0
    cur = json.loads((tmp_path / "events" / "nc-dwr-sso-2026.json").read_text())
    hist = json.loads((tmp_path / "events" / "nc-dwr-sso-2022-2025.json").read_text())
    assert cur["ok"] and cur["count"] == 6 and cur["meta"]["statewide"] and cur["meta"]["registry_ids"] == ["nc-dwr-sso-2026"]
    assert hist["count"] == 5 and hist["meta"]["frozen"]
    assert no_placeholder([cur, hist]) == []


# ---------------------------------------------------------------- coastal swimming advisories

def rwq(run, meta, prev=()):
    feats = json.loads((FIX / run).read_text())["features"]
    m = json.loads((FIX / meta).read_text())
    return R.build(feats, m, FETCHED, list(prev))


def test_advisory_spells_open_on_the_layer_edit_and_follow_the_rule():
    recs, stats = rwq("nc_rwq_run1.json", "nc_rwq_meta1.json")
    by = {r["raw"]["ASN"]: r for r in recs}
    assert set(by) == {"N88", "N15", "C10"} and [t["station"] for t in stats["tracked"]] == ["S01"]
    a = by["N88"]
    assert a["event_type"] == "beach_advisory" and a["status"] == "advisory_active"
    assert a["started_at"] == "2026-09-03T14:50:03-04:00" and a["time_precision"] == "poll"
    assert a["source_updated_at"] == a["started_at"] and a["waterbody_text"] == "Example Soundside Access (sound)"
    assert a["event_id"] == "nc-rwq-advisories:N88:advisory:20260903T1850Z" and "200'" in a["advice_text"]
    p = by["N15"]
    assert p["event_type"] == "rain_advisory" and p["status"] == "advisory_active" and ".3404(c)" in p["advice_window_basis"]
    assert by["C10"]["status"] == "advisory_active" and "Pending" in by["C10"]["raw"]["_status_label"]
    assert "GlobalID_2" not in a["raw"]


def test_a_lifted_or_changed_status_closes_the_spell_and_a_new_status_opens_one():
    first, _ = rwq("nc_rwq_run1.json", "nc_rwq_meta1.json")
    recs, stats = rwq("nc_rwq_run2.json", "nc_rwq_meta2.json", first)
    by = {r["event_id"]: r for r in recs}
    a = by["nc-rwq-advisories:N88:advisory:20260903T1850Z"]
    assert a["status"] == "advisory_lifted" and a["ended_at"] == "2026-11-05T09:00:00-05:00"
    p = by["nc-rwq-advisories:N15:precautionary:20260903T1850Z"]
    assert p["status"] == "advisory_lifted"
    n = by["nc-rwq-advisories:N15:advisory:20261105T1400Z"]
    assert n["status"] == "advisory_active" and n["started_at"] == "2026-11-05T09:00:00-05:00"
    c = by["nc-rwq-advisories:C10:pending-swimming-advisory:20260903T1850Z"]   # gone from the layer: left open, flagged
    assert c["status"] == "advisory_active" and c["ended_at"] is None and c["raw"]["_missing_from_layer_since"] == FETCHED
    assert stats["open"] == 2


def test_the_same_status_on_a_later_run_is_reconfirmed_not_duplicated():
    first, _ = rwq("nc_rwq_run1.json", "nc_rwq_meta1.json")
    again, stats = rwq("nc_rwq_run1.json", "nc_rwq_meta2.json", first)
    assert len(again) == 3 and stats["open"] == 3
    a = next(r for r in again if r["raw"]["ASN"] == "N88")
    assert a["started_at"] == "2026-09-03T14:50:03-04:00" and a["source_updated_at"] == "2026-11-05T09:00:00-05:00"


# ---------------------------------------------------------------- algal bloom reports

def test_bloom_reports_are_unconfirmed_bloom_records_and_fish_kills_alone_are_not_events():
    feats = json.loads((FIX / "nc_blooms_current.json").read_text())["features"]
    recs, stats = B.build(feats, FETCHED, [])
    by = {r["source_record_id"]: r for r in recs}
    assert set(by) == {"AB-WARO-202601031341", "FKAB-202611031318"} and stats["fish_kill_reports"] == 1
    r = by["AB-WARO-202601031341"]
    assert r["event_type"] == "hab_advisory" and r["status"] == "unknown" and r["ended_at"] is None
    assert r["started_at"] == "2026-01-03T13:41:00-05:00" and r["waterbody_text"] == "Example Canal"
    assert (r["lat"], r["lon"], r["coord_precision_m"]) == (35.933, -76.169, 150)
    assert r["advice_text"].startswith("NCDEQ advises the public to avoid contact")
    assert "incident_details" not in r["raw"] and "nearby_landmarks" not in r["raw"]
    assert no_placeholder(recs) == []


def test_bloom_archive_skips_reporter_fields_and_points_at_the_current_copy():
    cur, _ = B.build(json.loads((FIX / "nc_blooms_current.json").read_text())["features"], FETCHED, [])
    arc, stats = B.build(json.loads((FIX / "nc_blooms_archive.json").read_text())["features"], FETCHED, [], archive=True)
    assert stats["bloom_reports"] == 2 and stats["fish_kill_reports"] == 1
    assert B.mark_duplicates(arc, cur) == 1
    by = {r["source_record_id"]: r for r in arc}
    assert by["AB-WARO-202601031341"]["duplicate_of"] == "nc-dwr-algal-bloom-reports:AB-WARO-202601031341"
    r = by["AB-RRO-2026030842"]
    assert r["raw"]["_confirmed"] is True and r["reported_at"] == "2026-03-09T08:47:50-04:00"
    for k in ("Creator", "details", "locdesc"):
        assert k not in r["raw"]
    assert no_placeholder(arc) == []


@pytest.mark.parametrize("kind,want", [("Algal Bloom", True), ("Fish Kill and Algal Bloom", True), ("AlgalBloom", True),
                                       ("BothFKAB", True), ("Fish Kill", False), ("FishKill", False), (None, False)])
def test_bloom_kinds(kind, want):
    assert B.is_bloom(kind) is want
