"""Nevada: the Office of State Epidemiology's harmful algal bloom list (ingest/nv_ose_hab_list.py).

tests/fixtures/nv_ose_hab_list_2026-11-16.html is the page the pipeline's runner read on 2026-11-16 (runner probe
43869029579), trimmed to its two accordions with the images reduced and the general advice block cut to one line (its
help-line paragraph is not kept); no person is named. Variants below are edited copies; invented text is marked so.
"""
import json
import re
from pathlib import Path

import pytest

from ingest import nv_ose_hab_list as O
from ingest import nv_state_parks_hab as P

FIX = Path(__file__).parent / "fixtures"
PAGE = (FIX / "nv_ose_hab_list_2026-11-16.html").read_text()
PARKS_PAGE = (FIX / "nv_state_parks_hab_2026-11-16.html").read_text()
T1, T2, T3 = "2026-11-16T12:42:42Z", "2026-11-16T13:42:42Z", "2026-11-17T13:42:42Z"


def recs_by(recs):
    return {(r["raw"]["water"], r["raw"]["part"]): r for r in recs}


def drop_block(page, summary_start):
    """The page without the active block whose heading starts with summary_start."""
    m = re.search(r"<details\b[^>]*>\s*<summary\b[^>]*>\s*" + re.escape(summary_start) + r".*?</details>", page, re.S)
    assert m, summary_start
    return page[:m.start()] + page[m.end():]


# ---- the page as the runner read it ------------------------------------------------------------------------------

def test_every_advisory_on_the_runners_page_is_a_record():
    recs, meta = O.build(PAGE, T1, [])
    got = sorted((r["raw"]["water"], r["raw"]["part"] or "", r["raw"]["level"], r["started_at"], r["source_updated_at"],
                  r["raw"]["advisory_extent"], r["raw"]["_placement"]) for r in recs)
    assert got == sorted([
        ("Mountain View Pond", "", "Watch", "2026-10-14", "2026-10-14", "named_water", "listed_only"),
        ("Lahontan Reservoir", "", "Warning", "2026-09-09", "2026-11-02", "named_water", "named_water_only"),
        ("Lake Mohave", "", "Watch", "2026-06-11", "2026-06-11", "named_water", "named_water_only"),
        ("Lake Mohave", "Eagle Wash", "Watch", "2026-09-09", "2026-09-09", "part_of_water", "named_water_only"),
        ("Lake Mohave", "Placer Cove", "Watch", "2026-09-09", "2026-09-09", "part_of_water", "named_water_only"),
        ("Lake Mohave", "Cottonwood Cove", "Watch", "2026-10-28", "2026-10-28", "part_of_water", "named_water_only"),
        ("Rye Patch Reservoir", "", "Watch", "2026-09-30", "2026-09-30", "named_water", "named_water_only"),
        ("Wild Horse Reservoir", "", "Watch", "2026-08-13", "2026-08-13", "named_water", "named_water_only"),
        ("Virginia Lake", "", "Watch", "2026-06-23", "2026-06-23", "named_water", "listed_only"),
        ("South Meadows Community Pond", "", "Watch", "2026-06-23", "2026-06-23", "named_water", "listed_only"),
        ("Walker Lake", "", "Watch", "2026-05-19", "2026-05-19", "named_water", "named_water_only")])
    assert meta["on_page"] == 8 and meta["advisories_read"] == 11 and meta["unread"] == []
    assert meta["listed_only"] == ["Mountain View Pond", "South Meadows Community Pond", "Virginia Lake"]
    for r in recs:
        assert r["status"] == "advisory_active" and r["event_type"] == "hab_advisory" and r["ended_at"] is None
        assert r["lat"] is None and r["lon"] is None and r["coord_source"] is None        # no point is made
        assert r["time_precision"] == "day" and r["raw"]["start_basis"] == O.START_BASIS
        assert r["advice_text"].startswith(f"HAB {r['raw']['level']} advisory (Nevada Office of State Epidemiology)")
    by = recs_by(recs)
    assert by[("Mountain View Pond", None)]["raw"]["place"] == "Gardnerville, NV"
    lah = by[("Lahontan Reservoir", None)]["raw"]["level_history"]
    assert [(h["level"], h.get("date")) for h in lah] == [("Danger", "2026-09-09"), ("Danger", None),
                                                           ("Warning", "2026-11-02")]
    # the help line in the general advice block is never read
    assert "Signs that there" not in json.dumps(recs) and "Dashboard" not in json.dumps(recs)


