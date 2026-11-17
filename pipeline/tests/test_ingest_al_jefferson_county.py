"""Jefferson County (Alabama) sewer overflow advisories (ingest/al_jefferson_county_soa.py). Fixtures: the page
(https://soa.jccal.org/, read 2026-11-17; form state and grid rows trimmed) and rows of its CSV export read the same
day, the newest twelve and some older ones with the forms the reader must handle; every house number is replaced by
a made-up one and every point cut to three decimals. One row (2026-07-04) is made up: the first row with its
latitude and longitude swapped. No network."""
import json
from datetime import date
from pathlib import Path

import pytest
import requests

from common import HOUSE_NUMBER_REMOVED
from ingest import al_jefferson_county_soa as JC

FIX = Path(__file__).parent / "fixtures"
PAGE = (FIX / "al_jefferson_county_soa.html").read_text(encoding="utf-8")
CSV = (FIX / "al_jefferson_county_soa.csv").read_bytes()
NOW = "2026-11-17T10:00:00Z"


class R:
    def __init__(self, code=200, text="", content=b"", ctype="text/html; charset=utf-8"):
        self.status_code, self.text, self.content = code, text, content
        self.headers = {"content-type": ctype}

    def raise_for_status(self):
        if self.status_code != 200:
            raise requests.HTTPError(str(self.status_code))


def year_csv(y: int) -> bytes:
    lines = CSV.decode().split("\r\n")
    return "\r\n".join([lines[0]] + [x for x in lines[1:] if x.startswith(str(y))] + [""]).encode()


class Web:
    """The page by GET, the export by POST (per year)."""

    def __init__(self, page=PAGE, export=None, fail_years=()):
        self.page, self.export, self.fail_years, self.posts = page, export or year_csv, set(fail_years), []

    def get(self, url, timeout=None):
        assert url == JC.URL
        return R(text=self.page) if isinstance(self.page, str) else self.page

    def post(self, url, data=None, timeout=None):
        assert data["btnExport"] == "Download as CSV file" and data["__VIEWSTATE"] == "VIEWSTATE-TRIMMED"
        y = int(data["ddlYear"])
        self.posts.append(y)
        if y in self.fail_years:
            raise requests.ConnectionError("reset")
        return R(content=self.export(y), ctype="text/csv; charset=utf-8")


def run(tmp_path, web=None, adem=(), **kw):
    out = tmp_path / "ev.json"
    code = JC.run(NOW, tmp_path / "state.json", out, sess=web or Web(), adem=list(adem), sleep=lambda s: None,
                  today=kw.pop("today", date(2026, 11, 17)), save=False, **kw)
    return code, json.loads(out.read_text())


def by_start(doc):
    return {r["started_at"]: r for r in doc["records"]}


# ---------------------------------------------------------------- the export

def test_every_fixture_row_parses_with_its_fields():
    rows, bad = JC.parse_csv(CSV.decode())
    assert bad == [] and len(rows) == 21
    first = rows[0]
    assert first == {"date": "2026-11-16", "time": "9:19AM", "location": "100 Arthur Shores Dr. Sw.", "city": "BIRMINGHAM",
                     "zip": "35211", "waterway": "Nabors Branch - IDN: 00112862", "downstream_of": "N/A",
                     "reason": "Roots, Grease or Debris", "status": "Resolved", "date_resolved": "2026-11-16",
                     "maplink": "33.470, -86.852"}
    old = next(r for r in rows if r["date"] == "2013-03-29")
    assert old["reason"] == "Roots, Grease, or Debris" and old["waterway"] == "none"      # split in three fields
    comma = next(r for r in rows if r["date"] == "2025-01-27")
    assert comma["location"] == "1400 AVENUE T, BIRMINGHAM, 35208" and comma["city"] == "BIRMINGHAM"
    short = next(r for r in rows if r["time"] == "11:50AM")
    assert short["zip"] == "3502" and short["waterway"] == "Halls Creek - IDN: 00119594"
    down = next(r for r in rows if r["time"] == "9:21PM")
    assert down["downstream_of"] == "Otis Rd" and down["date_resolved"] == "2026-03-10"


