"""Name resolution with data/waters-extra.json aliases and town disambiguation (build/status.py Resolver).
Run from pipeline/: python -m pytest tests -q
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from build import status as S  # noqa: E402
from common import event  # noqa: E402


def w(slug, name, state, towns, aliases=(), kind="river"):
    return slug, {"slug": slug, "name": name, "kind": kind, "state": state, "towns": list(towns),
                  "aliases": list(aliases), "bbox": [-73, 42, -72, 43]}


WATERS = dict([
    w("mill-river-ma", "Mill River", "MA", ["Northampton"]),
    w("mill-river-springfield-ma", "Mill River", "MA", ["Agawam", "Springfield"], ["Mill R."]),
    w("north-branch-winooski-river-vt", "North Branch Winooski River", "VT", ["Montpelier"],
      ["North Branch", "North Branch of the Winooski River"]),
    w("east-creek-rutland-vt", "East Creek", "VT", ["Rutland", "Rutland Town"]),
    w("east-creek-vt", "East Creek", "VT", ["Orwell"]),
    w("pine-street-barge-canal-vt", "Pine Street Barge Canal", "VT", ["Burlington"], ["Pine St Barge Canal"], "canal"),
])


def ev(text, permit=None, raw=None, did=None):
    return event(source_id="t", source_record_id=text, event_type="cso", status="ended", waterbody_text=text,
                 npdes_permit=permit, discharger_id=did, raw=raw or {})


def test_aliases_are_names_short_ones_only_as_the_whole_text():
    r = S.Resolver(WATERS, [])
    assert r.resolve(ev("North Branch", "VT0100013"))["water_slugs"] == ["north-branch-winooski-river-vt"]
    assert r.resolve(ev("Pine St Barge Canal", "VT0100153"))["water_slugs"] == ["pine-street-barge-canal-vt"]
    # a short alias inside a longer text is not a match
    assert r.resolve(ev("North Branch of the Lamoille", "VT0100013"))["water_slugs"] == []
    # three words or more match inside a longer text, like a name
    assert r.resolve(ev("CSO to the North Branch of the Winooski River at Barre", "VT0100013"))["water_slugs"] == \
        ["north-branch-winooski-river-vt"]


def test_a_shared_name_is_settled_by_the_dischargers_towns():
    r = S.Resolver(WATERS, [], {"MA0101613": ["Springfield"]})
    pl = r.resolve(ev("MILL R.", "MA0101613"))
    assert pl["water_slugs"] == ["mill-river-springfield-ma"] and pl["water_match"] == "name"


def test_a_shared_name_is_settled_by_the_records_municipality():
    r = S.Resolver(WATERS, [])
    assert r.resolve(ev("East Creek", "VT0100374", raw={"Municipality": "Rutland City"}))["water_slugs"] == \
        ["east-creek-rutland-vt"]
    assert r.resolve(ev("east creek", "VT0100999", raw={"Town": "Town of Orwell"}))["water_slugs"] == ["east-creek-vt"]


def test_an_unsettled_shared_name_is_left_unplaced_as_ambiguous():
    r = S.Resolver(WATERS, [], {"VT0100374": ["Castleton"]})
    pl = r.resolve(ev("East Creek", "VT0100374"))
    assert pl["water_slugs"] == [] and pl["unplaced_reason"] == "ambiguous name"
    assert "east-creek-rutland-vt" in pl["note"]
