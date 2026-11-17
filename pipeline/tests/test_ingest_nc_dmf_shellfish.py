"""North Carolina: DMF's polluted area proclamations (ingest/nc_dmf_shellfish.py).

Fixtures, public pages with no person named: nc_dmf_proclamations_2026-11-16_p0/p1/p2/p16.html, the first three pages
and the last page of DMF's list as read on 2026-11-16, trimmed to the title and the proclamation list (the contact
paragraph above the list is not kept). Variants below are edited copies; invented text is marked so.
"""
import json
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ingest import nc_dmf_shellfish as N

FIX = Path(__file__).parent / "fixtures"
P0, P1, P2, P16 = ((FIX / f"nc_dmf_proclamations_2026-11-16_p{n}.html").read_text() for n in (0, 1, 2, 16))
PAGES = [P0, P1, P2]
# the first page with its pager naming three pages: a first run (which reads every page) reads the three fixtures
P0L = P0.replace('href="?page=16" title="Go to last page"', 'href="?page=2" title="Go to last page"')
LISTED = [P0L, P1, P2]


def as_last(page):
    """A first page whose pager names no other page: it may hold fewer than ten rows (the list as it stood before
    the proclamations dropped from it were issued)."""
    return page.replace('href="?page=16" title="Go to last page"', 'href="?page=0" title="Go to last page"')
T = "2026-11-16T23:30:00Z"


def by_id(recs):
    return {r["source_record_id"]: r for r in recs}


def row_of(page, pid):
    m = re.search(r'<div class="views-row">(?:(?!<div class="views-row">).)*?>' + re.escape(pid) + r"<.*?"
                  r'(?=<div class="views-row">|\s*</div>\s*<nav)', page, re.S)
    assert m, pid
    return m


def drop(page, pid):
    m = row_of(page, pid)
    return page[:m.start()] + page[m.end():]


def edit(page, old, new):
    assert old in page, old
    return page.replace(old, new, 1)


# ---- what a record is ----------------------------------------------------------------------------------------------

def test_each_area_of_a_temporary_closure_is_a_record_with_dmfs_times():
    recs, meta = N.build(PAGES, T, [])
    q = by_id(recs)["PA-64-2026:queens-creek"]
    assert q["event_type"] == "shellfish_closure" and q["waterbody_text"] == "Queens Creek"
    assert q["started_at"] == "2026-10-12T07:45:00-04:00" and q["time_precision"] == "minute"
    assert q["published_at"] == "2026-10-12" and q["source_updated_at"] == "2026-10-12" and q["fetched_at"] == T
    assert q["source_url"].startswith("https://files.nc.gov/deq/documents/2026-10/PA-64-2026")
    # ended by PA-65-2026, effective sunrise October 15: the day, never a time invented
    assert q["status"] == "advisory_lifted" and q["ended_at"] == "2026-10-15"
    assert q["raw"]["ended_at_precision"] == "day" and q["raw"]["ended_by"] == "PA-65-2026"
    assert q["raw"]["reason"] is None and "bacteriological water quality" in q["raw"]["reason_basis"]
    pa63 = [r for r in recs if r["raw"]["proclamation"] == "PA-63-2026"]
    assert sorted(r["waterbody_text"] for r in pa63) == sorted([
        "A portion of Myrtle Grove Sound", "Stump Sound", "Alligator Bay", "Chadwick Bay", "Core Creek", "North River",
        "Whitehurst Creek", "Sleepy Creek", "Jarrett Bay", "Oyster Creek", "Brett Bay"])
    assert all(r["status"] == "advisory_lifted" for r in pa63)                   # PA-65, PA-66 and PA-67 reopen all
    assert by_id(recs)["PA-63-2026:core-creek"]["raw"]["ended_by"] == "PA-67-2026"
    assert meta["newest"] == "PA-67-2026" and meta["unread"] == [] and meta["temporary_closures"] == 10
    assert meta["reopenings"] == 20
    for r in recs:
        assert "safe" not in json.dumps(r).lower() and "clean" not in r["advice_text"].lower()


