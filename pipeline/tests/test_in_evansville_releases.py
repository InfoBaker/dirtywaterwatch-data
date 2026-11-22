"""EWSU's real public records, trimmed before saving; network responses are mocked."""
import copy
import json
from datetime import date, datetime
from pathlib import Path

import pytest
import requests

from ingest import in_evansville_releases as E

FIXTURE = Path(__file__).parent / "fixtures/in_evansville_releases.json"
ROWS = json.loads(json.loads(FIXTURE.read_text())["Result"])
FETCHED = "2026-11-22T21:00:00Z"


def row(oid=4111):
    return copy.deepcopy(next(r for r in ROWS if r["Id"] == oid))


def test_source_values_and_three_clocks():
    r = E.to_record(row(), FETCHED)
    assert r["event_id"] == "in-evansville-releases:4111"
    assert r["started_at"] == "2026-09-06T19:30:00-05:00"
    assert r["ended_at"] == "2026-09-06T23:30:00-05:00"
    assert r["time_precision"] == r["raw"]["ended_at_precision"] == "minute"
    assert r["volume_gal"] == row()["VolumeReleased"]
    assert r["raw"]["CauseDescription"] == row()["CauseDescription"]
    assert r["raw"]["AffectedArea"] == row()["AffectedArea"]
    assert E.to_record(row(3839), FETCHED)["waterbody_text"] == "Carpentier Creek Tributary"
    assert r["raw"]["source_entered_at"] == "2026-09-08T16:13:30.480000-05:00"
    assert r["reported_at"] is r["published_at"] is r["source_updated_at"] is None
    assert r["fetched_at"] == FETCHED
    assert r["estimate_flag"] == "unknown"
    assert r["authority"] == E.AUTHORITY
    assert r["source_url"].startswith(E.QUERY)
    assert r["discharger_id"] == "in-city-of-evansville"
    assert r["npdes_permit"] is r["outfall_id"] is None


def test_winter_clock_and_invalid_source_end_are_not_repaired():
    r = E.to_record(row(3839), FETCHED)
    assert r["started_at"].endswith("-06:00")
    bad = E.to_record(row(3643), FETCHED)
    assert bad["ended_at"] is None and bad["status"] == "unknown"
    assert "before" in bad["parse_error"]
    assert bad["raw"]["EndDateTime"] == "2018-02-07T16:00:00"
    assert "estimated_end" not in bad["raw"]


@pytest.mark.parametrize("value", ["2026-03-08T02:30:00", "2026-11-01T01:30:00"])
def test_dst_gap_or_ambiguous_clock_is_unknown(value):
    a = row(); a["StartDateTime"] = value
    a["StartDate"] = value[:10] + "T00:00:00"; a["StartTime"] = value[11:]
    r = E.to_record(a, FETCHED)
    assert r["started_at"] is None and r["parse_error"]


def test_date_only_and_missing_end_respect_flags():
    a = row(); a["HasStartTime"] = a["HasEndTime"] = False
    r = E.to_record(a, FETCHED)
    assert r["time_precision"] == r["raw"]["ended_at_precision"] == "day"
    assert r["started_at"] == r["ended_at"] == "2026-09-06T00:00:00-05:00"
    a["HasEndDate"] = False
    assert E.to_record(a, FETCHED)["ended_at"] is None


def test_seconds_and_fractional_volume_are_preserved():
    a = row(); a["EndTime"] = "23:30:15"; a["EndDateTime"] = "2026-09-06T23:30:15"
    a["VolumeReleased"] = 12.5
    r = E.to_record(a, FETCHED)
    assert r["ended_at"].endswith("23:30:15-05:00")
    assert r["raw"]["ended_at_precision"] == "second" and r["volume_gal"] == 12.5
    a["VolumeReleased"] = 0
    assert E.to_record(a, FETCHED)["volume_gal"] == 0


@pytest.mark.parametrize("volume", [1234567.89, 123456789, 0.123456789])
def test_volume_text_preserves_more_than_six_significant_digits(volume):
    a = row(); a["VolumeReleased"] = volume
    r = E.to_record(a, FETCHED)
    assert r["volume_gal"] == volume
    assert r["volume_text"] == f"{volume} gallons"


@pytest.mark.parametrize("value", [-1, float("nan"), float("inf"), "invalid"])
def test_bad_volume_is_not_a_number(value):
    a = row(); a["VolumeReleased"] = value
    r = E.to_record(a, FETCHED)
    assert r["volume_gal"] is None and r["parse_error"]


def test_no_water_is_invented_and_private_operator_is_not_assigned():
    for a in ROWS:
        r = E.to_record(a, FETCHED)
        if a["AffectedArea"] in {"Storm Sewer", "Ground"}:
            assert r["waterbody_text"] == a["AffectedArea"] and r["water_slugs"] == []
            assert r["raw"]["AffectedArea"] == a["AffectedArea"]
            assert r["raw"]["_placement"] == "named_water_only"
        if a["EWSUSystem"] is False:
            assert r["discharger_id"] is None


