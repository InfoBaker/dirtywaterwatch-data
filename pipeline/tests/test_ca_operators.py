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