def test_a_level_the_office_words_otherwise_is_kept_as_the_sites_caution():
    page = PAGE.replace("<strong>HAB Watch</strong></span> advisory as of 10/14/2026",
                        "<strong>HAB Alert</strong></span> advisory as of 10/14/2026")      # invented wording
    recs, meta = O.build(page, T1, [])
    mv = recs_by(recs)[("Mountain View Pond", None)]
    assert mv["raw"]["level"] == "Alert" and mv["status"] == "advisory_active"
    assert "not one of Watch, Warning or Danger" in mv["raw"]["code_undecoded"]
    assert mv["raw"]["_caution_label"].startswith("HAB Alert (the Office's words)")
    assert meta["other_levels"] == ["Alert"]


def test_dates_two_digit_years_and_a_date_after_the_read():
    assert O.us_date("11/2/26").isoformat() == "2026-11-02" and O.us_date("09/30/2026").isoformat() == "2026-09-30"
    page = PAGE.replace("as of 8/13/2026", "as of 8/13/2027")                                  # invented
    recs, meta = O.build(page, T1, [])
    assert [u["heading"] for u in meta["unread"]] == ["Wild Horse Reservoir"]
    assert meta["unread"][0]["reason"] == "a date after the read"
    page = PAGE.replace("as of 8/13/2026", "as of 13/45/2026")
    assert O.build(page, T1, [])[1]["unread"][0]["reason"] == "a date the reader cannot take"


# ---- placement: a wrong tie is worse than no tie -----------------------------------------------------------------

def _lake(name, slug, lon0, lat0, d=0.03, state="NV"):
    return {"slug": slug, "name": name, "kind": "lake", "state": state, "bbox": [lon0 - d, lat0 - d, lon0 + d, lat0 + d],
            "geometry": {"type": "Polygon", "coordinates": [[[lon0 - d, lat0 - d], [lon0 + d, lat0 - d],
                                                              [lon0 + d, lat0 + d], [lon0 - d, lat0 + d],
                                                              [lon0 - d, lat0 - d]]]}}


@pytest.fixture
def nv_live(monkeypatch):
    from build import status as S
    monkeypatch.setattr(S, "_STATES", set(S.states()) | {"NV"})
    return S


def test_a_water_with_no_record_is_listed_never_tied_to_a_namesake(nv_live):
    S = nv_live
    waters = {  # invented namesakes: one in Nevada's Elko County, one in Maine
        "virginia-lake-elko-nv": _lake("Virginia Lake", "virginia-lake-elko-nv", -115.76, 40.83),
        "virginia-lake-me": _lake("Virginia Lake", "virginia-lake-me", -70.5, 44.5, state="ME"),
        "mountain-view-pond-nv": _lake("Mountain View Pond", "mountain-view-pond-nv", -114.9, 36.1),
        "walker-lake-nv": _lake("Walker Lake", "walker-lake-nv", -118.71, 38.7, 0.1),
        "walker-lake-elko-nv": _lake("Walker Lake", "walker-lake-elko-nv", -115.5, 41.5, 0.01),
        "lake-mohave-nv": _lake("Lake Mohave", "lake-mohave-nv", -114.65, 35.45, 0.05)}
    recs, _ = O.build(PAGE, T1, [])
    res = S.Resolver(waters, [], placement_rules={})
    by = recs_by(recs)
    for name in ("Virginia Lake", "Mountain View Pond", "South Meadows Community Pond"):
        pl = res.resolve(by[(name, None)])
        assert pl["water_slugs"] == [] and pl["unplaced_reason"] == S.LISTED_ONLY_WHY, name
    assert res.resolve(by[("Walker Lake", None)])["water_slugs"] == ["walker-lake-nv"]      # Mineral, not Elko
    assert res.resolve(by[("Lake Mohave", "Eagle Wash")])["water_slugs"] == ["lake-mohave-nv"]
    alone = S.Resolver({"walker-lake-elko-nv": waters["walker-lake-elko-nv"]}, [], placement_rules={})
    assert alone.resolve(by[("Walker Lake", None)])["water_slugs"] == []


