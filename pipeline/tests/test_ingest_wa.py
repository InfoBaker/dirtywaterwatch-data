"""Washington feeds. The fixtures are small, name-free samples shaped like the live answers; the personal details in
them are invented placeholders that must never reach a record or the saved raw page.
  - tests/fixtures/wa_ecology_spills.json: Ecology's sewage spill layer (pipeline/ingest/wa_ecology_spills.py)
Run from pipeline/: python -m pytest tests/test_ingest_wa.py -q
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from ingest import wa_ecology_spills as E

FIX = Path(__file__).resolve().parent / "fixtures"
FETCHED = "2026-11-04T12:00:00Z"
FACILITIES = {"Sample City STP": {"name": "Sample City Sewage Treatment Plant", "npdes_permit": "WA0099001", "basis": "name"},
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
    assert r["discharger_name"] == "Sample City Sewage Treatment Plant"          # the full name, not the 30-letter code
    assert r["volume_gal"] == 1200 and r["volume_text"] == "1,200 Gallons"
    assert r["waterbody_text"] == "Sample River" and r["raw"]["reached_water"] is True
    assert r["lat"] is None and r["material"] == "None (Raw Sewage)"
    assert "globalid" in r["source_url"] and r["raw"]["report_url"].endswith("id=1")


def test_ecology_report_without_an_end_is_unknown_and_never_given_one():
    """Review 2026-11-04: the layer has no status field and posts the end once known, so a blank end is an end not yet
    posted: status unknown, the 14-day caution (plan §2), never red as if Ecology said the spill goes on."""
    from datetime import datetime, timedelta
    from build import status as S
    recs, _ = eco()
    r = recs["aaaaaaaa-0000-4000-8000-000000000002"]
    assert r["status"] == "unknown" and r["ended_at"] is None
    assert "once known" in r["raw"]["_end_basis"] and "not that the spill goes on" in r["raw"]["_end_basis"]
    assert r["raw"]["reached_water"] is False                    # a backup into a home: kept, not placed
    assert r["volume_gal"] is None and r["volume_text"] is None
    r = {**r, "event_type": "sso"}
    start = datetime.fromisoformat(r["started_at"])
    ivs = S._event_intervals(r, "WA", start + timedelta(days=1), None, S.load_rules())
    assert ivs[0]["rule"] == "no_end" and ivs[0]["end"] == start + timedelta(days=14)
    assert not any(iv["rule"] == "ongoing" for iv in ivs)


def test_ecology_report_with_final_figures_but_no_end_is_ended_without_an_end():
    rows, _ = E.load_file(str(FIX / "wa_ecology_spills.json"))
    rows[1] = {**rows[1], "final_event_duration_hours": "1.5 hours", "final_total_event_volume": "50 gallons"}
    recs, _ = eco(rows=rows)
    r = recs["aaaaaaaa-0000-4000-8000-000000000002"]
    assert r["status"] == "ended" and r["ended_at"] is None and "final duration or volume" in r["raw"]["_end_basis"]


def test_ecology_backup_into_a_home_loses_the_house_number():
    from build import status as S
    recs, _ = eco()
    r = recs["aaaaaaaa-0000-4000-8000-000000000002"]
    assert r["outfall_name"] == "[house number removed] Example St, Seattle"
    assert "448" not in json.dumps(r)
    assert S.no_water_flag(r) == "the report names no water, only 'Backup into private residence'"


def test_ecology_a_home_named_in_the_location_also_loses_the_house_number():
    rows, _ = E.load_file(str(FIX / "wa_ecology_spills.json"))
    a = {**rows[3], "location": "512 Sample Ln (private residence)", "potentially_impacted_area": "Ground"}
    assert E.safe_row(a)["location"] == "[house number removed] Sample Ln (private residence)"
    assert E.safe_row({**a, "location": "512 Sample Ln"})["location"] == "512 Sample Ln"   # no home said: a site


def test_ecology_types_from_spill_type_and_level_of_treatment():
    recs, _ = eco()
    assert recs["aaaaaaaa-0000-4000-8000-000000000003"]["event_type"] == "plant_bypass"   # disinfection failure
    untyped = recs["aaaaaaaa-0000-4000-8000-000000000004"]
    assert untyped["event_type"] == "sso" and "no spill type" in untyped["raw"]["_type_basis"]
    assert recs["aaaaaaaa-0000-4000-8000-000000000005"]["event_type"] == "cso"           # Other: DWCSO


def test_ecology_end_before_start_is_published_not_used_and_did_not_reach_is_kept_unplaced():
    """Plan §2 "Published end not used": the end stays as Ecology published it and the status build sets it aside
    (end_not_used on every interval, which the pages explain)."""
    from datetime import datetime, timedelta
    from build import status as S
    recs, _ = eco()
    r = recs["aaaaaaaa-0000-4000-8000-000000000004"]
    assert r["status"] == "ended" and r["ended_at"] == r["raw"]["_end_not_used"] and r["ended_at"] < r["started_at"]
    assert S.end_not_credible(r) and "before started_at" in S.end_not_credible(r)
    start = datetime.fromisoformat(r["started_at"])
    ivs = S.event_intervals(r, "WA", start + timedelta(days=1), None, S.load_rules())
    assert ivs and all(iv.get("end_not_used") for iv in ivs) and ivs[0]["rule"] == "no_end"
    assert r["raw"]["reached_water"] is False and r["waterbody_text"] is None
    assert S.no_water_flag(r) == "the report says the sewage did not reach surface water"
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


# ---------------------------------------------------------------- King County / Seattle CSO status (generic snapshot)

def kc_polls():
    """Three polls ten minutes apart: Ballard overflowing, still overflowing, then 'in the last 48 hours'; the
    placeholder-point outfall 026 starts overflowing at the third poll."""
    base = (FIX / "wa_kc_cso_status.csv").read_text()
    p2 = base.replace("2026  2:30", "2026  2:40")
    p3 = (base.replace("2026  2:30", "2026  2:50")
          .replace("Ballard,3,11/04/2026  2:50,CurrentlyOverflowing", "Ballard,3,11/04/2026  2:50,OverflowLast48hrs")
          .replace("Seattle CSO,26,11/04/2026  2:50,NoRecentOverflow", "Seattle CSO,26,11/04/2026  2:50,CurrentlyOverflowing"))
    return [("2026-11-04T10:31:00Z", base), ("2026-11-04T10:41:00Z", p2), ("2026-11-04T10:51:00Z", p3)]


def kc_run():
    from ingest.generic import csv_json, runner
    _, block = runner.load_source("wa-kc-cso-status-csv")
    block = block["fetch"] if "fetch" in block else block
    state, recs = {}, []
    for fetched, text in kc_polls():
        rows = csv_json.read_csv(text, block)
        recs, stats = runner.build("wa-kc-cso-status-csv", block, rows, fetched, extra={"state": state})
    return {r["source_record_id"]: r for r in recs}, stats, state


def test_kc_cso_status_opens_and_closes_an_overflow_at_the_polls_on_the_permits_outfall():
    recs, stats, _ = kc_run()
    r = recs["ball-20261104T0230"]
    assert r["event_type"] == "cso" and r["status"] == "ended" and r["time_precision"] == "poll"
    assert r["started_at"] == "2026-11-04T02:30:00-08:00" and r["ended_at"] == "2026-11-04T02:50:00-08:00"
    assert r["raw"]["ended_after"] == "2026-11-04T02:40:00-08:00"
    assert r["discharger_id"] == "wa-king-county-west-point" and r["npdes_permit"] == "WA0029181"
    assert r["outfall_id"] == "003" and r["outfall_name"] == "Ballard"
    assert r["lat"] == 47.663916 and "48 hours" in r["advice_text"]
    assert r["advice_window_hours"] == 48 and "status map" in r["advice_window_basis"]


def test_kc_cso_status_first_seen_recent_has_no_start_and_a_placeholder_point_is_not_used():
    recs, stats, state = kc_run()
    r = recs["npdes124-20261104T0230"]
    assert r["status"] == "ended" and r["started_at"] is None and r["ended_at"] == "2026-11-04T02:30:00-08:00"
    assert r["raw"]["occurred_after"] == "2026-11-02T02:30:00-08:00"        # the map's own 48 hours
    assert r["npdes_permit"] == "WA0031682" and r["outfall_id"] == "124" and r["discharger_id"] == "wa-seattle-spu"
    o = recs["npdes026-20261104T0250"]
    assert o["status"] == "ongoing" and o["started_at"] == "2026-11-04T02:50:00-08:00" and o["ended_at"] is None
    assert o["lat"] is None and o["lon"] is None and o["outfall_id"] == "026"   # -120.0, 47.26 rejected
    assert "CSO_Status1" not in state["units"]                                   # the legend rows are dropped
    assert state["units"]["MAGN"]["state"] == "no_data"


def test_kc_cso_status_keeps_only_its_safe_fields():
    recs, _, state = kc_run()
    assert leaks(list(recs.values())) == [] and leaks(state) == []
    assert all("Contact" not in r["raw"]["row"] for r in recs.values())


def test_kc_status_file_outfalls_replace_epas_closed_rows_and_a_placeholder_point_is_never_drawn():
    import importlib.util
    spec = importlib.util.spec_from_file_location("build_wa_outfalls", Path(__file__).resolve().parents[2] / "scripts" / "build_wa_outfalls.py")
    B = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(B)
    doc = B.build((FIX / "wa_kc_cso_status.csv").read_text(), "2026-11-04T10:30:14Z")
    rows = {(r["npdes_permit"], r["outfall"]): r for r in doc["outfalls"]}
    assert set(rows) == {("WA0029181", "003"), ("WA0029181", "006"), ("WA0031682", "124"), ("WA0031682", "012")}
    b = rows[("WA0029181", "003")]
    assert b["outfall_name"] == "Ballard" and b["coords_from"] == "operator status file" and b["lat"] == 47.663916
    assert b["supersedes"]["outfall_status"] == "CLS" and b["outfall_kind"] == "cso"
    # EPA's permit-level text ("Duwamish Waterway" for Ballard, on Salmon Bay) is kept for reference, never the tie
    assert "receiving_water_echo" not in b and "water_slug" not in b
    assert b["supersedes"]["receiving_water_echo"] == "Duwamish Waterway"
    assert doc["not_placed"] == [{"npdes_permit": "WA0031682", "outfall": "026", "why": "the status file gives a "
                                  "placeholder point and EPA lists no point for this outfall"}]
    assert leaks(doc) == []


def test_kc_dsn_is_the_permits_outfall_as_epa_writes_it():
    """Review 2026-11-04: the file writes King County's Denny Way outfalls '027a', '027b' and '044a'; EPA's are 027A,
    027B and 044A, so the status file's rows did not replace EPA's closed ones."""
    from ingest.wa_transforms import dsn
    assert [dsn(x) for x in ("3", "124", "027a", "44a", "027B", "DSN", "", "12ab")] == \
        ["003", "124", "027A", "044A", "027B", None, None, None]


# ---------------------------------------------------------------- EPA's eRule tables (JBLM, Puyallup)

def test_washington_permits_are_read_from_the_epa_tables_under_the_general_rules():
    from ingest import echo_sewer_overflow_events as S
    assert "WA" in S.STATES and "WA" not in S.REPEATED_POINT_STATES
    ok, _ = S.reached_water({}, ["BYP"], ["Puget Sound"], [])            # JBLM's 2023 bypass to Puget Sound
    assert ok
    ok, why = S.reached_water({}, ["SSO"], [], [])                       # an SSO naming no water and no water impact
    assert not ok and why == "no evidence the discharge reached a water"


def test_adding_washington_to_the_epa_tables_changes_no_other_states_record(monkeypatch):
    """Review 2026-11-04: the same tables built with and without WA give identical records for every other state
    (also checked on the real 2026-11-04 extract: 1,033 non-Washington records identical, 1 Washington kept, 35
    dropped)."""
    from tests.test_ingest_dc import _row
    from ingest import echo_sewer_overflow_events as S
    tables = {
        "events": [_row(sewer_overflow_bypass_event_key="1", latitude_measure="38.9300", longitude_measure="-77.0400"),
                   _row(sewer_overflow_bypass_event_key="2", permit_identifier="NY0026131", program_report_form_set_id="2"),
                   _row(sewer_overflow_bypass_event_key="3", permit_identifier="WA0021954", program_report_form_set_id="3",
                        latitude_measure="47.0900", longitude_measure="-122.5800"),
                   _row(sewer_overflow_bypass_event_key="4", permit_identifier="WA0037168", program_report_form_set_id="4")],
        "types": [{"sewer_overflow_bypass_event_key": k, "sewer_overflow_bypass_type_code": t,
                   "sewer_overflow_bypass_type_desc": "", "sewer_overflow_bypass_type_code_sequence": "1"}
                  for k, t in (("1", "SSO"), ("2", "CSO"), ("3", "BYP"), ("4", "SSO"))],
        "waters": [{"sewer_overflow_bypass_event_key": "1", "name_receiving_water": "Rock Creek"},
                   {"sewer_overflow_bypass_event_key": "2", "name_receiving_water": "Hudson River"},
                   {"sewer_overflow_bypass_event_key": "3", "name_receiving_water": "Puget Sound"}],
    }
    info = {"extract_date": "2026-11-02", "last_modified": None}

    def others(states):
        monkeypatch.setattr(S, "STATES", states)
        kept, dropped, _ = S.build(tables, info)
        out = [json.dumps({k: v for k, v in r.items() if k != "fetched_at"}, sort_keys=True)
               for r in kept + dropped if not str(r.get("npdes_permit") or r.get("permit")).startswith("WA")]
        return sorted(out), kept, dropped
    with_wa, kept, dropped = others(set(S.STATES))
    without_wa, _, _ = others(set(S.STATES) - {"WA"})
    assert with_wa == without_wa and len(with_wa) == 2
    assert [r["source_record_id"] for r in kept if r["npdes_permit"].startswith("WA")] == ["WA0021954:3:1"]
    assert [d["permit"] for d in dropped] == ["WA0037168"]          # an SSO naming no water: dropped as everywhere


# ---------------------------------------------------------------- operator rows (scripts/add_wa_operators.py)

def test_every_washington_permit_of_the_registry_has_exactly_one_operator_row():
    root = Path(__file__).resolve().parents[2]
    dis = [r for r in json.loads((root / "data" / "dischargers.json").read_text()) if r.get("state") == "WA"]
    held = Counter(p for r in dis for p in r["npdes_permits"])
    assert all(n == 1 for n in held.values())
    permits = set()
    for f in ("outfalls-plants-us.json", "outfalls-us.json", "outfalls-wa.json"):
        doc = json.loads((root / "data" / f).read_text())
        permits |= {r["npdes_permit"] for r in doc["outfalls"] if str(r.get("npdes_permit", "")).startswith("WA")}
    assert permits <= set(held)
    by_id = {r["id"]: r for r in dis}
    assert {"WA0029181", "WA0029581", "WA0032247"} <= set(by_id["wa-king-county-west-point"]["npdes_permits"])
    assert by_id["wa-port-angeles"]["npdes_permits"] == ["WA0023973", "WAG994562"]
    assert by_id["wa-sound-transit-east-link"]["kind"] == "cso_closed_or_none"
    assert by_id["wa-wa0020923"]["legal_form"] == "city"              # EPA types Westport private; it is the city's
    assert by_id["wa-warm-beach-camp"]["legal_form"] == "institution"
    for r in dis:
        assert "[name removed]" not in r["name"] and r["notification_signup_url"] is None


def test_ecology_facilities_join_the_operator_rows():
    recs, _ = E.build(E.load_file(str(FIX / "wa_ecology_spills.json"))[0], FETCHED, [],
                      {"Seattle CSO": {"npdes_permit": "WA0031682", "basis": "name"}}, None)
    r = next(r for r in recs if r["discharger_name"] == "Seattle CSO")
    assert r["discharger_id"] == "wa-seattle-spu"


# ---------------------------------------------------------------- the register (scripts/add_wa_register_rows.py)

def test_every_washington_operator_has_its_permit_duty_row_and_every_cso_operator_its_notification_row():
    from ingest import notification_pages as NP
    root = Path(__file__).resolve().parents[2]
    dis = json.loads((root / "data" / "dischargers.json").read_text())
    doc = NP.load_register(root / "data" / "notice-channels")
    assert NP.validate_register(doc, dis, root) == []
    rows = {r["id"]: r for r in doc["channels"] if r["state"] == "WA"}
    for op in (r for r in dis if r.get("state") == "WA" and r["kind"] != "cso_closed_or_none"):
        rid = "wa-jblm-epa-report" if op["id"] == "wa-jblm" else f"{op['id']}-ecology-spill-report"
        assert rows[rid]["operator_id"] == op["id"] and rows[rid]["basis_kind"] == "permit"
        if op["kind"] == "cso":
            assert rows[f"{op['id']}-cso-public-notification"]["basis_kind"] == "permit"
    assert rows["wa-ecology-sewage-spills"]["feed_source_id"] == "wa-ecology-sewage-spills"
    assert rows["wa-seattle-spu-cso-public-notification"]["feed_source_id"] == "wa-kc-cso-status-csv"
    assert rows["wa-spokane-cso-public-notification"]["barrier"] == "bot_wall"
    assert rows["wa-ecology-spill-email-alerts"]["barrier"] == "no_web_page"
    assert not any("@ecy.wa.gov" in json.dumps(r).lower() for r in rows.values())


def test_washington_rules_row_cites_the_law_and_is_not_live():
    from build import status
    root = Path(__file__).resolve().parents[2]
    rules = json.loads((root / "data" / "rules.json").read_text())
    wa = rules["red"]["by_state"]["WA"]
    assert wa["hours"] is None and "RCW 90.48.636" in wa["basis"] and "WA" not in rules["live_states"]
    # an Ecology report follows the state row; a status-map overflow carries the operators' own 48 hours
    assert status.red_rule_for({"discharger_id": "wa-seattle-spu"}, "WA", rules)["rule"] == "red.by_state.WA"
    recs, _, _ = kc_run()
    assert status.red_rule_for(recs["ball-20261104T0230"], "WA", rules)["hours"] == 48
