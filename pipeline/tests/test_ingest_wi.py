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
    assert cso["started_at"] is None and cso["raw"]["started_after"] == "2022-09-11" and cso["raw"]["period_end"] == "2022-09-12"


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
    assert recs["storm-update-june-18-19-2018:sso"]["raw"]["start_basis"].startswith("the date the post")
    assert recs["storm-update-for-september-13-2019:sso"]["volume_gal"] == 41_000
    assert recs["storm-update-for-september-13-2019:cso"]["volume_gal"] == 282_000_000
    assert recs["storm-update-august-26-to-29:cso"]["volume_gal"] == 295_700_000
    assert recs["storm-update-august-26-to-29:cso"]["raw"]["started_after"] == "2018-08-26"


def test_letter_label_types_and_generic_overflows_never_unknown():
    recs = built()[0]
    assert {"storm-update-july-10-2020-1:cso", "storm-update-july-10-2020-1:sso"} <= set(recs)
    g = recs["letter-to-dnr-about-recent-overflows:sso"]
    assert g["started_at"] is None and g["raw"]["started_after"] == "2019-03-14" and "general case" in g["raw"]["_type_basis"]
    a = recs["mmsd-storm-update-april-2026:sso"]
    assert a["started_at"] is None and a["raw"]["started_after"] == "2026-04-14" and a["raw"]["period_end"] == "2026-04-18"
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
    # a facility placeholder with no outfall number is not an outfall (Astra review P2-11)
    plants = json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
    for r in rows:
        if r["kind"] == "plant":
            n = len({(x["npdes_permit"], x["outfall"]) for x in plants if x.get("state") == "WI"
                     and x["npdes_permit"] in r["npdes_permits"] and x.get("outfall") not in (None, "")})
            assert r["outfall_count"] == (n or None)
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
            # the newspaper minimum alone does not show a notice is printed only (Astra review P2-12)
            assert row["operator_id"] == r["id"] and "NR 210.21(5)" in row["legal_basis"] and row["barrier"] == "not_verified"
    assert reg["wi-mmsd-storm-updates"]["feed_source_id"] == "wi-mmsd-storm-updates"
    assert reg["wi-dnr-switchboard-sso-reports"]["barrier"] == "login_required"
    assert reg["wi-mmsd-cso-notification-plan"]["barrier"] == "image_only"
    assert reg["wi-mmsd-rain-facility-page"]["records"] is False      # a counter, never an overflow
    assert reg["wi-superior-cso-page"]["monitored"] is True and reg["wi-superior-cso-page"]["records"] is False
    # pages that can carry staff names are watched for availability only, with no text or body kept (Astra review
    # P1-6; re-review 2026-11-15 P1-7, P2-11), and Milwaukee's beach page's bot wall is a barrier, not worked around
    for cid in ("wi-dnr-serts-open-spills", "wi-dnr-brrts-search", "wi-dnr-beach-health", "wi-dnr-beach-layer"):
        assert reg[cid]["monitored"] is True and reg[cid]["records"] is False and reg[cid]["metadata_only"] is True
        assert reg[cid]["availability_only"] is True
    mb = reg["wi-milwaukee-health-beaches"]
    assert mb["monitored"] is False and mb["unmonitored_reason"] == "bot_wall" and mb["barrier"] == "bot_wall"
    assert "headers" not in mb
    assert not any(c["barrier"] == "print_only" for c in reg.values())
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
    # the counts the text gives, re-derived from the fixture's posts where it holds them all (the 2026 posts)
    assert "21 such posts" in t and "29 reports" in t and "13 combined sewer overflows" in t
    assert "2 spills at treatment plants" in t and "one to ten days" in t and "sends none" not in t
    reg = json.loads((ROOT / "data" / "notice-channels" / "wi.json").read_text())["channels"]
    assert not [c["id"] for c in reg if "four to ten days" in (c.get("note") or "")]
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


# ---------------------------------------------------------------- Astra review 2026-11-14, second pass