def test_real_out_of_state_point_is_not_relocated():
    r = E.to_record(row(3510), FETCHED)
    assert r["lat"] is r["lon"] is r["coord_source"] is None
    assert r["raw"]["Longitude"] == -76.766
    assert r["waterbody_text"] == "Ground/Eagle Creek"
    assert r["water_slugs"] == []


@pytest.mark.parametrize("oid", [4111, 4107])
def test_affected_area_names_no_water_in_status_and_public_record(oid, tmp_path):
    from build import status as S
    from build.redact import Lexicon, Redactor
    from export.build import public_record

    r = E.to_record(row(oid), FETCHED)
    assert r["lat"] is not None and r["lon"] is not None
    (tmp_path / f"{E.SOURCE_ID}.json").write_text(json.dumps({
        "source_id": E.SOURCE_ID, "ok": True, "last_ok_at": FETCHED,
        "meta": {}, "records": [r],
    }))
    status, _ = S.build(now=datetime.fromisoformat(FETCHED), write=False, events_dir=tmp_path,
                        waters={}, outfalls=[], registry={}, reaches={}, flows=({}, {}),
                        discharger_towns={}, discharger_waters={})
    assert status["counts"]["no_receiving_water"] == 1
    assert status["counts"]["unplaced"] == status["counts"]["no_release"] == 0
    assert status["no_receiving_water_events"] == [r["event_id"]]
    placement = status["placements"][r["event_id"]]
    public = public_record(r, placement, Redactor(Lexicon(), set()))
    assert public["no_receiving_water"] == f"the report names no water, only '{row(oid)['AffectedArea']}'"
    assert public["unplaced_reason"] is None
    assert public["water_slugs"] == []
    assert r["raw"]["AffectedArea"] == row(oid)["AffectedArea"]
    assert not placement.get("stated_no_water")
    assert S.no_water_flag(r) is None and S.reached_no_water(r) is None


def test_privacy_before_raw_storage_and_unknown_text_is_withheld():
    a = row()
    secret = "UNREVIEWED_PERSONAL_TEXT"
    a.update(LocationDescription=secret, Action=secret, UpStreamManhole=secret,
             reporter=secret, CauseDescription=secret, AffectedArea=secret, EventReason=secret)
    safe = E.safe_row(a)
    assert secret not in json.dumps(safe)
    assert "LocationDescription" not in safe and "UpStreamManhole" not in safe
    assert safe["Latitude"] == round(row()["Latitude"], 3)
    r = E.to_record(a, FETCHED)
    assert secret not in json.dumps(r) and r["parse_error"]


class Response:
    def __init__(self, rows):
        self.rows = rows
    def raise_for_status(self):
        pass
    def json(self):
        return {"Success": True, "HasWarning": False, "Result": json.dumps(self.rows)}


class Session:
    def __init__(self, pages):
        self.pages = iter(pages); self.urls = []
    def get(self, url, **kwargs):
        self.urls.append(url)
        return Response(next(self.pages))


def test_complete_year_windows_dedupe_boundary_rows_and_check_whole_query():
    a = row(); b = row(3839)
    sess = Session([[a, b], [b], [a, b]])
    rows, meta = E.fetch_rows(sess, date(2022, 1, 2), first_year=2021, pause=0)
    assert len(rows) == 2 and meta["partition_rows"] == 3
    assert sess.urls[1].endswith("01.01.2021/01.01.2022/*")
    assert sess.urls[2].endswith("01.01.2022/01.02.2022/*")


def test_truncated_page_or_conflicting_same_id_fails():
    a = row(); b = row(3839)
    with pytest.raises(ValueError):
        E.fetch_rows(Session([[a, b], [a]]), date(2026, 11, 22), first_year=2026, pause=0)
    revised = row(); revised["VolumeReleased"] += 1
    with pytest.raises(ValueError):
        E.fetch_rows(Session([[a], [a, revised]]), date(2026, 11, 22), first_year=2026, pause=0)


@pytest.mark.parametrize("payload", [{"Success": False, "Result": "[]"},
    {"Success": True, "HasWarning": True, "Result": "[]"},
    {"Success": True, "Result": "{}"}, {"Success": True, "Result": "[{}]"}])
def test_malformed_contract_is_not_a_quiet_feed(payload):
    with pytest.raises(ValueError):
        E.decode(payload)


