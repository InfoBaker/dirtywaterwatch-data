"""Wisconsin: MMSD's Storm Update posts (ingest/wi_mmsd_storm_updates.py) and the state's registry rows, register, rules
row, text and missing-waters list. The fixture is the real list and posts of 2026-11-14 (the safe document the module
keeps: titles, stamps, letter links and article lines cut at MMSD's standing advice block); the personal strings in
the privacy test are synthetic ("Example")."""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

import zones
from ingest import wi_mmsd_storm_updates as M

ROOT = Path(__file__).resolve().parents[2]
FIX = Path(__file__).resolve().parent / "fixtures" / "wi"
FETCHED = "2026-11-14T18:00:00Z"


def doc() -> dict:
    return json.loads((FIX / "mmsd_storm_updates.json").read_text())


def built(d: dict | None = None, prev: list[dict] | None = None) -> tuple[dict[str, dict], dict]:
    recs, stats = M.build(d or doc(), prev or [], FETCHED)
    return {r["source_record_id"]: r for r in recs}, stats


# ---------------------------------------------------------------- MMSD Storm Updates

def test_only_storm_updates_and_overflow_letters_are_read():
    recs, stats = built()
    assert stats["items"] == 15 and stats["posts_read"] == 12 and stats["not_read"] == 3
    assert not any("budget" in k or "audit" in k or "meeting" in k for k in recs)
    assert stats["records"] == len(recs) == 18
    assert M.TITLE_RE.search("Reducing Flooding, Sewer Overflows & Basement Backups Priorities") is None


def test_dated_post_volume_and_publication_clock():
    r = built()[0]["storm-update-august-1st-2026:cso"]
    assert r["event_type"] == "cso" and r["status"] == "unknown"
    assert r["started_at"] == "2026-08-01" and r["time_precision"] == "day"
    assert r["published_at"] == "2026-08-06T09:00:00-05:00"          # the post's own stamp, Central daylight time
    assert r["reported_at"] is None and r["source_updated_at"] is None and r["ended_at"] is None
    assert r["volume_gal"] == 96_000_000 and r["estimate_flag"] == "estimated"
    assert r["npdes_permit"] == "WI0036820" and r["discharger_id"] == "wi-mmsd"
    assert r["raw"]["time_zone"] == "America/Chicago" and r["raw"]["keeps_rain_caution"] is True
    assert r["waterbody_text"] is None and r["lat"] is None          # placed by the permit's outfalls, never a point


def test_stated_start_end_minutes_in_central_time():
    recs = built()[0]
    r = recs["mmsd-storm-update-april-1-thru-4-2024:cso"]
    assert r["started_at"] == "2024-04-02T17:55:00-05:00" and r["time_precision"] == "minute"
    assert r["ended_at"] == "2024-04-04T20:10:00-05:00" and r["status"] == "ended"
    assert r["raw"]["ended_at_precision"] == "minute" and r["raw"]["period_end"] == "2024-04-04"
    assert r["volume_gal"] == 357_000_000
    w = recs["overflow-alert-february-27-2023:cso"]
    assert w["started_at"] == "2023-02-27T11:30:00-06:00"            # standard time in February
    assert w["ended_at"] == "2023-03-01T08:00:00-06:00"


def test_named_water_and_hour_from_text():
    r = built()[0]["storm-update-september-3rd-2026:cso"]
    assert r["waterbody_text"] == "Lincoln Creek" and r["water_match"] == "name"
    assert r["started_at"] == "2026-09-03T10:00:00-05:00" and r["volume_gal"] == 331_500
    assert r["published_at"] == "2026-09-08T11:00:00-05:00"


def test_two_types_in_one_post_and_listed_sso_waters():
    recs = built()[0]
    cso, sso = recs["storm-update-september-11-12-2022:cso"], recs["storm-update-september-11-12-2022:sso"]
    assert cso["volume_gal"] == 751_000_000 and sso["volume_gal"] == 4_930_000
    assert sso["waterbody_text"].split("; ") == ["Wilson Park Creek", "Kinnickinnic River", "Lake Michigan", "Milwaukee River"]
    assert cso["waterbody_text"] is None
    # the member municipalities' own overflows are kept as text, never as MMSD's records
    assert "Brookfield" in cso["raw"]["local_overflows_text"]
    assert cso["started_at"] == "2022-09-11" and cso["raw"]["period_end"] == "2022-09-12"


