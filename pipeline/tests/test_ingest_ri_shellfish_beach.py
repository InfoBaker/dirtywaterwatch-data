"""Rhode Island: DEM's shellfish closure table (ingest/ri_dem_shellfish.py) and RIDOH's beach advisory feed
(ingest/ri_ridoh_beach_feed.py).

Fixtures, all public pages with no person named:
- ri_dem_shellfish_2026-11-16.html: the page the pipeline's runner read on 2026-11-16 (runner probe 43877571236),
  trimmed to the closures card up to its table, the footnote's first sentence and two rows of the growing-area table
  (the contact paragraph is not kept).
- ri_ridoh_beach_feed_2026-11-16.html: the feed page the runner read the same day, its list and 25 items as served.
- ri_ridohgis_beaches_view_2026-11-16.json: RIDOH's beach layer (points and master list, five fields) in the cache
  form ingest.ri_ridoh_beaches keeps; ri_ridoh_beaches_current_2026-11-16.csv: the sheet's current tab of that day.
Variants below are edited copies; invented text is marked so.
"""
import csv
import io
import json
import re
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from ingest import ri_dem_shellfish as D
from ingest import ri_ridoh_beach_feed as F
from ingest import ri_ridoh_beaches as R

FIX = Path(__file__).parent / "fixtures"
PAGE = (FIX / "ri_dem_shellfish_2026-11-16.html").read_text()
FEED = (FIX / "ri_ridoh_beach_feed_2026-11-16.html").read_text()
T1, T2, T3 = "2026-11-16T14:00:00Z", "2026-11-16T15:00:00Z", "2026-11-17T15:00:00Z"
ROOT = Path(__file__).resolve().parents[2]


def by_codes(recs):
    return {tuple(r["raw"]["area_codes"]): r for r in recs}


def drop_row(page, text):
    m = re.search(r"<tr>\s*<td>(?:(?!</tr>).)*?" + re.escape(text) + r".*?</tr>", page, re.S)
    assert m, text
    return page[:m.start()] + page[m.end():]


# ================================================================ DEM shellfish closures

def test_every_row_of_the_runners_page_is_a_closure_record():
    recs, meta = D.build(PAGE, T1, [])
    got = sorted((r["waterbody_text"], tuple(r["raw"]["area_codes"]), r["water_slugs"][0], r["lat"], r["lon"],
                  r["raw"]["scheduled_reopen"]["text"]) for r in recs)
    assert got == sorted([
        ("Upper Bay Conditional Area (Area 1A)", ("1A",), "narragansett-bay-ri", 41.7, -71.329, "Noon 11/14"),
        ("Lower Providence River Conditional Area (Area 16E)", ("16E",), "providence-river-ri", 41.731, -71.365,
         "Noon 11/14"),
        ("Greenwich Bay Area (Areas 8A, 8C)", ("8A", "8C"), "narragansett-bay-ri", 41.676, -71.418, "Noon 11/14"),
        ("Mount Hope Bay (Area 17)", ("17",), "mount-hope-bay-ri", 41.678, -71.231, "Noon 11/14"),
        ("Kickemuit River (Area 5)", ("5",), "mount-hope-bay-ri", 41.708, -71.247, "Noon 11/14"),
        ("Pt Judith Pond Conditional Areas (Areas 10PJ-N, 10PJ-E)", ("10PJ-N", "10PJ-E"), "point-judith-pond-ri",
         41.412, -71.504, "Noon 11/14")])
    assert meta["closed"] == 6 and meta["open"] == 0 and meta["unread"] == [] and meta["table_updated"] == "2026-11-07"
    assert meta["rain_totals_text"] == 'Closure rain totals: TF Green Airport = 2.73", Taunton = 3.12", Westerly = 2.58"'
    for r in recs:
        assert r["event_type"] == "shellfish_closure" and r["status"] == "advisory_active" and r["ended_at"] is None
        # no start is invented: the first read, at poll precision; DEM's Updated date is the publication only
        assert r["started_at"] == T1 and r["time_precision"] == "poll" and r["raw"]["start_basis"] == D.START_BASIS
        assert r["published_at"] == "2026-11-07" and r["source_updated_at"] == "2026-11-07" and r["fetched_at"] == T1
        assert r["raw"]["status_text"] == "CLOSED" and r["raw"]["reason"] is None
        assert r["raw"]["_point_extent_only"] is True and r["raw"]["_poll_confirmed"] is True
        assert r["raw"]["scheduled_reopen"]["at"] == "2026-11-14T12:00:00-05:00"
        assert r["raw"]["scheduled_reopen_passed"] is True and "not a confirmed reopening" in r["advice_text"]
        assert "safe" not in json.dumps(r).lower()
    assert by_codes(recs)[("16E",)]["raw"]["footnote_mark"] is True
    assert by_codes(recs)[("1A",)]["raw"]["footnote_mark"] is False


