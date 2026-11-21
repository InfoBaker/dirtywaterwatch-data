"""Michigan EGLE's MiEnviro beach export (ingest/mi_egle_beaches.py). Fixtures: 16 rows of report 2082 (closures and
contamination advisories) and their 12 beaches from report 2081, as the export answered on 2026-11-21 (18:22Z), with
sentinel text put in AdvisoryComments and in the sites' private and additional comments and description, which must
never be kept. The rows cover a closure and an advisory with EGLE's reason, the four advisories with no end, the 2026
sewage closure (a CSO at L'Anse), "Not Specified" and "Other" reasons, rainfall, Central-time beaches in Menominee and
Gogebic counties, an identical pair (2025) and a pair with one key and two ends (2006). No network."""
import json
from pathlib import Path

import pytest

from build import beach_reason
from ingest import mi_egle_beaches as M

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "mi"
T0 = "2026-11-21T18:22:00Z"
SENTINELS = ("COMMENT SENTINEL", "PRIVATE SENTINEL", "ADDITIONAL SENTINEL", "DESCRIPTION SENTINEL")
REAL_MIN_SITES = M.MIN_SITES


@pytest.fixture(autouse=True)
def small_site_floor(monkeypatch):
    monkeypatch.setattr(M, "MIN_SITES", 5)          # the fixture's 12 beaches; the real floor is tested below


def test_the_real_floors_fit_the_export_of_2026_11_21():
    assert 2000 <= REAL_MIN_SITES <= 2914 and M.MIN_ROWS <= 3650 and M.MAX_REJECTED >= 1


def adv_text():
    return (FIX / "advisories_2082.csv").read_text(encoding="utf-8")


def site_text():
    return (FIX / "sites_2081.csv").read_text(encoding="utf-8")


def run(state=None, at=T0, rows=None):
    rows = rows if rows is not None else M.parse_advisories(adv_text())
    return M.build(rows, M.parse_sites(site_text()), state if state is not None else {}, at)


def by_id(recs):
    return {r["source_record_id"]: r for r in recs}


def test_every_row_is_one_advisory_with_egles_type_dates_and_reason():
    recs, meta = run()
    assert meta["rows_read"] == 16 and meta["advisories"] == 15 and meta["no_site"] == 0
    r = by_id(recs)["1491-20260911-closure"]
    assert r["event_type"] == "beach_closure" and r["status"] == "advisory_lifted"
    assert (r["started_at"], r["ended_at"], r["time_precision"]) == ("2026-09-11", "2026-09-16", "day")
    assert r["raw"]["reason"] == "High bacteria levels" and r["raw"]["pollution_source"] == "Unknown"
    assert r["raw"]["days_under_advisory"] == 5
    assert r["authority"].startswith("Livingston County Department of Public Health (Michigan EGLE beach monitoring)")
    assert r["source_url"] == M.MAP_PAGE and r["published_at"] is None and r["reported_at"] is None
    a = by_id(recs)["3948-20260813-advisory"]
    assert a["event_type"] == "beach_advisory" and a["raw"]["advisory_type"] == "Contamination Advisory"


def test_the_sewage_closure_at_lanse_keeps_egles_reason_and_source():
    r = by_id(run()[0])["1502-20260625-closure"]
    assert r["raw"]["reason"] == "Sewage" and r["raw"]["pollution_source"] == "Combined Sewer Overflow"
    assert r["event_type"] == "beach_closure"          # a beach record, never a sewage discharge record


def test_an_advisory_with_no_end_stands_and_is_confirmed_only_at_its_start():
    recs, meta = run()
    open_ = [r for r in recs if r["raw"].get("no_end_in_source")]
    assert len(open_) == 4 == meta["no_end_in_source"] == meta["in_effect"]
    for r in open_:
        assert r["status"] == "advisory_active" and r["ended_at"] is None
        assert "_last_seen_in_source" not in r["raw"]       # an archive row is no fresh confirmation


def test_an_end_whose_local_day_is_not_over_keeps_the_advisory_active():
    rows = M.parse_advisories(adv_text())
    row = next(r for r in rows if r["Identifier"] == "1491")
    row["EndDate"] = "11/21/2026 12:00:00 AM"           # the read's own day in Michigan
    r = by_id(run(rows=rows)[0])["1491-20260911-closure"]
    assert r["status"] == "advisory_active" and r["ended_at"] == "2026-11-21"
    row["EndDate"] = "11/20/2026 12:00:00 AM"
    assert by_id(run(rows=rows)[0])["1491-20260911-closure"]["status"] == "advisory_lifted"


