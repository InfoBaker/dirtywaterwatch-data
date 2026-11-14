"""Wisconsin: MMSD's Storm Update posts (ingest/wi_mmsd_storm_updates.py) and the state's registry rows, register, rules
row, text and missing-waters list. The fixture is the real list and posts of 2026-11-14 (the safe document the module
keeps: titles, stamps, letter links and article lines cut at MMSD's standing advice block); the personal strings in
the privacy test are synthetic ("Example")."""
from __future__ import annotations

import json
import sys
from copy import deepcopy
from pathlib import Path

import pytest

import zones
from ingest import wi_mmsd_storm_updates as M

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
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
    assert stats["candidates"] == 18 and stats["posts_read"] == 15 and stats["not_read"] == 3
    assert not any("budget" in k or "audit" in k or "meeting" in k for k in recs)
    assert stats["records"] == len(recs) == 21
    assert not M.candidate("Reducing Flooding, Sewer Overflows & Basement Backups Priorities")


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
    assert all(r["event_type"] in ("cso", "sso", "plant_bypass") for r in recs.values())


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
                   "title": "MMSD Storm Update: Water Drop Alert issued"}]
    d["posts"] = {"example": {"stamp": "11/01/26 09:00:am", "letters": [],
                              "lines": ["Gallons Overflowed: 2,810,937,528", "Please use less water."]}}
    recs, stats = built(d)
    assert recs == {} and stats["posts_read"] == 1


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
    assert [i["slug"] for i in doc["items"]] == ["storm-update-example"]          # only candidates are kept
    assert doc["list_items_seen"] == 3
    assert sum(1 for _, p in sess.asked if p) == 3          # page 3 repeated page 1: the walk stopped there
    assert list(doc["posts"]) == ["storm-update-example"]   # only the storm update's page was asked for
    recs, _ = M.build(doc, [], FETCHED)
    assert recs[0]["started_at"] == "2026-09-03" and recs[0]["event_type"] == "cso"


# ---------------------------------------------------------------- the state's files

import re  # noqa: E402

from build import status as S  # noqa: E402


def ops() -> list[dict]:
    return [d for d in json.loads((ROOT / "data" / "dischargers.json").read_text())
            if d.get("state") == "WI" and "wi" in (d.get("source_areas") or [])]


def test_a_day_dated_post_gets_72_hours_from_the_start_of_its_central_day():
    from datetime import datetime, timedelta, timezone
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    r = built()[0]["storm-update-august-1st-2026:cso"]
    ivs = S.event_intervals(r, "WI", datetime(2026, 8, 6, 15, tzinfo=timezone.utc), rules=rules)
    day0 = datetime(2026, 8, 1, 5, tzinfo=timezone.utc)                  # midnight in Milwaukee (CDT)
    assert (ivs[0]["rule"], ivs[0]["color"], ivs[0]["start"], ivs[0]["end"]) == \
        ("day_start_caution", "yellow", day0, day0 + timedelta(hours=72))
    stated = built()[0]["mmsd-storm-update-april-1-thru-4-2024:cso"]
    assert S.event_intervals(stated, "WI", datetime(2024, 4, 8, tzinfo=timezone.utc), rules=rules)[0]["rule"] != \
        "day_start_caution"


def test_named_water_outfall_placement_is_keyed_on_wisconsin():
    assert "WI" in S.NAMED_WATER_OUTFALL_STATES and "OR" in S.NAMED_WATER_OUTFALL_STATES
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    assert rules["placement"]["no_outfall_all_waters"] is True


def test_every_wisconsin_permit_is_in_exactly_one_row():
    plants = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if r.get("state") == "WI"}
    cso = {r["npdes_permit"] for r in json.loads((ROOT / "data" / "outfalls-us.json").read_text())["outfalls"]
           if str(r.get("npdes_permit") or "").startswith("WI")}
    rows = ops()
    held = [p for r in rows for p in r["npdes_permits"]]
    assert len(held) == len(set(held)) and set(held) == plants | cso
    by = {r["id"]: r for r in rows}
    m = by["wi-mmsd"]
    assert m["npdes_permits"] == ["WI0036820"] and m["kind"] == "cso" and m["outfall_count"] == 114
    assert {"wi-milwaukee-metro-sew-dist-combi", "wi-mmsd-sso"} <= set(m["aliases"]) and m["legal_form"] == "special district"
    assert by["wi-superior-sewage-disposal-system"]["outfall_count"] == 3
    assert by["wi-fremont-sso"]["npdes_permits"] == ["WI0026158"]
    assert by["wi-village-of-stockbridge"]["legal_form"] == "town"                   # the village, not the band
    assert by["wi-columbus-city-wwtf"]["legal_form"] == "city"                       # not a federal facility
    tribal = [r for r in rows if r["legal_form"] == "tribal"]
    from add_wi_operators import EPA_TRIBAL_PERMITS
    assert all("EPA Region 5" in r["notification_channel"] for r in tribal if r["npdes_permits"][0] in EPA_TRIBAL_PERMITS)
    assert all("NR 210.21(5)" in r["notification_channel"] for r in rows if r not in tribal)
    assert all("122.38" in r["notification_channel"] for r in rows if r["kind"] == "cso")
    assert sum(1 for r in rows if r["kind"] == "cso") == 2


