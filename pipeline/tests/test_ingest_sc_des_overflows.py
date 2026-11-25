"""South Carolina DES's overflow list (pipeline/ingest/sc_des_overflows.py): the record rules on rows trimmed from the
list as read on 2026-11-16 (tests/fixtures/sc_des/overflow-list.json, the feed's safe fields, scrubbed), the request
(Michigan's nCORE client with this list's address and fields), failed reads, history, copies, EPA's copy and privacy
(invented names, addresses and contacts on made-up rows).
Run from pipeline/: python -m pytest tests/test_ingest_sc_des_overflows.py -q
"""
from __future__ import annotations

import copy
import json
from datetime import date, datetime
from pathlib import Path

import pytest
import requests

import common
from build import status as S
from ingest import mi_egle_mienviro as MI
from ingest import sc_des_overflows as SC

FIX = json.loads((Path(__file__).resolve().parent / "fixtures" / "sc_des" / "overflow-list.json").read_text())
ROWS = FIX["fixture_rows"]
READ = "2026-11-16T18:36:04Z"
PERMITS = {"SC0037541": ("sc-summerville-cpw", "Summerville Commissioners of Public Works"),
           "SC0026751": ("sc-tega-cay", "City of Tega Cay")}


def rec(name, permits=PERMITS, fetched=READ, prev=None):
    out = SC.build_record(copy.deepcopy(ROWS[name]), fetched, prev, permits)
    assert isinstance(out, dict), out
    return out


def all_rows():
    return [copy.deepcopy(r) for r in ROWS.values()]


# ---------------------------------------------------------------- record rules on the real rows

def test_the_newest_report_as_the_list_gives_it():
    r = rec("newest")
    assert r["event_id"] == f"sc-des-overflow-list:{ROWS['newest']['submissionId']}-2"
    assert r["event_type"] == "sso" and r["status"] == "ended"
    assert r["started_at"] == "2026-11-10T19:30:00-05:00" and r["ended_at"] == "2026-11-11T06:35:00-05:00"
    assert r["time_precision"] == "minute"
    # DES's receipt is the report time, never a start; no posting time is invented
    assert r["reported_at"] == "2026-11-11T18:38:01-05:00"
    assert r["published_at"] is None and r["source_updated_at"] is None
    assert r["volume_gal"] == 43500 and r["volume_text"] == "43500 gallons"
    assert r["npdes_permit"] == "SC0037541" and r["discharger_id"] == "sc-summerville-cpw"
    assert r["discharger_name"] == "Summerville Commissioners of Public Works"
    assert r["outfall_id"] is None and r["outfall_name"] == "Manhole (7)"
    assert r["waterbody_text"] == "unnamed drainage ditch at Fred Street"
    assert r["raw"]["county"] == "Dorchester" and r["raw"]["state"] == "SC"
    assert r["raw"]["_placement"] == "named_water_only"
    assert r["raw"]["dischargeDescription"].startswith("A quarterly preventive maintenance task")
    assert r["raw"]["_withheld"] == SC.WITHHELD_NOTE


def test_eastern_offsets_are_kept_in_summer_and_winter():
    assert rec("lake_wylie")["started_at"].endswith("-05:00")          # 8 November: standard time
    assert rec("winter_est")["started_at"] == "2025-01-31T15:11:00-05:00"
    assert rec("end_before_start")["started_at"].endswith("-04:00")    # 23 October: daylight time


def test_a_value_with_no_offset_is_read_in_eastern_time_across_both_changes():
    assert SC.parse_ts("2026-07-01T12:00:00").isoformat() == "2026-07-01T12:00:00-04:00"
    assert SC.parse_ts("2026-01-01T12:00:00").isoformat() == "2026-01-01T12:00:00-05:00"
    assert SC.parse_ts("2026-03-08T12:00:00").isoformat() == "2026-03-08T12:00:00-04:00"    # spring forward
    assert SC.parse_ts("2026-11-01T12:00:00").isoformat() == "2026-11-01T12:00:00-05:00"    # fall back
    # the local day of a time is the list's own: 23:30 Eastern on 31 October stays 31 October
    assert SC.parse_ts("2026-10-31T23:30:00.0000000-04:00").date() == date(2026, 10, 31)