def test_an_end_before_the_start_is_not_used():
    rows = M.parse_advisories(adv_text())
    row = next(r for r in rows if r["Identifier"] == "1491")
    row["EndDate"] = "9/1/2026 12:00:00 AM"
    r = by_id(run(rows=rows)[0])["1491-20260911-closure"]
    assert r["ended_at"] is None and "end_not_used" in r["raw"] and r["status"] == "advisory_active"


def test_the_upper_peninsula_counties_on_the_wisconsin_line_keep_central_time():
    recs = run()[0]
    zones_by_county = {r["raw"]["county"]: r["raw"]["time_zone"] for r in recs}
    assert zones_by_county["Menominee"] == zones_by_county["Gogebic"] == "America/Chicago"
    assert zones_by_county["Livingston"] == zones_by_county["Baraga"] == "America/New_York"


def test_identical_rows_are_one_advisory_and_one_key_with_two_ends_is_two():
    ids = by_id(run()[0])
    assert [k for k in ids if k.startswith("465-20250729")] == ["465-20250729-closure"]
    a, b = ids["2093-20060620-closure"], ids["2093-20060620-closure-2"]
    assert (a["ended_at"], b["ended_at"]) == ("2006-07-05", "2006-07-18")     # ordered by end


def test_keys_are_unique_and_stable_across_reads():
    s = {}
    first = sorted(r["event_id"] for r in run(state=s)[0])
    again = run(state=s, at="2026-11-21T19:22:00Z")[0]
    assert sorted(r["event_id"] for r in again) == first and len(set(first)) == len(first)
    r = by_id(again)["1491-20260911-closure"]
    assert r["raw"]["_first_seen_at"] == T0 and r["fetched_at"] == "2026-11-21T19:22:00Z"


def test_points_come_from_the_beach_list_rounded_to_three_decimals():
    recs = run()[0]
    assert all(r["lat"] is not None and r["coord_source"] == "source" for r in recs)
    for r in recs:
        assert round(r["lat"], 3) == r["lat"] and round(r["lon"], 3) == r["lon"]
    r = by_id(recs)["1491-20260911-closure"]
    assert (r["lat"], r["lon"], r["waterbody_text"]) == (42.582, -83.848, "Lake Chemung")


def test_a_beach_missing_from_the_list_is_a_record_without_a_point():
    rows = M.parse_advisories(adv_text())
    rows[0] = dict(rows[0], Identifier="999999")
    recs, meta = run(rows=rows)
    assert meta["no_site"] == 1
    r = next(x for x in recs if x["raw"]["identifier"] == "999999")
    assert r["lat"] is None and r["coord_source"] is None


def test_a_point_outside_michigan_is_not_used():
    text = site_text().replace("42.58", "12.58", 1)
    sites = M.parse_sites(text)
    assert any(s["lat"] is None for s in sites.values())


def test_comments_and_private_site_fields_never_reach_a_record_the_raw_save_or_the_site_list():
    rows = M.parse_advisories(adv_text())
    assert all("AdvisoryComments" not in r for r in rows)
    sites = M.parse_sites(site_text())
    recs = run()[0]
    blob = json.dumps(rows) + json.dumps(sites) + json.dumps(recs)
    for s in SENTINELS:
        assert s not in blob
    assert set(next(iter(sites.values()))) == set(M.SITE_FIELDS.values())


@pytest.mark.parametrize("bad", ["", "StartDate,EndDate\n1/1/2026,1/2/2026\n",
                                 "StartDate,EndDate,AdvisoryType,Reason,PollutionSource,DaysUnderAdvisory,"
                                 "IssuingOrganization,AdvisoryComments,Name,Identifier\n"])
def test_an_empty_or_changed_answer_is_refused(bad):
    with pytest.raises(M.ReadError):
        M.parse_advisories(bad)