def test_the_listed_only_rule_is_keyed_on_its_value(nv_live):
    S = nv_live
    waters = {"rye-patch-reservoir-nv": _lake("Rye Patch Reservoir", "rye-patch-reservoir-nv", -118.316, 40.59, 0.05)}
    recs, _ = P.build(PARKS_PAGE, T1, [])
    rye = next(r for r in recs if r["waterbody_text"] == "Rye Patch Reservoir")
    assert not S.listed_only(rye)
    assert S.Resolver(waters, [], placement_rules={}).resolve(rye)["water_slugs"] == ["rye-patch-reservoir-nv"]
    assert "nv-ose-hab-reports" in S.POLL_END_HORIZON_SOURCES and "nv-state-parks-hab" in S.POLL_END_HORIZON_SOURCES


# ---- one water, one listing --------------------------------------------------------------------------------------

def _status(S, tmp_path, recs, parks, waters, name="b"):
    from datetime import UTC, datetime
    d = tmp_path / name
    d.mkdir()
    (d / f"{O.SOURCE_ID}.json").write_text(json.dumps({"source_id": O.SOURCE_ID, "ok": True, "records": recs}))
    (d / f"{P.SOURCE_ID}.json").write_text(json.dumps({"source_id": P.SOURCE_ID, "ok": True, "records": parks}))
    st, _ = S.build(now=datetime(2026, 11, 16, 13, 0, tzinfo=UTC), events_dir=d, write=False, waters=waters,
                    outfalls=[], placement_cache=False, reaches={}, flows=({}, {}), discharger_towns={},
                    discharger_waters={})
    return st


WATERS = {"lake-mohave-nv": {**_lake("Lake Mohave", "lake-mohave-nv", -114.65, 35.45, 0.05), "kind": "reservoir"},
          "walker-lake-nv": _lake("Walker Lake", "walker-lake-nv", -118.71, 38.7, 0.1),
          "rye-patch-reservoir-nv": {**_lake("Rye Patch Reservoir", "rye-patch-reservoir-nv", -118.316, 40.59, 0.05),
                                     "kind": "reservoir"}}


def test_coordinator_2_both_feeds_show_once_with_the_offices_stated_date_and_both_publishers(nv_live, tmp_path):
    """Coordinator decision 2026-11-16: where the Office and the parks both carry a water, the record with the stated
    date (the Office's) is shown, the parks' record is its duplicate, and both publishers are cited."""
    S = nv_live
    parks, _ = P.build(PARKS_PAGE, "2026-11-16T12:40:00Z", [])
    recs, meta = O.build(PAGE, T1, [], parks)
    rye = recs_by(recs)[("Rye Patch Reservoir", None)]
    prye = next(r for r in parks if r["raw"]["water_key"] == "rye-patch-reservoir")
    assert rye["duplicate_of"] is None and rye["raw"]["_shown_over"] == prye["event_id"]
    assert rye["started_at"] == "2026-09-30" and rye["time_precision"] == "day"
    assert "Nevada Office of State Epidemiology" in rye["authority"] and "Nevada Division of State Parks" in rye["authority"]
    assert rye["raw"]["also_cited"]["source_url"] == P.URL and rye["raw"]["also_cited"]["source_id"] == P.SOURCE_ID
    assert meta["shown_over_parks"] == 3
    st = _status(S, tmp_path, recs, parks, WATERS)
    dups = st.get("duplicates") or {}
    assert dups.get(prye["event_id"]) == rye["event_id"] and rye["event_id"] not in dups      # shown once: the Office's
    assert st["waters"]["rye-patch-reservoir-nv"]["status"] == "red"
    # the parks' record lifted: the Office's record shows on its own, the parks' record is no one's duplicate
    lifted = [dict(p, status="advisory_lifted") for p in parks]
    dups = _status(S, tmp_path, recs, lifted, WATERS, "c").get("duplicates") or {}
    assert prye["event_id"] not in dups and rye["event_id"] not in dups


