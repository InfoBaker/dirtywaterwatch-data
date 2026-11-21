"""EPA's per-state DMR files: Ohio's and Kentucky's monthly CSO figures (ingest/echo_dmr_cso_states.py; decision 45).

The fixtures are trimmed real lines of OH_FY2026_NPDES_DMRS.csv and KY_FY2026_NPDES_DMRS.csv (EPA ECHO, file of
2026-11-15): Columbus (OH0024732) outfalls 045 and 047 and its station 300, Cincinnati (OH0105457) 522, Ohio's annual
51709 line (OH0024899 016), Northern Kentucky's SD1 (KY0021466) 010 and Maysville (KY0020257) 004. They name permits
and plants only."""
from __future__ import annotations

import json
import shutil
import zipfile
from collections import Counter
from datetime import date
from pathlib import Path

import pytest

import common

FIX = Path(__file__).parent / "fixtures" / "echo_dmr_states"
TODAY = date(2026, 11, 21)


def _zip(tmp_path: Path, st: str, name: str | None = None) -> Path:
    p = tmp_path / f"{st}_FY2026_NPDES_DMRS_LIMITS.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.write(FIX / f"{st}_FY2026_NPDES_DMRS.csv", name or f"{st}_FY2026_NPDES_DMRS.csv")
    return p


def _reg_rows() -> list[dict]:
    def row(st, permit, outfall, slug=None, lat=None, lon=None, status="CSO", coords="permitted_feature"):
        return {"npdes_permit": permit, "outfall": outfall, "state": st, "outfall_kind": "cso", "outfall_status": status,
                "lat": lat, "lon": lon, "coords_from": coords, "water_slug": slug,
                "receiving_water_echo": "Sample River" if slug else "Unnamed Ditch", "_file": "data/outfalls-us.json"}
    return [row("OH", "OH0024732", "045", "scioto-river-oh", 39.9512, -83.0101),
            row("OH", "OH0024732", "005", "scioto-river-oh", 39.9611, -83.0021),
            row("OH", "OH0024732", "047", "scioto-river-oh", 39.9501, -83.0122),
            row("OH", "OH0105457", "522", None, 39.1, -84.5, coords="facility"),
            row("OH", "OH0024899", "016", "sample-creek-oh", 40.0, -82.0),
            row("KY", "KY0021466", "010", "ohio-river-ky", 39.0921, -84.5103),
            row("KY", "KY0020257", "004", "ohio-river-ky", 38.6501, -83.7702),
            row("MA", "MA0101613", "007", "connecticut-river-ma", 42.1, -72.6),
            row("MA", "MA0100986", "002", "sample-river-ma", 42.5, -71.0)]