def test_the_floor_and_a_sharp_drop_against_the_last_good_read_are_refused():
    rows = [{"Identifier": str(i)} for i in range(1200)]
    M.check_rows(rows, {"last_rows": 1300})
    with pytest.raises(M.ReadError):
        M.check_rows(rows[:900], {})
    with pytest.raises(M.ReadError):
        M.check_rows(rows, {"last_rows": 3655})


def test_a_gzip_body_without_its_header_is_read():
    import gzip
    assert M.decode(gzip.compress("StartDate\n".encode())) == "StartDate\n"
    assert M.decode("﻿StartDate\n".encode("utf-8")) == "StartDate\n"


def test_decision_40_reads_egles_reason_and_source():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    ids = by_id(run()[0])

    def stated(key):
        v = beach_reason.judge(ids[key], rules)
        return v is None or bool(v.get("stated"))

    assert stated("1491-20260911-closure")              # High bacteria levels
    assert stated("1502-20260625-closure")              # Sewage, Combined Sewer Overflow
    assert stated("3288-20260630-closure")              # Rainfall
    assert not stated("374-20260811-closure")           # Not Specified, Not Specified
    assert not stated("374-20260729-closure")           # Other, Not Specified
    assert rules["beach_reason"]["sources"][M.SOURCE_ID]["kind"] == "fields"


def test_a_failed_read_keeps_the_held_records_and_marks_the_feed_not_ok(monkeypatch, tmp_path):
    import common
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(M, "STATE_PATH", tmp_path / "state.json")
    monkeypatch.setattr(M, "SITES_PATH", tmp_path / "sites.json")
    saved = []
    monkeypatch.setattr(M, "save_raw", lambda sid, content, ext: saved.append(content))
    monkeypatch.setattr(M, "check_rows", lambda rows, state: None)
    texts = {M.REPORT_ADVISORIES: adv_text(), M.REPORT_SITES: site_text()}
    monkeypatch.setattr(M, "fetch_report", lambda sess, rid: texts[rid])
    assert M.main([]) == 0
    first = json.loads((tmp_path / f"{M.SOURCE_ID}.json").read_text())
    assert first["ok"] and first["count"] == 15
    assert saved and not any(s in saved[0] for s in SENTINELS)

    def boom(sess, rid):
        raise M.ReadError("report 2082: no rows")
    monkeypatch.setattr(M, "fetch_report", boom)
    assert M.main([]) == 1
    after = json.loads((tmp_path / f"{M.SOURCE_ID}.json").read_text())
    assert not after["ok"] and after["count"] == 15 and "no rows" in after["error"]


def test_the_beach_list_is_read_again_only_when_old_or_incomplete(monkeypatch, tmp_path):
    monkeypatch.setattr(M, "SITES_PATH", tmp_path / "sites.json")
    calls = []

    def fetch(sess, rid):
        calls.append(rid)
        return site_text()
    monkeypatch.setattr(M, "fetch_report", fetch)
    rows = M.parse_advisories(adv_text())
    M.load_sites(None, rows, T0)
    M.load_sites(None, rows, "2026-11-21T20:00:00Z")
    assert calls == [M.REPORT_SITES]                       # fresh and complete: the saved list
    M.load_sites(None, rows + [dict(rows[0], Identifier="424242")], "2026-11-21T21:00:00Z")
    assert len(calls) == 2                                 # a beach the list lacks: read again
    M.load_sites(None, rows, "2026-11-23T21:00:00Z")
    assert len(calls) == 3                                 # older than a day: read again

    def boom(sess, rid):
        raise M.ReadError("down")
    monkeypatch.setattr(M, "fetch_report", boom)
    assert M.load_sites(None, rows, "2026-11-25T21:00:00Z")    # the saved list still places what it knows


def test_the_feed_is_in_the_ingest_list_and_its_source_record_exists():
    text = (ROOT / "pipeline" / "ingest" / "mi_egle_beaches.py").read_text()
    assert "__name__ == \"__main__\"" in text and "not a feed" not in text
    assert (ROOT / "data" / "sources" / f"{M.SOURCE_ID}.yaml").exists()


# ---- Astra review 2026-11-21 (.coordinator/reviews/2026-11-21-astra-mi-egle-beaches.md), each failing first

HEADER = ",".join(M.ADV_COLUMNS)


