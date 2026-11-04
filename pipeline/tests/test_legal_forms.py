"""The registry's legal forms: one controlled list (ingest/dischargers_schema.py) that every row of data/dischargers.json
uses (the renaming of 2026-11-04), a mapping from every value a builder's source still uses, and a check whose --strict
run on the registry is part of the tests. Run from pipeline/:
python -m pytest tests/test_legal_forms.py -q
"""
from __future__ import annotations

import importlib.util
import json

from common import DATA_DIR, ROOT
from ingest import dischargers_schema as L

REGISTRY = json.loads((DATA_DIR / "dischargers.json").read_text())


def test_the_list_has_a_public_and_a_private_side_and_every_mapping_lands_on_it():
    assert set(L.PUBLIC_FORMS).isdisjoint(L.PRIVATE_FORMS)
    assert set(L.LEGACY.values()) <= set(L.LEGAL_FORMS)
    assert not hasattr(L, "ROW_OVERRIDES")          # the rows carry their own value now
    assert not set(L.LEGACY) & set(L.LEGAL_FORMS)


def test_every_value_the_registry_uses_is_on_the_list():
    used = {r["legal_form"] for r in REGISTRY if r.get("legal_form")}
    assert used and used <= set(L.LEGAL_FORMS), used - set(L.LEGAL_FORMS)
    assert L.check_legal_forms(REGISTRY) == []


def test_the_renamed_rows_carry_the_value_the_review_agreed():
    """docs/reviews/2026-11-04-private-utilities-review.md: Georgia "municipal" is "city" but for the four county
    departments; JEA is an "authority"; North Carolina's companies are "business or industrial"; Lee County's Fiesta
    Village plant is the county's."""
    rows = {r["id"]: r.get("legal_form") for r in REGISTRY}
    want = {"ga-cobb-county": "county", "ga-dekalb-dwm": "county", "ga-fulton-county": "county",
            "ga-gwinnett-county": "county", "ga-atlanta-dwm": "city", "ga-albany": "city",
            "ga-augusta-utilities": "city", "ga-columbus-water-works": "city", "fl-jea": "authority",
            "fl-fl0039829": "county", "nc-birch-and-held": "business or industrial", "nc-hillco": "business or industrial",
            "nc-keyzer-catering": "business or industrial", "nc-lake-creek-corporation": "business or industrial",
            "nc-pcs-phosphate-company": "business or industrial", "nc-aqua-north-carolina": "investor-owned utility"}
    assert {i: rows[i] for i in want} == want


def test_the_research_files_and_the_north_carolina_script_values_are_mapped():
    used = set()
    for f in (ROOT / "research").glob("*/dischargers.json"):
        d = json.loads(f.read_text())
        rows = d if isinstance(d, list) else [r for v in d.values() if isinstance(v, list) for r in v]
        used |= {r["legal_form"] for r in rows if isinstance(r, dict) and r.get("legal_form")}
    spec = importlib.util.spec_from_file_location("add_nc_operators", ROOT / "scripts" / "add_nc_operators.py")
    nc = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(nc)
    used |= set(nc.LEGAL_FORMS)
    assert used <= set(L.LEGAL_FORMS) | set(L.LEGACY), used - set(L.LEGAL_FORMS) - set(L.LEGACY)


def test_the_candidates_scripts_proposed_forms_are_on_the_list():
    spec = importlib.util.spec_from_file_location("private_utilities", ROOT / "scripts" / "private_utilities.py")
    pu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pu)
    assert {f for f, _ in pu.LEGAL_FORM_HINTS} | {"facility (permittee not named)"} <= set(L.PRIVATE_FORMS)


def test_an_unknown_value_warns_and_never_raises_and_only_strict_fails(tmp_path):
    rows = [{"id": "zz-a", "name": "Example Sewer Company", "legal_form": "sewer cooperative"},
            {"id": "zz-b", "name": "Town of Example", "legal_form": "town"},
            {"id": "zz-c", "name": "Example Creek WWTP"}]
    w = L.check_legal_forms(rows)
    assert len(w) == 1 and w[0].startswith("zz-a:") and "not on the controlled list" in w[0]
    f = tmp_path / "d.json"
    f.write_text(json.dumps(rows))
    assert L.main(["--file", str(f)]) == 0
    assert L.main(["--file", str(f), "--strict"]) == 1


def test_the_registry_passes_the_strict_check():
    assert L.main([]) == 0
    assert L.main(["--strict"]) == 0


def test_a_legacy_value_warns_and_fails_strict(tmp_path):
    """A value that maps but is not on the list (a state build's own word) must be written as its controlled value."""
    rows = [{"id": "zz-a", "name": "Example Water Service Inc", "legal_form": "private utility"}]
    w = L.check_legal_forms(rows)
    assert len(w) == 1 and "'investor-owned utility'" in w[0] and "LEGACY" in w[0]
    f = tmp_path / "d.json"
    f.write_text(json.dumps(rows))
    assert L.main(["--file", str(f)]) == 0
    assert L.main(["--file", str(f), "--strict"]) == 1


def test_a_texas_water_supply_corporation_is_member_owned():
    """A water supply corporation is a non-profit owned by its members: never called investor-owned."""
    assert "member-owned utility" in L.PRIVATE_FORMS
    spec = importlib.util.spec_from_file_location("private_utilities", ROOT / "scripts" / "private_utilities.py")
    pu = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(pu)
    assert pu.legal_form_hint("EXAMPLE WSC WWTP", "EXAMPLE WATER SUPPLY CORPORATION", False) == "member-owned utility"
    assert pu.legal_form_hint("EXAMPLE RV RANCH WWTP", "EXRV WATER SUPPLY CORPORATION", False) == "member-owned utility"
    assert pu.legal_form_hint("EXAMPLE UTILITIES WWTP", "EXAMPLE UTILITIES INC", False) == "investor-owned utility"


def test_a_public_body_filed_as_private_warns():
    """A public district once filed as a privately owned facility."""
    rows = [{"id": "zz-district", "name": "Example County Water & Sewer District I",
             "legal_form": "facility (permittee not named)"},
            {"id": "zz-co", "name": "Example Utilities Inc", "legal_form": "city"},
            {"id": "zz-ok", "name": "Example Water Service Inc", "legal_form": "investor-owned utility"}]
    w = L.check_legal_forms(rows)
    assert [x.split(":")[0] for x in w] == ["zz-district", "zz-co"]


def test_a_value_is_controlled_mapped_unmapped_or_absent():
    assert L.controlled({"id": "ga-albany", "legal_form": "municipal"}) == ("city", "mapped")
    assert L.controlled({"id": "x", "legal_form": "sewer cooperative"}) == (None, "unmapped")
    assert L.controlled({"id": "x", "legal_form": "county"}) == ("county", "controlled")
    assert L.controlled({"id": "x"}) == (None, "absent")
