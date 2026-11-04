"""California: the State Water Board's CIWQS spill file (pipeline/ingest/ca_swrcb_ciwqs_spills.py). The fixture
tests/fixtures/ca_ciwqs_spills.txt has the file's real 95-column header and six invented rows; the certifier, the
narratives and the addresses in it are placeholders that must never reach a record or the saved raw page.
Run from pipeline/: python -m pytest tests/test_ca_swrcb_ciwqs.py -q
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from build import redact
from ingest import ca_swrcb_ciwqs_spills as M

FIX = Path(__file__).resolve().parent / "fixtures" / "ca_ciwqs_spills.txt"
FETCHED = "2026-11-04T10:00:00Z"
WDIDS = {"2SSO99001": "ca-sampleton", "2SSO99002": "ca-sample-bay-sd"}
PLACEHOLDERS = ["Pat Example", "916-555-0123", "pat.example@example.com", "Inspector Sample", "Robin Placeholder",
                "Lee Placeholder", "448 Example", "12 Sample Lane", "Behind the house", "Crew met"]


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


def leaks(obj):
    text = "\n".join(strings(obj))
    return [p for p in PLACEHOLDERS if p in text]


def rows():
    return M.read_rows(M.decode(FIX.read_bytes()))


def records(prev=(), backfill=True, rs=None, fetched=FETCHED):
    recs, stats = M.build(rows() if rs is None else rs, fetched, list(prev), dict(WDIDS), backfill=backfill,
                          file_modified="2026-11-03T14:00:27Z")
    return {r["source_record_id"]: r for r in recs}, stats


def test_a_certified_category_1_spill_is_shown_with_the_boards_times_point_and_volumes():
    recs, stats = records()
    r = recs["990001"]
    assert r["event_id"] == "ca-swrcb-ciwqs-spills-flatfile:990001"
    assert r["event_type"] == "sso" and r["status"] == "ended" and r["time_precision"] == "minute"
    assert r["started_at"] == "2026-10-01T08:15:00-07:00" and r["ended_at"] == "2026-10-01T11:45:00-07:00"
    assert r["reported_at"] == "2026-10-01T09:40:00-07:00" and "Cal OES" in r["raw"]["_reported_basis"]
    assert r["published_at"] is None and r["source_updated_at"] == "2026-10-20"
    assert r["raw"]["_first_seen_in_file"] == "2026-11-03T14:00:27Z" and r["raw"]["_first_seen_at"] == FETCHED
    assert r["raw"]["spill_category"] == "1" and r["raw"]["reached_water"] is True
    assert r["npdes_permit"] == "2SSO99001" and r["discharger_id"] == "ca-sampleton"
    assert r["discharger_name"] == "Sampleton City"
    assert r["waterbody_text"] == "Sample Creek" and r["lat"] == 37.8 and r["lon"] == -122.27
    assert r["coord_precision_m"] is None and r["raw"]["destination_points"] == [{"lat": 37.801, "lon": -122.271}]
    assert r["volume_gal"] == 1500 and r["estimate_flag"] == "estimated"
    assert "1,100 gallons reached surface water" in r["volume_text"]
    assert stats["shown_category_1"] == 3 and stats["kept_not_shown"] == {"Category 2": 1, "Category 3": 1}


def test_the_highest_report_version_is_the_record_and_earlier_versions_are_listed():
    recs, stats = records()
    r = recs["990001"]
    assert r["raw"]["version"] == "2.1" and r["raw"]["spill_status"] == "Certified"
    assert r["raw"]["_versions"] == [{"version": "1.1", "spill_status": "Amended", "final_certified_on": "10-OCT-26"}]
    assert stats["versions_folded"] == 1 and len(recs) == 5


def test_a_draft_has_no_end_and_is_never_given_one():
    recs, _ = records()
    r = recs["990002"]
    assert r["status"] == "unknown" and r["ended_at"] is None and r["started_at"] == "2026-10-29T17:00:00-07:00"
    assert "certified report" in r["raw"]["_end_basis"]
    assert r["reported_at"] == "2026-10-30" and "draft" in r["raw"]["_reported_basis"]
    assert r["waterbody_text"] is None and r["raw"]["reached_water"] is True and "names no receiving water" in \
        r["raw"]["_water_note"]
    assert r["discharger_id"] == "ca-sample-bay-sd"


def test_a_private_clean_out_point_is_rounded_and_a_missing_minus_sign_repaired():
    recs, _ = records()
    r = recs["990002"]
    assert r["lat"] == 37.812 and r["lon"] == -122.265 and r["coord_precision_m"] == 150
    assert "rounded" in r["raw"]["_coords_rounded"] and "minus sign" in r["raw"]["_coords_repaired"]


def test_category_2_and_3_spills_are_kept_but_say_they_reached_no_water():
    from build import status
    recs, _ = records()
    for sid, cat in (("990003", "2"), ("990004", "3")):
        r = recs[sid]
        assert r["raw"]["spill_category"] == cat and r["raw"]["reached_water"] is False
        assert status.no_water_flag(r)
    assert recs["990003"]["status"] == "ended"


def test_an_end_before_the_start_is_not_used():
    recs, _ = records()
    r = recs["990004"]
    assert r["ended_at"] is None and r["status"] == "unknown" and "before the start" in r["raw"]["_end_not_used"]


def test_a_water_entry_that_names_none_is_not_a_water_and_a_zero_point_is_not_used():
    recs, _ = records()
    r = recs["990005"]
    assert r["waterbody_text"] is None and r["raw"]["receiving_water"] == "N/A"
    assert r["lat"] is None and r["lon"] is None
    assert "names no water" in r["raw"]["_water_note"]


def test_an_hourly_run_reads_the_last_60_days_and_every_spill_already_on_record():
    recs, stats = records(backfill=False)
    assert "990005" not in recs and stats["outside_window_not_read"] == 1
    old, _ = records()
    recs2, stats2 = records(prev=[old["990005"]], backfill=False)
    assert "990005" in recs2 and stats2["outside_window_not_read"] == 0
    assert M.in_window(rows()[0], date(2026, 11, 4)) is True


def test_a_spill_that_leaves_the_file_is_kept_and_marked_and_a_change_is_a_revision():
    old, _ = records()
    rs = [r for r in rows() if r["spill_event_id"] != "990003"]
    for r in rs:
        if r["spill_event_id"] == "990002":
            r["end_at"] = "10/29/2026 19:30"
            r["spill_status"] = "Work In Progress"
    recs, stats = records(prev=list(old.values()), rs=rs, fetched="2026-11-05T10:00:00Z")
    assert recs["990003"]["raw"]["_missing_from_file_since"] == "2026-11-05T10:00:00Z"
    assert stats["kept_missing_from_file"] == 1
    r = recs["990002"]
    assert r["status"] == "ended" and r["ended_at"] == "2026-10-29T19:30:00-07:00"
    assert "not yet certified" in r["raw"]["_end_basis"]
    assert r["raw"]["_revisions"][0]["end_at"] is None and r["raw"]["_first_seen_at"] == FETCHED


def test_personal_fields_never_reach_a_record_or_the_saved_page():
    recs, _ = records()
    out = redact.redact_events(list(recs.values()))
    assert leaks(out) == []
    saved = [M.scrubbed_row(r) for r in rows()]
    assert leaks(saved) == []
    assert not any(k.isupper() for r in saved for k in r)            # only the short keys, never a file column
    r = recs["990001"]
    assert r["outfall_name"] == "[house number removed] Example St, Sampleton CA"
    assert r["raw"]["closing_entity"] == "[name removed]"
    assert recs["990002"]["outfall_name"] == "[name removed]"
    assert "CERTIFIED_BY" not in json.dumps(out) and "certified_by" not in json.dumps(out)


def test_a_file_without_the_spill_columns_is_refused():
    import pytest
    with pytest.raises(ValueError):
        M.read_rows("REGION\tWDID\n2\t2SSO99001\n")


def test_a_changed_layout_with_extra_columns_still_reads_only_the_safe_fields():
    text = M.decode(FIX.read_bytes())
    head, rest = text.split("\n", 1)
    text2 = head + "\tCONTACT_PHONE\n" + "\n".join(line + "\t916-555-0123" for line in rest.splitlines() if line)
    rs = M.read_rows(text2)
    assert leaks(rs) == [] or all("916-555-0123" not in json.dumps(r) for r in rs)
    assert all("CONTACT_PHONE" not in r for r in rs)