def test_reopenings_make_no_record_and_open_areas_are_never_called_safe():
    recs, _ = N.build(PAGES, T, [])
    assert not [r for r in recs if r["raw"]["proclamation"] in ("PA-65-2026", "PA-66-2026", "PA-67-2026")]


def test_what_is_closed_today_on_the_three_pages():
    recs, meta = N.build(PAGES, T, [])
    active = sorted(r["source_record_id"] for r in recs if r["status"] == "advisory_active")
    # PA-59-2026 closed Shallotte Inlet and Bay River; no later proclamation on the list reopens either whole. Its
    # Oyster Creek (PA-59 lists Carteret and Pamlico, each with an Oyster Creek) cannot be matched to a reopening
    assert active == ["PA-59-2026:bay-river", "PA-59-2026:oyster-creek", "PA-59-2026:shallotte-inlet"]
    assert meta["held_county_ambiguous"] == ["PA-59-2026:oyster-creek"]
    active = ["PA-59-2026:bay-river", "PA-59-2026:shallotte-inlet"]
    bay = by_id(recs)["PA-59-2026:bay-river"]
    assert [p["proclamation"] for p in bay["raw"]["partial_reopenings"]] == ["PA-62-2026"]   # "A portion of Bay River"
    assert meta["no_reopening_named"] == active and bay["raw"]["no_reopening_note"] == N.NO_REOPENING_NOTE


def test_a_reopening_proclaimed_for_a_later_day_is_a_plan_not_an_end():
    evening = "2026-10-16T22:00:00Z"                       # 6 p.m. on the 16th: PA-67 is effective at sunrise on the 17th
    recs, _ = N.build(PAGES, evening, [])
    core = by_id(recs)["PA-63-2026:core-creek"]
    assert core["status"] == "advisory_active" and core["ended_at"] is None
    assert core["raw"]["reopening_proclaimed"]["proclamation"] == "PA-67-2026"
    assert core["raw"]["reopening_proclaimed"]["basis"] == N.PLAN_BASIS
    # the next day the reopening is in effect; and it is applied even once PA-67 is no longer on the pages read
    later, _ = N.build([as_last(drop(P0, "PA-67-2026"))], "2026-10-17T15:00:00Z", recs)
    core = by_id(later)["PA-63-2026:core-creek"]
    assert core["status"] == "advisory_lifted" and core["ended_at"] == "2026-10-17" and core["raw"]["ended_by"] == "PA-67-2026"


def test_a_partial_reopening_never_ends_a_whole_closure_but_a_whole_one_ends_a_part():
    recs, _ = N.build(PAGES, T, [])
    assert by_id(recs)["PA-59-2026:bay-river"]["status"] == "advisory_active"
    # "A portion of Myrtle Grove Sound" (PA-63) is ended by "Myrtle Grove Sound" (PA-66)
    mg = by_id(recs)["PA-63-2026:myrtle-grove-sound-a-portion-of"]
    assert mg["raw"]["portion"] is True and mg["status"] == "advisory_lifted" and mg["raw"]["ended_by"] == "PA-66-2026"


def test_a_reopening_in_another_county_does_not_end_a_closure():
    page = edit(P0, "Counties Affected:</strong> Onslow and Carteret</p></div></div></div>\n  </div>\n    <div class=\"views-row\">"
                    "\n    <div class=\"views-field views-field-field-document-entity-body\"><div class=\"field-content\">"
                    "<div style=\"background-color:#FCFCFC;border-style:solid;padding:15px;\"><h3><a href=\"https://files"
                    ".nc.gov/deq/documents/2026-10/PA-64-2026",
                "Counties Affected:</strong> Carteret</p></div></div></div>\n  </div>\n    <div class=\"views-row\">"
                "\n    <div class=\"views-field views-field-field-document-entity-body\"><div class=\"field-content\">"
                "<div style=\"background-color:#FCFCFC;border-style:solid;padding:15px;\"><h3><a href=\"https://files"
                ".nc.gov/deq/documents/2026-10/PA-64-2026")             # invented: PA-65 for Carteret only
    recs, _ = N.build([page, P1, P2], T, [])
    assert by_id(recs)["PA-64-2026:queens-creek"]["status"] == "advisory_active"     # Queens Creek is in Onslow