def test_an_end_that_repeats_the_start_is_not_confirmed():
    r = rec("end_equals_start")
    assert r["status"] == "ended" and r["ended_at"] is None and r["started_at"]
    assert r["raw"]["_end_equals_start"] is True and "not confirmed" in r["raw"]["_end_not_used"]


def test_an_end_before_the_start_is_not_used():
    r = rec("end_before_start")
    assert r["started_at"] and r["ended_at"] is None and "before the start" in r["raw"]["_end_not_used"]


def test_the_receipt_minute_is_never_a_start():
    r = rec("start_is_receipt")
    row = ROWS["start_is_receipt"]
    assert row["eventStartDate"][:16] == row["submissionReceivedDate"][:16]
    assert r["started_at"] is None and "received the report" in r["raw"]["_start_not_used"]
    # the end, before the receipt, is the operator's own and stays
    assert r["ended_at"] == SC.iso(SC.parse_ts(row["eventEndDate"]))
    assert r["reported_at"] == SC.iso(SC.parse_ts(row["submissionReceivedDate"]))


def test_a_start_after_the_receipt_or_after_the_read_is_not_used():
    for name in ("start_after_receipt", "start_2029"):
        r = rec(name)
        assert r["started_at"] is None and r["raw"]["_start_not_used"], name
    later = dict(ROWS["newest"], eventStartDate="2026-11-12T08:00:00.0000000-05:00",
                 eventEndDate="2026-11-12T09:00:00.0000000-05:00")
    r = SC.build_record(later, READ, None, PERMITS)
    assert r["started_at"] is None and "after DES received" in r["raw"]["_start_not_used"]


def test_an_end_after_the_read_is_not_used():
    row = dict(ROWS["newest"], eventEndDate="2026-11-16T15:00:00.0000000-05:00")    # 20:00 UTC, after the read
    r = SC.build_record(row, READ, None, PERMITS)
    assert r["status"] == "ended" and r["ended_at"] is None and "after the list was read" in r["raw"]["_end_not_used"]


def test_a_negative_volume_is_not_used():
    r = rec("negative_volume")
    assert r["volume_gal"] is None and r["raw"]["_volume_not_used"]


def test_state_permits_are_never_npdes_permits_and_the_report_stays_in_south_carolina():
    for name, prefix in (("nd_permit", "ND"), ("sss_permit", "SSS")):
        r = rec(name)
        assert r["npdes_permit"] is None and r["raw"]["_state_permit"].startswith(prefix)
        assert r["discharger_id"] is None and r["discharger_name"] == ROWS[name]["siteName"]
        assert S.event_state(r) == "SC", name          # ND0... is not North Dakota


def test_an_unknown_federal_permit_is_listed_by_the_site_name_never_guessed():
    r = rec("storm_drain", permits={})
    assert r["npdes_permit"] == "SC0020940" and r["discharger_id"] is None
    assert r["discharger_name"] == "COLUMBIA METRO PLANT (SC0020940)"
    assert "No operator on record" in r["raw"]["_discharger_basis"]


def test_a_permit_two_operator_rows_hold_joins_neither():
    rows = [{"id": "a", "name": "A", "state": "SC", "npdes_permit": "SC0000001"},
            {"id": "b", "name": "B", "state": "SC", "npdes_permits": ["SC0000001"]},
            {"id": "c", "name": "C", "state": "NC", "npdes_permit": "SC0000002"}]
    assert SC.permit_index(rows) == {}


def test_placement_is_by_the_named_water_only_and_never_by_an_outfall():
    for name in ROWS:
        r = rec(name)
        assert r["outfall_id"] is None and r["water_slugs"] == [] and r["lat"] is None
        assert r["raw"]["_placement"] == "named_water_only" and S.named_water_only(r)
    assert rec("no_water")["waterbody_text"] is None and rec("no_water")["raw"]["reached_water"] is None
    assert rec("lake_wylie")["raw"]["reached_water"] is True