def test_coordinator_2_the_stricter_level_is_shown_never_the_weaker():
    parks, _ = P.build(PARKS_PAGE, "2026-11-16T12:40:00Z", [])
    stricter = [dict(p, raw={**p["raw"], "level": "Danger"}) if p["raw"]["water_key"] == "rye-patch-reservoir" else p
                for p in parks]                                                   # invented: the parks say Danger
    rye = recs_by(O.build(PAGE, T1, [], stricter)[0])[("Rye Patch Reservoir", None)]
    assert rye["raw"]["level"] == "Danger" and rye["raw"]["office_level"] == "Watch"
    assert rye["advice_text"].startswith("HAB Danger advisory") and "parks' page lists HAB Danger" in rye["raw"]["level_basis"]
    lah = recs_by(O.build(PAGE, T1, [], parks)[0])[("Lahontan Reservoir", None)]     # both Warning
    assert lah["raw"]["level"] == "Warning" and "level_basis" not in lah["raw"]
    weaker = [dict(p, raw={**p["raw"], "level": "Watch"}) if p["raw"]["water_key"] == "lahontan-reservoir" else p
              for p in parks]
    lah = recs_by(O.build(PAGE, T1, [], weaker)[0])[("Lahontan Reservoir", None)]
    assert lah["raw"]["level"] == "Warning"                                           # never the weaker
    stale = [dict(p, raw={**p["raw"], "_last_seen_in_source": "2026-11-13T12:00:00Z"}) for p in parks]
    assert "_shown_over" not in recs_by(O.build(PAGE, T1, [], stale)[0])[("Rye Patch Reservoir", None)]["raw"]


def test_coordinator_1_a_record_of_this_feed_is_held_as_end_not_confirmed_in_an_outage(nv_live):
    from datetime import timedelta
    S = nv_live
    recs, _ = O.build(PAGE, T1, [])
    wl = recs_by(recs)[("Walker Lake", None)]
    health = {"fetched_at": "2026-12-20T12:00:00Z", "ok": False, "last_ok_at": "2026-11-16T12:43:00Z",
              "prev_ok_at": "2026-11-16T11:43:00Z"}
    t = S.parse_time(T1) + timedelta(days=30)
    c, ivs = S.status_at(S.event_intervals({**wl, "_feed_health": health}, "NV", t, None, S.load_rules()), t)
    assert c == "unresolved" and ivs[0]["rule"] == "outage_unconfirmed"


def test_the_status_build_colours_whole_waters_never_for_a_part(nv_live, tmp_path):
    S = nv_live
    recs, _ = O.build(PAGE, T1, [])
    st = _status(S, tmp_path, [r for r in recs if r["raw"]["part"]], [], WATERS, "parts")
    assert st["waters"]["lake-mohave-nv"]["status"] != "red"           # a cove's advisory never colours the whole lake
    st = _status(S, tmp_path, recs, [], WATERS, "all")
    assert st["waters"]["lake-mohave-nv"]["status"] == "red" and st["waters"]["walker-lake-nv"]["status"] == "red"


# ---- a bad read changes nothing ----------------------------------------------------------------------------------

@pytest.mark.parametrize("bad", [
    PAGE.replace("</html>", ""),                                                      # truncated
    PAGE.replace("Active HAB Reports", "Current HAB Reports"),                        # heading renamed
    PAGE.replace("Previous HAB Reports", "Past Reports"),
    PAGE.replace("</details>", "", 1),                                                # a block cut open
    "<html><body>Just a moment...</body></html>",                                     # a challenge page
    "",
])
def test_a_page_not_read_whole_raises(bad):
    with pytest.raises(ValueError):
        O.parse(bad, T1)


def test_an_empty_active_section_needs_the_explicit_marker():
    blank = PAGE
    for s in ("Mountain View Pond", "Lahontan Reservoir", "Lake Mohave including", "Rye Patch", "Wild Horse",
              "Virginia Lake", "South Meadows", "Walker Lake"):
        blank = drop_block(blank, s)
    with pytest.raises(ValueError, match="does not say there are no active"):
        O.parse(blank, T1)
    marked = blank.replace('<h2 class="accordions__title">Active HAB Reports</h2>',
                           '<h2 class="accordions__title">Active HAB Reports</h2><p>There are currently no active HABs.</p>')
    prev, _ = O.build(PAGE, T1, [])
    recs, meta = O.build(marked, T2, prev)
    assert meta["advisories_read"] == 0 and all(r["status"] == "advisory_lifted" for r in recs) and len(recs) == 11
    assert all(r["ended_at"] == T2 and r["raw"]["ended_at_precision"] == "poll" for r in recs)
    with pytest.raises(ValueError, match="beside listed waters"):
        O.parse(PAGE.replace('<h2 class="accordions__title">Active HAB Reports</h2>',
                             '<h2 class="accordions__title">Active HAB Reports</h2><p>No active HABs.</p>'), T1)