def test_a_scheduled_reopening_is_never_an_end():
    first, _ = D.build(PAGE, "2026-11-12T14:00:00Z", [])
    a = by_codes(first)[("1A",)]
    assert a["raw"]["scheduled_reopen_passed"] is False and "scheduled_reopen_note" not in a["raw"]
    later, _ = D.build(PAGE, "2026-11-20T14:00:00Z", first)       # still listed CLOSED after noon 11/14
    b = by_codes(later)[("1A",)]
    assert b["event_id"] == a["event_id"] and b["status"] == "advisory_active" and b["ended_at"] is None
    assert b["started_at"] == "2026-11-12T14:00:00Z" and b["raw"]["scheduled_reopen_passed"] is True
    assert "still lists the area CLOSED" in b["raw"]["scheduled_reopen_note"]
    assert D.scheduled("Sunrise 11/14", date(2026, 11, 7)) == {"text": "Sunrise 11/14", "basis": D.REOPEN_BASIS}
    assert D.scheduled("1/3", date(2026, 11, 7))["at"] == "2027-01-03"
    assert D.scheduled("", date(2026, 11, 7))["text"] is None


def test_a_closure_that_leaves_a_complete_read_ends_there_and_a_return_is_a_new_record():
    prev, _ = D.build(PAGE, T1, [])
    gone = edit(drop_row(PAGE, "Mount Hope Bay (Area 17)"), "Updated 11/7/2026", "Updated 11/16/2026")
    opened = gone.replace('<h5 class="text-align-center">CLOSED</h5>\n</td>\n<td>\n<h5 class="text-align-center">Noon 11/14</h5>',
                          '<h5 class="text-align-center">OPEN</h5>\n</td>\n<td>\n<h5 class="text-align-center"></h5>', 1)
    recs, meta = D.build(opened, T2, prev)
    mh, ub = by_codes(recs)[("17",)], by_codes(recs)[("1A",)]
    assert mh["status"] == "advisory_lifted" and mh["ended_at"] == T2 and mh["raw"]["ended_at_precision"] == "poll"
    assert mh["raw"]["end_basis"] == D.END_BASIS and mh["raw"]["end_seen_as"] == "no longer listed"
    assert ub["status"] == "advisory_lifted" and ub["raw"]["end_seen_as"] == "listed OPEN"
    assert meta["open"] == 1 and meta["lifted_this_read"] == 2
    back, _ = D.build(PAGE, T3, recs)
    mhs = [r for r in back if r["raw"]["area_codes"] == ["17"]]
    assert len(mhs) == 2 and len({r["event_id"] for r in mhs}) == 2
    new = next(r for r in mhs if r["status"] == "advisory_active")
    assert new["started_at"] == T3 and next(r for r in mhs if r["status"] == "advisory_lifted")["ended_at"] == T2


@pytest.mark.parametrize("bad", [
    PAGE.replace("</html>", ""),                                                           # truncated
    PAGE.replace("Pollution-Related Conditional Area", "Pollution Closures"),                # heading renamed
    PAGE.replace("Updated 11/7/2026", "Revised 11/7/2026"),                                 # no Updated line
    PAGE.replace("Updated 11/7/2026", "Updated 11/30/2026"),                                # after the read
    PAGE.replace("Scheduled to Reopen</h3>", "Reopening</h3>"),                             # headings changed
    PAGE.replace("Status</h3>", "Condition</h3>"),
    PAGE.replace("</tbody>\n</table>\n<p>*Please", "</tbody>\n<p>*Please", 1).replace("</table>", "", 1),  # table cut
    PAGE.replace("<td>\n<h5 class=\"text-align-center\">Noon 11/14</h5>\n</td>", "", 1),    # a row of two cells
    re.sub(r"<tbody>.*?</tbody>", "<tbody></tbody>", PAGE, count=1, flags=re.S),           # no row
    "<html><body>Just a moment...</body></html>",                                          # a challenge page
    "",
])
def test_a_page_not_read_whole_raises(bad):
    with pytest.raises(ValueError):
        D.parse(bad, T1)


def test_negation_and_unknown_status_words_are_not_closures():
    page = edit(PAGE, '<h5 class="text-align-center">CLOSED</h5>', '<h5 class="text-align-center">NOT CLOSED</h5>')
    recs, meta = D.build(page, T1, [])
    assert [u["reason"] for u in meta["unread"]] == ["a status the reader does not take (not CLOSED or OPEN)"]
    assert ("1A",) not in by_codes(recs) and len(recs) == 5
    page = edit(PAGE, '<h5 class="text-align-center">CLOSED</h5>',
                        '<h5 class="text-align-center">CLOSED - emergency</h5>')                # invented wording
    assert by_codes(D.build(page, T1, [])[0])[("1A",)]["raw"]["status_text"] == "CLOSED - emergency"