def test_a_changed_header_is_a_failed_read():
    with pytest.raises(JC.ReadError):
        JC.parse_csv("Date,Location,City\r\n2026-11-16,x,y\r\n")


@pytest.mark.parametrize("line", [
    "2026-11-16,9:19AM,100 A ST,BIRMINGHAM,35211,Nabors Branch,N/A,Other,Resolved,,33.4,-86.8,",     # no Date Resolved
    "2026-11-16,99:19AM,100 A ST,BIRMINGHAM,35211,Nabors Branch,N/A,Other,Resolved,2026/11/16,33.4,-86.8,",
    "2026-11-16,9:19AM,100 A ST,BIRMINGHAM,ABCDE,Nabors Branch,N/A,Other,Resolved,2026/11/16,33.4,-86.8,",
    "2026-13-16,9:19AM,100 A ST,BIRMINGHAM,35211,Nabors Branch,N/A,Other,Resolved,2026/11/16,33.4,-86.8,",
])
def test_a_row_that_does_not_line_up_is_not_read(line):
    assert JC.parse_line(line) is None


def test_points_are_rounded_and_odd_ones_withheld():
    assert JC.point("33.470975, -86.852640") == (33.471, -86.853, None)
    assert JC.point("33.609835;  -86.682320")[:2] == (33.61, -86.682)
    assert JC.point("33.40022425/-86.95470728")[:2] == (33.4, -86.955)
    assert JC.point("-86.853, 33.471")[2] == "the map point lies outside Alabama"
    assert JC.point("33.4712")[2] == "the map link is not one latitude and one longitude"
    assert JC.point("")[2] == "the row gives no map point"


@pytest.mark.parametrize("text, want", [
    ("1501 Arthur Shores Dr. Sw.", f"{HOUSE_NUMBER_REMOVED} Arthur Shores Dr. Sw."),
    ("48 WOODWARD ESTATES", f"{HOUSE_NUMBER_REMOVED} WOODWARD ESTATES"),
    ("2511 15th Ave North", f"{HOUSE_NUMBER_REMOVED} 15th Ave North"),
    ("2025", HOUSE_NUMBER_REMOVED),
    ("99/105 SUMMIT BOULEVARD", f"{HOUSE_NUMBER_REMOVED} SUMMIT BOULEVARD"),
    ("3444 33RD COURT N3444 33RD COURT N", f"{HOUSE_NUMBER_REMOVED} 33RD COURT N {HOUSE_NUMBER_REMOVED} 33RD COURT N"),
    ("1234 HIGHWAY 150", f"{HOUSE_NUMBER_REMOVED} HIGHWAY 150"),
    ("I 22 E & HILLCREST ROAD", "I 22 E & HILLCREST ROAD"),
])
def test_street_only_drops_every_house_number(text, want):
    assert JC.street_only(text) == want


# ---------------------------------------------------------------- records

