"""Nebraska's go-live gates (2026-11-07): every one of Omaha's open combined sewer outfalls (permit NE0133680, EPA's
CSO inventory in data/outfalls-us.json) has a water record, the four on an 'Outfall channel to Missouri River' tied
to the Missouri River by scripts/ne_gate_ties.py. Data tests on the files as committed; no network.
Run from pipeline/: python -m pytest tests/test_ne_gates.py -q
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ROOT = Path(__file__).resolve().parents[2]
DATA = ROOT / "data"


def _omaha_cso():
    rows = json.loads((DATA / "outfalls-us.json").read_text())["outfalls"]
    return {str(o["outfall"]): o for o in rows if o.get("npdes_permit") == "NE0133680"}


def _script():
    spec = importlib.util.spec_from_file_location("ne_gate_ties", ROOT / "scripts" / "ne_gate_ties.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_every_open_omaha_cso_outfall_has_a_water_record():
    from build import status as S
    waters = S.load_waters()
    rows = {k: o for k, o in _omaha_cso().items() if not str(o.get("outfall_status") or "").upper().startswith("CLS")}
    assert len(rows) == 25
    untied = sorted(k for k, o in rows.items() if not o.get("water_slug"))
    assert untied == []
    assert all(o["water_slug"] in waters for o in rows.values())


def test_the_outfall_channel_rows_go_to_the_missouri_by_the_text_not_to_a_channel():
    """'Outfall channel to Missouri River' names the water the channel carries the overflow to: the cloud ties of
    2026-11-07 read 'Outfall channel' as the water and left 105 to 108 without one, while 111 to 117 (the same text,
    nearer the river line) kept the Missouri River."""
    rows = _omaha_cso()
    channel = sorted(k for k, o in rows.items() if o.get("receiving_water_echo", "").rstrip(".") ==
                     "Outfall channel to Missouri River")
    assert channel == ["105", "106", "107", "108", "111", "112", "114", "115", "117"]
    assert {rows[k]["water_slug"] for k in channel} == {"missouri-river-ne"}
    for k in ("105", "106", "107", "108"):
        o = rows[k]
        assert o["receiving_water_override"]["water"] == "Missouri River"
        assert "Outfall channel to Missouri River" in o["receiving_water_override"]["basis"]
        assert o["water_matched_by"].startswith("scripts/ne_gate_ties.py")
        assert "no_water_reason" not in o and "replaced_match" not in o
        assert o["match"] == "name_only" and 500 <= o["distance_m"] <= 1100      # a centre line: the bank is nearer


def test_the_table_is_what_the_file_says():
    mod = _script()
    doc = json.loads((DATA / "outfalls-us.json").read_text())
    before = json.dumps(doc, sort_keys=True)
    from build import status as S
    assert mod.apply(doc, S.load_waters()) == []
    assert json.dumps(doc, sort_keys=True) == before


def test_a_row_whose_text_changed_is_not_tied_by_the_table():
    mod = _script()
    doc = {"outfalls": [{"npdes_permit": "NE0133680", "outfall": "105", "receiving_water_echo": "Cole Creek"}]}
    missing = mod.apply(doc, {"missouri-river-ne": {"name": "Missouri River", "kind": "river"}})
    assert "NE0133680/105" in missing
    assert "water_slug" not in doc["outfalls"][0]