class _Resp:
    def __init__(self, text):
        self.text, self.headers, self.status_code = text, {}, 200

    def raise_for_status(self):
        return None


@pytest.fixture
def run(tmp_path, monkeypatch):
    import common
    monkeypatch.setattr(O, "EVENTS_DIR", tmp_path)
    monkeypatch.setattr(common, "EVENTS_DIR", tmp_path)
    saved = []
    monkeypatch.setattr(O, "save_raw", lambda src, body, ext: saved.append((ext, body)) or tmp_path / "raw")

    def go(page, stamp):
        monkeypatch.setattr(O, "now_iso", lambda: stamp)
        monkeypatch.setattr(O.requests, "get", lambda *a, **k: _Resp(page))
        code = O.main([])
        return code, json.loads((tmp_path / f"{O.SOURCE_ID}.json").read_text())
    go.saved = saved
    return go


def test_a_failed_read_keeps_every_record_and_fails_health(run):
    code, doc = run(PAGE, T1)
    assert code == 0 and doc["ok"] and len(doc["records"]) == 11
    code, doc = run(PAGE.replace("</html>", ""), T2)
    assert code == 1 and doc["ok"] is False and doc["last_ok_at"] is not None
    assert len(doc["records"]) == 11 and all(r["status"] == "advisory_active" for r in doc["records"])


def test_one_unreadable_block_is_held_the_rest_update_and_health_stays_false(run):
    code, doc = run(PAGE, T1)
    page = PAGE.replace("Walker Lake HAB advisory level has been lowered from a HAB Warning to a",
                        "Walker Lake HAB advisory level may soon change from a HAB Warning to a")      # invented
    page = drop_block(page, "Virginia Lake")
    code, doc = run(page, T2)
    assert code == 1 and doc["ok"] is False
    assert [u["heading"] for u in doc["meta"]["unread"]] == ["Walker Lake"]
    by = recs_by(doc["records"])
    assert by[("Walker Lake", None)]["status"] == "advisory_active" and by[("Walker Lake", None)]["ended_at"] is None
    assert by[("Walker Lake", None)]["raw"]["_held_unread"]
    # a partial read ends nothing (Astra review P1-3): Virginia Lake's absence is not taken as its end
    assert by[("Virginia Lake", None)]["status"] == "advisory_active" and by[("Virginia Lake", None)]["ended_at"] is None
    assert by[("Lake Mohave", None)]["raw"]["_last_seen_in_source"] == T2


def test_an_advisory_paragraph_naming_an_unlisted_place_leaves_the_block_unread():
    page = PAGE.replace("Cottonwood Cove has been placed", "Katherine Landing has been placed")    # not in the heading
    recs, meta = O.build(page, T1, [])
    assert meta["unread"][0]["reason"] == "an advisory for a place the block's heading does not name"
    assert not any(r["raw"]["water"] == "Lake Mohave" for r in recs)


def test_negation_is_not_a_level_or_a_lift():
    page = PAGE.replace("Wild Horse Reservoir has been placed on", "Wild Horse Reservoir has not been placed on")
    assert O.build(page, T1, [])[1]["unread"][0]["heading"] == "Wild Horse Reservoir"
    prev, _ = O.build(PAGE, T1, [])
    gone = drop_block(PAGE, "Walker Lake").replace(
        "<p><strong>Washoe Lake (Big)</strong></p>",
        "<p>Walker Lake's HAB advisory will be lifted when results allow.</p><p><strong>Washoe Lake (Big)</strong></p>", 1)
    wl = recs_by(O.build(gone, T2, prev)[0])[("Walker Lake", None)]
    assert wl["ended_at"] == T2 and wl["raw"]["ended_at_precision"] == "poll" and wl["raw"]["end_basis"] == O.END_BASIS