def test_r2_p1_1_negated_labelled_volumes_and_negated_waters_make_nothing():
    t = "MMSD Storm Update June 1, 2027"
    assert _recs(t, [t, "No combined sewer overflow of 100 gallons occurred on June 1, 2027."]) == {}
    assert _recs(t, [t, "A combined sewer overflow of 100 gallons may occur on June 1, 2027."]) == {}
    r = _recs(t, [t, "A combined sewer overflow occurred on June 1, 2027.", "No overflow into Example Creek occurred."])
    assert r["cso"]["waterbody_text"] is None


def test_r2_p1_2_each_overflow_keeps_its_own_day_in_one_paragraph_or_two():
    t = "MMSD Storm Update June 1-2, 2027"
    one = "A combined sewer overflow occurred on June 1, 2027. A separate sewer overflow occurred on June 2, 2027."
    for lines in ([t, one], [t, *one.split(". ", 1)]):
        r = _recs(t, lines)
        assert r["cso"]["started_at"] == "2027-06-01" and r["sso"]["started_at"] == "2027-06-02"
    storm = _recs("MMSD Storm Update June 1-2, 2027", ["MMSD Storm Update June 1-2, 2027",
                                                        "MMSD is reporting sewer overflows that resulted from rain."])
    assert storm["sso"]["started_at"] is None and "on or after raw.started_after" in storm["sso"]["raw"]["start_basis"]
    assert storm["sso"]["raw"]["period_end"] == "2027-06-02"


def test_r2_p1_3_an_expected_end_is_not_an_end():
    t = "MMSD Storm Update June 1, 2027"
    r = _recs(t, [t, "A combined sewer overflow started at 1:00 pm on June 1, 2027.",
                  "The combined sewer overflow is expected to continue until 2:00 pm on June 2, 2027."])
    assert r["cso"]["ended_at"] is None and r["cso"]["status"] == "unknown"


def test_r2_p1_4_a_stamped_holding_page_keeps_the_records_and_main_fails_an_incomplete_read(monkeypatch, tmp_path):
    recs, _ = built()
    d = doc()
    d["items"] = [i for i in d["items"] if i["slug"] == "storm-update-august-1st-2026"]
    d["posts"] = {"storm-update-august-1st-2026": {"stamp": "08/06/26 09:00:am", "letters": [],
                                                  "lines": ["MMSD Storm Update August 1st, 2026", "Temporarily unavailable"]}}
    again, stats = M.build(d, list(recs.values()), FETCHED)
    assert "storm-update-august-1st-2026:cso" in {r["source_record_id"] for r in again}
    assert stats["posts_without_report"] == ["storm-update-august-1st-2026"]
    written = {}
    monkeypatch.setattr(M, "write_events", lambda sid, recs, ok=True, error=None, meta=None, partial=False: written.update(
        ok=ok, error=error, meta=meta) or tmp_path / "x.json")
    monkeypatch.setattr(M, "read_json", lambda *a, **k: {"records": list(recs.values())})
    f = tmp_path / "doc.json"
    f.write_text(json.dumps(d))
    assert M.main(["--file", str(f)]) == 1
    assert written["ok"] is False and "storm-update-august-1st-2026" in written["error"]
    assert written["meta"]["retry"][0]["slug"] == "storm-update-august-1st-2026"


def test_r2_p1_6_nothing_after_the_contact_line_is_kept_and_records_hold_no_prose():
    html = ('<h1 class="ccm-block-page-title page-title">MMSD Storm Update Example</h1><div>01/02/27 09:00:am</div>'
            '<p>MMSD is reporting a combined sewer overflow that took place on January 1, 2027.</p>'
            '<p>Questions: call the office.</p>'
            '<p><a href="https://www.mmsd.com/download_file/view/y/2">Pat Example</a></p>')
    d = M.page_doc(html)
    assert "Pat Example" not in json.dumps(d) and d["letters"] == []
    r = M.records_for({"url": "u", "slug": "e", "title": "MMSD Storm Update Example", "list_date": None}, d, FETCHED)[0]
    assert "text" not in r["raw"] and "_doc" not in r["raw"]