def test_an_area_with_no_outline_is_listed_and_placed_on_no_water():
    page = edit(PAGE, "Kickemuit River</strong></a> (Area 5)",
                        "Bristol Harbor emergency closure</strong></a> (Area 3X)")                 # invented row
    r = by_codes(D.build(page, T1, [])[0])[("3X",)]
    assert r["raw"]["_placement"] == "listed_only" and r["water_slugs"] == [] and r["lat"] is None
    page = edit(PAGE, "Kickemuit River</strong></a> (Area 5)", "Kickemuit River</strong></a>")    # no code at all
    r = next(x for x in D.build(page, T1, [])[0] if x["waterbody_text"] == "Kickemuit River")
    assert r["raw"]["_placement"] == "listed_only" and r["raw"]["area_codes"] == []
    assert r["raw"]["area_key"] == "kickemuit-river"


def test_ids_do_not_depend_on_row_order():
    a, _ = D.build(PAGE, T1, [])
    rows = re.search(r"<tbody>(.*?)</tbody>", PAGE, re.S).group(1)
    trs = re.findall(r"<tr>.*?</tr>", rows, re.S)
    swapped = PAGE.replace(rows, "\n" + "\n".join(reversed(trs)) + "\n", 1)
    b, _ = D.build(swapped, T1, [])
    assert {r["event_id"] for r in a} == {r["event_id"] for r in b}


class _Resp:
    def __init__(self, text):
        self.text, self.headers, self.status_code = text, {}, 200

    def raise_for_status(self):
        return None