def test_absence_from_the_list_never_ends_or_drops_a_closure():
    first, _ = N.build(PAGES, "2026-10-16T22:00:00Z", [])
    held = [r for r in first if r["status"] == "advisory_active"]
    assert held
    later, meta = N.build([P1], "2026-10-16T23:00:00Z", first)          # only an older page read: nothing reopens
    for r in held:
        assert by_id(later)[r["source_record_id"]]["status"] == "advisory_active"
    assert len(later) == len(first) and meta["lifted_this_read"] == 0


def test_permanent_boundary_proclamations_are_left_out_and_counted():
    recs, meta = N.build({0: P0, 16: P16}, T, [])
    assert meta["left_out"]["permanent_boundary"] == ["PA-PC-2025"]
    assert not [r for r in recs if r["raw"]["proclamation"].startswith("PA-PC")]
    # the archive's last row (a bare date of 2024, no proclamation number) is skipped by name, never guessed
    assert meta["unread"] == [] and len(meta["skipped"]) == 1


def test_a_biotoxin_or_season_closure_is_never_shown_as_a_sewage_sign():
    page = edit(P0, "This proclamation closes the following area in Onslow County: Queens Creek.",
                "This proclamation closes the following area in Onslow County: Queens Creek due to a red tide.")  # invented
    recs, meta = N.build([page], T, [])
    assert meta["left_out"]["not_pollution"] == ["PA-64-2026"] and "PA-64-2026:queens-creek" not in by_id(recs)
    page = edit(P0, "Shellfish Temporary Closure effective at 7:45", "Shellfish Temporary Closure for the oyster "
                                                                      "season effective at 7:45")             # invented
    assert N.build([page], T, [])[1]["left_out"]["not_pollution"] == ["PA-64-2026"]


def test_negations_and_unknown_kinds_are_unread_not_closures():
    page = edit(P0, "This proclamation closes the following area in Onslow County: Queens Creek.",
                "This proclamation does not close the following area in Onslow County: Queens Creek.")  # invented
    recs, meta = N.build([page], T, [])
    assert "PA-64-2026:queens-creek" not in by_id(recs)
    assert meta["unread"] == [{"page": 0, "row": 4, "id": "PA-64-2026",
                               "reason": "a proclamation the reader cannot type (not a temporary closure or a reopening)"}]
    page = edit(P0, "Shellfish Temporary Closure effective at 7:45 a.m., Monday, October 12th, 2026.",
                "Shellfish Temporary Closure effective when results allow.")                                # invented
    assert N.build([page], T, [])[1]["unread"][0]["reason"].startswith("wording the reader does not take")


def test_one_unreadable_row_keeps_the_rest_and_fails_health(run_nc):
    code, doc = run_nc(LISTED, T)
    assert code == 0 and doc["ok"]
    page = edit(P0L, "<strong>Issued Date:</strong> 10/12/2026", "<strong>Issued Date:</strong> soon")       # invented
    code, doc = run_nc([page, P1, P2], "2026-11-16T23:45:00Z")
    assert code == 1 and doc["ok"] is False and doc["last_ok_at"] is not None
    assert [u["id"] for u in doc["meta"]["unread"]] == ["PA-64-2026"]
    q = by_id(doc["records"])["PA-64-2026:queens-creek"]              # held as it was
    assert q["status"] == "advisory_lifted" and q["ended_at"] == "2026-10-15"
    assert len(doc["records"]) == len(N.build(PAGES, T, [])[0])


@pytest.mark.parametrize("bad", [
    P0.replace("</html>", ""),                                                      # truncated
    P0.replace("Polluted Area Proclamations</span>", "Proclamations</span>"),       # title changed
    P0.replace("<h2>\n    Proclamations\n</h2>", "<h2>Notices</h2>"),               # list heading changed
    P0.replace("view-ncc-dmf-fm-proclamations", "view-news"),                       # another list
    P0.replace('<div class="views-row">', '<div class="row-item">'),                # rows renamed
    "<html><body>Just a moment...</body></html>",                                   # a challenge page
    "",
])
def test_a_page_not_read_whole_raises(bad):
    with pytest.raises(ValueError):
        N.parse(bad, 0)