def test_r3_source_yaml_names_every_emitted_category():
    y = (ROOT / "data" / "sources" / "wi-mmsd-storm-updates.yaml").read_text()
    types = {r["event_type"] for r in built()[0].values()}
    line = next(x for x in y.splitlines() if x.startswith("event_types:"))
    assert all(f'"{t}"' in line for t in types)


def test_r2_p2_10_a_timed_start_with_no_end_gets_14_days_from_its_report_as_the_text_says():
    from datetime import datetime, timedelta, timezone
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    r = built()[0]["storm-update-september-3rd-2026:cso"]
    ivs = S.event_intervals(r, "WI", datetime(2026, 9, 9, tzinfo=timezone.utc), rules=rules)
    told = datetime(2026, 9, 8, 16, tzinfo=timezone.utc)                  # the post's stamp, 11:00 CDT
    assert (ivs[0]["rule"], ivs[0]["color"], ivs[0]["start"], ivs[0]["end"]) == \
        ("no_end", "yellow", told, told + timedelta(days=14))
    assert "one with a time but no end, or with only the storm's dates and none of its own, shows caution for 14 days from its report" in \
        rules["red"]["by_state"]["WI"]["basis"]
    t = (ROOT / "research" / "wi" / "state-text.md").read_text()
    assert "one with a time but no end shows caution for 14 days from its report" in t
    assert "under a Wisconsin permit" in t and "tribal land" in t


# ---------------------------------------------------------------- Astra re-review 2026-11-15 (fix/wi-review)

def test_r3_p1_1_occurrence_is_read_per_clause_and_a_month_is_not_a_modal():
    t = "MMSD Storm Update May 1, 2027"
    r = _recs(t, [t, "A combined sewer overflow occurred on May 1, 2027."])
    assert set(r) == {"cso"} and r["cso"]["started_at"] == "2027-05-01"
    r = _recs(t, [t, "A combined sewer overflow occurred on May 1, 2027, but no separate sewer overflow occurred."])
    assert set(r) == {"cso"}
    r = _recs(t, [t, "No combined sewer overflow occurred, but a separate sewer overflow occurred on May 1, 2027."])
    assert set(r) == {"sso"} and r["sso"]["started_at"] == "2027-05-01"
    assert _recs(t, [t, "A combined sewer overflow may occur on May 1, 2027."]) == {}
    # the member municipalities' own overflows are theirs, not MMSD's
    assert _recs(t, [t, "Separate sewer overflows were reported by local sewer systems that are owned by municipalities."]) == {}
    # a spill title is not evidence: the body must report the spill
    s = "Treatment Plant Spill May 1, 2027"
    assert _recs(s, [s, "No wastewater spill occurred at the plant."]) == {}
    assert _recs(s, [s, "Temporarily unavailable"]) == {}
    assert set(_recs(s, [s, "Equipment failure led to an estimated 1,000 gallons of wastewater spilling onto land."])) \
        == {"plant_bypass"}


def test_r3_p1_2_an_end_is_never_a_start_and_a_storm_date_is_not_a_start():
    from datetime import datetime, timezone
    t = "MMSD Storm Update June 1-2, 2027"
    r = _recs(t, [t, "A combined sewer overflow occurred on June 1, 2027.",
                  "The combined sewer overflow ended at 2:00 pm on June 2, 2027."])["cso"]
    assert r["started_at"] == "2027-06-01" and r["time_precision"] == "day"
    assert r["ended_at"] == "2027-06-02T14:00:00-05:00" and r["status"] == "ended"
    # an end with no start: the end is kept, no start is made from it or from the storm's dates
    e = _recs(t, [t, "MMSD is reporting sewer overflows that resulted from rain.",
                  "The sewer overflow ended at 2:00 pm on June 2, 2027."])["sso"]
    assert e["started_at"] is None and e["ended_at"] == "2027-06-02T14:00:00-05:00"
    # storm dates only: kept as the period and a lower bound, never as the overflow's start
    s = _recs(t, [t, "MMSD is reporting sewer overflows that resulted from rain."])["sso"]
    assert s["started_at"] is None and s["time_precision"] is None
    assert s["raw"]["period_start"] == "2027-06-01" and s["raw"]["period_end"] == "2027-06-02"
    assert s["raw"]["started_after"] == "2027-06-01" and s["parse_error"] is None
    rules = json.loads((ROOT / "data" / "rules.json").read_text())
    ivs = S.event_intervals(s, "WI", datetime(2027, 6, 6, tzinfo=timezone.utc), rules=rules)
    told = datetime(2027, 6, 5, 14, tzinfo=timezone.utc)                 # the post's stamp, 09:00 CDT
    assert ivs and min(iv["start"] for iv in ivs) == told                 # from its report, not the storm's day
    assert all(iv["rule"] != "day_start_caution" for iv in ivs)


