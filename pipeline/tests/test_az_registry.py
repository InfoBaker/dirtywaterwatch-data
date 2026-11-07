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