def test_volume_for_both_types_is_not_split():
    recs = built()[0]
    cso, sso = recs["mmsd-storm-update-aug-9-11-2025:cso"], recs["mmsd-storm-update-aug-9-11-2025:sso"]
    assert cso["volume_gal"] is None and "5.14 billion" in cso["volume_text"]
    assert cso["raw"]["volume_covers"].startswith("combined and separate")
    assert sso["volume_gal"] is None and sso["raw"]["volume_covers"]


def test_volume_sentences_and_reductions():
    recs = built()[0]
    assert recs["storm-update-june-18-19-2018:cso"]["volume_gal"] == 360_000_000     # not the 112 million "reduced"
    assert recs["storm-update-june-18-19-2018:sso"]["volume_gal"] == 3_700_000      # the next sentence's figure
    assert recs["storm-update-june-18-19-2018:sso"]["raw"]["start_basis"].startswith("the first day")
    assert recs["storm-update-for-september-13-2019:sso"]["volume_gal"] == 41_000
    assert recs["storm-update-for-september-13-2019:cso"]["volume_gal"] == 282_000_000
    assert recs["storm-update-august-26-to-29:cso"]["volume_gal"] == 295_700_000
    assert recs["storm-update-august-26-to-29:cso"]["started_at"] == "2018-08-26"


def test_letter_label_types_and_generic_overflows_never_unknown():
    recs = built()[0]
    assert {"storm-update-july-10-2020-1:cso", "storm-update-july-10-2020-1:sso"} <= set(recs)
    g = recs["letter-to-dnr-about-recent-overflows:sso"]
    assert g["started_at"] == "2019-03-14" and "general case" in g["raw"]["_type_basis"]
    a = recs["mmsd-storm-update-april-2026:sso"]
    assert a["started_at"] == "2026-04-14" and a["raw"]["period_end"] == "2026-04-18"
    assert all(r["event_type"] in ("cso", "sso") for r in recs.values())


def test_a_month_day_is_not_scrubbed_as_a_house_number():
    assert M.safe_line("A separate sewer overflow occurred on June 18 at 35th St.") == \
        "A separate sewer overflow occurred on June 18 at 35th St."
    assert "1234" not in M.safe_line("Call 414-555-0199 about 1234 Example Ave")


def test_year_rules_and_ranges():
    from datetime import date
    assert M.period("STORM UPDATE -AUGUST 26 TO 29", date(2018, 8, 31))[:2] == (date(2018, 8, 26), date(2018, 8, 29))
    assert M.period("MMSD Winter Storm Update - Feb 27 to Mar 1, 2023", date(2023, 3, 3))[:2] == \
        (date(2023, 2, 27), date(2023, 3, 1))
    assert M.period("STORM UPDATE FROM 8-20-18", date(2018, 8, 24))[0] == date(2018, 8, 20)
    assert M.period("STORM UPDATE - SEPTEMBER 5,6", date(2018, 9, 10))[:2] == (date(2018, 9, 5), date(2018, 9, 6))
    assert M.period("Storm update December 30-31", date(2027, 1, 4))[0] == date(2026, 12, 30)   # never after the post
    assert M.period("MMSD Storm Update: April 2026", date(2026, 4, 24)) is None


def test_records_carried_when_a_post_scrolls_off_and_first_seen_kept():
    recs, _ = built()
    first = list(recs.values())
    d = doc()
    d["items"] = [i for i in d["items"] if i["slug"] != "storm-update-august-1st-2026"]
    again, _ = built(d, first)
    assert "storm-update-august-1st-2026:cso" in again
    assert again["storm-update-september-3rd-2026:cso"]["raw"]["_first_seen_at"] == FETCHED


def test_an_edited_post_drops_the_type_it_no_longer_reports():
    recs, _ = built()
    d = doc()
    p = d["posts"]["storm-update-september-11-12-2022"]
    p["lines"] = [x for x in p["lines"] if "Separate Sewer Overflows (SSO)" not in x and " – " not in x[:60]
                  and "Separate sewer overflows also" not in x]
    again, _ = built(d, list(recs.values()))
    assert "storm-update-september-11-12-2022:cso" in again
    assert "storm-update-september-11-12-2022:sso" not in again


