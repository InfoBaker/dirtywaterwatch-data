"""Michigan's registry rows (data/dischargers.json, data/notice-channels/mi.json) and the scripts that make them
(scripts/add_mi_operators.py, scripts/add_mi_register_rows.py): no individual named, one row per permit, towns that
are towns, and the 324.3112a duty rows only for sewer systems.
Run from pipeline/: python -m pytest tests/test_mi_registry.py -q
"""
from __future__ import annotations

import importlib.util
import json
import re
import sys
from collections import Counter

import pytest

from common import DATA_DIR, ROOT
from ingest import mi_egle_mienviro as M


def load(name):
    sys.path.insert(0, str(ROOT / "scripts"))
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def rows():
    return [r for r in json.loads((DATA_DIR / "dischargers.json").read_text()) if r.get("state") == "MI"]


@pytest.fixture(scope="module")
def register():
    return json.loads((DATA_DIR / "notice-channels" / "mi.json").read_text())["channels"]


def test_no_michigan_operator_row_names_an_individual(rows):
    for r in rows:
        for f in ("name", "short_name", "notes"):
            for seg in re.split(r"[,;()/]|\s-\s", r.get(f) or ""):
                assert not M._person(seg.strip()), (r["id"], f)
        first_two = " ".join(r["id"].split("-")[1:3]).title()             # an id made from "<given> <surname>, ..."
        assert not M._person(first_two), r["id"]


def test_a_drain_commissioners_permit_is_the_commissions():
    A = load("add_mi_operators")
    assert A.clean_name("Pat Example, Sample County Drain Commission") == "Sample County Drain Commission"
    assert A.clean_name("Sample Communities, Inc., c/o Pat Example") == "Sample Communities, Inc."
    assert A.clean_name("Sampleton, City of") == "Sampleton, City of"


def test_each_michigan_permit_is_in_one_row(rows):
    every = json.loads((DATA_DIR / "dischargers.json").read_text())
    c = Counter(p.upper() for r in every for p in {r.get("npdes_permit"), *(r.get("npdes_permits") or [])} if p)
    mine = {p.upper() for r in rows for p in r.get("npdes_permits") or []}
    assert [p for p in mine if c[p] > 1] == []
    assert any("MIG580319" in r["npdes_permits"] and r["id"] == "mi-lenawee-county-drain-commission" for r in rows)


@pytest.mark.parametrize("owner,towns", [
    ("Spring Arbor Township/Summit Township", ["Spring Arbor Township", "Summit Township"]),
    ("Charter Township of Clinton - Department of Public Services", ["Clinton"]),
    ("Charter Township of Waterford DPW", ["Waterford"]),
    ("City of Zeeland Clean Water Plant", ["Zeeland"]),
    ("Detroit Water and Sewerage Department (DWSD)", ["Detroit"]),
    ("City of Lincooln Park", ["Lincoln Park"]),
])
def test_an_owners_towns_are_towns(owner, towns):
    assert load("add_mi_operators").owner_towns(owner) == towns


def test_michigan_towns_carry_no_works_words(rows):
    bad = re.compile(r"(?i)\b(dpw|wwtp|wastewater|treatment plant|department|clean water plant)\b|/")
    assert [(r["id"], t) for r in rows for t in r.get("towns") or [] if bad.search(t)] == []


def test_the_duty_rows_go_to_sewer_systems_only(rows, register):
    named = Counter(c.get("operator_id") for c in register)
    for r in rows:
        if r["kind"] == "cso_closed_or_none" or re.search(r"\bMS4\b", r["name"]):
            assert named[r["id"]] == 0, r["id"]               # a petroleum site, a stormwater permit: no duty rows
        else:
            assert named[r["id"]] >= 3, r["id"]
    assert all(named[r["id"]] for r in rows if r["kind"] == "cso")   # the checklist's CSO one-liner