def test_register_rows_per_operator_and_the_state_channels():
    reg = {c["id"]: c for c in json.loads((ROOT / "data" / "notice-channels" / "wi.json").read_text())["channels"]}
    from add_wi_operators import EPA_TRIBAL_PERMITS
    for r in ops():
        if set(r["npdes_permits"]) & EPA_TRIBAL_PERMITS:
            assert reg[f"{r['id']}-epa-report"]["barrier"] == "no_web_page"
        else:
            row = reg[f"{r['id']}-nr210-notice"]
            assert row["operator_id"] == r["id"] and "NR 210.21(5)" in row["legal_basis"] and row["barrier"] == "print_only"
    assert reg["wi-mmsd-storm-updates"]["feed_source_id"] == "wi-mmsd-storm-updates"
    assert reg["wi-dnr-switchboard-sso-reports"]["barrier"] == "login_required"
    assert reg["wi-mmsd-cso-notification-plan"]["barrier"] == "image_only"
    assert reg["wi-mmsd-rain-facility-page"]["records"] is False      # a counter, never an overflow
    for cid in ("wi-superior-cso-page", "wi-dnr-serts-open-spills", "wi-dnr-beach-health"):
        assert reg[cid]["monitored"] is True and reg[cid]["records"] is False
    named = {c["operator_id"] for c in reg.values() if c.get("legal_basis") and "122.38" in c["legal_basis"]}
    assert {"wi-mmsd", "wi-superior-sewage-disposal-system"} <= named   # every CSO permittee named


def test_rules_row_cites_the_law_and_sets_no_window():
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    wi = rules["red"]["by_state"]["WI"]
    assert wi["hours"] is None and "NR 210.21(5)" in wi["source"] and "122.38" in wi["source"]
    assert not re.search(r"\b(safe|clean)\b", wi["basis"], re.I)
    assert "wi-mmsd-storm-updates" in rules["unresolved"]["day_start_caution"]["sources"]