def test_counter_and_water_drop_alert_are_not_overflows():
    d = doc()
    d["items"] = [{"url": "https://www.mmsd.com/about-us/news/example", "slug": "example", "list_date": "Nov 1, 2026, 9:00 AM",
                   "title": "Water Drop Alert issued: heavy rain expected"}]
    d["posts"] = {"example": {"stamp": "11/01/26 09:00:am", "letters": [],
                              "lines": ["Gallons Overflowed: 2,810,937,528", "Please use less water."]}}
    recs, stats = built(d)
    assert recs == {} and stats["not_read"] == 1


def test_page_doc_cuts_advice_block_and_scrubs():
    html = ('<div><h1 class="ccm-block-page-title page-title">MMSD Storm Update Example</h1></div>'
            '<div>01/02/27 09:00:am</div><div><p>MMSD is reporting a combined sewer overflow that took place on '
            'January 1, 2027. Contact Pat Example at 414-555-0199 or pat.example@example.org.</p>'
            '<ul><li><a href="https://www.mmsd.com/download_file/view/x/1">5-day letter</a></li></ul>'
            '<p>Text WATERDROP to 414-555-0100</p><p>after the cut</p></div><footer>f</footer>')
    d = M.page_doc(html)
    blob = json.dumps(d)
    assert d["stamp"] == "01/02/27 09:00:am"
    assert "414-555-0199" not in blob and "pat.example" not in blob and "after the cut" not in blob
    assert d["letters"] == [{"url": "https://www.mmsd.com/download_file/view/x/1", "label": "5-day letter"}]
    recs = M.records_for({"url": "u", "slug": "example", "title": "MMSD Storm Update Example", "list_date": None}, d, FETCHED)
    assert recs[0]["started_at"] == "2027-01-01" and recs[0]["published_at"] == "2027-01-02T09:00:00-06:00"


def test_wisconsin_is_central_time():
    assert zones.STATE_ZONES["WI"] == "America/Chicago"


class FakeResp:
    def __init__(self, body: bytes):
        self.content = body

    def raise_for_status(self):
        return None


class FakeSession:
    """The news list: two real pages, then the CMS answering any later page with page one (as mmsd.com does)."""

    def __init__(self, pages: dict[int, bytes], posts: dict[str, bytes]):
        self.pages, self.posts, self.asked = pages, posts, []

    def get(self, url, params=None, headers=None, timeout=None):
        self.asked.append((url, (params or {}).get(M.PAGE_PARAM)))
        if params:
            return FakeResp(self.pages.get(params[M.PAGE_PARAM], self.pages[1]))
        return FakeResp(self.posts[M.slug_of(url)])


def _list_page(items: list[tuple[str, str]]) -> bytes:
    rows = "".join(f'<div class="ccm-block-page-list-title"><a href="https://www.mmsd.com/about-us/news/{s}" '
                   f'target="_self"><h3>{t}</h3></a></div><div class="ccm-block-page-list-date">Sep 8, 2026, 11:00 AM</div>'
                   for s, t in items)
    return rows.encode()


def test_fetch_stops_when_the_cms_repeats_page_one(monkeypatch):
    monkeypatch.setattr(M, "PAUSE_S", 0)
    p1 = _list_page([("storm-update-example", "MMSD Storm Update September 3rd, 2026"), ("budget", "Budget news")])
    p2 = _list_page([("plant-sale", "Rain garden plant sale")])
    post = (b'<h1 class="ccm-block-page-title page-title">MMSD Storm Update September 3rd, 2026</h1><div>09/08/26 11:00:am'
            b'</div><p>MMSD is reporting a combined sewer overflow that occurred on September 3rd, 2026.</p>')
    sess = FakeSession({1: p1, 2: p2}, {"storm-update-example": post})
    doc = M.fetch_safe(sess, M.BACKFILL_PAGES, {})
    assert [i["slug"] for i in doc["items"]] == ["storm-update-example", "budget", "plant-sale"]
    assert sum(1 for _, p in sess.asked if p) == 3          # page 3 repeated page 1: the walk stopped there
    assert list(doc["posts"]) == ["storm-update-example"]   # only the storm update's page was asked for
    recs, _ = M.build(doc, [], FETCHED)
    assert recs[0]["started_at"] == "2026-09-03" and recs[0]["event_type"] == "cso"
