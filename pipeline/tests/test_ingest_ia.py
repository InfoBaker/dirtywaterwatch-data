"""Iowa: Waterloo's SSO and bypass notices (ingest/ia_waterloo_sso.py), DNR's field-office bypass reports (FOCOMP,
ingest/ia_dnr_focomp.py), and Iowa's combined sewer outfalls (EPA's inventory: a closed outfall is not counted and
carries no rain caution). Fixtures are synthetic pages in the sources' own formats ("Example" streets, made-up house
numbers and report IDs); no person, real house number or private point appears in them."""
import json
from datetime import datetime
from pathlib import Path

import pytest

from ingest import ia_waterloo_sso as W

FIX = Path(__file__).resolve().parent / "fixtures" / "ia"
AT = "2026-11-14T23:00:00Z"


def waterloo(prev=()):
    paras = W.notices((FIX / "waterloo-notices.html").read_text())
    recs, stats = W.build(paras, AT, list(prev))
    return {r["source_record_id"]: r for r in recs}, stats


# ---------------------------------------------------------------- Waterloo


def test_waterloo_list_read_and_nothing_outside_it():
    paras = W.notices((FIX / "waterloo-notices.html").read_text())
    assert len(paras) == 8
    assert not any("555-0100" in p for p in paras)          # the page's phone block lies outside the list
    with pytest.raises(ValueError):
        W.notices("<html><body>Page moved</body></html>")


def test_waterloo_times_ends_and_volumes():
    recs, stats = waterloo()
    assert stats["unreadable"] == 1
    a = recs["2026-10-01T0552"]
    assert a["event_type"] == "sso" and a["time_precision"] == "minute"
    assert a["started_at"] == "2026-10-01T05:52:00-05:00" and a["ended_at"] == "2026-10-01T15:57:00-05:00"
    assert a["raw"]["ended_at_precision"] == "minute" and "duration" in a["raw"]["end_basis"]
    assert a["volume_gal"] == 181600 and a["estimate_flag"] == "estimated" and a["status"] == "ended"
    b = recs["2026-10-01T0700"]                               # "7:00 AM AM", unknown volume and duration
    assert b["ended_at"] is None and b["status"] == "unknown" and b["volume_gal"] is None
    assert b["raw"]["permitted_overflow"] is True
    assert recs["2026-10-01T0740"]["ended_at"] == "2026-10-01T19:46:00-05:00"          # 12.1 hours
    assert recs["2026-10-01T0740~2"]["ended_at"] == "2026-10-01T15:25:00-05:00"        # 7.75 hours, same minute
    c = recs["2026-07-31T1904"]                               # "7:04PM", "two hours, 30 minutes"
    assert c["started_at"] == "2026-07-31T19:04:00-05:00" and c["ended_at"] == "2026-07-31T21:34:00-05:00"
    d = recs["2025-10-23T1100"]                               # "at11:00AM", "stopped at 12:00PM"
    assert d["ended_at"] == "2025-10-23T12:00:00-05:00" and "stopped" in d["raw"]["end_basis"]


def test_waterloo_notified_is_the_earliest_time_given_not_a_begin():
    recs, _ = waterloo()
    n = recs["2026-09-28T0846"]
    assert "notified" in n["raw"]["start_basis"] and "at or before" in n["raw"]["start_basis"]
    assert "began" in recs["2026-10-01T0552"]["raw"]["start_basis"]


def test_waterloo_placed_on_no_water_with_city_county_and_permit():
    recs, _ = waterloo()
    for r in recs.values():
        assert r["waterbody_text"] is None and r["lat"] is None and r["water_slugs"] == []
        assert r["raw"]["county"] == "Black Hawk County" and r["raw"]["time_zone"] == "America/Chicago"
        assert r["npdes_permit"] == "IA0042650" and r["discharger_name"] == "City of Waterloo"
        assert r["event_type"] == "sso"                       # never unknown: a sewage report keeps its type


def test_waterloo_house_numbers_never_reach_a_record():
    recs, _ = waterloo()
    blob = json.dumps(recs)
    assert "9876" not in blob and "1234" not in blob
    assert "Example St" in blob and "200-blk Example Ave" in blob     # the street and a block stay