def test_records_from_the_hourly_read(tmp_path):
    web = Web()
    code, doc = run(tmp_path, web)
    assert code == 0 and doc["ok"] and web.posts == [2026]
    recs = by_start(doc)
    assert len(recs) == 15                        # the 2026 rows of the fixture
    r = recs["2026-11-16T09:19:00-06:00"]
    assert r["event_id"] == "al-jefferson-county-soa:2026-11-16T0919:ARTHURSHORESDRSW"
    assert r["event_type"] == "sso" and r["status"] == "unknown" and r["ended_at"] is None
    assert r["time_precision"] == "minute" and r["reported_at"] is None and r["published_at"] is None
    assert r["waterbody_text"] == "Nabors Branch" and r["raw"]["gnis_id"] == "112862"
    assert (r["lat"], r["lon"], r["coord_source"], r["coord_precision_m"]) == (33.47, -86.852, "source", 100)
    assert r["discharger_id"] == "al-jefferson-county" and r["npdes_permit"] is None
    assert r["raw"]["date_resolved"] == "2026-11-16" and r["raw"]["status_as_written"] == "Resolved"
    assert r["raw"]["location"] == f"{HOUSE_NUMBER_REMOVED} Arthur Shores Dr. Sw."
    assert r["volume_gal"] is None and r["volume_text"] is None
    # summer time is CDT
    assert "2026-07-04T13:05:00-05:00" in recs
    # NONE: the county says no waterway was affected
    none = recs["2026-11-05T10:54:00-06:00"]
    assert none["waterbody_text"] is None and none["raw"]["reached_water"] is False
    assert "NONE" in none["raw"]["_no_water_reason"]
    assert recs["2026-07-04T13:05:00-05:00"]["lat"] is None
    assert recs["2026-07-04T13:05:00-05:00"]["raw"]["_point_withheld"] == "the map point lies outside Alabama"
    assert recs["2026-03-09T21:21:00-05:00"]["raw"]["downstream_of"] == "Otis Rd"
    assert "downstream_of" not in r["raw"]                                  # N/A is dropped


def test_no_house_number_reaches_a_record(tmp_path):
    _, doc = run(tmp_path, Web(), backfill=True)
    text = json.dumps(doc)
    for n in range(1, 21):
        assert f'"{n * 100} ' not in text and f" {n * 100} " not in text
    assert "1400 AVENUE T" not in text


def test_backfill_reads_each_year_offered_and_keeps_them(tmp_path):
    web = Web()
    code, doc = run(tmp_path, web, backfill=True)
    assert code == 0 and web.posts == list(range(2012, 2027))
    assert len(doc["records"]) == 21
    # the next hourly read of 2026 keeps the older years
    code, doc = run(tmp_path, Web())
    assert code == 0 and len(doc["records"]) == 21


def test_january_also_reads_the_year_before(tmp_path):
    web = Web()
    run(tmp_path, web, today=date(2027, 1, 5))
    assert web.posts == [2027, 2026]


def test_an_empty_year_is_a_healthy_read_with_nothing_new(tmp_path):
    code, doc = run(tmp_path, Web(export=lambda y: CSV.decode().split("\r\n")[0].encode() + b"\r\n"))
    assert code == 0 and doc["ok"] and doc["records"] == []


def test_a_failed_page_keeps_the_records_and_fails_health(tmp_path):
    run(tmp_path)
    code, doc = run(tmp_path, Web(page=R(503)))
    assert code == 1 and not doc["ok"] and len(doc["records"]) == 15
    code, doc = run(tmp_path, Web(page="<html>maintenance</html>"))
    assert code == 1 and not doc["ok"] and "no advisories table" in doc["error"]


def test_an_export_that_is_not_the_csv_fails_health(tmp_path):
    run(tmp_path)
    code, doc = run(tmp_path, Web(export=lambda y: b"<html>error</html>"))
    assert code == 1 and not doc["ok"] and len(doc["records"]) == 15
    code, doc = run(tmp_path, Web(fail_years=[2026]))
    assert code == 1 and not doc["ok"]


def test_too_many_rows_out_of_line_is_a_failed_read(tmp_path):
    bad = b"Date,Time,Location,City,Zip,Affected Waterway,Downstream Of,Reason,Status,Date Resolved,MapLink,\r\n" + \
        b"2026-11-16,9:19AM,x,BIRMINGHAM,ABCDE,y,N/A,Other,Resolved,2026/11/16,33.4,-86.8,\r\n"
    code, doc = run(tmp_path, Web(export=lambda y: bad))
    assert code == 1 and not doc["ok"] and "do not fit" in doc["error"]


def test_backfill_exits_0_when_some_years_read_and_names_the_rest(tmp_path):
    code, doc = run(tmp_path, Web(fail_years=[2013]), backfill=True)
    assert code == 0 and not doc["ok"] and "2013" in doc["meta"]["years_not_read"]
    assert len(doc["records"]) == 18
    (tmp_path / "x").mkdir()
    code, doc = run(tmp_path / "x", Web(fail_years=range(2012, 2027)), backfill=True)
    assert code == 1 and not doc["ok"]