def test_a_lift_the_office_states_with_a_date_is_the_end():
    prev, _ = O.build(PAGE, T1, [])
    gone = drop_block(PAGE, "Walker Lake").replace(
        "<p><strong>Washoe Lake (Big)</strong></p>",
        "<p>Walker Lake's HAB advisory has been lifted as of 11/10/2026.</p><p><strong>Washoe Lake (Big)</strong></p>", 1)
    recs, meta = O.build(gone, T2, prev)
    wl = recs_by(recs)[("Walker Lake", None)]
    assert wl["status"] == "advisory_lifted" and wl["ended_at"] == "2026-11-10"
    assert wl["raw"]["ended_at_precision"] == "day" and wl["raw"]["end_basis"] == O.STATED_END_BASIS
    # a stated date before the advisory's own start is not its end
    early = gone.replace("lifted as of 11/10/2026", "lifted as of 1/10/2026")
    wl = recs_by(O.build(early, T2, prev)[0])[("Walker Lake", None)]
    assert wl["ended_at"] == T2 and wl["raw"]["ended_at_precision"] == "poll"


def test_a_level_change_keeps_the_record_and_a_relisting_is_a_new_record():
    prev, _ = O.build(PAGE, T1, [])
    down = re.sub(r"On 11/2/26 the Lahontan Reservoir advisory level has been lowered from a (.*?)HAB Danger(.*?)HAB Warning",
                  r"On 11/15/26 the Lahontan Reservoir advisory level has been lowered from a \1HAB Warning\2HAB Watch",
                  PAGE, count=1)
    assert down != PAGE
    recs, _ = O.build(down, T2, prev)
    a, b = recs_by(prev)[("Lahontan Reservoir", None)], recs_by(recs)[("Lahontan Reservoir", None)]
    assert a["event_id"] == b["event_id"] and b["raw"]["level"] == "Watch" and b["started_at"] == a["started_at"]
    assert b["raw"]["level_history"][-1] == {"level": "Watch", "date": "2026-11-15", "seen_at": T2}
    gone, _ = O.build(drop_block(PAGE, "Virginia Lake"), T2, prev)
    back, _ = O.build(PAGE, T3, gone)
    vl = [r for r in back if r["raw"]["water"] == "Virginia Lake"]
    assert len(vl) == 2 and {r["status"] for r in vl} == {"advisory_active", "advisory_lifted"}
    assert len({r["event_id"] for r in vl}) == 2
    old = next(r for r in vl if r["status"] == "advisory_lifted")
    assert old["ended_at"] == T2 and old["started_at"] == "2026-06-23"


def test_ids_do_not_depend_on_order():
    a, _ = O.build(PAGE, T1, [])
    swapped = drop_block(PAGE, "Walker Lake")
    m = re.search(r"<details\b[^>]*>\s*<summary\b[^>]*>\s*Walker Lake.*?</details>", PAGE, re.S)
    swapped = swapped.replace('<h2 class="accordions__title">Active HAB Reports</h2>\n',
                              '<h2 class="accordions__title">Active HAB Reports</h2>\n' + m.group(0), 1)
    b, _ = O.build(swapped, T1, [])
    assert {r["event_id"] for r in a} == {r["event_id"] for r in b}


# ---- privacy -----------------------------------------------------------------------------------------------------

PRIVATE = ("Pat Example", "775-555-0100", "pat@example.org", "1234-A Example St", "39.12345", "Jane Sample")


def test_nothing_personal_reaches_any_save_and_advice_about_contact_with_water_stays(run):
    extra = (" Contact Pat Example at 775-555-0100 or pat@example.org. A bloom was seen near the home of Jane Sample, "
             "1234-A Example St, at 39.12345, -119.54321. Dr. Jane Sample reported it.")              # invented
    page = PAGE.replace("following visual observation and satellite imaging of a surface bloom. Hazardous",
                        "following visual observation and satellite imaging of a surface bloom." + extra + " Hazardous", 1)
    code, doc = run(page, T1)
    assert code == 0
    blob = json.dumps(doc) + json.dumps(run.saved)
    for p in PRIVATE:
        assert p not in blob, p
    assert len(run.saved) == 1 and run.saved[0][0] == "json" and "<" not in run.saved[0][1]
    mv = recs_by(doc["records"])[("Lake Mohave", None)]
    assert mv["raw"]["sentences_withheld"] == 3
    assert "avoid areas of algae accumulation" in mv["advice_text"] and "in contact with water" in mv["advice_text"]
    sm = recs_by(doc["records"])[("South Meadows Community Pond", None)]
    assert "People and pets should avoid contact with the water." in sm["advice_text"]
    lah = recs_by(doc["records"])[("Lahontan Reservoir", None)]
    assert "Contact with water is strongly discouraged." in lah["advice_text"]
    # the refused read's path cleans carried records again
    bad = dict(doc)
    bad["records"] = [dict(r, advice_text=r["advice_text"] + " Call Pat Example at 775-555-0100.") for r in doc["records"]]
    Path(O.EVENTS_DIR / f"{O.SOURCE_ID}.json").write_text(json.dumps(bad))
    code, doc = run("", T2)
    assert code == 1 and "Pat Example" not in json.dumps(doc) and "775-555-0100" not in json.dumps(doc)


