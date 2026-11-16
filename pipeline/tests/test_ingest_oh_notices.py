"""Ohio's Great Lakes CSO notices (40 CFR 122.38): Willard's HTML notices (oh_willard_cso) and Lakewood's CSO alerts
and status cards (oh_lakewood_cso). Fixtures are trimmed from the real pages: Willard's notice section of 2026-11-16
with the staff contacts removed ("Example Contact"); Lakewood's site cards as GitHub's runner read them on 2026-11-16
and as the Internet Archive captured them on 2026-05-11 (completed events) and 2026-06-16 (ongoing events). No
network."""
import json
import re
from pathlib import Path

import pytest

from ingest import oh_lakewood_cso as LW
from ingest import oh_willard_cso as WL

FIX = Path(__file__).parent / "fixtures"
NOW = "2026-11-16T20:00:00Z"
LATER = "2026-11-16T21:00:00Z"


def _ids(recs):
    return {r["source_record_id"]: r for r in recs}


# Willard ----------------------------------------------------------------------------------------------------------

WPAGE = (FIX / "oh_willard_cso.html").read_text()
SUPP_2026 = '<div class="paragraph"><em><strong><font size="5">SUPPLEMENTAL NOTIFICATION: April 2, 2026'
INIT_2025 = '<h2 class="wsite-content-title"><strong><em>INITIAL NOTIFICATION: April 6, 2025'
FORM = '<h2 class="wsite-content-title">&#8203;CSO Contact Request Form</h2>'


def _cut(page, a, b):
    i, j = page.index(a), page.index(b)
    return page[:i] + page[j:]


def test_willard_initial_and_supplemental_are_one_record(tmp_path):
    notices, unread = WL.parse(WPAGE)
    assert unread == [] and len(notices) == 4
    recs, meta = WL.run(notices, NOW, tmp_path / "s.json")
    ids = _ids(recs)
    assert sorted(ids) == ["20250405T0602", "20260401T1445"]
    r = ids["20260401T1445"]
    # "04/1/2026 2:45 pm" (initial) and "04/01/2026 2:45 pm" (supplemental) are the same start
    assert r["started_at"] == "2026-04-01T14:45:00-04:00" and r["ended_at"] == "2026-04-02T06:00:00-04:00"
    assert r["status"] == "ended" and r["time_precision"] == "minute" and r["raw"]["ended_at_precision"] == "minute"
    assert r["volume_gal"] == 7_780_000 and r["volume_text"] == "7.78 million gallons" and r["estimate_flag"] == "unknown"
    assert [n["kind"] for n in r["raw"]["notices"]] == ["initial", "supplemental"]
    assert [n["notice_date"] for n in r["raw"]["notices"]] == ["2026-04-01", "2026-04-02"]
    # a notice's heading date is a publication day, never a start or a publication time
    assert r["published_at"] is None and r["reported_at"] is None and r["source_updated_at"] is None
    old = ids["20250405T0602"]
    assert old["started_at"] == "2025-04-05T06:02:00-04:00" and old["ended_at"] == "2025-04-06T04:30:00-04:00"
    assert old["raw"]["notices"][0]["notice_date"] == "2025-04-06"       # posted the day after the start
    assert old["volume_gal"] == 11_240_000 and old["raw"]["rainfall_total"] == "3.12 inches"


def test_willard_place_permit_and_named_stream_no_outfall_tie(tmp_path):
    recs, _ = WL.run(WL.parse(WPAGE)[0], NOW, tmp_path / "s.json")
    for r in recs:
        assert r["npdes_permit"] == "OH0028118" and r["discharger_name"] == "City of Willard"
        # "J</span><span>acob Creek" on the page reads as one word
        assert r["raw"]["discharge_stream"] == "Jacob Creek"
        # the stream as named, then the areas the city names as affected (Holiday Lakes places the record by name)
        assert r["waterbody_text"] == ("Jacob Creek; areas affected: West Branch of Huron River, Holiday Lakes, "
                                       "Monroeville")
        # no outfall number in the notices: no outfall, no point (never the page's address, never a guess)
        assert r["outfall_id"] is None and r["lat"] is None and r["lon"] is None and r["coord_source"] is None
        assert r["raw"]["areas_affected"] == ["West Branch of Huron River", "Holiday Lakes", "Monroeville"]
        assert r["raw"]["location"] == "City of Willard, Combined Sewer Lagoon"   # the street address dropped
        assert r["event_type"] == "cso" and r["advice_text"] is None


