"""Knoxville Utilities Board's sewer overflow log (ingest/tn_kub_sso_log.py). Fixture: sixteen rows of the log's data
address read 2026-11-17 (the twelve newest, and older ones with no time, an odd time value, an "Unknown" volume), each
house number replaced by a made-up one. No network."""
import json
from datetime import date
from pathlib import Path

import pytest
import requests

from common import HOUSE_NUMBER_REMOVED
from ingest import tn_kub_sso_log as K

FIX = Path(__file__).parent / "fixtures"
DOC = json.loads((FIX / "tn_kub_sso_log.json").read_text())
NOW = "2026-11-17T10:00:00Z"


class R:
    def __init__(self, code=200, body=None, raw=None):
        self.status_code, self._body = code, body
        self.content = raw if raw is not None else json.dumps(body).encode()

    def raise_for_status(self):
        if self.status_code != 200:
            raise requests.HTTPError(str(self.status_code))

    def json(self):
        return json.loads(self.content)


def answer(first: date, last: date, rows=None):
    rows = DOC["customerSsoLog"] if rows is None else rows
    got = [r for r in rows if K.local_day(r["date"]) is None or first <= K.local_day(r["date"]) <= last]
    return {"meta": {"start": 0, "count": len(got), "total": len(got)}, "customerSsoLog": got}


class Web:
    def __init__(self, rows=None, fail=(), body=None):
        self.rows, self.fail, self.body, self.urls = rows, set(fail), body, []

    def __call__(self, url):
        self.urls.append(url)
        assert url.startswith(K.API + "?date[]=") and url.endswith("&sort=date")
        first = date.fromisoformat(url.split("date[]=")[1].split(":")[0])
        last = date.fromisoformat(url.split("date[]=")[2].split(":")[0])
        if f"{first:%Y-%m}" in self.fail:
            raise requests.ConnectionError("reset")
        if self.body is not None:
            return R(body=self.body) if not isinstance(self.body, bytes) else R(raw=self.body)
        return R(body=answer(first, last, self.rows))


def run(tmp_path, web=None, tdec=(), **kw):
    out = tmp_path / "ev.json"
    code = K.run(NOW, tmp_path / "state.json", out, get=web or Web(), tdec=list(tdec), sleep=lambda s: None,
                 today=kw.pop("today", date(2026, 11, 17)), save=False, **kw)
    return code, json.loads(out.read_text())


def by_start(doc):
    return {r["started_at"]: r for r in doc["records"]}


def test_times_are_read_as_the_page_shows_them_in_knoxville():
    assert K.local_day("2026-03-10T04:00:00.000+00:00") == date(2026, 3, 10)
    assert K.local_day("2026-02-05T05:00:00.000+00:00") == date(2026, 2, 5)
    assert K.local_clock("1970-01-01T16:49:00.000+00:00") == (11, 49)
    assert K.local_clock("1970-01-02T00:09:00.000+00:00") == (19, 9)          # an evening time
    assert K.local_clock(None) is None


def test_the_hourly_read_asks_last_month_and_this_month(tmp_path):
    web = Web()
    code, doc = run(tmp_path, web)
    assert code == 0 and doc["ok"]
    assert web.urls == [K.API + "?date[]=2026-10-01:greaterThanOrEquals&date[]=2026-11-30:lessThanOrEquals&sort=date"]
    assert len(doc["records"]) == 4                       # the October rows
    web = Web()
    run(tmp_path, web, today=date(2027, 1, 3))
    assert "2026-12-01:greaterThanOrEquals" in web.urls[0] and "2027-01-31:lessThanOrEquals" in web.urls[0]


