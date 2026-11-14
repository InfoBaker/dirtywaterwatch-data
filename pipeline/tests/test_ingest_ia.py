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