def test_state_text_is_in_the_page_shape_and_its_numbers_match_the_fetch():
    t = (ROOT / "research" / "wi" / "state-text.md").read_text()
    assert t.startswith("---\nstate: WI\nname: Wisconsin\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "{{dated_share}}" in t and "{{latest_dated}}" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I) and ".json" not in t and ".py" not in t
    assert "18 such posts" in t and "26 reports" in t and "13 combined sewer overflows" in t
    assert "331,500 gallons into Lincoln Creek on September 3, 2026, posted on September 8" in t


def test_missing_waters_list_leaves_out_the_national_lists_names():
    d = json.loads((ROOT / "research" / "wi" / "receiving-waters-missing.json").read_text())
    nat = json.loads((ROOT / "data" / "receiving-waters-national.json").read_text())

    def k(n):
        return re.sub(r"[^a-z0-9]", "", (n or "").lower())
    held = {k(n) for w in nat["states"]["WI"]["waters"]
            for n in [w.get("name"), w.get("key"), *(w.get("names_seen") or []), *(w.get("gnis_names") or [])] if n}
    assert d["state"] == "WI" and d["waters"] == len(d["rows"])
    assert not [r["name"] for r in d["rows"] if k(r["name"]) in held]
    resolved = {k(x.get("name")) for x in d.get("resolved") or []}   # a batch may move a name under resolved
    assert all(k(r["name"]) not in resolved for r in d["rows"])


def test_no_personal_string_reaches_the_records():
    d = doc()
    p = d["posts"]["storm-update-august-1st-2026"]
    html = ('<h1 class="ccm-block-page-title page-title">MMSD Storm Update August 1st, 2026</h1><div>08/06/26 09:00:am</div>'
            '<p>MMSD is reporting a combined sewer overflow that took place on August 1, 2026.</p>'
            '<p>Overflow volume of 96 million gallons.</p>'
            '<p>Questions: Pat Example, 414-555-0199, pat.example@example.org, 1234 Example Ave</p>')
    p.update(M.page_doc(html))
    blob = json.dumps(built(d)[0])
    for x in ("Pat Example", "414-555-0199", "pat.example", "1234 Example"):
        assert x not in blob
    assert built(d)[0]["storm-update-august-1st-2026:cso"]["volume_gal"] == 96_000_000


# ---------------------------------------------------------------- Astra review 2026-11-14

def _post(lines, stamp="06/05/27 09:00:am", letters=()):
    return {"stamp": stamp, "lines": list(lines), "letters": list(letters)}


def _recs(title, lines, **kw):
    return {r["event_type"]: r for r in M.records_for({"url": "u", "slug": "x", "title": title, "list_date": None},
                                                       _post(lines, **kw), FETCHED)}


def test_p1_1_denials_forecasts_and_zeros_make_no_report():
    t = "MMSD Storm Update June 1, 2027"
    assert _recs(t, [t, "No combined sewer overflow occurred on June 1, 2027."]) == {}
    assert _recs(t, [t, "A combined sewer overflow may occur if rain continues."]) == {}
    assert _recs(t, [t, "The deep tunnel prevented sewer overflows during the storm."]) == {}
    assert _recs(t, [t, "Combined Sewer Overflow: 0 gallons"]) == {}
    assert set(_recs(t, [t, "A combined sewer overflow occurred on June 1, 2027."])) == {"cso"}


def test_p1_2_each_overflow_keeps_its_own_times_and_years_never_come_from_the_clock():
    t = "MMSD Storm Update June 1-2"
    r = _recs(t, [t, "A combined sewer overflow started at 1:00 pm on June 1, 2027, and ended at 3:00 pm on June 1, 2027.",
                  "A separate sewer overflow started at 4:00 am on June 2, 2027, and ended at 6:00 am on June 2, 2027."])
    assert r["cso"]["started_at"] == "2027-06-01T13:00:00-05:00" and r["cso"]["ended_at"] == "2027-06-01T15:00:00-05:00"
    assert r["sso"]["started_at"] == "2027-06-02T04:00:00-05:00" and r["sso"]["ended_at"] == "2027-06-02T06:00:00-05:00"
    # no stamp and no list date: a date with no year stays unknown, whatever the day it is read
    f = M.read_post("Storm update", {"stamp": None, "lines": ["A combined sewer overflow occurred on June 1."]}, None)
    assert f["period"] is None


def test_p1_3_a_failed_or_holding_page_is_not_a_revision_and_is_retried(monkeypatch):
    monkeypatch.setattr(M, "PAUSE_S", 0)
    assert M.page_doc('<h1 class="ccm-block-page-title page-title">MMSD Storm Update</h1><p>Temporarily unavailable</p>') is None
    recs, _ = built()
    prev = {(r.get("raw") or {}).get("slug"): r for r in recs.values()}
    p1 = _list_page([("storm-update-september-3rd-2026", "MMSD Storm Update September 3rd, 2026")])

    class Down(FakeSession):
        def get(self, url, params=None, headers=None, timeout=None):
            if params:
                return FakeResp(p1)
            raise M.requests.ConnectionError("refused")
    doc = M.fetch_safe(Down({1: p1}, {}), 1, {k: v for k, v in prev.items() if k != "storm-update-september-3rd-2026"},
                       fetched_at=FETCHED)
    assert [f["slug"] for f in doc["failed"]] == ["storm-update-september-3rd-2026"]
    again, stats = M.build(doc, list(recs.values()), FETCHED)
    assert "storm-update-september-3rd-2026:cso" in {r["source_record_id"] for r in again}   # kept, not deleted
    assert stats["posts_failed"] == 1


def test_p1_4_spills_and_releases_are_read_and_a_no_water_spill_colours_nothing():
    recs = built()[0]
    p = recs["treatment-plant-spill-january-7-2026:plant_bypass"]
    assert p["started_at"] == "2026-01-06T23:25:00-06:00" and p["ended_at"] == "2026-01-07T02:22:00-06:00"
    assert p["volume_gal"] == 150_000 and p["raw"]["reached_water"] is False and p["waterbody_text"] is None
    s = recs["mmsd-sanitary-sewer-release-march-11-2025:sso"]
    assert s["started_at"] == "2025-03-11" and s["waterbody_text"] == "Lincoln Creek" and s["volume_gal"] == 9_600
    assert "wastewater-spill-september-18:plant_bypass" in recs
    assert not M.candidate("Proposed Budgets Would Lower Taxes in 2027 & Reduce Flooding, Overflows")
    assert M.candidate("Sanitary Sewer Release March, 11 2025") and M.candidate("Treatment Plant Spill January 7, 2026")


def test_p2_8_a_known_post_is_read_again_after_thirty_days_and_a_retry_beyond_page_two(monkeypatch):
    monkeypatch.setattr(M, "PAUSE_S", 0)
    recs, _ = built()
    prev = {(r.get("raw") or {}).get("slug"): r for r in recs.values()}
    p1 = _list_page([("budget", "Budget news")])
    sess = FakeSession({1: p1}, {k: b"<p>x</p>" for k in [*prev, "old-one"]})
    doc = M.fetch_safe(sess, 1, prev, retry=[{"url": "https://www.mmsd.com/about-us/news/old-one", "slug": "old-one",
                                              "title": "Storm Update - Old", "list_date": None}],
                       fetched_at="2026-12-20T18:00:00Z")
    asked = {M.slug_of(u) for u, p in sess.asked if not p}
    assert set(prev) | {"old-one"} <= asked       # every known post revalidated after 30 days, and the retry
    again = M.fetch_safe(FakeSession({1: p1}, {}), 1, prev, fetched_at="2026-11-20T18:00:00Z")
    assert again["failed"] == []                  # read six days ago: not asked for again
