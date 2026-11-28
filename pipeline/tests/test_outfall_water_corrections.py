"""Hand corrections to registry outfalls' water records (data/outfall-water-corrections.json,
ingest.outfall_water_corrections; registry water audit 2026-11-28). Data tests on the files as committed, and the
mechanism that keeps a correction through a rebuild. No network.
Run from pipeline/: python -m pytest tests/test_outfall_water_corrections.py -q
"""
from __future__ import annotations

import copy
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ingest import outfall_water_corrections as H  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def _rows(name):
    return json.loads((DATA / name).read_text())["outfalls"]


def _entry(**kw):
    e = {"file": "outfalls-new-england.json", "npdes_permit": "MA0100382", "outfall": "002", "state": "MA",
         "stated": "Mount Hope Bay", "was": "narragansett-bay-ma", "water_slug": "mount-hope-bay-ma",
         "water_name": "Mount Hope Bay", "water_kind": "bay", "distance_m": 0, "date": "2026-11-28",
         "basis": "the permit's receiving water in EPA's CSO inventory is 'Mount Hope Bay'"}
    e.update(kw)
    return e


def _matchers_row():
    """A row as scripts/match_outfalls.py writes it (the shape a rebuild resets a corrected row to)."""
    return {"npdes_permit": "MA0100382", "outfall": "002", "state": "MA", "receiving_water_echo": "Mount Hope Bay",
            "lat": 41.6799933, "lon": -71.1948204, "water_slug": "narragansett-bay-ma", "water_name": "Narragansett Bay",
            "water_kind": "bay", "distance_m": 233, "match": "geometry",
            "water_match": "EPA's point lies 233 m from Narragansett Bay", "water_matched_by": "scripts/match_outfalls.py (2026-11-01)"}


def test_every_entry_names_a_record_of_its_state_with_its_name_and_kind():
    from build import status as S
    waters = S.load_waters()
    cs = H.load()
    assert len(cs) == 138
    for c in cs:
        w = waters.get(c["water_slug"])
        assert w, c["water_slug"]
        assert w.get("state") == c["state"], c
        assert (w.get("name"), w.get("kind")) == (c["water_name"], c["water_kind"]), c
        # was None: the row had no water at all (untraced-outfall water fixes 2026-11-28: Defiance's Preston Run rows)
        assert c["was"] is None or (c["was"] in waters and c["was"] != c["water_slug"])
        assert 0 <= c["distance_m"] <= 400
        assert c["stated"] in c["basis"] and c["basis"].startswith("the permit's receiving water")
    assert len({(c["file"], c["npdes_permit"], c["outfall"]) for c in cs}) == len(cs)


def test_the_files_as_committed_carry_every_correction():
    by_file = defaultdict(list)
    for c in H.load():
        by_file[c["file"]].append(c)
    for name, cs in by_file.items():
        rows = _rows(name)
        assert H.check(name, rows) == [], name
        keys = {(str(o["npdes_permit"]), str(o["outfall"])) for o in rows}
        assert all((c["npdes_permit"], c["outfall"]) in keys for c in cs)
        before = json.dumps(rows, sort_keys=True)
        assert H.apply_rows(name, rows) == []
        assert json.dumps(rows, sort_keys=True) == before        # applying again changes nothing


def test_a_row_a_rebuild_reset_is_corrected_again():
    rows = [_matchers_row()]
    assert H.apply_rows("outfalls-new-england.json", rows, [_entry()]) == []
    o = rows[0]
    assert o["water_slug"] == "mount-hope-bay-ma" and o["match"] == "geometry+name" and o["distance_m"] == 0
    assert o["water_match"].startswith("hand correction: ") and "Mount Hope Bay" in o["water_match"]
    assert H.is_hand(o)
    assert o["replaced_match"]["water_slug"] == "narragansett-bay-ma"
    assert o["replaced_match"]["by"].startswith("scripts/match_outfalls.py")
    assert o["lat"] == 41.6799933 and o["receiving_water_echo"] == "Mount Hope Bay"    # point and text untouched


