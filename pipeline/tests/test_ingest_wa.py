"""Washington feeds. The fixtures are small, name-free samples shaped like the live answers; the personal details in
them are invented placeholders that must never reach a record or the saved raw page.
  - tests/fixtures/wa_ecology_spills.json: Ecology's sewage spill layer (pipeline/ingest/wa_ecology_spills.py)
Run from pipeline/: python -m pytest tests/test_ingest_wa.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

from ingest import wa_ecology_spills as E

FIX = Path(__file__).resolve().parent / "fixtures"
FETCHED = "2026-11-04T12:00:00Z"
FACILITIES = {"Sample City STP": {"name": "Sample City STP", "npdes_permit": "WA0099001", "basis": "name"},
              "Seattle CSO": {"name": "Seattle CSO", "npdes_permit": "WA0031682", "basis": "name"},
              "Sample Bay WWTP": {"name": "Sample Bay WWTP", "npdes_permit": "WA0099003", "basis": "hand"}}
OPERATORS = {"WA0099001": "wa-sample-city", "WA0031682": "wa-seattle-spu"}
PLACEHOLDERS = ["Pat Example", "206-555-0123", "Robin Placeholder", "Lee Placeholder", "lee.placeholder@example.com",
                "staff.member", "448 Example", "cleaned the manhole", "UV system", "Swept up"]


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


def eco(prev=(), rows=None, fetched=FETCHED):
    rs, _ = E.load_file(str(FIX / "wa_ecology_spills.json"))
    recs, stats = E.build(rs if rows is None else rows, fetched, list(prev), FACILITIES, OPERATORS)
    return {r["source_record_id"]: r for r in recs}, stats


def test_ecology_sso_keeps_its_times_operator_volume_and_named_water():
    recs, _ = eco()
    r = recs["aaaaaaaa-0000-4000-8000-000000000001"]
    assert r["event_id"] == "wa-ecology-sewage-spills:aaaaaaaa-0000-4000-8000-000000000001"
    assert r["event_type"] == "sso" and r["status"] == "ended" and r["time_precision"] == "minute"
    assert r["started_at"] == "2026-10-02T10:00:00-07:00" and r["ended_at"] == "2026-10-02T11:00:00-07:00"
    assert r["reported_at"] is None and r["published_at"] is None and r["source_updated_at"] is None
    assert r["raw"]["_first_seen_at"] == FETCHED
    assert r["npdes_permit"] == "WA0099001" and r["discharger_id"] == "wa-sample-city"
    assert r["volume_gal"] == 1200 and r["volume_text"] == "1,200 Gallons"
    assert r["waterbody_text"] == "Sample River" and r["raw"]["reached_water"] is True
    assert r["lat"] is None and r["material"] == "None (Raw Sewage)"
    assert "globalid" in r["source_url"] and r["raw"]["report_url"].endswith("id=1")


def test_ecology_report_without_an_end_is_ongoing_and_never_given_one():
    recs, _ = eco()
    r = recs["aaaaaaaa-0000-4000-8000-000000000002"]
    assert r["status"] == "ongoing" and r["ended_at"] is None
    assert "once known" in r["raw"]["_end_basis"]
    assert r["raw"]["reached_water"] is False                    # a backup into a home: kept, not placed
    assert r["volume_gal"] is None and r["volume_text"] is None


def test_ecology_backup_into_a_home_loses_the_house_number():
    recs, _ = eco()
    r = recs["aaaaaaaa-0000-4000-8000-000000000002"]
    assert r["outfall_name"] == "[house number removed] Example St, Seattle"
    assert "448" not in json.dumps(r)


def test_ecology_types_from_spill_type_and_level_of_treatment():
    recs, _ = eco()
    assert recs["aaaaaaaa-0000-4000-8000-000000000003"]["event_type"] == "plant_bypass"   # disinfection failure
    untyped = recs["aaaaaaaa-0000-4000-8000-000000000004"]
    assert untyped["event_type"] == "sso" and "no spill type" in untyped["raw"]["_type_basis"]
    assert recs["aaaaaaaa-0000-4000-8000-000000000005"]["event_type"] == "cso"           # Other: DWCSO


def test_ecology_end_before_start_is_not_used_and_did_not_reach_is_kept_unplaced():
    recs, _ = eco()
    r = recs["aaaaaaaa-0000-4000-8000-000000000004"]
    assert r["status"] == "unknown" and r["ended_at"] is None and r["raw"]["_end_not_used"]
    assert r["raw"]["reached_water"] is False and r["waterbody_text"] is None
    assert r["volume_gal"] is None and r["volume_text"] == "200 (unit not stated)"


def test_ecology_facility_without_a_permit_names_no_operator():
    recs, _ = eco()
    r = recs["aaaaaaaa-0000-4000-8000-000000000005"]
    assert r["discharger_id"] is None and r["npdes_permit"] is None
    assert "matched no permit" in r["raw"]["_discharger_basis"]
    assert r["volume_gal"] is None and r["volume_text"] == "10-20 gallons" and r["estimate_flag"] == "estimated"


def test_ecology_personal_fields_and_the_narrative_never_reach_a_record(tmp_path):
    recs, _ = eco()
    assert leaks(list(recs.values())) == []
    for r in recs.values():
        assert "steps_taken_to_contain_or_clean" not in r["raw"]["row"]
        assert "created_user" not in r["raw"]["row"] and "last_edited_user" not in r["raw"]["row"]
    out = tmp_path / "events.json"
    assert E.run(str(FIX / "wa_ecology_spills.json"), str(out)) == 0
    assert leaks(json.loads(out.read_text())) == []


def test_ecology_report_that_leaves_the_layer_is_kept_and_changes_are_revisions():
    first, _ = eco()
    rows, _ = E.load_file(str(FIX / "wa_ecology_spills.json"))
    rows[1] = {**rows[1], "end_event_timedate": 1791050400000, "final_total_event_volume": "300 gallons"}
    recs, stats = eco(prev=first.values(), rows=rows[1:], fetched="2026-11-05T12:00:00Z")
    gone = recs["aaaaaaaa-0000-4000-8000-000000000001"]
    assert gone["raw"]["_missing_from_layer_since"] == "2026-11-05T12:00:00Z" and gone["status"] == "ended"
    r = recs["aaaaaaaa-0000-4000-8000-000000000002"]
    assert r["status"] == "ended" and r["ended_at"] == "2026-10-03T11:00:00-07:00" and r["volume_gal"] == 300
    assert r["raw"]["_first_seen_at"] == FETCHED
    assert r["raw"]["_revisions"][0]["before"]["end_event_timedate"] is None
    assert stats["missing_from_layer"] == 1


def test_ecology_outage_keeps_the_records(tmp_path, monkeypatch):
    out = tmp_path / "events.json"
    assert E.run(str(FIX / "wa_ecology_spills.json"), str(out)) == 0
    n = json.loads(out.read_text())["count"]

    def boom(sess=None):
        raise E.requests.ConnectionError("refused")
    monkeypatch.setattr(E, "fetch", boom)
    assert E.run(None, str(out)) == 1
    doc = json.loads(out.read_text())
    assert doc["ok"] is False and doc["count"] == n