@pytest.fixture
def env(tmp_path, monkeypatch):
    from ingest import echo_dmr_cso_states as S
    from ingest import in_echo_cso_monthly as M
    ev = tmp_path / "events"
    monkeypatch.setattr(common, "EVENTS_DIR", ev)
    monkeypatch.setattr(S, "BUILD_DIR", tmp_path)
    monkeypatch.setattr(S, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(S, "save_raw", lambda *a, **k: None)
    for mod in (S, M):
        monkeypatch.setattr(mod, "write_events", lambda sid, recs, **kw: common.write_events(
            sid, recs, path=ev / f"{sid}.json", **kw))
    monkeypatch.setattr(S.time, "sleep", lambda s: None)
    return S, M, tmp_path


def _doc(tmp_path, sid):
    return json.loads((tmp_path / "events" / f"{sid}.json").read_text())


def _run(S, tmp_path, st, local=True, since=date(2025, 10, 1), budget=None):
    b = budget or S.Budget(None, None)
    return S.run_state(st, since, TODAY, b, _reg_rows(), {2026: _zip(tmp_path, st)} if local else None)


# ------------------------------------------------------------------------------------------------ the fold

def test_ohios_two_columns_agreeing_are_the_months_figure_and_cite_both(env):
    S, M, tmp = env
    keys = {common.outfall_key(r["npdes_permit"], r["outfall"]) for r in _reg_rows()}
    stats = Counter()
    rows = S.parse_zip(_zip(tmp, "OH"), keys, {"OH0024732", "OH0105457", "OH0024899"}, stats)
    # Columbus 005, March 2026: one overflow and 1.169 million gallons in both columns (one entry for the month)
    r = next(x for x in rows if x["feature"] == "005" and x["ParameterCode"] == "74062")
    v = next(x for x in rows if x["feature"] == "005" and x["ParameterCode"] == "74063")
    assert r["DMRValueNmbr"] == "1" and r["FiguredAs"] is None and v["DMRValueNmbr"] == "1.169" and v["FiguredAs"] is None
    assert r["StatisticalBases"] == "DAILY MX 1; MO AVG 1" and r["DMRUnitDesc"] == "occur/mo" and r["UnitFrom"] == "limit"
    assert r["MonitoringPeriodEndDate"] == "31-MAR-26" and r["VersionNmbr"] == "0" and r["DMRValueId"]


def test_disagreeing_columns_mark_the_month_and_give_no_volume(env):
    S, M, tmp = env
    keys = {common.outfall_key(r["npdes_permit"], r["outfall"]) for r in _reg_rows()}
    stats = Counter()
    rows = S.parse_zip(_zip(tmp, "OH"), keys, {"OH0024732", "OH0105457"}, stats)
    v = next(x for x in rows if x["feature"] == "045" and x["ParameterCode"] == "74063"
             and x["MonitoringPeriodEndDate"] == "31-MAY-26")
    assert v["FiguredAs"] == ("overflow volume filed as a daily maximum of 2.373 million gallons and a monthly average "
                              "of 0.4005 million gallons")
    assert v["DMRValueNmbr"] == "2.373"           # the larger marks the month; it is never counted
    # the same report's count, both columns 6, is one day's figure in a report of daily entries
    c = next(x for x in rows if x["feature"] == "045" and x["ParameterCode"] == "74062"
             and x["MonitoringPeriodEndDate"] == "31-MAY-26")
    assert c["FiguredAs"] == ("overflow count filed as 6 for both the daily maximum and the monthly average of daily "
                              "entries")
    assert stats["figures_with_disagreeing_bases"] == 3 and stats["figures_in_reports_of_daily_entries"] == 3
    cin = next(x for x in rows if x["feature"] == "522" and x["ParameterCode"] == "74062")
    assert cin["FiguredAs"].startswith("overflow count filed as 1 for both the daily maximum and the monthly average")


def test_lines_off_the_registry_per_year_and_off_the_permits_read_are_not_read(env):
    S, M, tmp = env
    keys = {common.outfall_key(r["npdes_permit"], r["outfall"]) for r in _reg_rows()}
    stats = Counter()
    rows = S.parse_zip(_zip(tmp, "OH"), keys, {"OH0024732", "OH0105457", "OH0024899"}, stats)
    assert not [x for x in rows if x["feature"] == "300" or x["ParameterCode"] == "51709"]
    assert stats["lines_at_outfalls_not_in_registry_as_cso:OH0024732:300"] == 2      # Columbus's station 300
    assert "51709" not in S.CODES and S._not_monthly_unit("occur/yr") and S._not_monthly_unit("hr/qtr")
    assert not S.parse_zip(_zip(tmp, "OH"), keys, {"OH0099999"}, Counter())


def test_kentuckys_monthly_totals_and_a_yes_no_line(env):
    S, M, tmp = env
    keys = {common.outfall_key(r["npdes_permit"], r["outfall"]) for r in _reg_rows()}
    stats = Counter()
    rows = S.parse_zip(_zip(tmp, "KY"), keys, {"KY0021466", "KY0020257"}, stats)
    yes = next(x for x in rows if x["permit"] == "KY0020257" and x["ParameterCode"] == "84165")
    assert yes["FiguredAs"] == "a discharge filed as observed (yes)" and yes["MonitoringLocationDesc"] == \
        "Effluent Gross (Supplementary)"
    tot = next(x for x in rows if x["permit"] == "KY0021466" and x["ParameterCode"] == "74063"
               and x["MonitoringPeriodEndDate"] == "28-FEB-26")
    assert tot["FiguredAs"] is None and tot["StatisticalBaseDesc"] == "MO TOTAL" and tot["DMRValueNmbr"] == "13"


def test_a_zip_without_the_table_or_a_field_is_a_failed_read(env, tmp_path):
    S, M, tmp = env
    bad = _zip(tmp, "OH", name="README.txt")
    with pytest.raises(ValueError):
        S.parse_zip(bad, set(), {"OH0024732"}, Counter())
    cut = tmp / "cut.csv"
    cut.write_text((FIX / "OH_FY2026_NPDES_DMRS.csv").read_text().replace('"NODI_CODE"', '"NODI"', 1))
    p = tmp / "cut.zip"
    with zipfile.ZipFile(p, "w") as z:
        z.write(cut, "OH_FY2026_NPDES_DMRS.csv")
    with pytest.raises(ValueError, match="NODI_CODE"):
        S.parse_zip(p, set(), {"OH0024732"}, Counter())


# ------------------------------------------------------------------------------------------------ records

def test_ohio_records_are_month_precision_monthly_marks_never_counted(env):
    S, M, tmp = env
    from build import status
    assert _run(S, tmp, "OH") == 0
    doc = _doc(tmp, "oh-echo-dmr-cso")
    assert doc["ok"] is True
    by = {r["source_record_id"]: r for r in doc["records"]}
    assert set(by) == {"OH0024732:045:2026-05", "OH0024732:045:2026-09", "OH0105457:522:2026-09",
                       "OH0024732:005:2026-03"}
    one = by["OH0024732:005:2026-03"]
    assert one["volume_text"] == "1 discharge event, 1.169 million gallons in 2026-03 (monthly DMR totals)"
    assert one["volume_gal"] == 1_169_000
    r = by["OH0024732:045:2026-05"]
    assert (r["started_at"], r["ended_at"], r["time_precision"], r["status"]) == ("2026-05-01", "2026-05-31", "month",
                                                                                 "ended")
    assert r["reported_at"] == "2026-06-19" and r["volume_gal"] is None
    assert r["water_slugs"] == ["scioto-river-oh"] and (r["lat"], r["lon"]) == (39.951, -83.01)
    assert r["raw"]["dmr"]["volume"]["StatisticalBases"] == "DAILY MX 2.373; MO AVG .4005"
    assert "authority" in r and "Ohio EPA" in r["authority"]
    assert r["source_id"] in status.EPA_MONTHLY_SOURCES
    mark = status.monthly_mark(r)
    assert mark["discharged"] is True and "dates not given (monthly report to EPA, received Jun 19, 2026)" in mark["label"]
    # Cincinnati's outfall: the registry gives only the plant's point, so no point; no water record, listed
    c = by["OH0105457:522:2026-09"]
    assert c["lat"] is None and c["water_slugs"] == [] and c["raw"]["point_note"]
    assert doc["meta"]["outfalls_without_water"] == {"OH0105457|522": "Unnamed Ditch"}
    # Columbus 047's November 2025 was filed NODI C: no record, and its latest month is a month of no discharge
    assert doc["meta"]["latest_month_by_outfall"]["OH0024732|047"]["discharged"] is False


def test_kentucky_totals_carry_counts_hours_and_gallons_and_a_no_discharge_month_clears(env):
    S, M, tmp = env
    from build import status
    assert _run(S, tmp, "KY") == 0
    doc = _doc(tmp, "ky-echo-dmr-cso")
    by = {r["source_record_id"]: r for r in doc["records"]}
    assert set(by) == {"KY0021466:010:2026-02", "KY0021466:010:2026-09", "KY0020257:004:2026-09"}
    r = by["KY0021466:010:2026-02"]
    assert r["volume_text"] == "6 discharge events, 5.1 hours, 13 million gallons in 2026-02 (monthly DMR totals)"
    assert r["volume_gal"] == 13_000_000 and r["raw"]["parameters"] == {"events": {"DMRValueNmbr": 6.0},
                                                                         "duration": {"DMRValueNmbr": 5.1}}
    assert status.monthly_mark(r)["events"] == 6
    m = by["KY0020257:004:2026-09"]
    assert m["volume_text"] == ("2 hours, 0.005 million gallons in 2026-09; a discharge filed as observed (yes), "
                                "not a monthly total")
    assert status.monthly_mark(m)["events"] is None
    # March 2026 was filed NODI C on every figure: no record; the September record is the latest month
    assert "KY0021466:010:2026-03" not in by
    assert doc["meta"]["latest_month_by_outfall"]["KY0021466|010"]["month"] == "2026-09"


def test_a_second_run_reads_the_cache_and_a_changed_file_is_read_again(env, monkeypatch):
    S, M, tmp = env
    z = _zip(tmp, "KY")
    asked = []
    heads = {"lm": "Sun, 15 Nov 2026 02:06:12 GMT"}

    def head(url):
        if "FY2027" in url:
            return 404, None, None, "HTTP 404"
        return 200, heads["lm"], z.stat().st_size, "ok"

    def download(url, dest):
        asked.append(url)
        shutil.copy(z, dest.parent.mkdir(parents=True, exist_ok=True) or dest)
        return ""
    monkeypatch.setattr(S, "head", head)
    monkeypatch.setattr(S, "download", download)
    assert _run(S, tmp, "KY", local=False) == 0
    first = _doc(tmp, "ky-echo-dmr-cso")
    assert first["meta"]["fetch"]["FY2026"].startswith("live") and len(asked) == 1
    assert first["meta"]["fetch"]["FY2027"] == "not published yet (HTTP 404)"      # within 120 days of October 1
    assert _run(S, tmp, "KY", local=False) == 0
    second = _doc(tmp, "ky-echo-dmr-cso")
    assert second["meta"]["fetch"]["FY2026"].startswith("cache") and len(asked) == 1
    assert [r["event_id"] for r in second["records"]] == [r["event_id"] for r in first["records"]]
    heads["lm"] = "Sun, 22 Nov 2026 02:06:12 GMT"
    assert _run(S, tmp, "KY", local=False) == 0 and len(asked) == 2


def test_a_past_years_404_or_a_failed_download_is_not_ok_and_keeps_the_records(env, monkeypatch):
    S, M, tmp = env
    assert _run(S, tmp, "KY") == 0
    n = len(_doc(tmp, "ky-echo-dmr-cso")["records"])
    monkeypatch.setattr(S, "head", lambda url: (404, None, None, "HTTP 404"))
    assert S.run_state("KY", date(2025, 1, 1), TODAY, S.Budget(None, None), _reg_rows()) == 1
    doc = _doc(tmp, "ky-echo-dmr-cso")
    assert doc["ok"] is False and doc["meta"]["fetch"]["FY2025"] == "failed (HTTP 404)"
    assert len(doc["records"]) == n                     # FY2026's rows from the cache; nothing withdrawn


def test_a_run_that_read_nothing_is_never_a_healthy_empty_feed(env, monkeypatch):
    S, M, tmp = env
    monkeypatch.setattr(S, "head", lambda url: (200, "x", 50_000_000, "ok"))
    assert S.run_state("OH", date(2025, 10, 1), TODAY, S.Budget(1, None), _reg_rows()) == 1
    doc = _doc(tmp, "oh-echo-dmr-cso")
    assert doc["ok"] is False and "no file read" in doc["error"] and doc["records"] == []


def test_over_the_budget_a_file_is_read_from_the_cache(env, monkeypatch):
    S, M, tmp = env
    assert _run(S, tmp, "KY") == 0
    monkeypatch.setattr(S, "head", lambda url: (200, "changed", 50_000_000, "ok") if "FY2026" in url
                        else (404, None, None, "HTTP 404"))
    assert S.run_state("KY", date(2025, 10, 1), TODAY, S.Budget(1, None), _reg_rows()) == 0
    doc = _doc(tmp, "ky-echo-dmr-cso")
    assert doc["meta"]["fetch"]["FY2026"].startswith("stale cache") and doc["meta"]["not_asked_this_run"] == ["FY2026"]
    assert len(doc["records"]) == 3


def test_massachusetts_leaves_the_three_permits_another_feed_reads(env):
    S, M, tmp = env
    reg = M.registry_outfalls(_reg_rows(), "MA")
    permits = [p for p in M.permits_to_read(reg) if p not in S.STATES["MA"]["exclude"]]
    assert permits == ["MA0100986"] and set(S.STATES["MA"]["exclude"]) == {"MA0101613", "MA0101630", "MA0101508"}
    assert S.locations_of("MA")["SW"] == "Storm Water" and "SW" not in S.locations_of("OH")


# ------------------------------------------------------------------------------------------------ registration

def test_every_state_source_is_registered_monthly_and_charted():
    from build import charts, status
    from ingest import echo_dmr_cso_states as S
    root = Path(__file__).resolve().parents[2]
    src = (root / "pipeline" / "ingest" / "echo_dmr_cso_states.py").read_text()
    assert "__name__ == \"__main__\"" in src and "not a feed" not in src          # the Makefile runs it hourly
    for st, cfg in S.STATES.items():
        sid = cfg["source_id"]
        assert sid in status.EPA_MONTHLY_SOURCES and sid in charts.UNKNOWN_IS_NULL_SOURCES
        assert sid in charts.SOURCE_LABEL and sid in charts.TOTAL_NOTES
        y = (root / "data" / "sources" / f"{sid}.yaml").read_text()
        assert f'id: "{sid}"' in y and f'states: ["{st}"]' in y and "echo_dmr_cso_states" in y


def test_fiscal_years_and_dates():
    from ingest import echo_dmr_cso_states as S
    assert S.fiscal_years(date(2025, 1, 1), TODAY) == [2025, 2026, 2027]
    assert S.ddmon("05/31/2026") == "31-MAY-26" and S.ddmon("") is None
    assert S.file_url("OH", 2026).endswith("NPDES_by_state_year/OH_FY2026_NPDES_DMRS_LIMITS.zip")


# ------------------------------------------------------------------------------------------------ the coverage grade

def _cov_events():
    dated = [{"event_id": f"oh-x:{i}", "source_id": "oh-neorsd-cso-notification-map", "event_type": "cso",
              "state": "OH", "time_precision": "minute", "started_at": f"2026-11-{10 + i % 9:02d}T08:00:00Z",
              "reported_at": f"2026-11-{10 + i % 9:02d}T09:00:00Z", "water_slugs": ["lake-erie-oh"]} for i in range(10)]
    monthly = [{"event_id": f"oh-echo-dmr-cso:{i}", "source_id": "oh-echo-dmr-cso", "event_type": "cso",
                "state": "OH", "time_precision": "month", "started_at": f"2026-{1 + i % 9:02d}-01",
                "ended_at": f"2026-{1 + i % 9:02d}-28", "reported_at": "2026-10-20", "water_slugs": ["lake-erie-oh"]}
               for i in range(40)]
    ky = [dict(m, event_id=f"ky-echo-dmr-cso:{i}", source_id="ky-echo-dmr-cso", state="KY",
               water_slugs=["ohio-river-ky"]) for i, m in enumerate(monthly)]
    return dated + monthly + ky


def test_monthly_figures_beside_dated_reports_leave_the_grade_and_count_in_the_figures():
    from export import coverage as C
    out = C.coverage(_cov_events(), [{"slug": "lake-erie-oh", "state": "OH",
                                      "events": [f"oh-x:{i}" for i in range(10)] +
                                                [f"oh-echo-dmr-cso:{i}" for i in range(40)]},
                                     {"slug": "ohio-river-ky", "state": "KY",
                                      "events": [f"ky-echo-dmr-cso:{i}" for i in range(40)]}],
                     [], [], [], {}, "2026-11-21T03:00:00Z", source_names={})
    oh = out["states"]["OH"]
    assert oh["records_12m"] == 50 and oh["dated_share"] == 0.2           # the published figures count them
    assert oh["grade"] == "Dated reports" and oh["sentence"].startswith("Ohio publishes dated overflow reports")
    assert out["waters"]["lake-erie-oh"]["grade"] == "Dated reports"
    # where the monthly figures are all there is, they grade as monthly totals
    assert out["states"]["KY"]["grade"] == "Monthly totals only"
    assert out["waters"]["ohio-river-ky"]["grade"] == "Monthly totals only"
    assert C.SUPPLEMENT_SOURCES == {cfg["source_id"] for cfg in __import__(
        "ingest.echo_dmr_cso_states", fromlist=["STATES"]).STATES.values()}


def test_a_volume_above_the_monthly_ceiling_is_kept_as_text_only(env):
    """IL0021113 002, June 2026: 7,841,548 'Mgal/mo' (gallons filed as million gallons)."""
    from collections import defaultdict
    S, M, tmp = env
    row = {"DMRValueId": "1", "DMRValueNmbr": "7841548", "DMRUnitDesc": "Mgal/mo", "NODICode": None,
           "ValueReceivedDate": "20-JUL-26", "VersionNmbr": "0", "MonitoringPeriodEndDate": "30-JUN-26",
           "StatisticalBaseDesc": "MO TOTAL", "ParameterCode": "82220"}
    res = {("IL0021113", "82220"): {"Message": "Success", "CWPName": None, "PermFeatures": [
        {"PermFeatureNmbr": "002", "PermFeatureTypeDesc": "External Outfall", "Parameters": [
            {"ParameterCode": "82220", "ParameterDesc": "Flow, total", "MonitoringLocationDesc": "Effluent Gross",
             "DischargeMonitoringReports": [row]}]}]}}
    reg = {("IL0021113", "2"): {"npdes_permit": "IL0021113", "outfall": "002", "state": "IL"}}
    stats = defaultdict(Counter)
    cells, names = M.collect(res, reg, stats, dict(S.CODES))
    r = M.build_records(cells, names, reg, {}, stats, {"source_id": "il-echo-dmr-cso",
                                                       "max_mgal_per_month": S.MAX_MGAL_PER_MONTH})[0]
    assert r["volume_gal"] is None and "7841548 million gallons in 2026-06" in r["volume_text"]
    assert "more than 4,000 million gallons in a month" in r["raw"]["volume_note"]
    # Indiana's records have no ceiling of their own (feed without max_mgal_per_month)
    r = M.build_records(cells, names, reg, {}, stats, {"source_id": "x"})[0]
    assert r["volume_gal"] == 7_841_548_000_000