def test_a_failed_read_keeps_every_record_and_fails_health(run_nc):
    code, doc = run_nc(LISTED, T)
    assert code == 0
    n = len(doc["records"])
    code, doc = run_nc([P0.replace("view-ncc-dmf-fm-proclamations", "view-news"), P1, P2], "2026-11-17T00:30:00Z")
    assert code == 1 and doc["ok"] is False and len(doc["records"]) == n


# ---- times ---------------------------------------------------------------------------------------------------------

def test_local_times_follow_daylight_saving_and_dmfs_forms():
    assert N.effective("Shellfish Temporary Closures effective at 8:00 a.m., Monday, November 2, 2026.")["at"] \
        == "2026-11-02T08:00:00-05:00"                                          # after the change back (invented)
    assert N.effective("Shellfish Temporary Closures effective at 8:00 a.m., Sunday, March 8, 2026.")["at"] \
        == "2026-03-08T08:00:00-04:00"                                          # the morning of the change (invented)
    e = N.effective("Shellfish reopenings effective at sunrise, Friday, July 11. 2025.")   # DMF's typing, as served
    assert e["at"] == "2025-07-11" and e["precision"] == "day" and e.get("sunrise") is True
    assert N.effective("Shellfish Temporary Closures effective 8:10 A.M., Thursday, September 24, 2026.")["at"] \
        == "2026-09-24T08:10:00-04:00"
    w = N.effective("Shellfish Temporary Closures effective at 8:00 a.m., Tuesday, October 11th, 2026.")  # invented
    assert w["weekday_mismatch"] is True and w["day"] == "2026-10-11"
    assert N.issued_day("4/26/26").isoformat() == "2026-04-26"


def test_an_issued_date_after_the_read_is_not_taken():
    page = edit(P0, "<strong>Issued Date:</strong> 10/16/2026", "<strong>Issued Date:</strong> 12/16/2026")  # invented
    recs, meta = N.build([page], T, [])
    assert [u["reason"] for u in meta["unread"]] == ["an issued date after the read"]


# ---- ids -----------------------------------------------------------------------------------------------------------

def test_ids_do_not_depend_on_row_order_or_on_which_pages_are_read_together():
    a, _ = N.build(PAGES, T, [])
    b, _ = N.build([P2, P0, P1], T, [])
    assert {r["event_id"] for r in a} == {r["event_id"] for r in b}
    one, _ = N.build([P0], T, [])
    assert {r["event_id"] for r in one} <= {r["event_id"] for r in a}
    again, _ = N.build(PAGES, "2026-11-17T23:30:00Z", a)
    assert {r["event_id"] for r in again} == {r["event_id"] for r in a}
    assert {r["event_id"]: r["started_at"] for r in again} == {r["event_id"]: r["started_at"] for r in a}


# ---- place ---------------------------------------------------------------------------------------------------------

def test_areas_are_placed_by_dmfs_polygon_or_listed_only():
    recs, _ = N.build(PAGES, T, [])
    s = by_id(recs)["PA-63-2026:stump-sound"]
    assert (s["lat"], s["lon"]) == (34.469, -77.486) and s["water_slugs"] == ["stump-sound-nc"]
    assert s["raw"]["_point_extent_only"] is True and s["raw"]["area_polygon"]["objectids"] == [17928, 17934, 17984, 18054]
    for sid in ("PA-63-2026:myrtle-grove-sound-a-portion-of",        # a portion: no outline of the part
                "PA-64-2026:queens-creek",
                "PA-63-2026:north-river"):                       # DMF's polygon, but no water record holds it
        r = by_id(recs)[sid]
        assert r["raw"]["_placement"] == "listed_only" and r["water_slugs"] == [] and r["lat"] is None, sid


def test_a_name_in_another_county_is_not_placed():
    area = {"key": "oyster creek", "portion": False, "county": "Pamlico", "text": "Oyster Creek (Pamlico County)"}
    assert N.place(area, {"counties": ["Pamlico", "Carteret"]}) is None
    area = {"key": "stump sound", "portion": False, "county": None, "text": "Stump Sound"}
    assert N.place(area, {"counties": ["Onslow"]}) is None                       # half of Stump Sound is in Pender
    assert N.place(area, {"counties": ["Pender", "Onslow"]})["water"] == "stump-sound-nc"