def test_records_from_the_log(tmp_path):
    code, doc = run(tmp_path, Web(), backfill=True)
    assert code == 0 and doc["ok"]
    recs = by_start(doc)
    assert len(recs) == 14                                 # 2023 on; the 2005 and 2019 rows are before the reach
    r = recs["2026-10-18T15:42:00-04:00"]
    assert r["event_type"] == "sso" and r["status"] == "unknown" and r["ended_at"] is None
    assert r["time_precision"] == "minute" and r["reported_at"] is None and r["published_at"] is None
    assert r["volume_gal"] == 5 and r["volume_text"] == "5 gallons" and r["estimate_flag"] == "unknown"
    assert r["raw"]["cleanup_status"] == "Complete" and r["raw"]["cleanup_completed_on"] == "2026-10-19"
    assert r["discharger_id"] == "tn-kub" and r["npdes_permit"] is None
    assert r["waterbody_text"] is None and r["lat"] is None and r["water_slugs"] == []
    assert r["raw"]["_placement"] == "named_water_only" and r["raw"]["county"] == "Knox"
    assert r["raw"]["location"] == "1100 PINE GROVE ROAD"
    assert r["source_url"] == K.api_url(date(2026, 10, 1), date(2026, 10, 31))
    assert r["event_id"] == "tn-kub-sso-log:2026-10-18T1542:PINEGROVERD"
    # an evening time stored on 1970-01-02, in daylight time
    assert recs["2026-10-19T20:34:00-04:00"]["raw"]["cleanup_status"] == "New"
    assert recs["2026-10-19T20:34:00-04:00"]["volume_gal"] is None
    # "Unknown" gallons stays unreported, as written
    unk = recs["2026-08-21T13:00:00-04:00"]
    assert unk["volume_gal"] is None and unk["volume_text"] is None and unk["raw"]["volume_as_written"] == "Unknown"
    assert unk["raw"]["cleanup_completed_on"] is None
    # winter: Eastern standard time
    assert "2023-02-17T06:04:00-05:00" in recs


def test_a_row_with_no_time_stays_a_date(tmp_path):
    code, doc = run(tmp_path, Web(), backfill=True, since="2005-01-01")
    r = by_start(doc)["2005-01-05T00:00:00-05:00"]
    assert r["time_precision"] == "day" and "no time" in r["raw"]["time_note"]
    assert r["event_id"] == "tn-kub-sso-log:2005-01-05Tday:CHATHAMCIR"


def test_backfill_reads_each_month_from_2023(tmp_path):
    web = Web()
    run(tmp_path, web, backfill=True)
    assert len(web.urls) == 47 and "2023-01-01:greaterThanOrEquals" in web.urls[0]
    assert "2026-11-01:greaterThanOrEquals" in web.urls[-1]


def test_source_house_numbers_reach_records(tmp_path):
    _, doc = run(tmp_path, Web(), backfill=True, since="2005-01-01")
    assert len(doc["records"]) == 16
    source_places = {row["location"] for row in DOC["customerSsoLog"]}
    for record in doc["records"]:
        assert record["raw"]["location"] in source_places
        assert record["outfall_name"] == record["raw"]["location"]


def test_an_empty_month_is_a_healthy_read(tmp_path):
    code, doc = run(tmp_path, Web(rows=[]))
    assert code == 0 and doc["ok"] and doc["records"] == []


@pytest.mark.parametrize("body", [{"errors": [{"date": ["A date filter with a minimum is required"]}]}, b"<html>",
                                  {"customerSsoLog": [{"date": None, "location": "x"}]}])
def test_an_answer_that_is_not_the_log_fails_and_keeps_the_records(tmp_path, body):
    run(tmp_path)
    code, doc = run(tmp_path, Web(body=body))
    assert code == 1 and not doc["ok"] and len(doc["records"]) == 4


def test_a_failed_request_fails_health(tmp_path):
    run(tmp_path)
    code, doc = run(tmp_path, Web(fail=["2026-10"]))
    assert code == 1 and not doc["ok"] and len(doc["records"]) == 4


def test_backfill_exits_0_when_some_months_read_and_names_the_rest(tmp_path):
    code, doc = run(tmp_path, Web(fail=["2026-09"]), backfill=True)
    assert code == 0 and not doc["ok"] and "2026-09" in doc["meta"]["months_not_read"]
    assert len(doc["records"]) == 9
    (tmp_path / "x").mkdir()
    code, doc = run(tmp_path / "x", Web(fail=[f"{y}-{m:02d}" for y in range(2023, 2027) for m in range(1, 13)]),
                    backfill=True)
    assert code == 1 and not doc["ok"]


def test_a_row_gone_from_its_month_keeps_its_record_and_says_so(tmp_path):
    run(tmp_path)
    rows = [r for r in DOC["customerSsoLog"] if not r["location"].endswith("SHIPETOWN ROAD")]
    code, doc = run(tmp_path, Web(rows=rows))
    r = by_start(doc)["2026-10-19T20:34:00-04:00"]
    assert code == 0 and r["raw"]["_missing_from_source_since"] == NOW


