"""California operator rows (scripts/add_ca_operators.py): the owner key that joins EPA's plant permittees to the State
Water Board's enrollees, the spelled-out names and the legal forms; and the rows in data/dischargers.json.
Run from pipeline/: python -m pytest tests/test_ca_operators.py -q
"""
from __future__ import annotations

import importlib.util
import json
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("add_ca_operators", ROOT / "scripts" / "add_ca_operators.py")
A = importlib.util.module_from_spec(spec)
spec.loader.exec_module(A)


def test_the_key_joins_epa_and_board_spellings_of_one_city_and_keeps_others_apart():
    assert A.key("Arcata, City of") == A.key("Arcata City") == "arcata"
    assert A.key("Los Angeles, City of") == A.key("Los Angeles City Bureau of Sanitation") == "los angeles"
    assert A.key("Stockton City MUD") == A.key("Stockton, City of") == "stockton"
    assert A.key("Crescent City, City of") == A.key("Crescent City") == "crescent city"
    assert A.key("Las Virgenes MWD") == A.key("Las Virgenes Municipal Water District")
    assert A.key("Los Angeles Cnty DPW") != A.key("Los Angeles, City of")
    assert A.key("Tahoe City PUD") != "tahoe"


def test_names_are_spelled_out_only_where_the_rest_is_a_department():
    assert A.public_name("Eureka City") == "City of Eureka"
    assert A.public_name("Petaluma City PWD") == "City of Petaluma (PWD)"
    assert A.public_name("Tahoe City PUD") == "Tahoe City PUD"
    assert A.public_name("Imperial Cnty") == "Imperial County"
    assert A.public_name("Arcata, City of") == "City of Arcata"


def test_legal_forms_come_from_the_controlled_list():
    assert A.form("Sacramento Area Sewer District (merged)") == "special district"
    assert A.form("CSU Long Beach") == "state facility"
    assert A.form("US Marine Corps Base Camp Pendleton") == "federal facility"
    assert A.form("Big Pine Indian Reservation") == "tribal"
    assert A.form("Golden State Water Company") == "investor-owned utility"
    assert A.form("Tesoro Viejo Master Mutual Water Company") == "member-owned utility"
    assert A.form("Encina Wastewater Authority") == "authority"


def test_the_california_rows_hold_each_permit_once_and_name_no_individual():
    from build import redact
    from ingest.dischargers_schema import LEGAL_FORMS
    rows = [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "CA"]
    if not rows:
        return
    perms = Counter(p for r in rows for p in r["npdes_permits"])
    assert [p for p, n in perms.items() if n > 1] == []
    assert len({r["id"] for r in rows}) == len(rows)
    assert all(r["legal_form"] in LEGAL_FORMS for r in rows)
    assert not any(redact.person_shaped(r["name"]) and not re.search(r"(?i)csd|cs$|district", r["name"]) for r in rows)
    sf = next(r for r in rows if r["id"] == "ca-sfpuc")
    assert {"CA0037664", "CA0037681", "2SSO10193", "2SSO10193-C"} <= set(sf["npdes_permits"])
    assert "CA0000018" not in perms                       # a desalination vessel test, not a sewer system


def test_the_name_pass_unites_an_invalid_outline_without_failing():
    from shapely.geometry import Polygon
    from ingest import waters_from_nhd as W
    bow = Polygon([(0, 0), (2, 2), (2, 0), (0, 2), (0, 0)])         # self-crossing, as some NHD lake outlines are
    good = Polygon([(3, 3), (4, 3), (4, 4), (3, 3)])
    u = W.safe_union([bow, good])
    assert u.is_valid and u.area > 0


def test_waters_named_in_spill_reports_are_not_the_operators_receiving_waters():
    """Review 2026-11-04 P2-2: an earlier spill's water listed as the operator's receiving water placed a later report
    that names no water there (status.Resolver.by_registry's single listed water). They are spill_report_waters."""
    pl = {"CA0099001": [{"receiving_water_echo": "Sample River"}]}
    rows = [{"id": "ca-sample", "state": "CA", "npdes_permits": ["2SSO99001", "CA0099001"], "aliases": ["ca-sample"],
             "receiving_waters": ["Sample Creek", "Sample River"]},
            {"id": "ca-other", "state": "CA", "npdes_permits": ["2SSO99002"], "aliases": ["ca-research-other"],
             "receiving_waters": ["Research Bay", "Sample Lake"]},
            {"id": "md-x", "state": "MD", "npdes_permits": [], "receiving_waters": ["Sample Creek"]}]
    research = {"ca-research-other": {"receiving_waters": ["Research Bay"]}}
    assert A.split_spill_waters(rows, pl, research) == 2
    assert rows[0]["receiving_waters"] == ["Sample River"] and rows[0]["spill_report_waters"] == ["Sample Creek"]
    assert list(rows[0]).index("spill_report_waters") == list(rows[0]).index("receiving_waters") + 1
    assert rows[1]["receiving_waters"] == ["Research Bay"] and rows[1]["spill_report_waters"] == ["Sample Lake"]
    assert rows[2] == {"id": "md-x", "state": "MD", "npdes_permits": [], "receiving_waters": ["Sample Creek"]}
    assert A.split_spill_waters(rows, pl, research) == 0                      # idempotent
    dis = json.loads((ROOT / "data" / "dischargers.json").read_text())
    ca = [r for r in dis if r.get("state") == "CA"]
    if ca:
        plants = A.plants()
        res = {r["id"]: r for r in json.loads(A.RESEARCH.read_text())}
        assert [r["id"] for r in ca if set(r["receiving_waters"]) - A.permit_waters(r, plants, res)] == []