def test_the_placement_table_points_lie_in_the_named_waters_records():
    from build import status as S
    from shapely.geometry import Point
    waters = S.load_waters()
    for key, a in N.AREAS.items():
        assert a["water"] in waters, key
        g = S.water_geometry(a["water"], waters)
        assert g is not None, key
        if g.area > 0:
            assert g.buffer(0.002).contains(Point(a["point"][1], a["point"][0])), key


# ---- privacy -------------------------------------------------------------------------------------------------------

PRIVATE = ("Pat Example", "919-555-0100", "pat@example.org")


def test_nothing_personal_reaches_any_save(run_nc):
    page = edit(P0L, "This proclamation closes the following area in Onslow County: Queens Creek.",
                "This proclamation closes the following area in Onslow County: Queens Creek near the home of Pat "
                "Example.")                                                                              # invented
    page = edit(page, "Onslow</p></div></div></div>", "Onslow. Call Pat Example at 919-555-0100 or pat@example.org.</p>"
                                                       "</div></div></div>")                            # invented
    code, doc = run_nc([page, P1, P2], T)
    assert code == 0 and doc["ok"]
    blob = json.dumps(doc) + json.dumps(run_nc.saved)
    for p in PRIVATE:
        assert p not in blob, p
    assert len(run_nc.saved) == 1 and run_nc.saved[0][0] == "json" and "<div" not in run_nc.saved[0][1]
    bad = dict(doc)
    bad["records"] = [dict(r, advice_text=r["advice_text"] + " Call Pat Example at 919-555-0100.") for r in doc["records"]]
    Path(N.EVENTS_DIR / f"{N.SOURCE_ID}.json").write_text(json.dumps(bad))
    code, doc = run_nc([""], "2026-11-17T00:30:00Z")
    assert code == 1 and "Pat Example" not in json.dumps(doc) and "919-555-0100" not in json.dumps(doc)


def test_the_fixtures_hold_no_contact():
    for page in (P0, P1, P2, P16):
        assert "@" not in page and "tel:" not in page and not re.search(r"\d{3}-\d{3}-\d{4}", page)


class _Resp:
    def __init__(self, text):
        self.text, self.headers, self.status_code = text, {}, 200

    def raise_for_status(self):
        return None


