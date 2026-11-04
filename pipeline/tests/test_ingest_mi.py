"""Michigan: EGLE's MiEnviro CSO/SSO list (pipeline/ingest/mi_egle_mienviro.py). The fixture
tests/fixtures/mi_mienviro_list.json is a small, name-free sample shaped like the live service's answer; the personal
details in it are invented placeholders that must never reach a record or the saved raw page.
Run from pipeline/: python -m pytest tests/test_ingest_mi.py -q
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

import common
from ingest import mi_egle_mienviro as M

FIX = Path(__file__).resolve().parent / "fixtures"
FETCHED = "2026-11-04T10:00:00Z"
PERMITS = {"MI0099001": "mi-sampleton", "3112A-0999": "mi-sample-charter-township", "MI0099004": "mi-sample-bay"}
PLACEHOLDERS = ["Pat Example", "517-555-0123", "pat.example@example.com", "Inspector Sample", "Robin Placeholder",
                "Lee Placeholder", "448 Example St", "Behind the house", "6517", "cleaned the manhole",
                "1234567890123456789"]


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
    return M.load_file(str(FIX / "mi_mienviro_list.json"))


def records(prev=(), fetched=FETCHED, rs=None, missing=None, left=None):
    recs, stats = M.build(rows() if rs is None else rs, fetched, list(prev), dict(PERMITS), missing,
                          {} if left is None else left)
    return {r["source_record_id"]: r for r in recs}, stats


def test_a_completed_cso_keeps_egles_times_permit_outfall_and_volume():
    recs, _ = records()
    r = recs["-1000000000000000001-3"]
    assert r["event_id"] == "mi-egle-mienviro-cso-sso-list:-1000000000000000001-3"
    assert r["event_type"] == "cso" and r["status"] == "ended" and r["time_precision"] == "minute"
    assert r["started_at"] == "2026-10-02T03:18:00-04:00" and r["ended_at"] == "2026-10-02T04:19:00-04:00"
    assert r["reported_at"] == "2026-10-02T08:44:01-04:00" and r["published_at"] is None
    assert r["source_updated_at"] is None and r["raw"]["_first_seen_at"] == FETCHED
    assert r["npdes_permit"] == "MI0099001" and r["discharger_id"] == "mi-sampleton"
    assert r["outfall_id"] == "002" and r["outfall_name"] == "Pine St Pump Station"
    assert r["waterbody_text"] == "Detroit River (Trenton Channel)" and r["raw"]["reached_water"] is True
    assert r["volume_gal"] == 3985200 and r["volume_text"] == "3.9852 Million Gallons"
    assert r["material"] == "Diluted Raw Sewage" and r["lat"] is None
    assert "submissionId%22%3A%22-1000000000000000001" in r["source_url"]


def test_an_open_report_whose_end_repeats_its_start_has_no_end():
    recs, _ = records()
    r = recs["-1000000000000000002-2"]
    assert r["status"] == "ongoing" and r["ended_at"] is None and r["event_type"] == "sso"
    assert "form repeats the start" in r["raw"]["_end_basis"]
    assert r["npdes_permit"] == "3112a-0999" and r["discharger_id"] == "mi-sample-charter-township"
    assert r["raw"]["reached_water"] is None                       # an open report often names no water yet


def test_an_open_report_with_a_later_end_is_ended_by_the_operators_end_and_rtb_is_a_cso():
    recs, _ = records()
    r = recs["-1000000000000000003-2"]
    assert r["status"] == "ended" and r["ended_at"] == "2026-10-31T03:30:00-04:00"
    assert "not yet completed" in r["raw"]["_end_basis"]
    assert r["event_type"] == "cso" and r["raw"]["_discharge_kind"] == "RTB" and "retention treatment basin" in r["material"]
    assert r["npdes_permit"] == "MI0099002" and r["raw"]["_permit_as_given"] == "MI 0099002 V4.1"
    assert r["outfall_id"] == "R03" and r["volume_gal"] == 480000


def test_a_completed_report_with_the_same_start_and_end_keeps_the_filers_end_flagged():
    recs, _ = records()
    r = recs["-1000000000000000016-3"]
    assert r["status"] == "ended" and r["ended_at"] == r["started_at"] and r["raw"]["_end_equals_start"] is True
    assert r["raw"]["reached_water"] is False                      # completed, no water named, land named


def test_glwa_without_a_permit_is_joined_by_name_only_from_the_list_of_names():
    recs, _ = records()
    r = recs["-1000000000000000004-14"]
    assert r["npdes_permit"] is None and r["discharger_id"] == "mi-glwa-wrrf-mi0022802"
    assert "no permit" in r["raw"]["_discharger_basis"]
    other = recs["-1000000000000000010-3"]                          # GW permit no row holds: no operator guessed
    assert other["discharger_id"] is None and "No operator on record for permit GW1899999" in other["raw"]["_discharger_basis"]


def test_a_start_typed_in_another_millennium_and_an_end_before_the_start_are_not_used():
    recs, _ = records()
    r = recs["-1000000000000000005-3"]
    assert r["started_at"] is None and "3021" in r["raw"]["_start_not_used"]
    assert r["ended_at"] == "2021-08-16T15:00:00-04:00" and r["event_type"] == "plant_bypass"
    assert r["outfall_id"] is None and r["outfall_name"] == "Sample Drain - Receiving stream"
    s = recs["-1000000000000000006-3"]
    assert s["ended_at"] is None and "before the start" in s["raw"]["_end_not_used"]


def test_other_pollution_and_biosolids_on_land_are_left_out_and_counted_but_sludge_in_a_river_is_kept():
    left = {}
    recs, stats = records(left=left)
    assert "-1000000000000000007-3" not in recs and "-1000000000000000008-3" not in recs
    assert left == {"-1000000000000000007-3": "other pollution", "-1000000000000000008-3": "biosolids"}
    assert stats["left_out_this_run"] == {"other pollution": 1, "biosolids": 1}
    assert recs["-1000000000000000009-3"]["event_type"] == "plant_bypass"
    assert recs["-1000000000000000015-3"]["event_type"] == "bypass"          # raw sewage at a plant
    u = recs["-1000000000000000014-3"]
    assert u["event_type"] == "unknown" and "no discharge type" in u["parse_error"]


@pytest.mark.parametrize("types,quality,want", [
    (["CSO Discharge"], ["Diluted Raw Sewage"], "cso"),
    (["SSO Discharge"], ["Raw Sewage"], "sso"),
    (["Other Discharge", "overflow of lift station"], ["Diluted Raw Sewage"], "sso"),
    (["Other Discharge", "Retention basin overflow"], ["RTB"], "cso"),
    (["Other Discharge", "Combined Sewer"], ["Blended Sewage"], "blended"),
    (["Other Discharge", "Hydraulic leak from trash truck"], ["Diluted Raw Sewage"], None),
])
def test_classify(types, quality, want):
    assert M.classify(types, quality)[0] == want


def test_permits_as_typed_are_read_to_one_permit():
    assert M.norm_permit("MI 0022802") == "MI0022802"
    assert M.norm_permit("PERMITMI0023582V4.1") == "MI0023582"
    assert M.norm_permit("3112A-1031V1.0") == "3112a-1031"
    assert M.norm_permit("GW1810021") == "GW1810021" and M.norm_permit("MIG570128") == "MIG570128"
    assert M.norm_permit("N/A") is None and M.norm_permit("Various") is None and M.norm_permit("MI10025585") is None


def test_personal_details_never_reach_a_record_or_the_saved_raw_page():
    from build import redact
    recs, _ = records()
    for r in recs.values():
        for k in M.WITHHELD:                                           # never requested, never kept
            assert k not in r["raw"]
    assert recs["-1000000000000000010-3"]["discharger_name"] == "[name removed]"
    assert recs["-1000000000000000010-3"]["raw"]["siteName"] == "[name removed]"
    assert recs["-1000000000000000011-3"]["discharger_name"] == "Sample Heights"
    assert "[house number removed]" in recs["-1000000000000000010-3"]["raw"]["landImpacted"]
    out = redact.redact_events(list(recs.values()))
    assert leaks(out) == []
    saved = {"rows": [M.scrubbed_row(r) for r in rows()]}            # what main() saves as the raw page
    assert leaks(saved) == []


def test_only_the_safe_fields_are_requested():
    seen = {}

    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return json.loads((FIX / "mi_mienviro_list.json").read_text())

    class Sess:
        def get(self, url, params=None, timeout=None):
            seen.update(params)
            return Resp()

    got = M.query(Sess(), {"reportStatusId": "IN_PROCESS"})
    asked = seen["responseFields"].split(",")
    assert set(asked) == set(M.FIELDS) and not set(asked) & set(M.WITHHELD)
    assert all(not set(r) & set(M.WITHHELD) for r in got)            # a service that ignored the list keeps none


def test_a_report_that_completes_keeps_its_id_and_its_earlier_fields_and_kept_records_stay():
    first, _ = records()
    rs = rows()
    done = dict(next(r for r in rs if r["submissionId"] == "-1000000000000000002"))
    done.update(reportStatusId="COMPLETE", reportStatusDescription="Completed", eventEndDate="2026-11-03T09:30:00.0000000-05:00",
                dischargeVolume="1100.00000 Gallons", dischargeVolumeNumeric=1100, receivingWater="Sample Creek", sectionNumber=2)
    later = "2026-11-05T10:00:00Z"
    again, stats = records(prev=first.values(), fetched=later, rs=[done], missing={"-1000000000000000004-14"})
    r = again["-1000000000000000002-2"]
    assert r["status"] == "ended" and r["ended_at"] == "2026-11-03T09:30:00-05:00" and r["volume_gal"] == 1100
    assert r["raw"]["_first_seen_at"] == FETCHED
    assert r["raw"]["_revisions"][-1]["reportStatusId"] == "IN_PROCESS" and r["raw"]["_revisions"][-1]["seen_until"] == FETCHED
    assert stats["kept_from_earlier_runs"] == len(first) - 1
    assert again["-1000000000000000004-14"]["raw"]["_missing_from_list_since"] == later
    assert "_missing_from_list_since" not in again["-1000000000000000001-3"]["raw"]


def test_a_report_filed_twice_keeps_the_one_received_last():
    recs, stats = records()
    a, b = recs["-1000000000000000012-3"], recs["-1000000000000000013-3"]
    assert a["duplicate_of"] == b["event_id"] and b["duplicate_of"] is None and stats["copies"] == 1


def test_no_open_reports_is_an_outage():
    class Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"queryResults": [], "hasResultsRemaining": False}

    class Sess:
        def get(self, url, params=None, timeout=None):
            return Resp()

    with pytest.raises(RuntimeError, match="outage"):
        M.fetch_current(Sess(), M.date(2026, 11, 4))


def test_a_window_with_more_rows_than_the_service_returns_is_halved():
    from datetime import date
    asked = []

    class Resp:
        def __init__(self, flt):
            self.flt = flt

        def raise_for_status(self):
            pass

        def json(self):
            a, b = date.fromisoformat(self.flt["eventStartDateMin"]), date.fromisoformat(self.flt["eventStartDateMax"])
            return {"queryResults": [], "hasResultsRemaining": (b - a).days > 200}

    class Sess:
        def get(self, url, params=None, timeout=None):
            flt = json.loads(params["queryParams"])["filter"][0]
            asked.append(flt)
            return Resp(flt)

    M.query_window(Sess(), "COMPLETE", date(2025, 1, 1), date(2026, 1, 1))
    assert len(asked) == 3 and asked[1]["eventStartDateMax"] == asked[2]["eventStartDateMin"]


def test_main_writes_the_events_file_with_public_left_out_counts(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(M, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(M, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(M, "permit_index", lambda rows=None: dict(PERMITS))
    assert M.main(["--file", str(FIX / "mi_mienviro_list.json")]) == 0
    d = json.loads((tmp_path / "events" / "mi-egle-mienviro-cso-sso-list.json").read_text())
    assert d["ok"] and d["count"] == 14 and d["meta"]["statewide"] and d["meta"]["registry_ids"] == [M.SOURCE_ID]
    assert d["meta"]["left_out"] == {"other pollution": 1, "biosolids": 1}
    assert leaks(d) == []
    assert M.main(["--file", str(FIX / "mi_mienviro_list.json")]) == 0          # a re-read never doubles the counts
    d = json.loads((tmp_path / "events" / "mi-egle-mienviro-cso-sso-list.json").read_text())
    assert d["meta"]["left_out"] == {"other pollution": 1, "biosolids": 1} and d["count"] == 14


def test_permit_index_reads_michigan_rows_only():
    rows_ = [{"id": "mi-a", "state": "MI", "npdes_permit": "MI0000001", "npdes_permits": ["MI0000001", "3112a-0001"]},
             {"id": "mi-b", "state": "MI", "npdes_permit": "MI0000002", "npdes_permits": ["MI0000002"]},
             {"id": "mi-c", "state": "MI", "npdes_permit": "MI0000002", "npdes_permits": []},
             {"id": "oh-a", "state": "OH", "npdes_permit": "OH0000001", "npdes_permits": []}]
    idx = M.permit_index(rows_)
    assert idx == {"MI0000001": "mi-a", "3112A-0001": "mi-a"}


@pytest.mark.parametrize("given,want", [
    ("Pat Example - Sample Lake Sewer", "Sample Lake Sewer"),
    ("Sample County WRC - Pat Example", "Sample County WRC"),
    ("Pat Example, Owner", "[name removed]"),
    ("Sample Heights (Pat Example)", "Sample Heights"),
    ("Sample Holdings, LLC", "Sample Holdings, LLC"),
    ("Sampleton, City of", "Sampleton, City of"),
    ("Western Sample Utilities Authority (WSUA)", "Western Sample Utilities Authority (WSUA)"),
])
def test_a_persons_name_joined_to_a_body_is_cut_and_the_body_kept(given, want):
    assert M.party_name(given) == want


def test_an_address_typed_on_the_land_reached_loses_its_number():
    out = M.scrubbed_row({"landImpacted": "Address 51751 Example Road. grassy area by the cleanout"})
    assert "51751" not in out["landImpacted"] and "grassy area" in out["landImpacted"]