def test_willard_no_contact_is_kept(tmp_path):
    recs, _ = WL.run(WL.parse(WPAGE)[0], NOW, tmp_path / "s.json")
    text = json.dumps(recs) + (tmp_path / "s.json").read_text()
    assert "Example Contact" not in text and "information" not in text.lower()
    assert not re.search(r"\d{3}[ .-]\d{4}|@", text)


def test_willard_initial_only_is_ongoing_without_an_end(tmp_path):
    page = _cut(WPAGE, SUPP_2026, INIT_2025)
    recs, _ = WL.run(WL.parse(page)[0], NOW, tmp_path / "s.json")
    r = _ids(recs)["20260401T1445"]
    assert r["status"] == "ongoing" and r["ended_at"] is None and "ended_at_precision" not in r["raw"]
    assert r["volume_gal"] is None and r["started_at"] == "2026-04-01T14:45:00-04:00"


def test_willard_supplemental_on_a_later_read_revises_the_same_record(tmp_path):
    state = tmp_path / "s.json"
    WL.run(WL.parse(_cut(WPAGE, SUPP_2026, INIT_2025))[0], NOW, state)
    recs, meta = WL.run(WL.parse(WPAGE)[0], LATER, state)
    assert len(recs) == 2 and meta["notices_held"] == 4
    r = _ids(recs)["20260401T1445"]
    assert r["status"] == "ended" and r["ended_at"] == "2026-04-02T06:00:00-04:00"
    first = {n["kind"]: n for n in r["raw"]["notices"]}
    assert first["initial"]["_first_seen_at"] == NOW and first["supplemental"]["_first_seen_at"] == LATER


def test_willard_a_notice_that_leaves_the_page_stays(tmp_path):
    state = tmp_path / "s.json"
    WL.run(WL.parse(WPAGE)[0], NOW, state)
    gone = _cut(WPAGE, INIT_2025, FORM)                  # the 2025 notices taken off the page
    notices, unread = WL.parse(gone)
    assert len(notices) == 2 and unread == []
    recs, _ = WL.run(notices, LATER, state)
    old = _ids(recs)["20250405T0602"]
    assert old["status"] == "ended" and old["raw"]["_last_seen_in_source"] == NOW


def test_willard_negation_and_an_end_without_a_time(tmp_path):
    assert WL.said_active("not active the CSO event has ended") is False
    assert WL.said_active("active") is True and WL.said_active("inactive") is False
    page = WPAGE.replace("Date and Time CSO ended:</span>", "Date and Time CSO ended (pending):</span>")
    page = re.sub(r"Date and Time CSO ended:.*?6:00 am", "", page, flags=re.S)
    recs, _ = WL.run(WL.parse(page)[0], NOW, tmp_path / "s.json")
    r = _ids(recs)["20260401T1445"]
    assert r["ended_at"] is None and r["status"] == "unknown" and "end not confirmed" in r["raw"]["end_note"]


def test_willard_local_times_midnight_and_daylight_changes():
    assert WL.local("11/01/2026 1:30 am").isoformat() == "2026-11-01T01:30:00-04:00"     # repeated hour: the first
    assert WL.local("03/08/2026 3:15 am").isoformat() == "2026-03-08T03:15:00-04:00"
    assert WL.local("03/07/2026 11:59 pm").isoformat() == "2026-03-07T23:59:00-05:00"
    assert WL.local("04/1/2026 12:05 am").isoformat() == "2026-04-01T00:05:00-04:00"
    assert WL.local("04/1/2026 12:05 pm").isoformat() == "2026-04-01T12:05:00-04:00"
    assert WL.local("April 1") is None