def test_a_row_with_an_extra_cell_is_rejected_so_shifted_comment_text_is_never_kept():
    good = adv_text().splitlines()
    # an unquoted comma inside a comment shifts the comment's second half into Name
    bad = '9/1/2026 12:00:00 AM,9/2/2026 12:00:00 AM,Closed,High bacteria levels,Unknown,1,Some HD,COMMENT SENTINEL a,' \
          'COMMENT SENTINEL b,Beach X,1491'
    rows, rejected = M.read_advisories("\n".join(good + [bad]) + "\n")
    assert rejected == 1 and len(rows) == 16
    assert "COMMENT SENTINEL" not in json.dumps(rows)


@pytest.mark.parametrize("cells", [
    ",,,,,,,,,",                                                            # every cell empty
    "9/1/2026 12:00:00 AM,,Closed,High bacteria levels,Unknown,1,HD,,Beach,",  # no identifier
    "not a date,,Closed,High bacteria levels,Unknown,1,HD,,Beach,1491",     # no start date
    "9/1/2026 12:00:00 AM,soon,Closed,High bacteria levels,Unknown,1,HD,,Beach,1491",   # an end that is no date
    "9/1/2026 12:00:00 AM",                                                 # a short row
])
def test_a_malformed_row_is_rejected(cells):
    rows, rejected = M.read_advisories(HEADER + "\n" + cells + "\n")
    assert rows == [] and rejected == 1


def test_a_read_of_mostly_malformed_rows_is_refused_whatever_its_length():
    with pytest.raises(M.ReadError):
        M.parse_advisories(HEADER + "\n" + "x\n" * 3655)


def test_the_floor_counts_distinct_advisories_not_rows():
    rows = M.parse_advisories(adv_text())
    with pytest.raises(M.ReadError):
        M.check_rows([rows[0]] * 3655, {})                 # 3,655 copies of one advisory


def test_a_partial_beach_list_keeps_the_complete_one(monkeypatch, tmp_path):
    monkeypatch.setattr(M, "SITES_PATH", tmp_path / "sites.json")
    full = site_text()
    lines = full.splitlines()
    answers = [full, "\n".join(lines[:2]) + "\n"]          # then a list cut after one site
    monkeypatch.setattr(M, "fetch_report", lambda sess, rid: answers.pop(0))
    rows = M.parse_advisories(adv_text())
    first = M.load_sites(None, rows, T0)
    second = M.load_sites(None, rows, "2026-11-23T21:00:00Z")    # stale: read again, answered short
    assert second == first and len(second) == 12
    assert len(json.loads((tmp_path / "sites.json").read_text())["sites"]) == 12


@pytest.mark.parametrize("lat,lon", [("42.58", ""), ("", "-83.84"), ("42.58", "west"), ("north", "-83.84")])
def test_a_point_missing_either_coordinate_is_no_point(lat, lon):
    import csv as _csv
    import io as _io
    rd = list(_csv.DictReader(_io.StringIO(site_text())))
    rd[0]["Latitude"], rd[0]["Longitude"] = lat, lon
    out = _io.StringIO()
    w = _csv.DictWriter(out, fieldnames=list(rd[0].keys()))
    w.writeheader()
    w.writerows(rd)
    sites = M.parse_sites(out.getvalue())
    s = sites[rd[0]["Beach ID"].strip()]
    assert s["lat"] is None and s["lon"] is None


def test_correcting_one_end_of_a_same_day_pair_never_swaps_their_ids():
    state = {}
    rows = M.parse_advisories(adv_text())
    before = by_id(run(state=state, rows=rows)[0])
    assert before["2093-20060620-closure"]["ended_at"] == "2006-07-05"
    assert before["2093-20060620-closure-2"]["ended_at"] == "2006-07-18"
    fixed = [dict(r) for r in rows]
    for r in fixed:
        if r["Identifier"] == "2093" and r["EndDate"].startswith("7/5/2006"):
            r["EndDate"] = "7/20/2006 12:00:00 AM"
    after = by_id(run(state=state, rows=fixed, at="2026-11-21T19:22:00Z")[0])
    assert after["2093-20060620-closure-2"]["ended_at"] == "2006-07-18"      # the unchanged one keeps its id
    assert after["2093-20060620-closure"]["ended_at"] == "2006-07-20"        # the corrected one keeps its own
