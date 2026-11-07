"""Arizona's operator rows and register rows (review 2026-11-07 P1-1, P2-5, P2-4, P2-6): EPA's permits in Indian
country carry EPA's channel, not ADEQ's rule; no row claims the Navajo Nation files no reports; the state text says
what the site does with dropped reports and what was not searched."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "AZ"]


def register():
    return json.loads((ROOT / "data" / "notice-channels" / "az.json").read_text())["channels"]


def test_navajo_nation_permits_carry_epas_channel_not_arizonas_rule():
    nn_ops = [r for r in ops() if any(p.startswith("NN") for p in r["npdes_permits"])]
    assert {r["id"] for r in nn_ops} == {"az-navajo-tribal-utility-authority", "az-nn0021610"}
    for r in nn_ops:
        assert "EPA Region 9" in r["notification_channel"] and "R18-9-C305(F) requires" not in r["notification_channel"]
    reg = {c["id"]: c for c in register()}
    for r in nn_ops:
        assert f"{r['id']}-adeq-report" not in reg
        row = reg[f"{r['id']}-epa-report"]
        assert "R18-9" not in row["legal_basis"] and "ADEQ" not in row["legal_basis"]


def test_no_row_says_the_navajo_nation_files_no_reports():
    for c in register():
        assert "none are there" not in (c.get("note") or ""), c["id"]
    ntua = next(r for r in ops() if r["id"] == "az-navajo-tribal-utility-authority")
    assert "No report under these permits" not in ntua["notes"]


def test_state_text_says_what_is_shown_and_what_was_not_searched():
    t = (ROOT / "research" / "az" / "state-text.md").read_text()
    assert "counted but not placed" not in t and "is not shown" in t
    assert "No operator or agency in Arizona offers" not in t and "not searched one by one" in t
    assert "Navajo" in t and "asset number" not in t


def test_stormwater_and_cleanup_permits_are_held_back_and_their_operators_have_no_row():
    """AZ final audit (2026-11-07, P2-2): the MS4 permits (Tucson, Pima County, Phoenix, Tempe) entered the plants file
    by ICIS's POTW owner indicator and Tucson's airport groundwater cleanup by its POTW component; EPA's records show
    stormwater and a remediation discharge, not a sewage plant. They are held back with the record read, a rebuild
    holds them back too, and every Arizona operator row and register row agree (Tempe and Tucson have no row)."""
    import ast
    import sys
    sys.path.insert(0, str(ROOT / "pipeline"))
    import common
    held = {"AZS000001": "stormwater_ms4", "AZS000002": "stormwater_ms4", "AZS000003": "stormwater_ms4",
            "AZS000005": "stormwater_ms4", "AZ0026417": "groundwater_remediation"}
    doc = json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())
    assert not [r for r in doc["outfalls"] if r.get("npdes_permit") in held]
    ex = {x["npdes_permit"]: x for x in doc["excluded_not_sewage"] if x["npdes_permit"] in held}
    assert {p: x["reason"] for p, x in ex.items()} == held
    for p, x in ex.items():
        assert x["state"] == "AZ" and x["why"] and p in x["basis"] and "ECHO" in x["basis"]
    assert "Urban Stormwater (Medium/Large MS4)" in ex["AZS000005"]["basis"]
    assert "4581" in ex["AZ0026417"]["basis"] and ex["AZ0026417"]["sic_codes"] == ["4581"]
    assert doc["counts"]["excluded_not_sewage"]["stormwater_ms4"] == 4
    assert doc["counts"]["excluded_not_sewage"]["groundwater_remediation"] == 1
    assert doc["count"] == len(doc["outfalls"]) == sum(doc["counts"]["by_state"].values())
    assert doc["counts"]["by_state"]["AZ"] == 178
    reg_rows = [r for r in common.load_outfall_registry(provisional=False) if str(r.get("state")).upper() == "AZ"]
    assert not [r for r in reg_rows if r.get("npdes_permit") in held]
    src = (ROOT / "research" / "federal" / "build_plant_outfalls.py").read_text()     # a rebuild holds them back too
    hand = next(ast.literal_eval(n.value) for n in ast.parse(src).body if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", None) == "HAND_NOT_SEWAGE")
    assert all(hand[p] == ex[p]["basis"] for p in held)
    rows = ops()
    assert not {r["id"] for r in rows} & {"az-city-of-tempe", "az-city-of-tucson"}
    assert not [r for r in rows if set(r["npdes_permits"]) & set(held)]
    plant_permits = {r["npdes_permit"] for r in doc["outfalls"] if r.get("state") == "AZ"}
    held_by_rows = {p for r in rows for p in r["npdes_permits"]}
    assert plant_permits <= held_by_rows
    named = {c["operator_id"] for c in register() if c.get("operator_id")}
    assert {r["id"] for r in rows} <= named