def test_identity_revisions_and_missing_history():
    first, _ = E.build([row()], FETCHED, [])
    a = row(); a["VolumeReleased"] += 1
    second, _ = E.build([a, a], "2026-11-23T21:00:00Z", first)
    assert len(second) == 1 and second[0]["event_id"] == first[0]["event_id"]
    assert second[0]["volume_gal"] == a["VolumeReleased"]
    assert second[0]["raw"]["_first_seen_at"] == FETCHED
    assert len(second[0]["raw"]["_revisions"]) == 1
    third, _ = E.build([a], "2026-11-24T21:00:00Z", second)
    assert len(third[0]["raw"]["_revisions"]) == 1
    kept, stats = E.build([], "2026-11-25T21:00:00Z", third)
    assert kept[0]["fetched_at"] == third[0]["fetched_at"]
    assert stats["kept_from_earlier_runs"] == 1


def test_outage_retains_records_and_last_good_raw(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(E, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(E, "STATE_FILE", tmp_path / "state.json")
    records, _ = E.build([row()], FETCHED, [])
    p = common.write_events(E.SOURCE_ID, records, meta={"raw_path": "last-good.json"})
    before = json.loads(p.read_text())
    def fail(*args, **kwargs):
        raise requests.ConnectionError("unreachable")
    monkeypatch.setattr(E, "fetch_rows", fail)
    assert E.main([]) == 1
    after = json.loads(p.read_text())
    assert after["records"] == before["records"] and after["ok"] is False
    assert after["last_ok_at"] == before["last_ok_at"]
    assert after["meta"]["raw_path"] == "last-good.json"


@pytest.mark.parametrize("missing", ["StartTime", "EndTime"])
@pytest.mark.parametrize("bad_page", ["whole", "year"])
def test_missing_clock_key_fails_fetch_and_retains_history(missing, bad_page, tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(E, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(E, "STATE_FILE", tmp_path / "state.json")
    records, _ = E.build([row()], FETCHED, [])
    p = common.write_events(E.SOURCE_ID, records, meta={"raw_path": "last-good.json"})
    before = json.loads(p.read_text())
    malformed = row(); del malformed[missing]
    pages = [[malformed], [malformed]] if bad_page == "whole" else [[row()], [malformed]]
    fetch = E.fetch_rows
    with pytest.raises(ValueError, match="missing core fields"):
        fetch(Session(pages), date(2026, 11, 22), first_year=2026, pause=0)
    monkeypatch.setattr(E, "fetch_rows", lambda *args, **kwargs: fetch(
        Session(pages), date(2026, 11, 22), first_year=2026, pause=0))
    assert E.main([]) == 1
    after = json.loads(p.read_text())
    assert after["ok"] is False and after["records"] == before["records"]
    assert after["last_ok_at"] == before["last_ok_at"]
    assert after["meta"]["raw_path"] == "last-good.json"
    assert not E.STATE_FILE.exists()


def test_null_clock_keys_are_valid_when_clocks_are_unavailable():
    a = row()
    a.update(StartTime=None, EndTime=None, HasStartTime=False, HasEndTime=False)
    decoded = E.decode(Response([a]).json())
    r = E.to_record(decoded[0], FETCHED)
    assert r["started_at"] == r["ended_at"] == "2026-09-06T00:00:00-05:00"
    assert r["time_precision"] == r["raw"]["ended_at_precision"] == "day"
    assert r["parse_error"] is None
    a["HasEndDate"] = False
    assert E.to_record(E.decode(Response([a]).json())[0], FETCHED)["ended_at"] is None


def test_empty_history_fails_instead_of_clearing_records():
    with pytest.raises(ValueError, match="empty"):
        E.fetch_rows(Session([[]]), date(2026, 11, 22), first_year=2026, pause=0)


def test_saved_raw_is_scrubbed_and_repeated_read_reuses_it(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(E, "EVENTS_DIR", tmp_path / "events")
    monkeypatch.setattr(E, "STATE_FILE", tmp_path / "state.json")
    monkeypatch.setattr(E, "ROOT", tmp_path)
    a = row(); a.update(LocationDescription="PRIVATE_LOCATION", Action="PRIVATE_ACTION",
                        CauseDescription="UNREVIEWED_TEXT", reporter="PRIVATE_REPORTER")
    source = tmp_path / "input.json"
    source.write_text(json.dumps([a]))
    saved = []
    def save(sid, content, ext):
        target = tmp_path / "raw.json"
        target.write_bytes(content)
        saved.append(content)
        return target
    monkeypatch.setattr(E, "save_raw", save)
    assert E.main(["--file", str(source)]) == 0
    assert E.main(["--file", str(source)]) == 0
    assert len(saved) == 1
    assert b"PRIVATE_" not in saved[0] and b"UNREVIEWED_TEXT" not in saved[0]
    assert json.loads(saved[0])[0]["_withheld_fields"] == ["CauseDescription"]
    output = json.loads((tmp_path / "events" / f"{E.SOURCE_ID}.json").read_text())
    assert output["ok"] and len(output["records"]) == 1
    assert "_revisions" not in output["records"][0]["raw"]