@pytest.fixture
def run_nc(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(N, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(N.time, "sleep", lambda s: None)
    saved = []
    monkeypatch.setattr(N, "save_raw", lambda src, body, ext: saved.append((ext, body)) or tmp_path / "raw")

    def go(pages, stamp):
        monkeypatch.setattr(N, "now_iso", lambda: stamp)
        asked = []

        def get(url, *a, **k):
            n = int(url.rsplit("=", 1)[1]) if "?page=" in url else 0
            asked.append(n)
            return _Resp(pages[n] if n < len(pages) else pages[-1])
        monkeypatch.setattr(N.requests, "get", get)
        code = N.main([])
        go.asked = asked
        return code, json.loads((tmp_path / f"{N.SOURCE_ID}.json").read_text())
    go.saved = saved
    return go


def test_a_first_run_reads_every_page_and_a_later_run_the_first_three(run_nc):
    first = P0.replace('href="?page=16" title="Go to last page"', 'href="?page=3" title="Go to last page"')  # 4 pages
    assert N.last_page(first) == 3 and N.last_page(P0) == 16
    code, doc = run_nc([first, P1, P2, P16], T)
    assert run_nc.asked == [0, 1, 2, 3]
    # the archive's last row (a bare 2024 date, no number) is skipped by name; the first run is healthy
    assert code == 0 and doc["ok"] and doc["meta"]["unread"] == [] and len(doc["meta"]["skipped"]) == 1
    assert doc["records"] and doc["meta"]["left_out"]["permanent_boundary"] == ["PA-PC-2025"]
    code, doc = run_nc(PAGES, "2026-11-17T00:30:00Z")
    assert run_nc.asked == [0, 1, 2] and code == 0 and doc["ok"]


# ---- the status build: one marker in the area, no water coloured whole ----------------------------------------------

def _status(S, tmp_path, recs, waters, now):
    d = tmp_path / "ev"
    d.mkdir()
    iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    (d / f"{N.SOURCE_ID}.json").write_text(json.dumps({"source_id": N.SOURCE_ID, "ok": True, "records": recs,
                                                        "fetched_at": iso, "last_ok_at": iso}))
    st, _ = S.build(now=now, events_dir=d, write=False, waters=waters, outfalls=[], placement_cache=False, reaches={},
                    flows=({}, {}), discharger_towns={}, discharger_waters={})
    return st


def test_on_the_day_of_pa_63_each_placed_closure_is_a_red_marker_and_no_water_is_red(tmp_path):
    from build import status as S
    allw = S.load_waters()
    waters = {k: allw[k] for k in ("stump-sound-nc", "core-sound-nc", "bogue-sound-nc", "masonboro-sound-nc",
                                    "topsail-sound-nc", "shallotte-river-nc", "lockwoods-folly-river-nc",
                                    "intracoastal-waterway-calabash-nc")}
    page = as_last(drop(drop(drop(P0, "PA-67-2026"), "PA-66-2026"), "PA-65-2026"))
    recs, _ = N.build([page], "2026-10-12T15:00:00Z", [])
    st = _status(S, tmp_path, recs, waters, datetime(2026, 10, 12, 16, 0, tzinfo=UTC))
    for slug in waters:
        assert (st["waters"].get(slug) or {}).get("status") != "red", slug
    active = [r for r in recs if r["status"] == "advisory_active"]
    placed = {r["event_id"] for r in active if r["water_slugs"]}
    # PA-63's areas with an outline here, and PA-59's still closed that day (PA-67 had not reopened them)
    assert placed == {"nc-dmf-polluted-area-proclamations:" + k for k in (
        "PA-63-2026:stump-sound", "PA-63-2026:sleepy-creek", "PA-63-2026:oyster-creek", "PA-63-2026:brett-bay",
        "PA-59-2026:tubbs-inlet", "PA-59-2026:lockwoods-folly-river", "PA-59-2026:nelson-bay",
        "PA-59-2026:shallotte-river")}
    pts = {p["event_id"]: p for p in st["advisory_points"]}
    for eid in placed:
        assert pts[eid]["status"] == "red", eid
    listed = [r for r in active if not r["water_slugs"]]
    for r in listed:
        assert st["placements"][r["event_id"]]["water_slugs"] == [] and r["event_id"] not in pts


# ---- the independent review (2026-11-16), one test per finding -------------------------------------------------------

def test_review_p1_1_a_withheld_name_never_reaches_a_key_or_an_id():
    page = edit(P0, "This proclamation closes the following area in Onslow County: Queens Creek.",
                "This proclamation closes the following area in Onslow County: Queens Creek near the home of Pat "
                "Example.")                                                                              # invented
    recs, meta = N.build([page, P1, P2], T, [])
    blob = json.dumps(recs) + json.dumps(meta)
    for p in ("Pat Example", "pat example", "pat-example", "home of"):
        assert p not in blob, p


def test_review_p1_4_a_different_portion_does_not_end_a_portion_closure():
    page = edit(P0, "closes the following areas in New Hanover, Pender, Onslow, and Carteret Counties: A portion of "
                    "Myrtle Grove Sound", "closes the following areas in New Hanover, Pender, Onslow, and Carteret "
                    "Counties: the northern portion of Myrtle Grove Sound")                          # invented
    page = edit(page, "normal closure boundaries: Myrtle Grove Sound, Stump Sound",
                "normal closure boundaries: the southern portion of Myrtle Grove Sound, Stump Sound")  # invented
    recs, _ = N.build([page, P1, P2], T, [])
    mg = [r for r in recs if r["raw"]["proclamation"] == "PA-63-2026" and r["raw"]["area_key"] == "myrtle grove sound"]
    assert len(mg) == 1 and mg[0]["status"] == "advisory_active"
    # the same words ("A portion of", as DMF closed it) or the whole area do end it
    recs, _ = N.build(PAGES, T, [])
    assert by_id(recs)["PA-63-2026:myrtle-grove-sound-a-portion-of"]["status"] == "advisory_lifted"


def test_review_p1_5_a_name_in_two_counties_is_neither_placed_nor_ended_by_another_county():
    recs, _ = N.build(PAGES, T, [])
    oc = by_id(recs)["PA-59-2026:oyster-creek"]          # PA-59 lists Carteret and Pamlico: which Oyster Creek is unknown
    assert oc["raw"]["_placement"] == "listed_only" and oc["water_slugs"] == []
    page = edit(P0, "normal closure boundaries: A portion of Bay River and Jones Bay.",
                "normal closure boundaries: A portion of Bay River, Jones Bay, and Oyster Creek.")   # invented, Pamlico
    p0 = edit(page, "boundaries: Myrtle Grove Sound, Topsail Sound, and Oyster Creek.",
              "boundaries: Myrtle Grove Sound and Topsail Sound.") if "Topsail Sound, and Oyster Creek" in page else page
    recs, _ = N.build([p0, P1, P2], T, [])
    assert by_id(recs)["PA-59-2026:oyster-creek"]["raw"].get("ended_by") != "PA-62-2026"
    oc63 = by_id(recs)["PA-63-2026:oyster-creek"]         # PA-63 lists no Pamlico: Carteret's, placed
    assert oc63["water_slugs"] == ["core-sound-nc"]


def test_review_p1_6_a_page_with_a_missing_row_fails_the_read():
    with pytest.raises(ValueError):
        N.build([drop(P0, "PA-64-2026"), P1, P2], T, [])
    with pytest.raises(ValueError):
        N.build({0: P0, 1: drop(P1, "PA-55-2026")}, T, [])
    N.build({0: P0, 16: P16}, T, [])                      # the last page may hold fewer than ten


def test_review_p1_7_an_unread_row_stays_unread_until_its_page_is_read_again(run_nc):
    page2 = edit(P2, "<strong>Issued Date:</strong> 9/7/2026", "<strong>Issued Date:</strong> soon")   # invented
    code, doc = run_nc([P0L, P1, page2], T)
    assert code == 1 and [u["id"] for u in doc["meta"]["unread"]] == ["PA-47-2026"]
    # the next run reads page 2 again (the first three pages) and the row is still unread: health stays false
    code, doc = run_nc([P0L, P1, page2], "2026-11-17T00:30:00Z")
    assert code == 1 and doc["ok"] is False
    # a carried unread row on a page not read this run keeps health false, and its page is asked for again
    prev = doc["meta"]["unread"]
    recs, meta = N.build({0: P0}, "2026-11-17T01:30:00Z", doc["records"], prev)
    assert [u["id"] for u in meta["unread"]] == ["PA-47-2026"] and meta["unread"][0]["carried"] is True
    assert N.pages_to_read(prev, 16) == [0, 1, 2]
    assert N.pages_to_read([{"page": 9, "id": "PA-1-2026"}], 16) == [0, 1, 2, 9]
    # read whole again: resolved
    code, doc = run_nc([P0L, P1, P2], "2026-11-17T02:30:00Z")
    assert code == 0 and doc["ok"] and doc["meta"]["unread"] == []


def test_review_p1_7_the_archives_bare_date_row_is_skipped_by_name_not_unread():
    recs, meta = N.build({0: P0, 16: P16}, T, [])
    assert meta["unread"] == [] and meta["skipped"] == [{"page": 16, "row": 3, "text": "2:01 A.M., Saturday, June 8, 2024",
                                                         "reason": "an archive entry with a date and no proclamation"}]


def test_review_p1_8_negated_or_conditional_effective_wording_is_unread():
    for words in ("Shellfish reopenings NOT effective at sunrise, Thursday, October 15, 2026.",
                  "Shellfish reopenings effective at sunrise, Thursday, October 15, 2026, if results allow.",
                  "Shellfish reopenings postponed; previously effective at sunrise, Thursday, October 15, 2026."):
        page = edit(P0, "Shellfish reopenings effective at sunrise, Thursday, October 15, 2026.", words)     # invented
        recs, meta = N.build([page, P1, P2], T, [])
        assert [u["id"] for u in meta["unread"]] == ["PA-65-2026"], words
        assert by_id(recs)["PA-64-2026:queens-creek"]["status"] == "advisory_active", words