def test_willard_unreadable_notice_is_partial_and_named(tmp_path):
    page = WPAGE.replace("04/1/2026", "the afternoon of the first")     # the 2026 initial notice: no start
    page = page.replace("SUPPLEMENTAL NOTIFICATION: April 7, 2025", "UPDATED NOTIFICATION: April 7, 2025")
    notices, unread = WL.parse(page)
    assert len(notices) == 2 and len(unread) == 2
    assert any("no start" in u for u in unread) and any("UPDATED NOTIFICATION" in u for u in unread)
    f = tmp_path / "p.html"
    f.write_text(page)
    out = tmp_path / "e.json"
    assert WL.main(["--file", str(f), "--out", str(out)]) == 1
    d = json.loads(out.read_text())
    assert d["ok"] is False and "no start" in d["error"] and d["count"] == 2      # readable ones published


def test_willard_layout_change_fails_and_keeps_the_records(tmp_path):
    f, out = tmp_path / "p.html", tmp_path / "e.json"
    f.write_text(WPAGE)
    assert WL.main(["--file", str(f), "--out", str(out)]) == 0
    assert json.loads(out.read_text())["count"] == 2
    f.write_text(WPAGE.replace("PUBLIC NOTIFICATION", "Public notices"))      # the section's title changed
    assert WL.main(["--file", str(f), "--out", str(out)]) == 1
    d = json.loads(out.read_text())
    assert d["ok"] is False and d["count"] == 2 and "section" in d["error"]


def test_willard_empty_section_needs_the_none_sentence(tmp_path):
    empty = _cut(WPAGE, '<h2 class="wsite-content-title"><strong><em>INITIAL NOTIFICATION:&nbsp; April 1, 2026', FORM)
    assert WL.parse(empty) == ([], [])                             # the city's "none at this time" sentence
    with pytest.raises(WL.LayoutError):
        WL.parse(empty.replace("There are currently none at this time.", ""))
    state = tmp_path / "s.json"
    WL.run(WL.parse(WPAGE)[0], NOW, state)
    recs, _ = WL.run([], LATER, state)                             # an empty list never drops a past report
    assert len(recs) == 2


# Lakewood ---------------------------------------------------------------------------------------------------------

LIVE = (FIX / "oh_lakewood_cso_live.html").read_text()
ONGOING = (FIX / "oh_lakewood_cso_ongoing.html").read_text()
COMPLETED = (FIX / "oh_lakewood_cso_completed.html").read_text()
REGISTRY = [  # the registry rows of OH0026018 as data/outfalls-oh.json and data/outfalls-us.json give them (trimmed)
    {"npdes_permit": "OH0026018", "outfall": "052", "outfall_status": "CSO", "outfall_kind": "cso",
     "coords_from": "permitted_feature", "lat": 41.47806, "lon": -81.82333, "water_name": "Rocky River"},
    {"npdes_permit": "OH0026018", "outfall": "055", "outfall_status": "CSO", "outfall_kind": "cso",
     "coords_from": "permitted_feature", "lat": 41.49389, "lon": -81.81222, "water_name": "Lake Erie"},
    {"npdes_permit": "OH0026018", "outfall": "056", "outfall_status": "CSO", "outfall_kind": "cso",
     "coords_from": "permitted_feature", "lat": 41.49528, "lon": -81.80528, "water_name": "Lake Erie"},
    {"npdes_permit": "OH0026018", "outfall": "059", "outfall_status": "CSO", "outfall_kind": "cso",
     "coords_from": "permitted_feature", "lat": 41.49306, "lon": -81.78194, "water_name": "Lake Erie"},
    {"npdes_permit": "OH0026018", "outfall": "054", "outfall_status": "CLS", "outfall_kind": "cso",
     "coords_from": "facility", "lat": 41.47838, "lon": -81.82545},
    {"npdes_permit": "OH0026018", "outfall": "001", "outfall_kind": "plant", "coords_from": "permitted_feature",
     "lat": 41.47908, "lon": -81.8249},
]