def test_a_kub_record_is_the_duplicate_of_tdecs_record_of_the_same_overflow(tmp_path):
    tdec = [{"event_id": "tn-tdec-events-report:TN0021822:20261018:SSO:PINEGROVEROAD", "npdes_permit": "TN0021822",
             "discharger_id": "tn-kub", "started_at": "2026-10-18T00:00:00-04:00",
             "outfall_name": f"{HOUSE_NUMBER_REMOVED} PINE GROVE ROAD, KNOXVILLE",
             "raw": {"_outfall_name_basis": "Event Address and Event City (the house number removed)"},
             "duplicate_of": None},
            {"event_id": "tn-tdec-events-report:other", "npdes_permit": "TN0099999", "discharger_id": "tn-other",
             "started_at": "2026-10-07T00:00:00-04:00", "outfall_name": "x PINE GROVE RD, KNOXVILLE",
             "raw": {"_outfall_name_basis": "x"}, "duplicate_of": None}]
    _, doc = run(tmp_path, tdec=tdec)
    recs = by_start(doc)
    assert recs["2026-10-18T15:42:00-04:00"]["duplicate_of"] == tdec[0]["event_id"]
    assert "same street" in recs["2026-10-18T15:42:00-04:00"]["raw"]["_duplicate_basis"]
    assert recs["2026-10-07T13:45:00-04:00"]["duplicate_of"] is None
    assert doc["meta"]["tdec_links"] == {"linked": 1}


def test_main_reads_a_saved_answer(tmp_path):
    out = tmp_path / "o.json"
    assert K.main(["--file", str(FIX / "tn_kub_sso_log.json"), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["count"] == 14


# ---------------------------------------------------------------- review 2026-11-17 (Astra) fixes

def test_source_address_in_state_and_invalid_row_not_published(tmp_path):
    run(tmp_path, Web(), backfill=True)
    state = (tmp_path / "state.json").read_text()
    assert "1100 PINE" in state
    code, doc = run(tmp_path, Web(body={"customerSsoLog": [{"date": None, "location": "4321 SECRET LANE"}],
                                        "meta": {"start": 0, "count": 1, "total": 1}}))
    assert "4321" not in json.dumps(doc)


def test_review_p2_6_street_suffixes_match_and_ambiguous_pairs_are_left(tmp_path):
    t = {"event_id": "tn-tdec-events-report:a", "npdes_permit": "TN0021822", "discharger_id": "tn-kub",
         "started_at": "2026-10-07T00:00:00-04:00", "outfall_name": f"{HOUSE_NUMBER_REMOVED} PINE GROVE ROAD, KNOXVILLE",
         "raw": {"_outfall_name_basis": "Event Address"}, "duplicate_of": None}
    _, doc = run(tmp_path, tdec=[t])
    assert by_start(doc)["2026-10-07T13:45:00-04:00"]["duplicate_of"] == "tn-tdec-events-report:a"   # RD = ROAD
    t2 = {**t, "event_id": "tn-tdec-events-report:b"}
    (tmp_path / "y").mkdir()
    _, doc = run(tmp_path / "y", tdec=[t, t2])
    assert by_start(doc)["2026-10-07T13:45:00-04:00"]["duplicate_of"] is None


def test_review_p2_8_a_bad_row_does_not_lose_the_month(tmp_path):
    rows = DOC["customerSsoLog"] + [{"date": None, "time": None, "location": "x", "volume": "1", "status": "Complete",
                                     "completionDate": None}]
    code, doc = run(tmp_path, Web(rows=rows), backfill=True)
    assert code == 0 and not doc["ok"] and len(doc["records"]) == 14


def test_review_p2_9_an_answer_short_of_its_total_is_not_read(tmp_path):
    run(tmp_path)
    code, doc = run(tmp_path, Web(body={"meta": {"start": 0, "count": 0, "total": 12}, "customerSsoLog": []}))
    assert code == 1 and not doc["ok"] and len(doc["records"]) == 4
    assert not any(r["raw"].get("_missing_from_source_since") for r in doc["records"])