# ---- registry, list and texts ------------------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[2]


def test_the_source_file_and_register_row_say_the_list_is_ingested():
    import yaml
    src = yaml.safe_load((ROOT / "data" / "sources" / "nv-ose-hab-reports.yaml").read_text())
    assert src["id"] == O.SOURCE_ID and src["url"] == O.URL and src["event_types"] == ["hab_advisory"]
    doc = json.loads((ROOT / "data" / "notice-channels" / "nv.json").read_text())
    rows = doc if isinstance(doc, list) else doc.get("channels") or doc.get("rows") or []
    row = next(r for r in rows if r.get("id") == O.SOURCE_ID)
    assert row.get("feed_source_id") == O.SOURCE_ID
    text = (ROOT / "research" / "nv" / "state-text.md").read_text()
    assert "does not yet read" not in text and "Virginia Lake" in text


# ---- Astra review 2026-11-16 (scratchpad reviews/astra-nv-ose-review.md) -------------------------------------------

def test_review_p1_1_an_unread_blocks_key_carries_nothing_personal():
    page = PAGE.replace("Wild Horse Reservoir            </summary>",
                        "Wild Horse Reservoir reported by Pat Example at 775-555-0100</summary>").replace(
        "as of 8/13/2026", "as of 13/45/2026")                                                     # invented
    _, meta = O.build(page, T1, [])
    assert meta["unread"] and "Pat" not in json.dumps(meta) and "775" not in json.dumps(meta)
    assert "pat" not in meta["unread"][0]["block_key"] and "775" not in meta["unread"][0]["block_key"]


def test_review_p1_2_advisory_text_outside_a_read_block_fails_the_read():
    m = re.search(r"<details\b[^>]*>\s*<summary\b[^>]*>\s*(Walker Lake)\s*</summary>(.*?)</details>", PAGE, re.S)
    page = PAGE.replace(m.group(0), f"<div><h3>{m.group(1)}</h3>{m.group(2)}</div>")
    with pytest.raises(ValueError, match="outside"):
        O.parse(page, T1)


def test_review_p1_3_a_partial_read_ends_nothing():
    prev, _ = O.build(PAGE, T1, [])
    page = drop_block(PAGE, "Walker Lake").replace("as of 8/13/2026", "as of 13/45/2026")
    recs, meta = O.build(page, T2, prev)
    assert meta["unread"] and meta["lifted_this_read"] == 0
    assert all(r["status"] == "advisory_active" for r in recs) and len(recs) == 11


def test_review_p1_4_a_place_that_contradicts_the_known_water_is_never_tied():
    page = PAGE.replace("Rye Patch Reservoir has been downgraded",
                        "Rye Patch Reservoir in Lincoln County, NV has been downgraded")             # invented
    rye = recs_by(O.build(page, T1, [])[0])[("Rye Patch Reservoir", None)]
    assert rye["raw"]["_placement"] == "listed_only" and rye["raw"]["place"] == "Lincoln County, NV"
    ok = PAGE.replace("Rye Patch Reservoir has been downgraded",
                      "Rye Patch Reservoir in Pershing County has been downgraded")
    assert recs_by(O.build(ok, T1, [])[0])[("Rye Patch Reservoir", None)]["raw"]["_placement"] == "named_water_only"


def test_coordinator_2_the_shown_over_rule_is_keyed_on_this_source():
    from build import status as S
    a = {"event_id": "x:1", "source_id": "x", "status": "advisory_active", "time_precision": "day",
         "raw": {"_shown_over": "y:1"}}
    b = {"event_id": "y:1", "source_id": "y", "status": "advisory_active", "time_precision": "poll", "raw": {}}
    assert S.shown_over_links([a, b], {"q:1": "r:1"}) == {"q:1": "r:1"}