def _poll(page, now, state):
    cards, unread = LW.parse(page)
    assert unread == []
    return LW.run(cards, now, state, registry=REGISTRY)


def _card(page, site):
    i = page.index(f'>{site}</h4>')
    a = page.rindex('<div class="modal fade"', 0, i)
    b = page.find('<div class="modal fade"', i)
    return a, (b if b >= 0 else page.index("</main>"))


def _swap_card(page, site, other_page):
    a, b = _card(page, site)
    c, d = _card(other_page, site)
    return page[:a] + other_page[c:d] + page[b:]


def test_lakewood_completed_cards(tmp_path):
    cards, unread = LW.parse(COMPLETED)
    assert unread == [] and len(cards) == 24
    recs, meta = LW.run(cards, "2026-05-11T11:42:17Z", tmp_path / "s.json", registry=REGISTRY)
    ids = _ids(recs)
    r = ids["cso-052:20260509T1740"]
    assert r["started_at"] == "2026-05-09T17:40:00-04:00" and r["ended_at"] == "2026-05-09T19:10:00-04:00"
    assert r["status"] == "ended" and r["raw"]["ended_at_precision"] == "minute"
    assert r["volume_gal"] == 77_000 and r["volume_text"] == "0.077 million gallons" and r["estimate_flag"] == "unknown"
    assert r["waterbody_text"] == "Rocky River" and r["raw"]["discharge_location"] == "West end of Fries Ave."
    assert r["source_updated_at"] == "2026-05-11T04:00:00-04:00" and r["published_at"] is None
    # CSO-052 is registry outfall 052: its point from the registry, never the page's marker
    assert r["outfall_id"] == "052" and (r["lat"], r["lon"]) == (41.47806, -81.82333)
    assert r["coord_source"] == "outfall_layer"
    # CSO-056B is not outfall 056, and a LEWS meter is no registry outfall: no tie, no point
    b = ids["cso-056b:20260509T1740"]
    assert b["outfall_id"] is None and b["lat"] is None and b["outfall_name"] == "CSO-056B"
    m = ids["lews-1040:20260509T1745"]
    assert m["outfall_id"] is None and m["lat"] is None and m["volume_gal"] == 2_000


def test_lakewood_ongoing_then_completed_is_one_record(tmp_path):
    state = tmp_path / "s.json"
    recs, _ = _poll(ONGOING, "2026-06-16T05:47:49Z", state)
    r = _ids(recs)["cso-052:20260615T1220"]
    assert r["status"] == "ongoing" and r["ended_at"] is None and r["volume_gal"] is None
    a, b = _card(ONGOING, "CSO-052")
    card = ONGOING[a:b].replace("<td>Ongoing</td>", "<td>Completed</td>")
    card = re.sub(r"(<td>6/15/2026 12:20 PM</td></tr>)",
                  r'\1<tr><td class="text-right font-weight-bold">Event end</td><td>6/15/2026 9:05 PM</td></tr>'
                  r'<tr><td class="text-right font-weight-bold">Total CSO event volume</td><td>1.234 million gallons</td></tr>',
                  card)
    done = ONGOING[:a] + card + ONGOING[b:]
    assert done != ONGOING
    recs, _ = _poll(done, "2026-06-16T06:47:49Z", state)
    same = [x for x in recs if x["outfall_name"] == "CSO-052"]
    assert len(same) == 1 and same[0]["status"] == "ended" and same[0]["ended_at"] == "2026-06-15T21:05:00-04:00"
    assert same[0]["volume_gal"] == 1_234_000