def test_a_row_whose_text_changed_is_left_as_it_is():
    row = dict(_matchers_row(), receiving_water_echo="Taunton River")
    rows = [row]
    keep = copy.deepcopy(rows)
    problems = H.apply_rows("outfalls-new-england.json", rows, [_entry()])
    assert problems and "not corrected" in problems[0]
    assert rows == keep


def test_the_registry_pass_keeps_a_corrected_row_and_applies_the_file_after_it():
    """ingest.outfall_waters: match_cso_row and match_plant_row keep a hand row without matching it again."""
    from ingest import outfall_waters as OW
    rows = [_matchers_row()]
    H.apply_rows("outfalls-new-england.json", rows, [_entry()])
    o = rows[0]
    keep = copy.deepcopy(o)
    counts, diag = defaultdict(Counter), []
    OW.match_cso_row(None, "outfalls-new-england.json", o, Counter(), diag, counts)    # no matcher needed: kept first
    assert o == keep and counts["MA"]["kept: hand correction"] == 1 and diag == []
    OW.match_plant_row(None, o, counts, diag)
    assert o == keep and counts["MA"]["kept: hand correction"] == 2


def test_status_places_a_report_at_a_corrected_outfall_on_the_corrected_water():
    from build import status as S
    waters = S.load_waters()
    res = S.make_resolver(waters)
    row = next(o for o in _rows("outfalls-new-england.json") if (o["npdes_permit"], o["outfall"]) == ("MA0100382", "002"))
    slug, how = res.row_water(dict(row, _file="data/outfalls-new-england.json"))
    assert slug == "mount-hope-bay-ma", how
    row = next(o for o in _rows("outfalls-new-england.json") if (o["npdes_permit"], o["outfall"]) == ("ME0102075", "010"))
    assert res.row_water(dict(row, _file="data/outfalls-new-england.json"))[0] == "back-cove-me"


def test_springfield_mill_river_rows_keep_the_dammed_stretch_in_their_basis():
    rows = {o["outfall"]: o for o in _rows("outfalls-new-england.json") if o["npdes_permit"] == "MA0101613"}
    for k in ("024", "025", "048"):
        o = rows[k]
        assert o["water_slug"] == "mill-river-springfield-ma"
        assert "Lake Massasoit" in o["water_match"] and "dammed stretch" in o["water_match"]
        assert o["replaced_match"]["water_slug"] == "lake-massasoit-ma"


# ---------------------------------------------------------------- registry water review 2026-11-28 (P2-2, P3)

def _write(d, name, rows):
    (d / name).write_text(json.dumps({"outfalls": rows}, indent=1))


def test_an_outfall_number_in_another_form_is_corrected_in_every_copy_and_the_loaders_copy_is_checked(tmp_path):
    """EPA writes '2' where the row said '002': both rows stand in the file (a permit-scoped append keeps the old one),
    the loader reads one of them, so every copy is corrected, in the entry's file and any other registry file, and
    check_registry() fails while the copy the loader reads is not corrected."""
    from common import load_outfall_registry
    new = dict(_matchers_row(), outfall="2")
    old = _matchers_row()
    rows = [new, old]
    assert H.apply_rows("outfalls-new-england.json", rows, [_entry()]) == []
    assert all(o["water_slug"] == "mount-hope-bay-ma" and H.is_hand(o) for o in rows)
    # a copy in another registry file (the entry names the regional file) is corrected too
    us = [dict(_matchers_row(), outfall="02")]
    assert H.apply_rows("outfalls-us.json", us, [_entry()]) == []
    assert us[0]["water_slug"] == "mount-hope-bay-ma"
    # the files as a rebuild left them: the old '002' corrected, EPA's new '2' (read by the loader) not
    old_fixed = copy.deepcopy(rows[1])
    _write(tmp_path, "outfalls-new-england.json", [dict(_matchers_row(), outfall="2"), old_fixed])
    loaded = [o for o in load_outfall_registry(tmp_path, provisional=False) if o["npdes_permit"] == "MA0100382"]
    assert [o["outfall"] for o in loaded] == ["2"]
    probs = H.check_registry(tmp_path, [_entry()])
    assert any("(row outfall '2')" in p and "differ" in p for p in probs), probs
    assert any("the registry loader reads the row of data/outfalls-new-england.json (outfall '2'), which is not "
               "corrected" in p for p in probs), probs
    assert H.check("outfalls-new-england.json", [dict(_matchers_row(), outfall="2"), old_fixed], [_entry()])
    # applied to the file, all is well
    doc = json.loads((tmp_path / "outfalls-new-england.json").read_text())
    assert H.apply_rows("outfalls-new-england.json", doc["outfalls"], [_entry()]) == []
    _write(tmp_path, "outfalls-new-england.json", doc["outfalls"])
    assert H.check_registry(tmp_path, [_entry()]) == []
    # an entry whose outfall the registry no longer holds fails too
    _write(tmp_path, "outfalls-new-england.json", [])
    probs = H.check_registry(tmp_path, [_entry()])
    assert any("no such row" in p for p in probs) and any("reads no row" in p for p in probs)


