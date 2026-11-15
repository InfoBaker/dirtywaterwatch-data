"""Puerto Rico: operator rows, outfalls, register, rules row, state text and the missing-waters list."""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _ops():
    return [r for r in json.loads((ROOT / "data" / "dischargers.json").read_text()) if r.get("state") == "PR"]


def _register():
    return json.loads((ROOT / "data" / "notice-channels" / "pr.json").read_text())["channels"]


def test_every_puerto_rico_permit_is_in_one_row_and_no_person_is_named():
    ops = _ops()
    permits = [p for r in ops for p in r["npdes_permits"]]
    assert len(permits) == len(set(permits)) == 63
    prasa = next(r for r in ops if r["id"] == "pr-prasa")
    assert prasa["legal_form"] == "authority" and prasa["kind"] == "cso" and len(prasa["npdes_permits"]) == 53
    assert "PR0021555" in prasa["npdes_permits"]
    plants = {o["npdes_permit"] for o in json.loads((ROOT / "data" / "outfalls-plants-us.json").read_text())["outfalls"]
              if o.get("state") == "PR"}
    assert plants <= set(permits)
    forms = {"authority", "city", "state facility", "business or industrial", "institution", "campground or resort",
             "homeowners' association", "investor-owned utility", None}
    assert {r["legal_form"] for r in ops} <= forms
    assert not re.search(r"\b(Sr|Sra|Ing|Lcdo)\.", json.dumps(ops, ensure_ascii=False))


def test_prasas_twelve_outfalls_come_from_its_layer_and_replace_epas_rows():
    import sys
    sys.path.insert(0, str(ROOT / "pipeline"))
    from common import load_outfall_registry
    rows = [o for o in load_outfall_registry(provisional=False) if o.get("npdes_permit") == "PR0021555"
            and o.get("outfall_kind") == "cso"]
    assert len(rows) == 12 and all(o["_file"].endswith("outfalls-pr.json") for o in rows)
    assert all(o["lat"] is not None and -66.13 < o["lon"] < -66.05 for o in rows)   # EPA's 010 had -66.44
    assert {o["receiving_water_echo"] for o in rows} == {"Caño Martín Peña", "Bahía de San Juan", "Río de Puerto Nuevo"}
    assert "direccion" not in json.dumps(rows) and not any("Calle" in str(o.get("outfall_name")) for o in rows)


def test_the_register_has_a_row_per_operator_and_prasas_cso_pages_watched():
    reg = _register()
    ids = {r["id"] for r in reg}
    assert {f"{r['id']}-epa-report" for r in _ops()} <= ids
    pages = next(r for r in reg if r["id"] == "pr-prasa-cso-pages")
    assert pages["monitored"] and pages["records"] is False and "PR0021555" in pages["legal_basis"]
    notify = next(r for r in reg if r["id"] == "pr-prasa-cso-public-notification")
    assert notify["barrier"] == "no_web_page"
    beach = next(r for r in reg if r["id"] == "pr-drna-beach-notices")
    assert beach["feed_source_id"] == "pr-drna-beach-notices" and beach["unmonitored_reason"] == "feed_ingested"
    assert [r["id"] for r in reg] == sorted(r["id"] for r in reg)


def test_the_rules_row_sets_no_window_and_names_puerto_rico_not_a_state():
    row = json.loads((ROOT / "data" / "rules.json").read_text())["red"]["by_state"]["PR"]
    assert row["hours"] is None and "Atlantic Standard Time" in row["basis"]
    assert "the state" not in row["basis"] and "PR0021555" in row["source"]


def test_the_rain_caution_is_not_computed_and_the_text_says_so():
    import sys
    sys.path.insert(0, str(ROOT / "pipeline"))
    from ingest import rainfall
    import zones
    assert "PR" in rainfall.OUTSIDE_RADAR_GRID
    assert zones.STATE_ZONES["PR"] == "America/Puerto_Rico"
    t = (ROOT / "research" / "pr" / "state-text.md").read_text()
    assert "not computed for Puerto Rico" in t


def test_state_text_is_in_the_page_shape_and_names_puerto_rico():
    t = (ROOT / "research" / "pr" / "state-text.md").read_text()
    assert t.startswith("---\nstate: PR\nname: Puerto Rico\nupdated: ")
    for h in ("What the law requires", "What is published", "What is not published", "What stands in the way",
              "Known problems in the data", "What this site does about it"):
        assert f"**{h}.**" in t
    assert "{{share_line}}" in t and "Of Puerto Rico's reports" in t and "{{grade}}" in t
    assert not re.search(r"\b(safe|clean)\b", t, re.I)
    assert not re.search(r"\bthe state\b|\bthis state\b", t, re.I) and ".json" not in t and ".py" not in t
    assert "green flag" in t and "shows grey" in t and "never translated" in t


def test_missing_waters_list_leaves_out_held_and_generic_names():
    d = json.loads((ROOT / "research" / "pr" / "receiving-waters-missing.json").read_text())
    names = {r["name"] for r in d.get("rows", [])} | {r["name"] for r in d.get("resolved") or []}
    assert d["state"] == "PR" and "RIO BAIROA" not in names and "ATLANTIC OCEAN" not in names
    assert not {"unnamed creek", "CREEK (UNKNOWN THE NAME)", "CREEK", "QUEBRADA"} & names
    assert "Caño Martín Peña" in names or "Caño Martín Peña" in json.dumps(d, ensure_ascii=False)
    for r in d.get("rows", []):
        assert all(round(p[0], 3) == p[0] and round(p[1], 3) == p[1] for p in r["points"])