@pytest.fixture
def run_dem(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(D, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    saved = []
    monkeypatch.setattr(D, "save_raw", lambda src, body, ext: saved.append((ext, body)) or tmp_path / "raw")

    def go(page, stamp):
        monkeypatch.setattr(D, "now_iso", lambda: stamp)
        monkeypatch.setattr(D.requests, "get", lambda *a, **k: _Resp(page))
        code = D.main([])
        return code, json.loads((tmp_path / f"{D.SOURCE_ID}.json").read_text())
    go.saved = saved
    return go


def test_a_failed_read_keeps_every_closure_and_fails_health(run_dem):
    code, doc = run_dem(PAGE, T1)
    assert code == 0 and doc["ok"] and len(doc["records"]) == 6
    code, doc = run_dem(PAGE.replace("Location</h3>", "Place</h3>"), T2)
    assert code == 1 and doc["ok"] is False and doc["last_ok_at"] is not None
    assert len(doc["records"]) == 6 and all(r["status"] == "advisory_active" for r in doc["records"])


def test_one_unreadable_row_holds_every_earlier_closure(run_dem):
    run_dem(PAGE, T1)
    page = drop_row(PAGE, "Mount Hope Bay (Area 17)").replace(
        '<h5 class="text-align-center">CLOSED</h5>', '<h5 class="text-align-center">PENDING</h5>', 1)   # invented
    code, doc = run_dem(page, T2)
    assert code == 1 and doc["ok"] is False and [u["reason"] for u in doc["meta"]["unread"]] == [
        "a status the reader does not take (not CLOSED or OPEN)",
        "a closed area is missing from a table with the same Updated date"]
    by = by_codes(doc["records"])
    assert by[("17",)]["status"] == "advisory_active" and by[("17",)]["raw"]["_held_unread"]       # absent, held
    assert by[("1A",)]["status"] == "advisory_active" and by[("1A",)]["raw"]["_held_unread"]       # unread, held
    assert by[("5",)]["raw"]["_last_seen_in_source"] == T2                                       # readable, updated


PRIVATE = ("Pat Example", "401-555-0100", "pat@example.org", "1234-A Example St")


def test_nothing_personal_reaches_any_save(run_dem):
    page = edit(PAGE, "Kickemuit River</strong></a> (Area 5)",
                        "Kickemuit River near the home of Pat Example, 1234-A Example St</strong></a> (Area 5)")
    page = edit(page, "Westerly = 2.58\"", "Westerly = 2.58\" Call Pat Example at 401-555-0100 or pat@example.org.")
    code, doc = run_dem(page, T1)
    assert code == 0
    blob = json.dumps(doc) + json.dumps(run_dem.saved)
    for p in PRIVATE:
        assert p in blob, p
    assert len(run_dem.saved) == 1 and run_dem.saved[0][0] == "json" and "<" not in run_dem.saved[0][1]
    # the refused read's path cleans carried records again
    bad = dict(doc)
    bad["records"] = [dict(r, advice_text=r["advice_text"] + " Call Pat Example at 401-555-0100.") for r in doc["records"]]
    Path(D.EVENTS_DIR / f"{D.SOURCE_ID}.json").write_text(json.dumps(bad))
    code, doc = run_dem("", T2)
    assert code == 1 and "Pat Example" in json.dumps(doc) and "401-555-0100" in json.dumps(doc)


# ---- the status build: one marker in the area, the water never coloured whole ----------------------------------

@pytest.fixture(scope="module")
def ri_waters_real():
    from build import status as S
    allw = S.load_waters()
    return S, {k: allw[k] for k in ("narragansett-bay-ri", "mount-hope-bay-ri", "point-judith-pond-ri",
                                     "providence-river-ri")}


def _status(S, tmp_path, files, waters, now=datetime(2026, 11, 16, 15, 0, tzinfo=UTC), name="b"):
    d = tmp_path / name
    d.mkdir()
    for sid, recs in files.items():
        (d / f"{sid}.json").write_text(json.dumps({"source_id": sid, "ok": True, "records": recs,
                                                   "fetched_at": iso(now), "last_ok_at": iso(now)}))
    st, _ = S.build(now=now, events_dir=d, write=False, waters=waters, outfalls=[], placement_cache=False, reaches={},
                    flows=({}, {}), discharger_towns={}, discharger_waters={})
    return st


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_each_closure_is_one_red_marker_and_no_water_is_coloured_whole(ri_waters_real, tmp_path):
    S, waters = ri_waters_real
    assert waters["point-judith-pond-ri"]["kind"] == "lake" and waters["point-judith-pond-ri"]["area_km2"] < 50
    recs, _ = D.build(PAGE, T1, [])
    st = _status(S, tmp_path, {D.SOURCE_ID: recs}, waters)
    for slug in waters:
        assert st["waters"][slug]["status"] != "red", slug          # a part of the water never colours it whole
    pts = {p["event_id"]: p for p in st["advisory_points"]}
    assert set(pts) == {r["event_id"] for r in recs}                   # one marker per closure
    for r in recs:
        assert pts[r["event_id"]]["status"] == "red" and pts[r["event_id"]]["water_slugs"] == r["water_slugs"]
        assert st["placements"][r["event_id"]]["water_slugs"] == r["water_slugs"]
    assert {e for e in st["waters"]["point-judith-pond-ri"]["events"]} == {by_codes(recs)[("10PJ-N", "10PJ-E")]["event_id"]}


def test_listed_only_closures_are_not_placed_by_name_or_point(ri_waters_real):
    S, waters = ri_waters_real
    page = edit(PAGE, "Kickemuit River</strong></a> (Area 5)", "Mount Hope Bay emergency</strong></a> (Area 3X)")
    r = by_codes(D.build(page, T1, [])[0])[("3X",)]
    pl = S.Resolver(waters, [], placement_rules={}).resolve(r)
    assert pl["water_slugs"] == [] and pl["unplaced_reason"] == S.LISTED_ONLY_WHY      # never on Mount Hope Bay by name


def test_an_end_seen_late_never_colours_the_unread_time(ri_waters_real):
    S, _ = ri_waters_real
    recs, _ = D.build(PAGE, T1, [])
    r = by_codes(recs)[("17",)]
    late = "2027-01-05T15:00:00Z"                                    # unread for weeks, then no longer listed
    lifted, _ = D.build(edit(drop_row(PAGE, "Mount Hope Bay (Area 17)"), "Updated 11/7/2026", "Updated 1/5/2027"),
                        late, recs)
    r = by_codes(lifted)[("17",)]
    assert r["ended_at"] == late and r["raw"]["_last_seen_in_source"] == T1
    now = S.parse_time(late) + timedelta(days=1)
    ivs = S.event_intervals(r, "RI", now, None, S.load_rules())
    red = [iv for iv in ivs if iv.get("rule") == "advisory_active"]
    assert red and max(S.parse_time(iv["end"]) if isinstance(iv["end"], str) else iv["end"] for iv in red) \
        <= S.parse_time(T1) + timedelta(days=S.CONFIRM_DAYS)


# ================================================================ RIDOH beach feed

def _beaches(tmp_path, monkeypatch):
    cache = json.loads((FIX / "ri_ridohgis_beaches_view_2026-11-16.json").read_text())
    cache["fetched_at"] = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    p = tmp_path / "bv.json"
    p.write_text(json.dumps(cache))
    monkeypatch.setattr(R, "BV_CACHE", p)
    return R.load_beaches(None)


@pytest.fixture
def beaches(tmp_path, monkeypatch):
    return _beaches(tmp_path, monkeypatch)


def _sheet(beaches):
    rows = list(csv.reader(io.StringIO((FIX / "ri_ridoh_beaches_current_2026-11-16.csv").read_text())))
    head = [h.strip() for h in rows[0]]
    items = [{"sheet": "current", "row": n, "cells": dict(zip(head, r))} for n, r in enumerate(rows[1:], start=2)]
    return [R.row_to_record(it, "u", beaches, date(2026, 11, 16), T1) for it in items]


def edit(page, old, new):
    """page with old replaced once; old must be there, so no variant is the unchanged page."""
    assert old in page, old
    return page.replace(old, new, 1)


def feed_key(r):
    return (r["raw"]["beach"], r["raw"]["town"], r["started_at"])


def test_every_item_on_the_runners_feed_page(beaches):
    sheet = _sheet(beaches)
    recs, meta = F.build(FEED, T1, [], sheet, beaches)
    assert meta["on_page"] == 25 and meta["items_read"] == 22 and meta["notices"] == 3 and meta["unread"] == []
    assert meta["closing_items"] == 9 and meta["reopening_items"] == 13 and meta["unmatched_reopenings"] == []
    got = sorted((r["raw"]["beach"], r["raw"]["town"], r["started_at"], r["ended_at"]) for r in recs)
    assert got == sorted([
        ("Easton’s Beach", "Newport", "2026-05-29T19:11:34Z", "2026-06-01T16:02:24Z"),
        ("Easton’s Beach", "Newport", "2026-06-16T19:53:23Z", "2026-06-18T19:34:39Z"),
        ("Oakland Beach", "Warwick", "2026-06-16T19:53:23Z", "2026-06-25T19:52:23Z"),
        ("Briar Point Beach", "Coventry", "2026-06-16T19:53:23Z", "2026-06-18T19:34:39Z"),
        ("Mackerel Cove Beach", "Jamestown", "2026-06-24T19:52:24Z", "2026-06-26T13:34:10Z"),
        ("Hazards Beach", "Newport", "2026-06-24T19:52:24Z", "2026-06-27T12:33:37Z"),
        ("Gooseberry Beach", "Newport", "2026-06-24T19:52:24Z", "2026-06-27T12:33:37Z"),
        ("Fogland Beach", "Tiverton", "2026-06-24T19:52:24Z", "2026-06-26T20:27:43Z"),
        ("Grinnell's Beach", "Tiverton", "2026-06-24T19:52:24Z", "2026-06-26T20:27:43Z"),
        ("City Park Beach", "Warwick", "2026-07-08T20:14:47Z", "2026-07-10T20:48:05Z"),
        ("Third Beach", "Middletown", "2026-07-08T20:14:47Z", "2026-07-10T20:48:05Z"),
        ("Sandy Point Beach", "Portsmouth", "2026-07-08T20:14:47Z", "2026-07-09T20:16:59Z"),
        ("Georgiaville Pond Beach", "Smithfield", "2026-07-21T19:03:07Z", "2026-07-24T19:02:43Z"),
        ("Sandy Point Beach", "Portsmouth", "2026-07-23T18:49:26Z", "2026-07-24T19:02:43Z"),
        ("Bristol Town Beach", "Bristol", "2026-07-23T18:49:26Z", "2026-07-24T19:02:43Z"),
        ("Warren Town Beach", "Warren", "2026-07-23T18:49:26Z", "2026-07-27T14:31:07Z"),
        ("City Park Beach", "Warwick", "2026-07-23T18:49:26Z", "2026-07-28T19:02:55Z"),
        ("Oakland Beach", "Warwick", "2026-08-04T19:06:25Z", "2026-08-07T14:06:22Z"),
        ("Conimicut Beach", "Warwick", "2026-08-04T19:06:25Z", "2026-08-07T14:06:22Z"),
        ("Bristol Town Beach", "Bristol", "2026-08-12T18:49:22Z", "2026-08-14T16:33:44Z"),
        ("King Park Beach", "Newport", "2026-08-13T19:16:04Z", None)])
    for r in recs:
        assert r["event_type"] == "beach_closure" and r["raw"]["reason"] == "high bacteria counts"
        assert r["time_precision"] == "minute" and r["published_at"] == r["started_at"]
        assert r["status"] == ("advisory_lifted" if r["ended_at"] else "advisory_active")
        if r["ended_at"]:
            assert r["raw"]["ended_at_precision"] == "minute" and r["raw"]["end_basis"] == F.END_BASIS
        assert r["lat"] is not None               # the beach's point, 0.001 degree
        assert "safe" not in json.dumps(r).lower() and "222-2751" not in json.dumps(r)
        assert r["advice_text"].startswith("RIDOH recommends closing the swimming area at ")
    # one advisory, one listing: every 2026 closure is the sheet's record of the same beach and day
    assert meta["same_as_sheet"] == 21 and meta["shown_on_their_own"] == 0
    hz = next(r for r in recs if r["raw"]["beach"] == "Hazards Beach")
    assert hz["duplicate_of"] == "ri-ridoh-beaches:hazards-beach:newport:2026-06-24"
    assert hz["raw"]["same_as_sheet"]["basis"] == F.SAME_AS_SHEET and "name_basis" not in hz["raw"]
    gr = next(r for r in recs if r["raw"]["beach"] == "Grinnell's Beach")
    assert gr["duplicate_of"] == "ri-ridoh-beaches:grinelles-beach:tiverton:2026-06-24"      # the sheet's typo


def test_the_feed_shows_once_beside_the_sheet(beaches, ri_waters_real, tmp_path):
    S, _ = ri_waters_real
    sheet = _sheet(beaches)
    recs, _ = F.build(FEED, T1, [], sheet, beaches)
    st = _status(S, tmp_path, {F.SOURCE_ID: recs, R.SOURCE_ID: sheet}, {}, now=datetime(2026, 8, 13, 22, tzinfo=UTC))
    for r in recs:
        assert st["duplicates"].get(r["event_id"]) == r["duplicate_of"]
        assert r["duplicate_of"] not in st["duplicates"]


def test_without_the_sheets_record_a_closure_shows_on_its_own(beaches):
    recs, meta = F.build(FEED, T1, [], [], beaches)
    assert meta["same_as_sheet"] == 0 and all(r["duplicate_of"] is None for r in recs)
    sheet = [dict(s, started_at=s["started_at"].replace("2026-08-13", "2026-08-12")) for s in _sheet(beaches)]
    kp = next(r for r in F.build(FEED, T1, [], sheet, beaches)[0] if r["raw"]["beach"] == "King Park Beach")
    assert kp["duplicate_of"] is None                                 # another day is not evidence of the same closure


def test_negation_and_conditions_are_not_a_reopening(beaches):
    for text in ("The Rhode Island Department of Health (RIDOH) does not recommend re-opening the swimming area at "
                 "Bristol Town Beach",
                 "The Rhode Island Department of Health (RIDOH) will recommend re-opening the swimming area at Bristol "
                 "Town Beach when bacteria counts allow"):                                       # invented
        page = edit(FEED, "The Rhode Island Department of Health (RIDOH) recommends re-opening the swimming area at "
                    "Bristol Town Beach because bacteria counts have returned to safe levels.", text + ".")
        recs, meta = F.build(page, T1, [], [], beaches)
        b = [r for r in recs if r["raw"]["beach"] == "Bristol Town Beach" and r["started_at"] == "2026-08-12T18:49:22Z"]
        assert b[0]["status"] == "advisory_active" and b[0]["ended_at"] is None
        assert [u["reason"] for u in meta["unread"]] == ["an item about an advisory in a form the reader does not take"]


def test_a_season_notice_ends_nothing_and_a_reissue_is_a_new_record(beaches):
    recs, _ = F.build(FEED, T1, [], [], beaches)
    kp = [r for r in recs if r["raw"]["beach"] == "King Park Beach"]
    assert len(kp) == 1 and kp[0]["status"] == "advisory_active"         # "Beach Monitoring ... Has Ended" ends nothing
    sp = [r for r in recs if r["raw"]["beach"] == "Sandy Point Beach"]
    assert len(sp) == 2 and len({r["event_id"] for r in sp}) == 2


def test_a_rerun_and_an_item_scrolled_off_keep_ids_and_ends(beaches):
    first, _ = F.build(FEED, T1, [], [], beaches)
    again, meta = F.build(FEED, T2, first, [], beaches)
    assert {r["event_id"]: (r["status"], r["ended_at"]) for r in first} == \
        {r["event_id"]: (r["status"], r["ended_at"]) for r in again}
    assert meta["opened"] == 0
    # the closing item of Easton's 5/29 scrolls off the page: its record is kept with its end
    m = re.search(r'<article\b(?:(?!</article>).)*?/node/48701".*?</article>', FEED, re.S)
    later, _ = F.build(FEED.replace(m.group(0), ""), T3, again, [], beaches)
    e = next(r for r in later if r["raw"]["node"] == "48701")
    assert e["status"] == "advisory_lifted" and e["ended_at"] == "2026-06-01T16:02:24Z"
    assert e["raw"]["_last_seen_in_source"] == T2
    # a reopening read before its closing was ever seen ends nothing and invents no record
    m2 = re.search(r'<article\b(?:(?!</article>).)*?/node/49446".*?</article>', FEED, re.S)
    recs, meta = F.build(FEED.replace(m2.group(0), ""), T1, [], [], beaches)
    assert not any(r["raw"]["beach"] == "King Park Beach" for r in recs)


def test_a_reason_naming_cyanobacteria_is_a_bloom_advisory(beaches):
    page = edit(FEED, "King Park Beach in Newport due to high bacteria counts",
                "King Park Beach in Newport due to a cyanobacteria bloom")                     # invented
    kp = next(r for r in F.build(page, T1, [], [], beaches)[0] if r["raw"]["beach"] == "King Park Beach")
    assert kp["event_type"] == "hab_advisory" and kp["raw"]["reason"] == "a cyanobacteria bloom"


def test_a_beach_the_layer_does_not_hold_is_listed_only(beaches):
    page = edit(FEED, "King Park Beach in Newport due to", "Example Cove Beach in Newport due to")    # invented
    r = next(r for r in F.build(page, T1, [], [], beaches)[0] if r["raw"]["beach"] == "Example Cove Beach")
    assert r["raw"]["_placement"] == "listed_only" and r["lat"] is None and r["water_slugs"] == []


@pytest.mark.parametrize("bad", [
    FEED.replace("</html>", ""),                                                     # truncated
    FEED.replace("view-ridoh-feed-beaches", "view-ridoh-feed-news"),                 # another list
    FEED.replace("<h1>Beach Advisories</h1>", "<h1>News</h1>"),
    FEED.replace("</article>", "", 1),                                               # an item cut open
    re.sub(r"<article\b.*</article>", "", FEED, flags=re.S),                          # no item
    "<html><body>Just a moment...</body></html>",
    "",
])
def test_a_feed_page_not_read_whole_raises(bad):
    with pytest.raises(ValueError):
        F.parse(bad)


def test_split_beaches_forms():
    assert F.split_beaches("Oakland and Conimicut beach in Warwick") == [
        {"name": "Oakland Beach", "town": "Warwick", "name_basis": "RIDOH's shared word 'beach' completed for this name"},
        {"name": "Conimicut Beach", "town": "Warwick"}]
    assert F.split_beaches("Easton’s Beach in Newport, Oakland Beach in Warwick, and Briar Point Beach in Coventry") \
        == [{"name": "Easton’s Beach", "town": "Newport"}, {"name": "Oakland Beach", "town": "Warwick"},
            {"name": "Briar Point Beach", "town": "Coventry"}]
    # a comma never carries a town over
    assert F.split_beaches("Oakland Beach, Third Beach in Middletown") == [
        {"name": "Oakland Beach", "town": None}, {"name": "Third Beach", "town": "Middletown"}]
    assert F.split_beaches("Sandy Point Beach in Portsmouth, ") is None                  # an empty part


@pytest.fixture
def run_feed(tmp_path, monkeypatch):
    import common
    _beaches(tmp_path, monkeypatch)
    monkeypatch.setattr(F, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    saved = []
    monkeypatch.setattr(F, "save_raw", lambda src, body, ext: saved.append((ext, body)) or tmp_path / "raw")

    def go(page, stamp):
        monkeypatch.setattr(F, "now_iso", lambda: stamp)
        monkeypatch.setattr(F.requests, "get", lambda *a, **k: _Resp(page))
        code = F.main([])
        return code, json.loads((tmp_path / f"{F.SOURCE_ID}.json").read_text())
    go.saved = saved
    return go


def test_feed_failed_and_partial_reads(run_feed):
    code, doc = run_feed(FEED, T1)
    assert code == 0 and doc["ok"] and len(doc["records"]) == 21
    code, doc = run_feed(FEED.replace("</html>", ""), T2)
    assert code == 1 and doc["ok"] is False and len(doc["records"]) == 21
    page = edit(FEED, "King Park Beach in Newport due to high bacteria counts", "King Park Beach in Newport")  # invented
    code, doc = run_feed(page, T3)
    assert code == 1 and doc["ok"] is False and doc["meta"]["unread"][0]["node"] == "49446"
    assert len(doc["records"]) == 21


def test_feed_nothing_personal_reaches_any_save(run_feed):
    page = edit(FEED, '<a href="/node/49446" rel="bookmark"> RIDOH Recommends',
                '<a href="/node/49446" rel="bookmark"> Call Pat Example 401-555-0100 or pat@example.org: RIDOH Recommends')
    page = edit(page, "high bacteria counts.\u202f</span><span>&nbsp;</span></p>",
                "high bacteria counts.</span></p><p>Contact Pat Example at 401-555-0100, 1234-A Example St.</p>")  # invented
    code, doc = run_feed(page, T1)
    assert code == 0
    blob = json.dumps(doc) + json.dumps(run_feed.saved)
    for p in ['401-555-0100', 'Pat Example', 'pat@example.org']:
        assert p in blob
    assert "222-2751" not in blob                         # RIDOH's closing paragraph is never read
    assert len(run_feed.saved) == 1 and run_feed.saved[0][0] == "json" and "<" not in run_feed.saved[0][1]


# ================================================================ register, sources and texts

def test_the_register_rows_and_sources_say_what_is_collected():
    import yaml
    doc = json.loads((ROOT / "data" / "notice-channels" / "ri.json").read_text())
    rows = {r["id"]: r for r in doc["channels"]}
    assert rows["ri-ridem-shellfish-closures"]["feed_source_id"] == D.SOURCE_ID
    assert rows["ri-ridem-shellfish-closures"]["unmonitored_reason"] == "feed_ingested"
    assert rows["ri-ridoh-beach-feed"]["feed_source_id"] == F.SOURCE_ID
    for rid in ("ri-ridem-press-releases", "ri-ridoh-press-releases"):
        assert rows[rid]["monitored"] is True and rows[rid].get("records") is False and not rows[rid].get("barrier")
    for sid, et in ((D.SOURCE_ID, ["shellfish_closure"]), (F.SOURCE_ID, ["beach_closure", "hab_advisory"])):
        src = yaml.safe_load((ROOT / "data" / "sources" / f"{sid}.yaml").read_text())
        assert src["id"] == sid and src["event_types"] == et
    research = {r["id"]: r for r in json.loads((ROOT / "research" / "ri" / "sources.json").read_text())}
    assert research[D.SOURCE_ID]["status"] == "used" and research[F.SOURCE_ID]["status"] == "used"
    assert "not collected yet" not in research[D.SOURCE_ID]["status_reason"]


# ================================================================ Astra review 2026-11-16 (reviews/astra-ri-feeds-review.md)

def test_review_p1_1_a_row_missing_from_an_unchanged_table_ends_nothing():
    prev, _ = D.build(PAGE, T1, [])
    recs, meta = D.build(drop_row(PAGE, "Mount Hope Bay (Area 17)"), T2, prev)        # same Updated date
    assert meta["lifted_this_read"] == 0 and meta["unread"]
    assert meta["unread"][0]["reason"] == "a closed area is missing from a table with the same Updated date"
    assert all(r["status"] == "advisory_active" for r in recs) and len(recs) == 6
    # DEM republished the table (a new Updated date) without the area: that read ends it
    moved = edit(drop_row(PAGE, "Mount Hope Bay (Area 17)"), "Updated 11/7/2026", "Updated 11/16/2026")
    recs, meta = D.build(moved, T2, prev)
    assert meta["unread"] == [] and by_codes(recs)[("17",)]["status"] == "advisory_lifted"


def test_review_p1_3_area_codes_take_a_strict_form_and_nothing_personal_is_saved():
    page = edit(PAGE, "(Area 5)", "(Area 5; contact Pat Example at 401-555-0100 or pat@example.org)")   # invented
    parsed = D.parse(page, T1)
    blob = D.saved_form(parsed)
    for p in ("Pat Example", "401-555-0100", "pat@example.org"):
        assert p in blob, p
    assert [u["reason"] for u in parsed["unread"]] == ["area codes the reader cannot take"]


def test_review_p1_2_a_partial_feed_read_ends_nothing(beaches):
    neg = FEED.replace("recommends re-opening", "does not recommend re-opening")       # invented: no reopenings
    prev, _ = F.build(neg, T1, [], [], beaches)
    assert all(r["status"] == "advisory_active" for r in prev)
    page = edit(FEED, "King Park Beach in Newport due to high bacteria counts", "King Park Beach in Newport")
    recs, meta = F.build(page, T2, prev, [], beaches)
    assert meta["unread"] and meta["ended_this_read"] == 0
    assert all(r["status"] == "advisory_active" and r["ended_at"] is None for r in recs)


def test_review_p2_4_a_bacteria_reopening_does_not_lift_a_bloom_advisory(beaches):
    page = FEED.replace("due to high bacteria counts", "due to a cyanobacteria bloom")                 # invented
    assert page != FEED
    bt = next(r for r in F.build(page, T1, [], [], beaches)[0] if r["raw"]["node"] == "49426")
    assert bt["event_type"] == "hab_advisory" and bt["status"] == "advisory_active" and bt["ended_at"] is None


def test_review_p2_5_a_carried_record_gains_its_sheet_link(beaches):
    first, _ = F.build(FEED, T1, [], [], beaches)
    m = re.search(r'<article\b(?:(?!</article>).)*?/node/49446".*?</article>', FEED, re.S)
    recs, _ = F.build(FEED.replace(m.group(0), ""), T2, first, _sheet(beaches), beaches)
    kp = next(r for r in recs if r["raw"]["beach"] == "King Park Beach")
    assert kp["duplicate_of"] == "ri-ridoh-beaches:king-park-beach:newport:2026-08-13"
