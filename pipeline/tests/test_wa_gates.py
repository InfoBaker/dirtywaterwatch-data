"""Washington's go-live gates (2026-11-06): the NHD records tidied against openboatlaunch's extract, the King County and
Seattle outfalls tied by the operators' own lists (Ecology's permits WA0029181, WA0031682 and WA0029581, and Seattle
Public Utilities' CSO basin layer), the Census TIGER/Line records those lists need, and Puget Sound under the shoreline
model. Data tests on the files as committed; no network.
Run from pipeline/: python -m pytest tests/test_wa_gates.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def _json(name):
    return json.loads((DATA / name).read_text())


def _nhd_wa():
    return [r for r in _json("waters-nhd.json")["waters"] if r.get("state") == "WA"]


def _obl_wa():
    return {r["slug"]: r for r in _json("waters-wa.json")["waters"]}


def test_no_washington_nhd_record_hides_behind_an_openboatlaunch_slug():
    """The tidy (waters_from_nhd --state WA --tidy) ran after openboatlaunch's extract: an NHD record that shared a
    slug with an openboatlaunch record was either the same water (dropped) or another one (renamed). Before it, 35
    shared a slug and the status build kept openboatlaunch's: Renton's Black River was read as the Black River
    near Olympia, 78 km away, and two King County South plant outfalls were tied to it."""
    obl = _obl_wa()
    shared = sorted(r["slug"] for r in _nhd_wa() if r["slug"] in obl)
    assert shared == []
    renton = [r for r in _nhd_wa() if r["slug"] == "black-river-renton-wa"]
    assert len(renton) == 1 and renton[0]["name"] == "Black River" and "Renton" in renton[0]["towns"]