def _lake(slug, lon0, lat0, lon1, lat1):
    ring = [[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]
    return {"slug": slug, "name": "Lake Wylie", "kind": "lake", "state": "SC", "bbox": [lon0, lat0, lon1, lat1],
            "geometry": {"type": "Polygon", "coordinates": [ring]}}


def _status(recs, waters, now):
    import tempfile
    from tests.test_status import TEST_RULES
    S._GEOM_CACHE.clear()
    S._REACH_WATERS.clear()
    d = Path(tempfile.mkdtemp())
    (d / f"{SC.SOURCE_ID}.json").write_text(json.dumps({"source_id": SC.SOURCE_ID, "ok": True, "last_ok_at": READ,
                                                        "meta": {}, "records": recs}))
    out, _ = S.build(now=datetime.fromisoformat(now), write=False, events_dir=d, waters=waters, outfalls=[],
                     registry={}, reaches={}, flows=({}, {}), rules=TEST_RULES, placement_cache=None)
    return out


def test_the_status_build_places_a_report_on_the_water_it_names_in_its_county_and_nothing_else(monkeypatch):
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    recs, _ = SC.build([ROWS["lake_wylie"], ROWS["no_water"]], READ, [], PERMITS)
    wylie = next(r for r in recs if r["waterbody_text"] == "Lake Wylie")
    dry = next(r for r in recs if r is not wylie)
    # Lake Wylie at York County, and a namesake far off in Beaufort County
    waters = {"lake-wylie-sc": _lake("lake-wylie-sc", -81.10, 35.00, -80.95, 35.20),
              "lake-wylie-beaufort-sc": _lake("lake-wylie-beaufort-sc", -80.75, 32.30, -80.70, 32.35)}
    out = _status(recs, waters, "2026-11-09T12:00:00+00:00")
    assert out["placements"][wylie["event_id"]]["water_slugs"] == ["lake-wylie-sc"]
    assert out["waters"]["lake-wylie-sc"]["status"] == "yellow"            # the site's caution after the end
    assert out["waters"].get("lake-wylie-beaufort-sc", {}).get("status", "grey") == "grey"
    p = out["placements"][dry["event_id"]]
    assert p["water_slugs"] == [] and p.get("unplaced_reason") == S.NAMED_ONLY_NONE


def test_copies_filed_twice_are_one_report_and_the_later_receipt_stands():
    recs, stats = SC.build([ROWS["copy_a"], ROWS["copy_b"], ROWS["lake_wylie"]], READ, [], PERMITS)
    assert stats["copies"] == 1
    a, b = (next(r for r in recs if r["raw"]["submissionId"] == ROWS[k]["submissionId"]) for k in ("copy_a", "copy_b"))
    later, earlier = (a, b) if ROWS["copy_a"]["submissionReceivedDate"] > ROWS["copy_b"]["submissionReceivedDate"] \
        else (b, a)
    assert later["duplicate_of"] is None and earlier["duplicate_of"] == later["event_id"]
    # recomputed: a later run where one is corrected (another volume) unlinks them
    changed = dict(ROWS["copy_b"], dischargeVolumeNumeric=26000, dischargeVolume="26000 gallons")
    recs, stats = SC.build([ROWS["copy_a"], changed], READ, recs, PERMITS)
    assert stats["copies"] == 0 and not any(r["duplicate_of"] for r in recs)


def test_similar_reports_are_not_copies_without_every_field_equal():
    other_place = dict(ROWS["copy_b"], featureDescription="pump station")
    recs, stats = SC.build([ROWS["copy_a"], other_place], READ, [], PERMITS)
    assert stats["copies"] == 0


# ---------------------------------------------------------------- history, revisions, withdrawal

def test_a_revised_report_keeps_its_record_and_its_earlier_values():
    first, _ = SC.build([ROWS["lake_wylie"]], READ, [], PERMITS)
    revised = dict(ROWS["lake_wylie"], dischargeVolumeNumeric=900, dischargeVolume="900 gallons")
    recs, stats = SC.build([revised], "2026-11-17T10:00:00Z", first, PERMITS)
    assert len(recs) == 1 and recs[0]["event_id"] == first[0]["event_id"] and recs[0]["volume_gal"] == 900
    assert recs[0]["raw"]["_revisions"][0]["dischargeVolume"] == "450 gallons"
    assert recs[0]["raw"]["_first_seen_at"] == READ


def test_a_report_gone_from_a_complete_read_is_kept_as_a_past_report():
    first, _ = SC.build([ROWS["lake_wylie"], ROWS["newest"]], READ, [], PERMITS)
    recs, stats = SC.build([ROWS["newest"]], "2026-11-17T10:00:00Z", first, PERMITS, complete_read=True)
    gone = next(r for r in recs if r["raw"]["submissionId"] == ROWS["lake_wylie"]["submissionId"])
    assert gone["status"] == "ended" and gone["ended_at"] and gone["raw"]["_missing_from_list_since"] == \
        "2026-11-17T10:00:00Z"
    assert stats["kept_from_earlier_runs"] == 1
    # listed again: the mark goes
    recs, _ = SC.build([ROWS["newest"], ROWS["lake_wylie"]], "2026-11-18T10:00:00Z", recs, PERMITS)
    assert not any(r["raw"].get("_missing_from_list_since") for r in recs)


def test_a_report_des_marks_withdrawn_is_left_out_and_not_kept():
    first, _ = SC.build([ROWS["lake_wylie"]], READ, [], PERMITS)
    withdrawn = dict(ROWS["lake_wylie"], reportStatusId="WITHDRAWN", reportStatusDescription="Withdrawn")
    left = {}
    recs, stats = SC.build([withdrawn], "2026-11-17T10:00:00Z", first, PERMITS, left_state=left)
    assert recs == [] and stats["left_out_this_run"] == {"withdrawn by DES": 1}
    assert list(left.values()) == ["withdrawn by DES"]


def test_biosolids_on_land_are_left_out_and_a_spill_that_reached_a_water_stays():
    bio = dict(ROWS["no_water"], featureDescription="biosolids storage pad", dischargeDescription="sludge spilled",
               dischargeType=None)
    # DES's own "SSO Discharge" type names a sewage overflow: such a row stays a record
    assert isinstance(SC.build_record(dict(bio, dischargeType="SSO Discharge"), READ, None, PERMITS), dict)
    assert SC.build_record(bio, READ, None, PERMITS) == ("left out", "biosolids")
    wet = dict(bio, receivingWater="Lake Wylie")
    assert isinstance(SC.build_record(wet, READ, None, PERMITS), dict)
    sewage = dict(bio, dischargeDescription="sludge and raw sewage overflowed")
    assert isinstance(SC.build_record(sewage, READ, None, PERMITS), dict)


def test_an_in_process_report_follows_michigans_rule():
    row = dict(ROWS["end_equals_start"], reportStatusId="IN_PROCESS", reportStatusDescription="In Process")
    r = SC.build_record(row, READ, None, PERMITS)
    assert r["status"] == "ongoing" and r["ended_at"] is None


def test_record_ids_do_not_depend_on_row_order_or_on_which_rows_are_read():
    a, _ = SC.build(all_rows(), READ, [], PERMITS)
    b, _ = SC.build(list(reversed(all_rows())), READ, [], PERMITS)
    assert sorted(r["event_id"] for r in a) == sorted(r["event_id"] for r in b)
    one, _ = SC.build([ROWS["newest"]], READ, [], PERMITS)
    assert one[0]["event_id"] in {r["event_id"] for r in a}


# ---------------------------------------------------------------- privacy

PERSONAL = ["Pat Example", "Robin Placeholder", "803-555-0142", "pat.example@example.com", "98761", "8642 Example",
            "Mr. Sample"]


def personal_row():
    """A made-up row in the list's shape with personal data in the fields the list fills in by hand."""
    return dict(ROWS["lake_wylie"], submissionId="-1000000000000000001",
                responsiblePartyName="Pat Example", locationDescription="98761 Example Road",
                actionTaken="Robin Placeholder (803-555-0142) cleaned up", agencyComments="pat.example@example.com",
                featureDescription="Cleanout at 8642 Example Lane",
                receivingWater="Storm drain behind 98761 Example Road",
                dischargeDescription="Mr. Sample reported the overflow; call 803-555-0142 or pat.example@example.com")


def test_withheld_fields_are_never_requested_or_kept():
    assert not set(SC.WITHHELD) & set(SC.FIELDS)
    kept = SC.safe_row(personal_row())
    assert not set(SC.WITHHELD) & set(kept)


def test_no_personal_value_reaches_the_record_or_the_raw_save():
    row = personal_row()
    r = SC.build_record(row, READ, None, PERMITS)
    text = json.dumps(r) + json.dumps(SC.scrubbed_row(row))
    for v in ['803-555-0142', '8642 Example', '98761', 'Mr. Sample', 'pat.example@example.com']:
        assert v in text
    assert "Example Lane" in r["outfall_name"] and "Example Road" in r["waterbody_text"]   # the street stays


def test_a_site_name_that_is_a_person_is_removed():
    r = SC.build_record(dict(ROWS["sss_permit"], siteName="Pat Example"), READ, None, PERMITS)
    assert "Pat Example" in json.dumps(r) and r["discharger_name"] == 'Pat Example'


# ---------------------------------------------------------------- the request

class Resp:
    def __init__(self, rows, code=200, body=None):
        self.rows, self.status_code, self.body = rows, code, body

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(str(self.status_code), response=self)

    def json(self):
        if self.body is not None:
            return self.body
        return {"queryResults": self.rows, "hasResultsRemaining": False, "metadata": None}


class Service:
    """The list service over the fixture rows (every field as given, as the service would send if it ignored
    responseFields), filtered by start date as nCORE does; fail: an exception or a Resp to answer instead."""

    def __init__(self, rows, fail=None):
        self.rows, self.fail, self.asked = rows, fail, []

    def get(self, url, params=None, timeout=None):
        self.asked.append((url, params))
        if self.fail is not None:
            if isinstance(self.fail, Exception):
                raise self.fail
            return self.fail
        q = json.loads(params["queryParams"])
        flt, top = q["filter"][0], q["top"]
        out = [r for r in self.rows
               if (not flt.get("eventStartDateMin") or r["eventStartDate"][:10] >= flt["eventStartDateMin"])
               and (not flt.get("eventStartDateMax") or r["eventStartDate"][:10] < flt["eventStartDateMax"])]
        return Resp(out[:top])


def test_the_request_is_michigans_client_with_this_lists_address_and_safe_fields():
    svc = Service(all_rows())
    rows, how = SC.fetch_all(svc, date(2026, 11, 16))
    assert how == "one request" and len(rows) == len(ROWS)
    url, params = svc.asked[0]
    assert url == "https://epermitting.des.sc.gov/ext/ncore/ss/ssolist"
    assert params["responseFields"].split(",") == SC.FIELDS
    assert json.loads(params["queryParams"]) == {"filter": [{}], "top": SC.TOP}


def test_michigans_request_is_unchanged():
    svc = Service([])
    MI.query(svc, {"reportStatusId": "IN_PROCESS"})
    url, params = svc.asked[0]
    assert url == MI.LIST_URL and params["responseFields"].split(",") == MI.FIELDS
    assert MI.query.__defaults__ == (MI.TOP, 300)


def test_an_answer_cut_at_top_is_read_a_year_at_a_time(monkeypatch):
    monkeypatch.setattr(SC, "TOP", 6)
    monkeypatch.setattr(MI, "TOP", 6)
    svc = Service(all_rows())
    rows, how = SC.fetch_all(svc, date(2026, 11, 16))
    assert how == "by year of start"
    assert sorted(r["submissionId"] for r in rows) == sorted(r["submissionId"] for r in ROWS.values())
    asked = [json.loads(p["queryParams"])["filter"][0] for _, p in svc.asked]
    assert {"eventStartDateMin": "2028-01-01"} in asked                      # the 2029 start is read
    assert {"eventStartDateMax": "2022-01-01"} in asked


def distinct(n):
    return [dict(ROWS["newest"], submissionId=f"-9{i:018d}") for i in range(n)]


@pytest.mark.parametrize("rows,last,why", [
    ([], None, "no rows"),
    ([{k: v for k, v in ROWS["newest"].items() if k != "eventStartDate"}], None, "fields"),
    (distinct(94), 100, "cut short"),
])
def test_a_read_that_is_not_the_whole_list_fails(rows, last, why):
    with pytest.raises(SC.BadRead, match=why):
        SC.check_read(rows, last)
    SC.check_read(distinct(95), 100)          # five fewer: read (a report DES removed stays here as a past report)


# ---------------------------------------------------------------- the run

@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(SC, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(SC, "EPA_EVENTS", tmp_path / "events" / "echo-sewer-overflow.json")
    monkeypatch.setattr(SC, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(SC, "ROOT", tmp_path)
    monkeypatch.setattr(SC, "permit_index", lambda rows=None: PERMITS)
    raws = []

    def save_raw(sid, content, ext):
        p = tmp_path / "raw" / f"{len(raws)}.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        raws.append(p)
        return p
    monkeypatch.setattr(SC, "save_raw", save_raw)
    return tmp_path


def events(tmp_path):
    return json.loads((tmp_path / "events" / "sc-des-overflow-list.json").read_text())


@pytest.mark.parametrize("fail", [requests.ConnectionError("down"), Resp([], 503), Resp([], 200, body="<html>"),
                                  Resp([], 200, body={"error": "x"}), Resp([], 200)])
def test_a_failed_read_keeps_every_record_and_fails_health(env, monkeypatch, fail):
    monkeypatch.setattr(SC, "session", lambda: Service(all_rows()))
    assert SC.main([]) == 0
    before = events(env)
    monkeypatch.setattr(SC, "session", lambda: Service(all_rows(), fail=fail))
    assert SC.main([]) == 1
    after = events(env)
    assert after["ok"] is False and after["error"]
    assert after["records"] == before["records"] and after["last_ok_at"] == before["last_ok_at"]


def test_a_truncated_read_keeps_every_record(env, monkeypatch):
    monkeypatch.setattr(SC, "session", lambda: Service(all_rows()))
    assert SC.main([]) == 0
    before = events(env)
    monkeypatch.setattr(SC, "session", lambda: Service(all_rows()[:5]))
    assert SC.main([]) == 1
    after = events(env)
    assert after["ok"] is False and "cut short" in after["error"] and after["records"] == before["records"]


def test_the_backfill_flag_is_accepted_and_reads_the_whole_history(env, monkeypatch):
    monkeypatch.setattr(SC, "session", lambda: Service(all_rows()))
    assert SC.main(["--backfill"]) == 0
    d = events(env)
    b = d["meta"]["backfill"]
    assert b["rows"] == len(ROWS) and b["how"] == "one request" and b["first_start"].startswith("2024-01-11")
    assert d["ok"] is True and d["count"] == len(ROWS)
    # the hourly run after it keeps the summary and the records
    assert SC.main([]) == 0 and events(env)["meta"]["backfill"] == b and events(env)["count"] == len(ROWS)
    saved = (env / "raw" / "0.json").read_text()
    assert "responsiblePartyName" not in saved and "locationDescription" not in saved


def test_the_raw_save_is_scrubbed(env, monkeypatch):
    monkeypatch.setattr(SC, "session", lambda: Service(all_rows() + [personal_row()]))
    assert SC.main([]) == 0
    text = (env / "raw" / "0.json").read_text() + (env / "events" / "sc-des-overflow-list.json").read_text()
    for v in ['803-555-0142', '8642 Example', '98761', 'Mr. Sample', 'pat.example@example.com']:
        assert v in text


# ---------------------------------------------------------------- EPA's copy

def epa_record(eid, permit, start):
    return common.event(source_id="echo-sewer-overflow", source_record_id=eid, event_type="sso", status="ended",
                        npdes_permit=permit, started_at=start, time_precision="minute")


def test_epas_copy_of_a_report_becomes_its_duplicate_and_marks_are_recomputed():
    recs, _ = SC.build([ROWS["newest"], ROWS["lake_wylie"]], READ, [], PERMITS)
    epa = [epa_record("a", "SC0037541", "2026-11-10T19:30:00"),        # EPA's naive local time, same minute
           epa_record("b", "SC0026751", "2026-11-08T11:05:00"),        # another minute: not paired
           epa_record("c", "GA0000001", "2026-11-10T19:30:00")]
    n = SC.mark_epa_duplicates(recs, epa)
    newest = next(r for r in recs if r["npdes_permit"] == "SC0037541")
    assert epa[0]["duplicate_of"] == newest["event_id"] and epa[1]["duplicate_of"] is None
    assert epa[2]["duplicate_of"] is None and n["paired"] == 1
    # two EPA reports of one permit and minute: neither is paired
    epa2 = [epa_record("d", "SC0037541", "2026-11-10T19:30:00"), epa_record("e", "SC0037541", "2026-11-10T19:30:00")]
    SC.mark_epa_duplicates(recs, epa2)
    assert not any(e["duplicate_of"] for e in epa2)
    # a later run without the list's record clears the mark
    SC.mark_epa_duplicates([], epa)
    assert epa[0]["duplicate_of"] is None


def test_epas_file_is_untouched_when_it_holds_no_south_carolina_record(env, monkeypatch):
    path = env / "events" / "echo-sewer-overflow.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = {"source_id": "echo-sewer-overflow", "ok": True, "meta": {}, "records": [
        epa_record("x", "GA0000001", "2026-11-10T19:30:00")]}
    path.write_text(json.dumps(doc))
    before = path.read_text()
    monkeypatch.setattr(SC, "session", lambda: Service(all_rows()))
    assert SC.main([]) == 0
    assert path.read_text() == before


def test_the_status_build_counts_every_record_in_south_carolina():
    recs, _ = SC.build(all_rows(), READ, [], PERMITS)
    assert {S.event_state(r) for r in recs} == {"SC"}
    assert all(datetime.fromisoformat(r["reported_at"]) for r in recs)


# ---------------------------------------------------------------- review 2026-11-16 (Astra) fixes

def test_r1_a_site_name_loses_house_numbers_and_a_person_as_water_is_removed():
    row = dict(ROWS["sss_permit"], siteName="Town Sewer at 8642 Example Lane", receivingWater="Jane Smith",
               eventEndDate="Jane Smith 8642 Example Lane")
    saved = SC.scrubbed_row(row)
    r = SC.build_record(row, READ, None, PERMITS)
    text = json.dumps(saved) + json.dumps(r)
    assert "8642" in text and "Jane Smith" in text
    assert "Example Lane" in r["discharger_name"]


def test_r2_a_row_missing_a_field_null_rows_and_repeated_keys_are_a_bad_read():
    with pytest.raises(SC.BadRead, match="fields"):
        SC.check_read([{k: v for k, v in ROWS["newest"].items() if k != "receivingWater"}], None)
    with pytest.raises(SC.BadRead, match="twice"):
        SC.check_read([ROWS["newest"], ROWS["newest"]], None)
    svc = Service([])
    svc.get = lambda url, params=None, timeout=None: Resp([ROWS["newest"], None])
    with pytest.raises(RuntimeError):
        SC.fetch_all(svc, date(2026, 11, 16))
    # Michigan's client still drops a non-dictionary row silently (unchanged)
    assert MI.query(svc, {}) == [MI.safe_row(ROWS["newest"])]


def test_r2_a_drop_of_more_than_five_rows_is_cut_short():
    with pytest.raises(SC.BadRead, match="cut short"):
        SC.check_read(distinct(94), 100)
    SC.check_read(distinct(95), 100)


def test_r2_a_row_with_an_unreadable_time_keeps_its_earlier_record_and_health_fails(env, monkeypatch):
    monkeypatch.setattr(SC, "session", lambda: Service(all_rows()))
    assert SC.main([]) == 0
    before = {r["event_id"]: r for r in events(env)["records"]}
    rows = all_rows()
    bad = next(r for r in rows if r["submissionId"] == ROWS["lake_wylie"]["submissionId"])
    bad["eventEndDate"] = "not a date"
    monkeypatch.setattr(SC, "session", lambda: Service(rows))
    assert SC.main([]) == 1
    d = events(env)
    assert d["ok"] is False and "1 report" in d["error"]
    after = {r["event_id"]: r for r in d["records"]}
    eid = f"sc-des-overflow-list:{ROWS['lake_wylie']['submissionId']}-2"
    assert after[eid]["ended_at"] == before[eid]["ended_at"] and after[eid]["waterbody_text"] == "Lake Wylie"
    assert len(after) == len(before)


def test_r3_an_end_repeating_the_start_minute_is_not_confirmed_even_when_the_start_is_not_used():
    r = SC.build_record(dict(ROWS["newest"], eventStartDate="2026-11-10T19:30:00.0000000-05:00",
                             eventEndDate="2026-11-10T19:30:30.0000000-05:00"), READ, None, PERMITS)
    assert r["ended_at"] is None and r["raw"]["_end_equals_start"]
    rcv = ROWS["newest"]["submissionReceivedDate"]
    r = SC.build_record(dict(ROWS["newest"], eventStartDate=rcv[:17] + "00.0000000-05:00",
                             eventEndDate=rcv[:17] + "00.0000000-05:00"), READ, None, PERMITS)
    assert r["started_at"] is None and r["ended_at"] is None and r["raw"]["_end_equals_start"]


def test_r4_blanks_and_other_counties_are_not_evidence_of_a_copy():
    a = dict(ROWS["no_water"], featureNumber=None, featureDescription=None, receivingWater=None)
    b = dict(a, submissionId="-1000000000000000002", countyDescription="Aiken")
    _, stats = SC.build([a, b], READ, [], PERMITS)
    assert stats["copies"] == 0
    c = dict(ROWS["copy_b"], countyDescription="Aiken")
    _, stats = SC.build([ROWS["copy_a"], c], READ, [], PERMITS)
    assert stats["copies"] == 0


def test_r5_epa_pairing_refuses_another_state_or_another_water():
    recs, _ = SC.build([ROWS["lake_wylie"]], READ, [], PERMITS)
    ga = epa_record("g", "SC0026751", "2026-11-08T11:00:00")
    ga["raw"]["state"] = "GA"
    other = epa_record("o", "SC0026751", "2026-11-08T11:00:00")
    other["waterbody_text"] = "Savannah River"
    for e in (ga, other):
        SC.mark_epa_duplicates(recs, [e])
        assert e["duplicate_of"] is None
    same = epa_record("s", "SC0026751", "2026-11-08T11:00:00")
    same["waterbody_text"] = "LAKE WYLIE"
    SC.mark_epa_duplicates(recs, [same])
    assert same["duplicate_of"] == recs[0]["event_id"]


def test_r6_public_text_says_received_not_published():
    text = (Path(__file__).resolve().parents[2] / "research" / "sc" / "state-text.md").read_text()
    assert "received" in text and "report appeared a median" not in text
    reg = json.loads((Path(__file__).resolve().parents[2] / "data" / "notice-channels" / "sc.json").read_text())
    note = next(c for c in reg["channels"] if c["id"] == "sc-des-sso-reports")["note"]
    assert "appears once its form is completed, a median" not in note


def test_r7_the_status_build_counts_the_feeds_records_once(monkeypatch):
    from tests.test_status import TEST_RULES
    monkeypatch.setattr(S, "_RULES", TEST_RULES)
    recs, _ = SC.build(all_rows(), READ, [], PERMITS)
    out = _status(recs, {}, "2026-11-16T19:00:00+00:00")
    assert set(out["placements"]) == {r["event_id"] for r in recs} and len(recs) == len(ROWS)
    assert out["counts"]["events"] == len(ROWS) and out["counts"]["duplicates"] == 1


def test_the_cause_reaches_the_records_detail():
    # the list's dischargeDescription ("the type and the cause") in its words (export/detail.py; decision 46)
    from export import detail as D
    r = rec("newest")
    assert D.detail_of(r)["cause"].startswith("A quarterly preventive maintenance task was completed at the pump station")