def test_a_corrected_row_whose_receiving_water_text_changed_goes_back_to_the_matchers_tie_and_needs_review(tmp_path):
    """EPA's text on a corrected row changes in place ('Mount Hope Bay' to 'Taunton River'): the correction is neither
    applied nor kept; the row goes back to the tie it replaced, and check() names the entry as needing review."""
    from ingest import outfall_waters as OW
    rows = [_matchers_row()]
    H.apply_rows("outfalls-new-england.json", rows, [_entry()])
    rows[0]["receiving_water_echo"] = "Taunton River"
    changed = copy.deepcopy(rows[0])
    probs = H.check("outfalls-new-england.json", [changed], [_entry()])
    assert len(probs) == 1 and "MA0100382:002" in probs[0] and "needs review" in probs[0]
    assert "'Taunton River', not 'Mount Hope Bay'" in probs[0] and "still carries the correction" in probs[0]
    _write(tmp_path, "outfalls-new-england.json", [changed])
    assert any("needs review" in p for p in H.check_registry(tmp_path, [_entry()]))
    assert not H.holds(changed, [_entry()])
    # applying the file again does not keep the old tie
    p = H.apply_rows("outfalls-new-england.json", rows, [_entry()])
    assert p and "needs review" in p[0]
    o = rows[0]
    assert not H.is_hand(o) and o["water_slug"] == "narragansett-bay-ma" and o["match"] == "geometry"
    assert o["water_matched_by"].startswith("scripts/match_outfalls.py") and "replaced_match" not in o
    assert o["distance_m"] == 233 and o["water_kind"] == "bay"          # the replaced tie's own values
    assert o["receiving_water_echo"] == "Taunton River" and o["lat"] == 41.6799933
    # the registry pass does the same before it matches the row (no longer kept as a hand correction)
    o2 = copy.deepcopy(changed)
    counts = defaultdict(Counter)
    assert OW.hand_kept(o2, counts) is False
    assert counts["MA"]["hand correction no longer applies: matched again"] == 1
    assert o2["water_slug"] == "narragansett-bay-ma" and not H.is_hand(o2)
    # a row whose correction holds is kept
    held = [_matchers_row()]
    H.apply_rows("outfalls-new-england.json", held, [_entry()])
    assert OW.hand_kept(held[0], counts) is True and counts["MA"]["kept: hand correction"] == 1


# ---------------------------------------------------------------- untraced-outfall fixes 2026-11-28 (the module's defects)

def _no_water_row(**kw):
    """A row the registry pass left with no water (ingest.outfall_waters: no record of the permit's name then)."""
    o = {"npdes_permit": "OH0024899", "outfall": "014", "state": "OH", "receiving_water_echo": "Preston Run",
         "lat": 41.28, "lon": -84.36, "water_slug": None, "water_name": None, "water_kind": None, "distance_m": None,
         "match": "none", "water_match": "none: no record named 'Preston Run' in OH",
         "no_water_reason": "no record named 'Preston Run' in OH", "water_matched_by": "ingest.outfall_waters (2026-11-17)"}
    o.update(kw)
    return o