def test_lakewood_unknown_after_ongoing_is_end_not_confirmed(tmp_path):
    state = tmp_path / "s.json"
    _poll(ONGOING, "2026-06-16T05:47:49Z", state)
    recs, _ = _poll(_swap_card(ONGOING, "CSO-059", LIVE), "2026-06-16T06:47:49Z", state)   # CSO-059 now Unknown
    r = _ids(recs)["cso-059:20260615T1750"]
    assert r["status"] == "unknown" and r["ended_at"] is None and "end not confirmed" in r["raw"]["end_note"]


def test_lakewood_last_ended_within_48_hours_bounds_the_open_event(tmp_path):
    state = tmp_path / "s.json"
    _poll(ONGOING, "2026-06-16T05:47:49Z", state)
    green = _swap_card(ONGOING, "CSO-052", LIVE).replace("11/12/2026 7:10 PM", "6/16/2026 1:10 AM")
    recs, _ = _poll(green, "2026-06-16T06:47:49Z", state)
    r = _ids(recs)["cso-052:20260615T1220"]
    assert r["ended_at"] == "2026-06-16T01:10:00-04:00" and r["raw"]["ended_at_precision"] == "bound"
    assert "at or before" in r["raw"]["_end_basis"] and r["volume_gal"] is None
    assert not any(k.startswith("cso-052:end:") for k in _ids(recs))     # the same event, not a second record


def test_lakewood_a_late_bound_is_not_an_end(tmp_path):
    state = tmp_path / "s.json"
    _poll(ONGOING, "2026-06-16T05:47:49Z", state)
    recs, _ = _poll(LIVE, NOW, state)          # five months later: CSO-052's last event ended 11/12/2026 7:10 PM
    ids = _ids(recs)
    r = ids["cso-052:20260615T1220"]
    assert r["ended_at"] is None and r["status"] == "unknown" and r["raw"]["later_bound"]["at"].startswith("2026-11-12")
    e = ids["cso-052:end:20261112T1910"]                  # that last end is its own, start-less record
    assert e["started_at"] is None and e["ended_at"] == "2026-11-12T19:10:00-05:00" and e["status"] == "ended"
    assert "no start" in e["raw"]["start_note"]


def test_lakewood_newer_start_bounds_an_earlier_open_event_only_within_48_hours(tmp_path):
    state = tmp_path / "s.json"
    _poll(ONGOING, "2026-06-16T05:47:49Z", state)
    newer = ONGOING.replace("6/15/2026 12:20 PM", "6/16/2026 3:00 PM")
    recs, _ = _poll(newer, "2026-06-16T19:10:00Z", state)
    ids = _ids(recs)
    old = ids["cso-052:20260615T1220"]
    assert old["ended_at"] == "2026-06-16T15:00:00-04:00" and old["raw"]["ended_at_precision"] == "bound"
    assert ids["cso-052:20260616T1500"]["status"] == "ongoing"


def test_lakewood_first_read_of_the_live_page(tmp_path):
    recs, meta = _poll(LIVE, NOW, tmp_path / "s.json")
    ids = _ids(recs)
    # the green cards' "Last event ended" only; the white (unknown) cards make nothing
    assert sorted(ids) == ["cso-002:end:20260823T1920", "cso-052:end:20261112T1910", "cso-057:end:20250402T1125",
                           "lews-1130:end:20250728T1845"]
    for r in recs:
        assert r["started_at"] is None and r["status"] == "ended" and r["volume_gal"] is None
    assert ids["cso-052:end:20261112T1910"]["outfall_id"] == "052"
    # a second read confirms the same ends and adds nothing
    recs2, meta2 = _poll(LIVE, LATER, tmp_path / "s.json")
    assert sorted(_ids(recs2)) == sorted(ids) and meta2["poll"]["end_only"] == 0