def test_r3_p1_3_only_a_completed_end_is_an_end():
    t = "MMSD Storm Update June 1, 2027"
    start = "A combined sewer overflow started at 1:00 pm on June 1, 2027."
    for later in ("The combined sewer overflow will continue until 2:00 pm on June 2, 2027.",
                  "The combined sewer overflow is scheduled to end at 2:00 pm on June 2, 2027.",
                  "If rain stops, the combined sewer overflow would end at 2:00 pm on June 2, 2027.",
                  "The combined sewer overflow is expected to have ended at 2:00 pm on June 2, 2027.",
                  "The combined sewer overflow has not ended at 2:00 pm on June 2, 2027.",
                  "The combined sewer overflow should continue until 2:00 pm on June 2, 2027."):
        r = _recs(t, [t, start, later])["cso"]
        assert r["ended_at"] is None and r["status"] == "unknown", later
        assert r["started_at"] == "2027-06-01T13:00:00-05:00", later
    for done in ("The combined sewer overflow ended at 2:00 pm on June 2, 2027.",
                 "The combined sewer overflow continued until 2:00 pm on June 2, 2027."):
        r = _recs(t, [t, start, done])["cso"]
        assert r["ended_at"] == "2027-06-02T14:00:00-05:00" and r["status"] == "ended", done


@pytest.mark.parametrize("slug", ["treatment-plant-spill-january-7-2026", "mmsd-sanitary-sewer-release-march-11-2025",
                                  "storm-update-september-3rd-2026"])
def test_r3_p1_4_a_holding_page_under_any_title_keeps_every_field(slug):
    recs, _ = built()
    d = doc()
    item = next(i for i in d["items"] if i["slug"] == slug)
    d["items"] = [item]
    d["posts"] = {slug: {"stamp": d["posts"][slug]["stamp"], "letters": [],
                         "lines": [item["title"], "Temporarily unavailable"]}}
    again, stats = M.build(d, list(recs.values()), FETCHED)
    after = {r["source_record_id"]: r for r in again}
    for k, r in recs.items():
        if k.startswith(slug + ":"):
            assert after[k] == r                      # start, end, volume and reached_water as before
    assert stats["posts_without_report"] == [slug]


def _post_html(title, stamp, text):
    return (f'<h1 class="ccm-block-page-title page-title">{title}</h1><div>{stamp}</div><p>{text}</p>').encode()