def _preston(**kw):
    e = {"file": "outfalls-us.json", "npdes_permit": "OH0024899", "outfall": "014", "state": "OH", "stated": "Preston Run",
         "was": None, "water_slug": "preston-run-oh", "water_name": "Preston Run", "water_kind": "stream",
         "distance_m": 96, "date": "2026-11-28",
         "basis": "the permit's receiving water in EPA's CSO inventory is 'Preston Run'"}
    e.update(kw)
    return e


def test_a_row_that_had_no_water_is_not_said_to_have_had_another_one():
    rows = [_no_water_row()]
    assert H.apply_rows("outfalls-us.json", rows, [_preston()]) == []
    why = rows[0]["replaced_match"]["why"]
    assert "another water" not in why and "no water record" in why
    # a row that had a water keeps the wording of a re-tie
    rows = [_matchers_row()]
    H.apply_rows("outfalls-new-england.json", rows, [_entry()])
    assert rows[0]["replaced_match"]["why"] == "the permit names another water, which has its own record at the point"


def test_revert_gives_back_the_reason_the_row_had_no_water():
    rows = [_no_water_row()]
    H.apply_rows("outfalls-us.json", rows, [_preston()])
    o = rows[0]
    assert "no_water_reason" not in o and o["replaced_match"]["no_water_reason"] == "no record named 'Preston Run' in OH"
    o["receiving_water_echo"] = "Preston Ditch"                 # the permit's text changed: the correction goes back
    assert H.apply_rows("outfalls-us.json", rows, [_preston()])
    assert o["water_slug"] is None and o["match"] == "none" and not H.is_hand(o)
    assert o["no_water_reason"] == "no record named 'Preston Run' in OH"
    assert o["water_match"] == "none: no record named 'Preston Run' in OH" and "replaced_match" not in o


def test_the_committed_rows_that_had_no_water_say_so_and_keep_their_reason():
    for o in _rows("outfalls-us.json"):
        before = o.get("replaced_match") if H.is_hand(o) else None
        if before is not None and not before.get("water_slug"):
            assert "another water" not in before["why"], (o["npdes_permit"], o["outfall"])
            assert before.get("no_water_reason"), (o["npdes_permit"], o["outfall"])


def _ninemile(**kw):
    e = {"file": "outfalls-oh.json", "npdes_permit": "OH0043991", "outfall": "211", "state": "OH",
         "stated": "Nine Mile Creek", "was": None, "water_slug": "ninemile-creek-cleveland-oh",
         "water_name": "Ninemile Creek", "water_kind": "stream", "distance_m": 10, "date": "2026-11-28",
         "basis": "the permit's receiving water in NEORSD's CSO notification layer is 'Nine Mile Creek'"}
    e.update(kw)
    return e


def test_a_copy_with_no_receiving_water_text_in_another_file_takes_the_entry():
    """NEORSD's outfall 211: the row the loader reads (data/outfalls-oh.json) names Nine Mile Creek; EPA's copy in
    data/outfalls-us.json has no text at all, which says nothing against the entry, so it is corrected too and not
    flagged for review. The entry's own row must still carry the text."""
    us = [_no_water_row(npdes_permit="OH0043991", outfall="211", receiving_water_echo=None)]
    assert H.apply_rows("outfalls-us.json", us, [_ninemile()]) == []
    assert us[0]["water_slug"] == "ninemile-creek-cleveland-oh" and H.is_hand(us[0])
    assert H.check("outfalls-us.json", us, [_ninemile()]) == []
    assert H.holds(us[0], [_ninemile()])
    # the entry's own file: a row with no text is not the row the correction read
    oh = [_no_water_row(npdes_permit="OH0043991", outfall="211", receiving_water_echo=None)]
    p = H.apply_rows("outfalls-oh.json", oh, [_ninemile()])
    assert p and "needs review" in p[0] and oh[0]["water_slug"] is None
    # a copy in another file whose text names another water still needs review
    other = [_no_water_row(npdes_permit="OH0043991", outfall="211", receiving_water_echo="Euclid Creek")]
    assert H.apply_rows("outfalls-us.json", other, [_ninemile()]) and other[0]["water_slug"] is None