def test_lakewood_end_revision_is_kept(tmp_path):
    state = tmp_path / "s.json"
    _poll(COMPLETED, "2026-05-11T11:42:17Z", state)
    recs, _ = _poll(COMPLETED.replace("5/9/2026 7:10 PM", "5/9/2026 7:25 PM"), "2026-05-11T12:42:17Z", state)
    r = _ids(recs)["cso-052:20260509T1740"]
    assert r["ended_at"] == "2026-05-09T19:25:00-04:00"
    assert r["raw"]["end_revisions"][0]["end"] == "2026-05-09T19:10:00-04:00"


def test_lakewood_unknown_card_is_partial_and_no_card_is_a_failure(tmp_path):
    odd = COMPLETED.replace(">Total CSO event volume<", ">Estimated volume<", 1)
    cards, unread = LW.parse(odd)
    assert len(cards) == 23 and len(unread) == 1 and "Estimated volume" in unread[0]
    odd2 = LIVE.replace("<td>Overflow not active</td>", "<td>Overflow active</td>", 1)
    assert len(LW.parse(odd2)[1]) == 1
    with pytest.raises(LW.LayoutError):
        LW.parse("<html><body>Service unavailable</body></html>")
    f, out = tmp_path / "p.html", tmp_path / "e.json"
    f.write_text(COMPLETED)
    assert LW.main(["--file", str(f), "--out", str(out)]) == 0
    n = json.loads(out.read_text())["count"]
    f.write_text("<html><body>Service unavailable</body></html>")
    assert LW.main(["--file", str(f), "--out", str(out)]) == 1
    d = json.loads(out.read_text())
    assert d["ok"] is False and d["count"] == n
    f.write_text(odd)
    assert LW.main(["--file", str(f), "--out", str(out)]) == 1
    d = json.loads(out.read_text())
    assert d["ok"] is False and "Estimated volume" in d["error"] and d["count"] == n


def test_lakewood_location_house_number_removed(tmp_path):
    page = COMPLETED.replace("West end of Fries Ave.", "Behind 1234 Fries Ave.")
    recs, _ = _poll(page, NOW, tmp_path / "s.json")
    loc = _ids(recs)["cso-052:20260509T1740"]["raw"]["discharge_location"]
    assert "1234" not in loc and "Fries Ave." in loc


def test_lakewood_local_times():
    assert LW.local("11/1/2026 1:30 AM").isoformat() == "2026-11-01T01:30:00-04:00"
    assert LW.local("3/8/2026 3:15 AM").isoformat() == "2026-03-08T03:15:00-04:00"
    assert LW.local("6/15/2026 12:20 PM").isoformat() == "2026-06-15T12:20:00-04:00"
    assert LW.local("6/15/2026 12:20 AM").isoformat() == "2026-06-15T00:20:00-04:00"
    assert LW.local("Unknown") is None


def test_no_backfill_flag():
    for mod in (WL, LW):
        with pytest.raises(SystemExit):
            mod.main(["--backfill"])


def test_lakewood_card_water_unlike_the_registry_ties_nothing(tmp_path):
    a, b = _card(COMPLETED, "CSO-052")
    page = COMPLETED[:a] + COMPLETED[a:b].replace("<td>Rocky River</td>", "<td>Lake Erie</td>") + COMPLETED[b:]
    recs, _ = _poll(page, NOW, tmp_path / "s.json")
    r = _ids(recs)["cso-052:20260509T1740"]
    assert r["outfall_id"] is None and r["lat"] is None and r["waterbody_text"] == "Lake Erie"
    assert "Rocky River" in r["raw"]["place_basis"]


def test_lakewood_start_less_record_takes_the_sites_named_water(tmp_path):
    state = tmp_path / "s.json"
    _poll(COMPLETED, "2026-05-11T11:42:17Z", state)
    recs, _ = _poll(LIVE, NOW, state)
    ids = _ids(recs)
    e = ids["cso-052:end:20261112T1910"]
    assert e["waterbody_text"] == "Rocky River" and "same site" in e["raw"]["water_basis"]
    assert ids["lews-1130:end:20250728T1845"]["waterbody_text"] is None       # never named for that site