def test_a_row_gone_from_its_year_keeps_its_record_and_says_so(tmp_path):
    run(tmp_path)
    lines = year_csv(2026).decode().split("\r\n")
    code, doc = run(tmp_path, Web(export=lambda y: "\r\n".join(lines[:1] + lines[2:]).encode()))
    r = by_start(doc)["2026-11-16T09:19:00-06:00"]
    assert code == 0 and r["raw"]["_missing_from_source_since"] == NOW


# ---------------------------------------------------------------- one event, one record (ADEM)

def adem(rid, start, lat, lon, permit="AL0023655", reached=None):
    raw = {} if reached is None else {"reached_water": reached}
    return {"event_id": f"al-adem-sso-history:{rid}", "npdes_permit": permit, "started_at": start, "lat": lat, "lon": lon,
            "raw": raw, "duplicate_of": None}


def test_a_county_record_is_the_duplicate_of_adems_report_of_the_same_overflow(tmp_path):
    a = [adem("SSO-1", "2026-11-16T08:50:00-06:00", 33.4712, -86.8528),          # 25 m away, same day
         adem("SSO-2", "2026-11-16T08:50:00-06:00", 33.60, -86.80),             # 15 km away
         adem("SSO-3", "2026-11-11T10:00:00-06:00", 33.545, -86.689, permit="AL0099999"),   # another operator
         adem("SSO-4", "2026-11-11T03:00:00-06:00", 33.4715, -86.7862)]          # the Manor Drive row
    _, doc = run(tmp_path, adem=a)
    recs = by_start(doc)
    assert recs["2026-11-16T09:19:00-06:00"]["duplicate_of"] == "al-adem-sso-history:SSO-1"
    assert "same day" in recs["2026-11-16T09:19:00-06:00"]["raw"]["_duplicate_basis"]
    assert recs["2026-11-11T10:52:00-06:00"]["duplicate_of"] is None
    assert recs["2026-11-11T03:12:00-06:00"]["duplicate_of"] == "al-adem-sso-history:SSO-4"
    assert doc["meta"]["adem_links"] == {"linked": 2}


def test_a_dry_land_adem_report_never_absorbs_a_county_record_of_a_water(tmp_path):
    a = [adem("SSO-1", "2026-11-16T08:50:00-06:00", 33.4712, -86.8528, reached=False),
         adem("SSO-5", "2026-11-05T10:00:00-06:00", 33.609, -86.682, reached=False)]   # county says NONE too
    _, doc = run(tmp_path, adem=a)
    recs = by_start(doc)
    assert recs["2026-11-16T09:19:00-06:00"]["duplicate_of"] is None
    assert recs["2026-11-05T10:54:00-06:00"]["duplicate_of"] == "al-adem-sso-history:SSO-5"


def test_one_adem_report_absorbs_one_county_record_the_closest(tmp_path):
    a = [adem("SSO-9", "2026-11-11T12:00:00-06:00", 33.508, -86.737)]          # between the two 11-11 rows
    _, doc = run(tmp_path, adem=a)
    linked = [r for r in doc["records"] if r["duplicate_of"]]
    assert len(linked) <= 1


def test_utc_starts_are_compared_on_the_central_day(tmp_path):
    # 2026-11-17T04:30Z is 2026-11-16 22:30 in Birmingham
    a = [adem("SSO-1", "2026-11-17T04:30:00Z", 33.4712, -86.8528)]
    _, doc = run(tmp_path, adem=a)
    assert by_start(doc)["2026-11-16T09:19:00-06:00"]["duplicate_of"] == "al-adem-sso-history:SSO-1"


def test_main_accepts_backfill_and_csv(tmp_path):
    out = tmp_path / "o.json"
    assert JC.main(["--csv", str(FIX / "al_jefferson_county_soa.csv"), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["count"] == 21