def test_waterloo_unreadable_paragraph_kept_with_parse_error_and_old_notices_kept():
    recs, _ = waterloo()
    bad = [r for r in recs.values() if r["parse_error"]]
    assert len(bad) == 1 and bad[0]["event_type"] == "sso" and bad[0]["source_record_id"].startswith("unread-")
    old = dict(recs["2025-10-23T1100"], source_record_id="2024-05-01T0800", event_id="ia-waterloo-sso-notices:x")
    recs2, stats = waterloo([old])
    assert stats["kept_from_previous"] == 1 and recs2["2024-05-01T0800"]["raw"]["_unlisted_since"] == AT


def test_waterloo_caution_from_the_end():
    from build import status as S
    rules = S.load_rules()
    recs, _ = waterloo()
    ivs = S.event_intervals(recs["2026-10-01T0552"], "IA", datetime.fromisoformat("2026-10-02T12:00:00+00:00"),
                            None, rules)
    assert ivs and ivs[0]["start"].isoformat().startswith("2026-10-01T10:52")


# ---------------------------------------------------------------- DNR news releases

from ingest import ia_dnr_news as N  # noqa: E402

ART = {"https://www.iowadnr.gov/news-release/2026-08-04/wastewater-discharge-exampleton": "dnr-article-plant.html",
       "https://www.iowadnr.gov/news-release/2026-10-01/statewide-bypasses": "dnr-article-statewide.html",
       "https://www.iowadnr.gov/news-release/2026-04-28/company-wastewater": "dnr-article-company.html"}


def news(tmp_path, monkeypatch):
    monkeypatch.setattr(N, "STATE_PATH", tmp_path / "state.json")
    out = {}
    monkeypatch.setattr(N, "write_events", lambda sid, recs, **kw: out.update(recs=recs, **kw) or tmp_path)
    monkeypatch.setattr(N, "get", lambda url: (_ for _ in ()).throw(AssertionError(f"no network in tests: {url}")))
    args = ["--rss-file", str(FIX / "dnr-rss.xml"), "--at", AT]
    for url, f in ART.items():
        args += ["--article-file", f"{url}={FIX / f}"]
    assert N.main(args) == 0
    return {r["source_record_id"]: r for r in out["recs"]}, out["meta"]


def test_dnr_news_titles_filter_and_company_wastewater_is_not_a_sewage_report(tmp_path, monkeypatch):
    recs, meta = news(tmp_path, monkeypatch)
    assert meta["not_municipal"] == ["Wastewater enters Fixture Creek near Sampleville"]
    assert not any("manure" in k for k in recs)
    assert len(recs) == 3


def test_dnr_news_plant_bypass_times_from_the_text_never_the_release(tmp_path, monkeypatch):
    recs, _ = news(tmp_path, monkeypatch)
    r = recs["2026-08-04/wastewater-discharge-exampleton"]
    assert r["event_type"] == "plant_bypass" and r["status"] == "ended"
    assert r["started_at"] == "2026-07-25T14:00:00-05:00" and r["time_precision"] == "minute"
    assert r["ended_at"] == "2026-07-27T16:00:00-05:00" and r["raw"]["ended_at_precision"] == "minute"
    assert r["reported_at"] == "2026-07-26" and r["published_at"] == "2026-08-04"
    assert r["waterbody_text"] == "Sample River" and r["volume_gal"] == 1_500_000 and r["estimate_flag"] == "estimated"
    assert r["discharger_name"] == "City of Exampleton" and r["raw"]["county"] == "Example County"
    assert "take caution and avoid the area" in r["advice_text"]
    blob = json.dumps(recs)
    assert "4321" not in blob and "555-0199" not in blob


def test_dnr_news_sections_split_and_a_landmark_town_is_not_the_operator(tmp_path, monkeypatch):
    recs, _ = news(tmp_path, monkeypatch)
    s = recs["2026-10-01/statewide-bypasses"]
    assert s["event_type"] == "bypass" and s["waterbody_text"] is None and s["raw"]["statewide"]
    assert s["started_at"] is None and s["published_at"] == "2026-10-01"
    c = recs["2026-10-01/statewide-bypasses#example-county"]
    assert c["event_type"] == "sso" and c["material"] == "sewage sludge / biosolids"
    assert c["waterbody_text"] == "Fixture Creek" and c["discharger_name"] is None
    assert c["raw"]["county"] == "Example County" and "avoid Fixture Creek" in c["advice_text"]


def test_dnr_news_a_date_after_the_release_month_is_last_year():
    assert N._year_for(12, __import__("datetime").date(2026, 1, 5)) == 2025
    assert N._year_for(1, __import__("datetime").date(2026, 1, 5)) == 2026
