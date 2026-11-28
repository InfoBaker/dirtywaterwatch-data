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
    assert len(cs) == 116
    for c in cs:
        w = waters.get(c["water_slug"])
        assert w, c["water_slug"]
        assert w.get("state") == c["state"], c
        assert (w.get("name"), w.get("kind")) == (c["water_name"], c["water_kind"]), c
        assert c["was"] in waters and c["was"] != c["water_slug"]
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