def test_r3_p1_5_a_failed_old_post_never_freezes_a_new_one(monkeypatch, tmp_path):
    import common
    monkeypatch.setattr(M, "PAUSE_S", 0)
    monkeypatch.setattr(M, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(M, "save_raw", lambda *a, **k: None)
    monkeypatch.setattr(M, "write_events", lambda sid, recs, **kw: common.write_events(
        sid, recs, path=tmp_path / f"{sid}.json", **kw))
    out = tmp_path / f"{M.SOURCE_ID}.json"
    old = ("storm-update-example-old", "MMSD Storm Update May 1, 2027")
    new = ("storm-update-example-new", "MMSD Storm Update June 1, 2027")
    good_old = _post_html(old[1], "05/05/27 09:00:am", "A combined sewer overflow occurred on May 1, 2027.")
    good_new = _post_html(new[1], "06/05/27 09:00:am", "A separate sewer overflow occurred on June 1, 2027.")

    class Sess(FakeSession):
        def get(self, url, params=None, headers=None, timeout=None):
            if not params and self.posts.get(M.slug_of(url)) is None:
                raise M.requests.ConnectionError("refused")
            return super().get(url, params, headers, timeout)

    def run(pages, posts):
        monkeypatch.setattr(M.requests, "Session", lambda: Sess({1: _list_page(pages)}, posts))
        return M.main(["--pages", "1"])

    assert run([old], {old[0]: good_old}) == 0                     # the first good run
    first_ok = json.loads(out.read_text())["last_ok_at"]
    # 30 days on, the old post is refused while a new one is posted: the new one is written at once, health false
    monkeypatch.setattr(M, "now_iso", lambda: "2027-07-10T00:00:00Z")
    assert run([new, old], {new[0]: good_new}) == 1
    f = json.loads(out.read_text())
    ids = {r["source_record_id"] for r in f["records"]}
    assert {f"{old[0]}:cso", f"{new[0]}:sso"} <= ids
    assert f["ok"] is False and f["last_ok_at"] == first_ok and [x["slug"] for x in f["meta"]["retry"]] == [old[0]]
    # the new post scrolls off before the old one recovers: still kept
    assert run([("budget", "Budget news")], {}) == 1
    f = json.loads(out.read_text())
    assert f"{new[0]}:sso" in {r["source_record_id"] for r in f["records"]} and f["ok"] is False
    # recovery: healthy again, nothing lost
    assert run([("budget", "Budget news")], {old[0]: good_old, new[0]: good_new}) == 0
    f = json.loads(out.read_text())
    assert f["ok"] is True and {f"{old[0]}:cso", f"{new[0]}:sso"} <= {r["source_record_id"] for r in f["records"]}


def test_r3_p1_5_write_events_default_failure_path_is_unchanged(tmp_path):
    import common
    p = tmp_path / "x.json"
    common.write_events("x", [{"event_id": "a"}], ok=True, path=p)
    common.write_events("x", [{"event_id": "b"}], ok=False, error="down", path=p)
    f = json.loads(p.read_text())
    assert [r["event_id"] for r in f["records"]] == ["a"] and f["ok"] is False


PRIVATE = ("Pat Example", "Sam Sample", "Lee Example", "555-0100", "pat@example.org", "1234 N", "43.123456",
           "-87.987654")


def test_r3_p1_6_inline_names_never_reach_a_raw_save_or_a_record(monkeypatch, tmp_path):
    monkeypatch.setattr(M, "PAUSE_S", 0)
    monkeypatch.setattr(M, "EVENTS_DIR", tmp_path)
    saved, written = [], []
    monkeypatch.setattr(M, "save_raw", lambda sid, content, ext: saved.append(content))
    monkeypatch.setattr(M, "write_events", lambda sid, recs, **kw: written.append((recs, kw)) or tmp_path / "x")
    title = "MMSD Storm Update June 1, 2027, Director Pat Example"
    html = (f'<h1 class="ccm-block-page-title page-title">{title}</h1><div>06/05/27 09:00:am</div>'
            '<p>Director Pat Example reported a combined sewer overflow into Lincoln Creek that occurred on June 1, 2027.</p>'
            '<p>"The overflow was short," said Sam Sample. Lee Example, district engineer, called 414-555-0100 and '
            'pat@example.org about 1234 N Example St at 43.123456, -87.987654.</p>'
            '<p><a href="https://www.mmsd.com/download_file/view/z/1">Pat Example</a></p>'
            '<p><a href="https://www.mmsd.com/download_file/view/z/2">DNR Letter for: Combined Sewer Overflow</a></p>'
            '<p>Pat Example</p><p>Sincerely,</p>')
    page = (f'<div class="ccm-block-page-list-title"><a href="https://www.mmsd.com/about-us/news/x-example" '
            f'target="_self"><h3>{title}</h3></a></div><div class="ccm-block-page-list-date">Jun 5, 2027, 9:00 AM</div>')
    monkeypatch.setattr(M.requests, "Session", lambda: FakeSession({1: page.encode()}, {"x-example": html.encode()}))
    assert M.main(["--pages", "1"]) == 0
    blob = json.dumps(saved, ensure_ascii=False) + json.dumps(written, ensure_ascii=False, default=str)
    for p in PRIVATE:
        assert p not in blob, p
    recs = written[-1][0]
    assert [r["event_type"] for r in recs] == ["cso"] and recs[0]["waterbody_text"] == "Lincoln Creek"
    assert recs[0]["started_at"] == "2027-06-01"
    assert any("Combined Sewer Overflow" in x["label"] for x in recs[0]["raw"]["letters"])


def _np_run(np_mod, rows, bodies, tmp_path, at):
    from datetime import datetime, timezone
    saved = []

    def fetcher(url, browser=False):
        b = bodies[url]
        if isinstance(b, int):
            return {"at": at, "ok": False, "http_status": b, "error": f"HTTP {b}",
                    "body": b"<p>Error. Call Pat Example at 414-555-0100</p>"}
        return {"at": at, "ok": True, "http_status": 200, "final_url": url, "content_type": "text/html", "error": None,
                "body": b}
    out = np_mod.run(rows, now=datetime.fromisoformat(at.replace("Z", "+00:00")).astimezone(timezone.utc),
                     fetcher=fetcher, store=tmp_path / "store", root=tmp_path,
                     raw_saver=lambda src, body, ext: saved.append(body) or tmp_path / "raw.bin")
    return out, saved


def test_r3_p1_7_watched_wisconsin_pages_keep_no_body_and_no_text(tmp_path):
    from ingest import notification_pages as NP
    reg = json.loads((ROOT / "data" / "notice-channels" / "wi.json").read_text())["channels"]
    rows = [r for r in reg if r.get("monitored")]
    assert rows and all(r.get("metadata_only") is True and r.get("records") is False for r in rows)
    personal = ("<html><body><h1>Example page</h1><p>Contact Pat Example, 414-555-0100, pat@example.org, "
                "1234 N Example St.</p></body></html>").encode()
    urls = [u for r in rows for u in r["urls"]]
    for k, bodies in enumerate(({u: personal for u in urls}, {u: 503 for u in urls},
                                {u: personal.replace(b"Example page", b"Example page 2") for u in urls})):
        out, saved = _np_run(NP, rows, bodies, tmp_path, ("2026-11-15T12:00:00Z", "2026-11-23T12:00:00Z",
                                                          "2026-12-01T12:00:00Z")[k])
        assert saved == []                                    # no response body, good or error, is saved
        blob = json.dumps(out["snaps"], default=str) + "".join(p.read_text() for p in (tmp_path / "store").rglob("*.json"))
        for p in PRIVATE[:5]:
            assert p not in blob, p
    assert out["stats"]["reachable"] == len(set(urls))         # still watched: availability recorded
    assert any(c.get("added") for s in out["snaps"].values() for c in s.get("changes") or [])   # a change still shows


def test_r3_p1_7_other_states_pages_are_watched_as_before(tmp_path):
    import importlib.util
    import subprocess
    from ingest import notification_pages as NP
    old_src = subprocess.run(["git", "show", "fa9fb34:pipeline/ingest/notification_pages.py"], cwd=ROOT,
                             capture_output=True, text=True)
    if old_src.returncode != 0:
        pytest.skip("the state branch's commit is not in this clone")
    f = tmp_path / "np_state_branch.py"
    f.write_text(old_src.stdout)
    spec = importlib.util.spec_from_file_location("np_state_branch", f)
    OLD = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(OLD)
    rows = [{"id": "zz-example", "state": "ZZ", "monitored": True, "urls": ["https://example.org/notices"],
             "method": "html", "records": True, "dated_lines_are_notices": True, "channel_kind": "operator_page"}]
    body = b"<html><body><p>Overflow notice</p><p>11/14/2026 Example overflow at Example Creek</p></body></html>"
    outs = []
    for mod, d in ((NP, tmp_path / "new"), (OLD, tmp_path / "old")):
        d.mkdir()
        out, saved = _np_run(mod, rows, {rows[0]["urls"][0]: body}, d, "2026-11-15T12:00:00Z")
        outs.append((json.dumps({k: out[k] for k in ("records", "snaps", "stats")}, sort_keys=True, default=str)
                     .replace(str(d), "D"), saved))
    assert outs[0] == outs[1] and outs[0][1] == [body]
